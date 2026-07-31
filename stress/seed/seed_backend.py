"""Build the backend fixture the S7/S9 scenarios need.

`POST /trace-links` returns 409 unless the project has both a paper row and a code
repository row (`backend/app/api/routes/traces.py:122`), and the workspace code
endpoints 404 without an imported archive. This script creates a project, uploads a
minimal PDF, and imports a ZIP built from real Python sources so the AST analyzer has
genuine work to do.

Usage:
    uv run python -m seed.seed_backend --host http://127.0.0.1:58123 --source ../backend/app
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile

PAGE_LINES = [
    "3 Method",
    "We introduce a bidirectional traceability workbench that links paper claims to",
    "source code. The encoder maps each paragraph into a semantic tensor field, and",
    "the matcher scores candidate code spans against that field.",
    "3.1 Training objective",
    "We minimise a contrastive loss over aligned paper and code pairs, with a",
    "temperature term controlling the sharpness of the similarity distribution.",
    "4 Experiments",
    "We evaluate retrieval precision on a held out set of reviewed trace links.",
]


def _valid_pdf(pages: int = 3) -> bytes:
    """Produce a structurally valid PDF whose pages contain extractable text.

    Two constraints drive this being hand-built. A stub with only a header and
    trailer makes pypdf raise "startxref not found" before the route's own
    validation runs, so the xref table has to be real. And blank pages parse fine
    but yield no anchors, so `POST /trace-links` rejects every paper_ref with 422 --
    the write scenario would then measure nothing but error handling. Writing the
    objects out directly, tracking byte offsets for the xref, avoids depending on a
    PDF generator that is not in this project's dependency set.
    """
    objects: list[bytes] = []

    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    page_ids = [4 + 2 * i for i in range(pages)]
    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(
        b"<< /Type /Pages /Count %d /Kids [%s] >>" % (pages, kids)
    )
    objects.append(font)

    for page_index in range(pages):
        content_id = page_ids[page_index] + 1
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id
        )
        lines = []
        for line_index, line in enumerate(PAGE_LINES):
            text = line.replace("(", r"\(").replace(")", r"\)")
            lines.append(
                b"BT /F1 11 Tf 72 %d Td (%s) Tj ET"
                % (760 - line_index * 22, text.encode("latin-1"))
            )
        stream = b"\n".join(lines)
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))

    out = bytearray(b"%PDF-1.7\n")
    offsets: list[int] = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + payload + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)


def _json_request(url: str, payload: dict | None = None, method: str = "POST"):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, error.read()[:400].decode(errors="replace")


def _multipart(url: str, filename: str, content: bytes, content_type: str):
    boundary = "----stress" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    body = head + content + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, error.read()[:400].decode(errors="replace")


def _build_zip(source: pathlib.Path) -> tuple[bytes, int, list[str]]:
    buffer = io.BytesIO()
    names: list[str] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*.py")):
            arcname = "repo/" + path.relative_to(source).as_posix()
            archive.write(path, arcname)
            names.append(arcname)
    return buffer.getvalue(), len(names), names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://127.0.0.1:58123")
    parser.add_argument("--source", default="../backend/app")
    parser.add_argument("--name", default="stress-fixture")
    parser.add_argument("--wait-analysis", type=int, default=180)
    args = parser.parse_args()

    api = args.host.rstrip("/") + "/api/v1"
    source = pathlib.Path(args.source).resolve()
    if not source.is_dir():
        print(f"source not found: {source}", file=sys.stderr)
        return 2

    status, project = _json_request(f"{api}/projects", {"name": args.name})
    if status >= 400:
        print(f"create project failed: {status} {project}", file=sys.stderr)
        return 1
    project_id = project["id"]
    print(f"project id={project_id}")

    status, body = _multipart(
        f"{api}/projects/{project_id}/paper", "stress.pdf", _valid_pdf(), "application/pdf"
    )
    print(f"paper upload: {status}")
    if status >= 400:
        print(f"  detail: {body}", file=sys.stderr)

    payload, count, names = _build_zip(source)
    print(f"archive: {count} python files, {len(payload) / 1024:.0f} KiB")
    status, body = _multipart(
        f"{api}/projects/{project_id}/code", "stress-repo.zip", payload, "application/zip"
    )
    print(f"code import: {status}")
    if status >= 400:
        print(f"  detail: {body}", file=sys.stderr)
        return 1

    # Analysis runs on a background worker; the workspace endpoints 404 until it lands.
    deadline = time.time() + args.wait_analysis
    tree_status = 0
    while time.time() < deadline:
        tree_status, _ = _json_request(
            f"{api}/projects/{project_id}/workspace/code-tree", method="GET"
        )
        if tree_status == 200:
            break
        time.sleep(3)
    print(f"code-tree: {tree_status}")

    # Prefer a substantial file: __init__.py is often empty, which would make the
    # S9 edit path write a trivial payload and understate the write cost.
    sample = max(
        names,
        key=lambda n: (source / n[len("repo/") :]).stat().st_size if n.startswith("repo/") else 0,
        default="",
    )
    code_path = sample[len("repo/") :] if sample.startswith("repo/") else sample
    print(f"STRESS_PROJECT_ID={project_id}")
    print(f"STRESS_CODE_PATH={code_path}")
    return 0 if tree_status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
