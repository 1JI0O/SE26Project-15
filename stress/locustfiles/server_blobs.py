"""S4 concurrent chunked blob upload.

Chunks for a single blob must be appended strictly in order (blob_store.write_chunk
rejects offset mismatches with 409), so concurrency is expressed as concurrent
blobs, never concurrent chunks of one blob.

Environment:
    STRESS_IDENTITIES   seed file path (default identities.json)
    STRESS_BLOB_MIB     payload size per blob in MiB (default 60)
    STRESS_CHUNK_MIB    chunk size in MiB, must match server cloud_upload_chunk_bytes
                        (default 8)
    STRESS_VERIFY_DOWNLOAD  "1" to download and sha256-verify after complete
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from pathlib import Path

from locust import HttpUser, between, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import API, auth_headers, classify, env_int, load_pool  # noqa: E402

POOL = None
BLOB_BYTES = 60 * 1024**2
CHUNK_BYTES = 8 * 1024**2
VERIFY_DOWNLOAD = False


@events.init.add_listener
def _on_init(environment, **_kwargs) -> None:
    global POOL, BLOB_BYTES, CHUNK_BYTES, VERIFY_DOWNLOAD
    POOL = load_pool()
    BLOB_BYTES = env_int("STRESS_BLOB_MIB", 60) * 1024**2
    CHUNK_BYTES = env_int("STRESS_CHUNK_MIB", 8) * 1024**2
    VERIFY_DOWNLOAD = os.environ.get("STRESS_VERIFY_DOWNLOAD", "").strip() == "1"
    print(
        f"[stress] blob={BLOB_BYTES // 1024**2}MiB chunk={CHUNK_BYTES // 1024**2}MiB "
        f"verify_download={VERIFY_DOWNLOAD}"
    )


_SEQ = 0


def _next_index() -> int:
    global _SEQ
    _SEQ += 1
    return _SEQ


class BlobUploader(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.identity = POOL.next_identity()
        self.headers = auth_headers(self.identity)
        index = _next_index()
        workspace = POOL.workspace(index)
        self.workspace_id = workspace["workspace_id"]
        self.project_id = workspace["projects"][index % len(workspace["projects"])]
        # One reusable body per user: generating fresh random bytes each iteration
        # would make the load generator the bottleneck rather than the server.
        # The body must start with the PDF magic or `complete` rejects it with 400
        # ("Invalid PDF signature", blob_store.py) and never exercises the write path.
        self._filler = os.urandom(BLOB_BYTES - 9)
        self._new_body()

    def _new_body(self) -> None:
        """Give every iteration a distinct sha256 without regenerating the payload.

        Reusing one body per user makes the server dedup it: after the first upload
        the content already exists, so upload-init hands back the finished blob and
        chunk 0 conflicts with 409. Varying only a short unique prefix keeps the
        digest fresh while the expensive filler bytes stay allocated once.
        """
        marker = uuid.uuid4().hex.encode()  # 32 bytes
        self.body = b"%PDF-1.7\n" + marker + self._filler[len(marker) :]
        self.digest = hashlib.sha256(self.body).hexdigest()

    def _record(self, response, name: str) -> bool:
        if response.status_code >= 400:
            response.failure(f"{name}:{classify(response.status_code, response.text)}")
            return False
        response.success()
        return True

    @task
    def upload_cycle(self) -> None:
        self._new_body()
        blob_id = self._init_upload()
        if blob_id is None:
            return
        if not self._send_chunks(blob_id):
            return
        if not self._complete(blob_id):
            return
        if VERIFY_DOWNLOAD:
            self._download_and_verify(blob_id)

    def _init_upload(self) -> str | None:
        with self.client.post(
            f"{API}/blobs/upload-init",
            json={
                "workspace_id": self.workspace_id,
                "project_public_id": self.project_id,
                "sha256": self.digest,
                "byte_size": len(self.body),
                "mime_type": "application/pdf",
                "filename": f"stress-{uuid.uuid4().hex}.pdf",
            },
            headers=self.headers,
            name="POST /blobs/upload-init",
            catch_response=True,
        ) as response:
            if not self._record(response, "upload-init"):
                return None
            body = response.json()
            # A dedup hit returns status "ready" with nothing left to upload.
            if body.get("status") == "ready":
                return None
            return body.get("blob_id")

    def _send_chunks(self, blob_id: str) -> bool:
        total = (len(self.body) + CHUNK_BYTES - 1) // CHUNK_BYTES
        for index in range(total):
            chunk = self.body[index * CHUNK_BYTES : (index + 1) * CHUNK_BYTES]
            with self.client.put(
                f"{API}/blobs/{blob_id}/chunks/{index}",
                data=chunk,
                headers={
                    "Authorization": self.headers["Authorization"],
                    "Content-Type": "application/octet-stream",
                },
                name="PUT /blobs/{id}/chunks/{i}",
                catch_response=True,
            ) as response:
                if not self._record(response, "chunk"):
                    return False
        return True

    def _complete(self, blob_id: str) -> bool:
        with self.client.post(
            f"{API}/blobs/{blob_id}/complete",
            headers=self.headers,
            name="POST /blobs/{id}/complete",
            catch_response=True,
        ) as response:
            return self._record(response, "complete")

    def _download_and_verify(self, blob_id: str) -> None:
        """Byte-level correctness under load is a first-class result (plan section 8)."""
        with self.client.get(
            f"{API}/blobs/{blob_id}/download",
            headers={"Authorization": self.headers["Authorization"]},
            name="GET /blobs/{id}/download",
            catch_response=True,
        ) as response:
            if not self._record(response, "download"):
                return
            if hashlib.sha256(response.content).hexdigest() != self.digest:
                response.failure("download:sha256_mismatch")
