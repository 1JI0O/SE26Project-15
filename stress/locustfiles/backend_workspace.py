"""S7 analysis-queue saturation and S9 write-heavy mix, against the local backend.

The local backend is single-user, so the question is not concurrent user count but
whether interactive reads stay available while small thread pools (paper parse 1,
code analysis 2, agent analysis 2, agent conversation 4) are saturated, and whether
SQLite's single writer trips its 30 s lock timeout.

Environment:
    STRESS_PROJECT_ID   numeric backend project id (required)
    STRESS_CODE_PATH    repo-relative file path used for read/save (required for S9)
    STRESS_WRITE        "1" to enable the write tasks (S9); default read-only (S7)
    STRESS_SAVE_KIB     approximate code-file save size in KiB (default 64, cap 500;
                        MAX_EDIT_BYTES is 512_000)
"""

from __future__ import annotations

import json
import os
import random
import sys
import urllib.request
import uuid
from pathlib import Path

from locust import HttpUser, between, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import API, classify, env_int  # noqa: E402

# Backend routers are project-scoped by path:
#   /api/v1/projects/{project_id}/workspace/...
#   /api/v1/projects/{project_id}/trace-links
#   /api/v1/projects/{project_id}/rag/search
PROJECT_ID = ""
CODE_PATH = ""
WRITE_ENABLED = False
SAVE_BYTES = 64 * 1024
# Number of paragraph anchors to draw paper_ref from; seed_backend's fixture yields
# 3. Override if the fixture paper is larger.
PAPER_BLOCKS = 3
# Real file paths from the imported archive. A (paper_ref, code_ref) pair can only be
# created once -- a repeat returns 409 -- so writes must vary code_ref to keep
# producing genuine inserts rather than duplicate-key rejections.
CODE_FILES: list[str] = []


def _collect_files(nodes: list[dict], out: list[str]) -> None:
    for node in nodes:
        if node.get("kind") == "file" and node.get("path"):
            out.append(node["path"])
        children = node.get("children") or []
        if children:
            _collect_files(children, out)


@events.init.add_listener
def _on_init(environment, **_kwargs) -> None:
    global PROJECT_ID, CODE_PATH, WRITE_ENABLED, SAVE_BYTES, PAPER_BLOCKS, CODE_FILES
    PAPER_BLOCKS = env_int("STRESS_PAPER_BLOCKS", 3)
    PROJECT_ID = os.environ.get("STRESS_PROJECT_ID", "").strip()
    if not PROJECT_ID:
        raise RuntimeError("STRESS_PROJECT_ID is required.")
    CODE_PATH = os.environ.get("STRESS_CODE_PATH", "").strip()
    WRITE_ENABLED = os.environ.get("STRESS_WRITE", "").strip() == "1"
    # MAX_EDIT_BYTES is 512_000; stay under it so saves fail on contention only.
    SAVE_BYTES = min(env_int("STRESS_SAVE_KIB", 64), 500) * 1024
    if WRITE_ENABLED and not CODE_PATH:
        raise RuntimeError("STRESS_CODE_PATH is required when STRESS_WRITE=1.")
    if WRITE_ENABLED:
        host = (environment.host or "").rstrip("/")
        url = f"{host}{API}/projects/{PROJECT_ID}/workspace/code-tree"
        with urllib.request.urlopen(url, timeout=60) as response:
            _collect_files(json.loads(response.read()), CODE_FILES)
        if not CODE_FILES:
            raise RuntimeError(f"No files in the archive at {url}; import a repository first.")
    print(
        f"[stress] backend project={PROJECT_ID} write={WRITE_ENABLED} "
        f"save_bytes={SAVE_BYTES} code_path={CODE_PATH or '(none)'} "
        f"paper_blocks={PAPER_BLOCKS} code_files={len(CODE_FILES)}"
    )


class WorkspaceUser(HttpUser):
    wait_time = between(0.5, 1.0)

    def on_start(self) -> None:
        self.headers = {"Content-Type": "application/json"}
        self.created_links: list[str] = []
        self.base = f"{API}/projects/{PROJECT_ID}"

    def _record(self, response, name: str) -> bool:
        if response.status_code >= 400:
            response.failure(f"{name}:{classify(response.status_code, response.text)}")
            return False
        response.success()
        return True

    @task(3)
    def code_tree(self) -> None:
        with self.client.get(
            f"{self.base}/workspace/code-tree",
            name="GET /workspace/code-tree",
            catch_response=True,
        ) as response:
            self._record(response, "code-tree")

    @task(3)
    def tensor_flow(self) -> None:
        with self.client.get(
            f"{self.base}/workspace/tensor-flow",
            name="GET /workspace/tensor-flow",
            catch_response=True,
        ) as response:
            self._record(response, "tensor-flow")

    @task(2)
    def code_file(self) -> None:
        if not CODE_PATH:
            return
        with self.client.get(
            f"{self.base}/workspace/code-files/{CODE_PATH}",
            name="GET /workspace/code-files/{path}",
            catch_response=True,
        ) as response:
            self._record(response, "code-file")

    @task(2)
    def list_traces(self) -> None:
        with self.client.get(
            f"{self.base}/trace-links",
            name="GET /trace-links",
            catch_response=True,
        ) as response:
            self._record(response, "trace-links")

    @task(1)
    def rag_search(self) -> None:
        with self.client.get(
            f"{self.base}/rag/search",
            params={"query": "tensor attention gradient", "scope": "paper", "limit": 5},
            name="GET /rag/search",
            catch_response=True,
        ) as response:
            self._record(response, "rag-search")

    @task(2)
    def write_trace_link(self) -> None:
        """S9: exercises the SQLite single writer."""
        if not WRITE_ENABLED:
            return
        # paper_ref must anchor to a block that actually exists in the parsed paper,
        # otherwise the route rejects it with 422 before any write happens and the
        # scenario measures validation instead of the SQLite writer. code_ref must
        # likewise be a real path in the imported archive.
        paper_ref = f"paragraph:{random.randint(1, PAPER_BLOCKS)}"
        code_ref = random.choice(CODE_FILES) if CODE_FILES else CODE_PATH
        with self.client.post(
            f"{self.base}/trace-links",
            json={
                "paper_ref": paper_ref,
                "code_ref": code_ref,
                "status": "candidate",
                "evidence": [],
            },
            headers=self.headers,
            name="POST /trace-links",
            catch_response=True,
        ) as response:
            if self._record(response, "trace-create"):
                link_id = response.json().get("id")
                if link_id:
                    self.created_links.append(link_id)

    @task(1)
    def delete_trace_link(self) -> None:
        if not WRITE_ENABLED or not self.created_links:
            return
        link_id = self.created_links.pop()
        with self.client.delete(
            f"{self.base}/trace-links/{link_id}",
            name="DELETE /trace-links/{id}",
            catch_response=True,
        ) as response:
            self._record(response, "trace-delete")

    @task(1)
    def save_code_file(self) -> None:
        """S9: large-ish writes competing with reads for the write lock."""
        if not WRITE_ENABLED or not CODE_PATH:
            return
        filler = f"# stress {uuid.uuid4().hex}\n"
        content = filler * max(1, SAVE_BYTES // len(filler))
        with self.client.put(
            f"{self.base}/workspace/code-files/{CODE_PATH}",
            json={"content": content},
            headers=self.headers,
            name="PUT /workspace/code-files/{path}",
            catch_response=True,
        ) as response:
            self._record(response, "code-save")
