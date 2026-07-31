"""TraceLab CLI for VS Code extension."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tracelab_core.analyze import analyze_workspace
from tracelab_core.parse import parse_paper
from tracelab_core.probe import probe_llm, probe_mineru
from tracelab_core.progress import emit_progress
from tracelab_core.review import load_links, mark_stale, update_link_status, update_links_batch
from tracelab_core.tensor_flow_view import build_tensor_flow_view
from tracelab_core.trace import run_trace_batch
from tracelab_core.workspace import ensure_layout, import_pdf, read_json, tracelab_paths, write_json


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _load_config_file(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_init(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    paths = ensure_layout(workspace)
    _emit({"ok": True, "tracelab_root": str(paths.root)})
    return 0


def cmd_import_pdf(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    pdf = Path(args.pdf).resolve()
    paths = import_pdf(workspace, pdf)
    _emit({"ok": True, "source_pdf": str(paths.source_pdf)})
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    paths = ensure_layout(workspace)
    config = _load_config_file(Path(args.config) if args.config else None)
    result = parse_paper(paths, config.get("mineru"))
    _emit({"ok": True, **result})
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    paths = ensure_layout(workspace)
    emit_progress("analyze", "Scanning Python sources")
    analysis = analyze_workspace(workspace)
    revision = str(analysis.pop("revision", ""))
    write_json(paths.symbols_json, analysis.get("symbols", []))
    write_json(paths.analysis_dir / "imports.json", analysis.get("imports", []))
    write_json(paths.analysis_dir / "calls.json", analysis.get("calls", []))
    write_json(paths.analysis_dir / "pytorch.json", analysis.get("pytorch_candidates", []))
    write_json(paths.tensor_graph_json, analysis.get("tensor_graph", {}))
    write_json(paths.architecture_json, analysis.get("architecture_graph", {}))
    summary = analysis.get("summary", {})
    write_json(paths.revision_json, {"fingerprint": revision, "summary": summary})
    stale = mark_stale(paths, revision)
    emit_progress(
        "analyze",
        f"Done: {summary.get('symbol_count', 0)} symbols, "
        f"{summary.get('architecture_roots', 0)} architecture roots",
    )
    _emit({"ok": True, "revision": revision, "stale_marked": stale, "summary": summary})
    return 0


def cmd_tensor_flow(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    paths = ensure_layout(workspace)
    payload = build_tensor_flow_view(
        paths,
        view=str(args.view),
        root_symbol=args.root or None,
    )
    _emit({"ok": True, "graph": payload})
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    paths = ensure_layout(workspace)
    config = _load_config_file(Path(args.config) if args.config else None)
    result = run_trace_batch(
        paths,
        llm_config=config.get("llm"),
        limit=int(args.limit),
        replace=bool(getattr(args, "replace", False)),
    )
    _emit({"ok": True, **result})
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    paths = tracelab_paths(workspace)
    paper_ready = (
        paths.normalized_json.is_file()
        or paths.paper_document_json.is_file()
        or paths.document_md.is_file()
    )
    analysis_ready = paths.symbols_json.is_file()
    links = load_links(paths) if paths.links_json.is_file() else []
    proposed = sum(1 for item in links if item.get("status") == "proposed")
    accepted = sum(1 for item in links if item.get("status") == "accepted")
    tensor = read_json(paths.tensor_graph_json, {}) or {}
    _emit(
        {
            "ok": True,
            "tracelab_root": str(paths.root),
            "paper_ready": paper_ready,
            "analysis_ready": analysis_ready,
            "links_total": len(links),
            "links_proposed": proposed,
            "links_accepted": accepted,
            "tensor_nodes": len(tensor.get("nodes") or []),
            "has_pdf": paths.source_pdf.is_file(),
            "revision": read_json(paths.revision_json, {}),
        }
    )
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    paths = ensure_layout(workspace)
    updated = update_link_status(paths, args.link_id, args.status)
    if updated is None:
        _emit({"ok": False, "error": "link not found"})
        return 1
    _emit({"ok": True, "link": updated})
    return 0


def cmd_review_batch(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    paths = ensure_layout(workspace)
    ids = [item for item in (args.ids or "").split(",") if item.strip()] if args.ids else None
    result = update_links_batch(
        paths,
        args.status,
        link_ids=ids,
        all_proposed=bool(args.all_proposed),
    )
    _emit({"ok": True, **result})
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    config = _load_config_file(Path(args.config) if args.config else None)
    if args.target == "llm":
        result = probe_llm(config.get("llm") or {})
    else:
        result = probe_mineru(config.get("mineru") or {})
    _emit({"ok": bool(result.get("ok")), **result})
    return 0 if result.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tracelab")
    parser.add_argument("--workspace", required=True, help="VS Code workspace root")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create .tracelab layout").set_defaults(func=cmd_init)

    import_cmd = sub.add_parser("import-pdf", help="Copy PDF into .tracelab/papers/")
    import_cmd.add_argument("--pdf", required=True)
    import_cmd.set_defaults(func=cmd_import_pdf)

    parse_cmd = sub.add_parser("parse", help="Parse paper PDF")
    parse_cmd.add_argument("--config", help="JSON config with mineru settings")
    parse_cmd.set_defaults(func=cmd_parse)

    sub.add_parser("analyze", help="Analyze workspace Python code").set_defaults(func=cmd_analyze)

    trace_cmd = sub.add_parser("trace", help="Generate trace candidates")
    trace_cmd.add_argument("--config", help="JSON config with llm settings")
    trace_cmd.add_argument("--limit", default="30")
    trace_cmd.add_argument(
        "--replace",
        action="store_true",
        help="Clear existing links.json before running Agent trace",
    )
    trace_cmd.set_defaults(func=cmd_trace)

    sub.add_parser("status", help="Workspace TraceLab status").set_defaults(func=cmd_status)

    review_cmd = sub.add_parser("review", help="Accept/reject a trace link")
    review_cmd.add_argument("--link-id", required=True)
    review_cmd.add_argument("--status", choices=["accepted", "rejected", "proposed"], required=True)
    review_cmd.set_defaults(func=cmd_review)

    batch_cmd = sub.add_parser("review-batch", help="Batch accept/reject/reset links")
    batch_cmd.add_argument("--status", choices=["accepted", "rejected", "proposed"], required=True)
    batch_cmd.add_argument("--ids", help="Comma-separated link ids")
    batch_cmd.add_argument("--all-proposed", action="store_true")
    batch_cmd.set_defaults(func=cmd_review_batch)

    probe_cmd = sub.add_parser("probe", help="Probe LLM or MinerU connectivity")
    probe_cmd.add_argument("--target", choices=["llm", "mineru"], required=True)
    probe_cmd.add_argument("--config", required=True)
    probe_cmd.set_defaults(func=cmd_probe)

    tensor_cmd = sub.add_parser("tensor-flow", help="Layout one tensor-flow layer")
    tensor_cmd.add_argument("--view", choices=["architecture", "debug"], default="architecture")
    tensor_cmd.add_argument("--root", default="")
    tensor_cmd.set_defaults(func=cmd_tensor_flow)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        code = args.func(args)
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)})
        raise SystemExit(1) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()
