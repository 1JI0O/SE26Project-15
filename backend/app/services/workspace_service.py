import hashlib
import shutil
import zipfile
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.models.entities import (
    CodeRepository,
    PaperDocument,
    Project,
    TraceLink,
)
from app.services.code_analysis.archive import list_archive_entries, read_member_bytes
from app.services.code_analysis.definition_resolve import DefinitionResolution, resolve_definition
from app.services.code_analysis.editor import FileAccessError, RepositoryFileNotFoundError
from app.services.code_analyzer import (
    build_hierarchical_tree,
    count_filtered_files,
    is_editor_readable_file,
    read_repository_file,
    save_repository_file,
)
from app.services.paper_parser import parse_pdf
from app.services.tensor_flow.layout import layout_tensor_graph
from app.services.workspace_placeholder import (
    code_file_payload,
    workspace_payload,
)


def _repository_edits_root(repository: CodeRepository) -> Path:
    repository_key = repository.id or Path(repository.storage_path).stem
    return (
        Path(settings.upload_root)
        / f"project-{repository.project_id}"
        / "code-edits"
        / str(repository_key)
    )


def _latest_paper(session: Session, project_id: int) -> PaperDocument | None:
    statement = (
        select(PaperDocument)
        .where(PaperDocument.project_id == project_id)
        .order_by(PaperDocument.created_at.desc(), PaperDocument.id.desc())
    )
    return session.exec(statement).first()


def _latest_code(session: Session, project_id: int) -> CodeRepository | None:
    statement = (
        select(CodeRepository)
        .where(CodeRepository.project_id == project_id)
        .order_by(CodeRepository.created_at.desc(), CodeRepository.id.desc())
    )
    return session.exec(statement).first()


def _latest_trace_links(session: Session, project_id: int) -> list[TraceLink]:
    statement = (
        select(TraceLink)
        .where(TraceLink.project_id == project_id)
        .order_by(TraceLink.created_at.desc(), TraceLink.id.desc())
    )
    return list(session.exec(statement).all())


def build_paper_pages(document: PaperDocument | None) -> list[dict[str, Any]]:
    if document is None:
        return []

    if document.pages_json:
        return [
            {
                "page_number": int(page.get("page_number", index)),
                "title": str(page.get("title", f"Page {index}"))[:200],
                "body": [str(item) for item in page.get("body", [])],
                "anchors": list(page.get("anchors", [])),
            }
            for index, page in enumerate(document.pages_json, start=1)
        ]

    if document.storage_path:
        try:
            parsed = parse_pdf(document.storage_path)
            return parsed.get("pages", [])
        except Exception:
            pass

    sections_by_page: dict[int, list[str]] = {}
    for section in document.sections_json:
        page_number = int(section.get("page", 1))
        sections_by_page.setdefault(page_number, []).append(str(section.get("title", "")))

    paragraphs_by_page: dict[int, list[str]] = {}
    max_page = 1
    for paragraph in document.paragraphs_json:
        page_number = int(paragraph.get("page", 1))
        max_page = max(max_page, page_number)
        paragraphs_by_page.setdefault(page_number, []).append(str(paragraph.get("text", "")))

    pages: list[dict[str, Any]] = []
    for page_number in range(1, max_page + 1):
        section_titles = sections_by_page.get(page_number, [])
        body = paragraphs_by_page.get(page_number, [])
        title = (
            section_titles[0]
            if section_titles
            else (document.title if page_number == 1 else f"Page {page_number}")
        )
        pages.append(
            {
                "page_number": page_number,
                "title": title[:200],
                "body": body,
                "anchors": [
                    {"type": "section", "label": section_title, "page": page_number}
                    for section_title in section_titles
                ],
            }
        )
    return pages


def build_import_steps(
    paper: PaperDocument | None,
    code: CodeRepository | None,
) -> list[dict[str, Any]]:
    paper_status = "已解析" if paper else "待上传"
    paper_tag = "success" if paper else "info"
    code_status = "已分析" if code else "待上传"
    code_tag = "success" if code else "info"
    trace_status = "可生成追溯建议" if paper and code else "等待论文与代码导入"
    trace_tag = "success" if paper and code else "warning"

    return [
        {
            "index": "01",
            "title": "导入论文 PDF",
            "description": "读取 MinerU 结构化 Markdown、章节、公式、表格和图片；论文区只读展示。",
            "status": paper_status,
            "tag_type": paper_tag,
            "action": "重新上传" if paper else "上传 PDF",
        },
        {
            "index": "02",
            "title": "导入代码 ZIP",
            "description": "按 .gitignore 和 macOS 元数据规则过滤，生成 IDE 风格完整代码仓库树。",
            "status": code_status,
            "tag_type": code_tag,
            "action": "替换代码包" if code else "上传 ZIP",
        },
        {
            "index": "03",
            "title": "生成追溯视图",
            "description": "基于论文解析与代码静态分析输出候选追溯关系。",
            "status": trace_status,
            "tag_type": trace_tag,
            "action": "",
        },
    ]


