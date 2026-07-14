from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.models.entities import CodeRepository, PaperDocument, Project, TraceLink
from app.services.code_analyzer import (
    build_hierarchical_tree,
    count_filtered_files,
    is_editor_readable_file,
    read_archive_file,
    save_archive_file_edit,
)
from app.services.paper_parser import parse_pdf
from app.services.trace_suggester import suggest_trace_links
from app.services.workspace_placeholder import (
    code_file_payload,
    tensor_flow_payload,
    workspace_payload,
)


def _project_edits_root(project_id: int) -> Path:
    return Path(settings.upload_root) / f"project-{project_id}" / "code-edits"


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
            "description": "保留原文页视图，抽取章节、段落和页码；论文区只读展示。",
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

    content = read_archive_file(
        code.storage_path,
        file_path,
        edits_root=_project_edits_root(project_id),
    )
    if content is None:
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

    if paper is None or code is None:
        return []

    suggestions = suggest_trace_links(
        paper.sections_json,
        paper.paragraphs_json,
        code.symbols_json,
        code.pytorch_candidates_json,
    )
    return [
        {
            "paper_ref": item["paper_ref"],
            "code_ref": item["code_ref"],
            "relation_type": item["relation_type"],
            "confidence": int(round(float(item["confidence"]) * 100)),
            "rationale": item["rationale"],
        }
        for item in suggestions
    ]


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
            payload = build_code_file_payload(project_id, file_path, code)
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
        "tensor_flow": tensor_flow_payload(str(project_id)),
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

    save_archive_file_edit(_project_edits_root(project_id), file_path, content)
    return {
        "project_id": str(project_id),
        "path": file_path,
        "status": "accepted",
        "message": f"Saved edited content with {len(content)} characters.",
    }


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