def _symbol_summary(code: CodeRepository | None, file_path: str) -> tuple[str, str, str]:
    if code is None:
        return "", "待分析", "info"
    matches = [symbol for symbol in code.symbols_json if symbol.get("path") == file_path]
    if not matches:
        return "", "普通文件", "info"
    preferred = next(
        (symbol for symbol in matches if symbol.get("type") in {"class", "function"}),
        matches[0],
    )
    symbol_name = str(preferred.get("name", ""))
    if preferred.get("type") == "class":
        return symbol_name, "模型/类定义候选", "success"
    if preferred.get("type") == "function":
        return symbol_name, "函数实现候选", "primary"
    return symbol_name, "符号已索引", "info"


def build_code_file_payload(
    project_id: int,
    file_path: str,
    code: CodeRepository | None,
) -> dict[str, Any] | None:
    if code is None:
        return None

    if not is_editor_readable_file(file_path):
        return None

    try:
        content = read_repository_file(
            code.storage_path,
            file_path,
            edits_root=_repository_edits_root(code),
        )
    except RepositoryFileNotFoundError:
        return None

    symbol, status, status_type = _symbol_summary(code, file_path)
    pytorch_hits = [
        candidate
        for candidate in code.pytorch_candidates_json
        if candidate.get("path") == file_path
    ]
    badge = "pytorch" if pytorch_hits else Path(file_path).suffix.lstrip(".") or "file"

    return {
        "path": file_path,
        "name": file_path,
        "badge": badge,
        "status": status,
        "status_type": status_type,
        "symbol": symbol,
        "paper_ref": "待匹配",
        "content": content,
        "linked_lines": [],
    }


def build_trace_rows(
    session: Session,
    project_id: int,
    paper: PaperDocument | None,
    code: CodeRepository | None,
) -> list[dict[str, Any]]:
    stored_links = _latest_trace_links(session, project_id)
    if stored_links:
        return [
            {
                "paper_ref": link.paper_ref,
                "code_ref": link.code_ref,
                "relation_type": link.relation_type,
                "confidence": int(round(link.confidence * 100)),
                "rationale": link.rationale,
            }
            for link in stored_links[:20]
        ]

    return []


def build_workspace_payload(session: Session, project_id: int) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} not found")

    paper = _latest_paper(session, project_id)
    code = _latest_code(session, project_id)
    paper_pages = build_paper_pages(paper)
    code_tree = (
        build_hierarchical_tree(code.file_tree_json, root_name=Path(code.filename).stem)
        if code
        else []
    )

    code_files: list[dict[str, Any]] = []
    if code:
        for entry in code.file_tree_json[:30]:
            file_path = str(entry.get("path", ""))
            if not file_path or entry.get("language") not in {"python", "docs", "config", "other"}:
                continue
            try:
                payload = build_code_file_payload(project_id, file_path, code)
            except FileAccessError:
                continue
            if payload is not None:
                code_files.append(payload)

    trace_rows = build_trace_rows(session, project_id, paper, code)
    placeholder = workspace_payload(str(project_id))

    return {
        "project_id": str(project_id),
        "project_name": project.name,
        "import_steps": build_import_steps(paper, code),
        "paper_pages": paper_pages,
        "code_tree": code_tree,
        "code_files": code_files,
        "trace_rows": trace_rows,
        "flow_nodes": placeholder["flow_nodes"],
        "tensor_flow": build_tensor_flow_payload(code, str(project_id)),
        "conflict_items": placeholder["conflict_items"],
        "report_cards": _build_report_cards(paper, code, trace_rows),
    }


def _build_report_cards(
    paper: PaperDocument | None,
    code: CodeRepository | None,
    trace_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    paragraph_count = len(paper.paragraphs_json) if paper else 0
    file_count = len(code.file_tree_json) if code else 0
    symbol_count = len(code.symbols_json) if code else 0
    return [
        {
            "value": str(paragraph_count),
            "title": "论文段落数",
            "description": "已完成静态切分的论文片段数量。",
        },
        {
            "value": str(file_count),
            "title": "代码文件数",
            "description": "过滤忽略规则后保留的仓库文件数量。",
        },
        {
            "value": str(symbol_count),
            "title": "代码符号数",
            "description": "静态分析提取的类、函数和导入信息。",
        },
        {
            "value": str(len(trace_rows)),
            "title": "追溯候选数",
            "description": "当前可展示的论文-代码关联建议。",
        },
    ]


def get_paper_pages(session: Session, project_id: int) -> list[dict[str, Any]]:
    return build_paper_pages(_latest_paper(session, project_id))


def get_code_tree(session: Session, project_id: int) -> list[dict[str, Any]]:
    code = _latest_code(session, project_id)
    if code is None:
        return []
    return build_hierarchical_tree(code.file_tree_json, root_name=Path(code.filename).stem)


def get_code_file(session: Session, project_id: int, file_path: str) -> dict[str, Any] | None:
    return build_code_file_payload(project_id, file_path, _latest_code(session, project_id))


def save_code_file(
    session: Session, project_id: int, file_path: str, content: str
) -> dict[str, Any]:
    code = _latest_code(session, project_id)
    if code is None:
        raise FileNotFoundError("Code archive has not been uploaded")

    existing = build_code_file_payload(project_id, file_path, code)
    if existing is None:
        raise FileNotFoundError(f"Code file not found: {file_path}")

    save_repository_file(
        code.storage_path,
        _repository_edits_root(code),
        file_path,
        content,
    )
    _sync_saved_file_to_checkout(code, file_path, content)
    from app.services.tracing.lifecycle import record_artifact_revision_change

    stale_count = record_artifact_revision_change(
        session,
        project_id,
        "code",
        code.id or 0,
        "code_file_saved",
    )
    repository_revision = code.revision
    code.analysis_status = "stale"
    code.analysis_error = None
    session.add(code)
    project = session.get(Project, project_id)
    if project is not None:
        from app.services.local_sync import record_local_operation

        edit_id = hashlib.sha256(
            f"{code.public_id}:{code.revision}:{file_path}".encode()
        ).hexdigest()
        record_local_operation(
            session,
            project,
            "code_edit",
            edit_id,
            {
                "project_public_id": project.public_id,
                "repository_public_id": code.public_id,
                "repository_revision": code.revision,
                "path": file_path,
                "filename": Path(file_path).name,
                "requires_blob": True,
                # Kept only in the Desktop SQLite outbox. The sync client
                # removes it before push and sends a blob reference instead.
                "_upload_content": content,
            },
            base_version=0,
        )
    session.commit()
    from app.services.analysis_jobs import ensure_repository_analysis

    try:
        ensure_repository_analysis(project_id)
    except ValueError:
        pass
    return {
        "project_id": str(project_id),
        "path": file_path,
        "status": "accepted",
        "message": f"Saved edited content with {len(content)} characters.",
        "repository_revision": repository_revision,
        "stale_trace_count": stale_count,
    }


def build_tensor_flow_payload(
    code: CodeRepository | None,
    project_id: str,
    *,
    analysis: dict[str, Any] | None = None,
    view: str = "architecture",
    root_symbol: str | None = None,
) -> dict[str, Any]:
    if code is None:
        payload = layout_tensor_graph(
            {"nodes": [], "edges": []},
            project_id,
            renderer="architecture-dag-v2",
            view="architecture",
        )
        payload.update(
            analysis_status="missing",
            analysis_revision=0,
            repository_revision=0,
            stale=False,
        )
        return payload
    analysis = (
        analysis
        or code.analysis_json
        or {
            "architecture_graph": {"roots": [], "graphs": {}, "default_root": None},
            "tensor_graph": code.tensor_graph_json,
        }
    )
    architecture = analysis.get("architecture_graph", {})
    graphs = architecture.get("graphs", {})
    selected_root = root_symbol if root_symbol in graphs else architecture.get("default_root")
    selected_graph = graphs.get(selected_root, {"nodes": [], "edges": []})
    roots = list(architecture.get("roots", []))
    if selected_root and not any(root.get("symbol_id") == selected_root for root in roots):
        graph_nodes = selected_graph.get("nodes", [])
        roots.append(
            {
                "symbol_id": selected_root,
                "label": selected_graph.get("root_label") or selected_root.rsplit("::", 1)[-1],
                "source_path": graph_nodes[0].get("source_path", "") if graph_nodes else "",
                "score": 0,
            }
        )
    if view == "debug":
        execution_symbol = selected_graph.get("execution_symbol")
        raw_graph = analysis["tensor_graph"]
        node_ids = {
            str(node["id"])
            for node in raw_graph.get("nodes", [])
            if not execution_symbol or node.get("symbol_id") == execution_symbol
        }
        debug_graph = {
            "nodes": [node for node in raw_graph.get("nodes", []) if str(node["id"]) in node_ids],
            "edges": [
                edge
                for edge in raw_graph.get("edges", [])
                if str(edge["source"]) in node_ids and str(edge["target"]) in node_ids
            ],
            "root_symbol": selected_root,
            "root_label": selected_graph.get("root_label"),
        }
        payload = layout_tensor_graph(
            debug_graph,
            project_id,
            renderer="semantic-dag-v1",
            view="debug",
            available_roots=roots,
        )
    else:
        payload = layout_tensor_graph(
            selected_graph,
            project_id,
            renderer="architecture-dag-v2",
            view="architecture",
            available_roots=roots,
        )
    payload.update(
        analysis_status=code.analysis_status,
        analysis_revision=code.analysis_revision,
        repository_revision=code.revision,
        stale=(
            code.analysis_revision != code.revision
            or code.analysis_version != _local_analyzer_version()
            or code.analysis_status != "ready"
        ),
    )
    return payload


def _local_analyzer_version() -> str:
    from app.services.analysis_jobs import ANALYZER_VERSION

    return ANALYZER_VERSION


def get_tensor_flow(
    session: Session,
    project_id: int,
    *,
    view: str = "architecture",
    root_symbol: str | None = None,
) -> dict[str, Any]:
    code = _latest_code(session, project_id)
    if code is not None:
        from app.services.analysis_jobs import analysis_is_current, ensure_repository_analysis

        if not analysis_is_current(code) and code.analysis_status not in {"queued", "running"}:
            try:
                ensure_repository_analysis(project_id)
                session.refresh(code)
            except ValueError:
                pass
    return build_tensor_flow_payload(
        code,
        str(project_id),
        analysis=code.analysis_json if code else None,
        view=view,
        root_symbol=root_symbol,
    )


def get_code_analysis(session: Session, project_id: int) -> dict[str, Any] | None:
    code = _latest_code(session, project_id)
    if code is None:
        return None
    if not code.analysis_json:
        from app.services.analysis_jobs import ensure_repository_analysis

        if code.analysis_status not in {"queued", "running"}:
            try:
                ensure_repository_analysis(project_id)
            except ValueError:
                pass
        return None
    return code.analysis_json


def get_trace_rows(session: Session, project_id: int) -> list[dict[str, Any]]:
    paper = _latest_paper(session, project_id)
    code = _latest_code(session, project_id)
    return build_trace_rows(session, project_id, paper, code)


def get_filtered_file_summary(session: Session, project_id: int) -> str:
    code = _latest_code(session, project_id)
    if code is None:
        return "尚未上传代码包。"
    ignored = count_filtered_files(code.storage_path)
    return f"{ignored} 个文件被隐藏，包括 .DS_Store、__MACOSX/、.venv/、dist/ 等规则匹配项。"


def fallback_code_file(project_id: str, file_path: str) -> dict[str, Any] | None:
    payload = code_file_payload(project_id, file_path)
    return payload


def _sync_saved_file_to_checkout(
    repository: CodeRepository,
    file_path: str,
    content: str,
) -> None:
    checkout_root = _repository_checkout_root(repository)
    marker = checkout_root / ".revision"
    if not marker.is_file():
        return
    if marker.read_text(encoding="utf-8").strip() != str(repository.revision):
        return
    destination = checkout_root / file_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


def _repository_checkout_root(repository: CodeRepository) -> Path:
    repository_key = repository.id or Path(repository.storage_path).stem
    return (
        Path(settings.upload_root)
        / f"project-{repository.project_id}"
        / "code-checkout"
        / str(repository_key)
    )


def materialize_code_checkout(session: Session, project_id: int) -> dict[str, Any]:
    code = _latest_code(session, project_id)
    if code is None:
        raise FileNotFoundError("Code archive has not been uploaded")

    checkout_root = _repository_checkout_root(code)
    marker = checkout_root / ".revision"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == str(code.revision):
        return {
            "path": str(checkout_root.resolve()),
            "revision": code.revision,
            "repository_id": code.id or 0,
        }

    shutil.rmtree(checkout_root, ignore_errors=True)
    checkout_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(code.storage_path) as archive:
        entries, _root, _ignored = list_archive_entries(archive)
        for entry in entries:
            destination = checkout_root / entry.display_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(read_member_bytes(archive, entry.member_name))

    edits_root = _repository_edits_root(code)
    if edits_root.is_dir():
        for edited in edits_root.rglob("*"):
            if not edited.is_file() or edited.is_symlink():
                continue
            relative = edited.relative_to(edits_root)
            target = checkout_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(edited, target)

    marker.write_text(str(code.revision), encoding="utf-8")
    return {
        "path": str(checkout_root.resolve()),
        "revision": code.revision,
        "repository_id": code.id or 0,
    }


def resolve_code_definition(
    session: Session,
    project_id: int,
    *,
    path: str,
    line: int,
    column: int,
    identifier: str | None,
) -> DefinitionResolution:
    code = _latest_code(session, project_id)
    if code is None:
        raise FileNotFoundError("Code archive has not been uploaded")
    return resolve_definition(
        code,
        path=path,
        line=line,
        column=column,
        identifier=identifier,
        edits_root=_repository_edits_root(code),
    )
