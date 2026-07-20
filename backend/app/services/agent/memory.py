from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import or_
from sqlmodel import Session, select

from app.models.entities import AgentConversation, AgentMemory, Project, utc_now
from app.schemas.agent import AgentMemoryCreate, AgentMemoryRead


def _tokens(value: str) -> set[str]:
    lowered = value.lower()
    words = set(re.findall(r"[a-z0-9_./:-]{2,}", lowered))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    words.update(chinese[index : index + 2] for index in range(max(len(chinese) - 1, 0)))
    return {token for token in words if token}


def _fingerprint(scope: str, project_id: int | None, kind: str, content: str) -> str:
    normalized = " ".join(content.strip().split()).lower()
    raw = f"{scope}:{project_id or 'global'}:{kind}:{normalized}"
    return hashlib.sha256(raw.encode()).hexdigest()


def memory_to_read(memory: AgentMemory) -> AgentMemoryRead:
    return AgentMemoryRead(
        memory_id=memory.memory_id,
        project_id=memory.project_id,
        conversation_id=memory.conversation_id,
        scope=memory.scope,
        kind=memory.kind,
        content=memory.content,
        importance=memory.importance,
        source=memory.source_json,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        last_used_at=memory.last_used_at,
    )


def create_memory(
    session: Session,
    project_id: int,
    payload: AgentMemoryCreate,
    *,
    source: dict[str, Any] | None = None,
) -> AgentMemory:
    scoped_project_id = None if payload.scope == "global" else project_id
    fingerprint = _fingerprint(payload.scope, scoped_project_id, payload.kind, payload.content)
    existing = session.exec(
        select(AgentMemory).where(AgentMemory.fingerprint == fingerprint)
    ).first()
    now = utc_now()
    if existing is not None:
        previous_version = existing.version
        existing.importance = max(existing.importance, payload.importance)
        existing.updated_at = now
        if source:
            existing.source_json = {**existing.source_json, **source}
        existing.version += 1
        session.add(existing)
        project = session.get(Project, project_id)
        if project is not None and project.agent_history_sync:
            from app.services.local_sync import record_local_operation

            record_local_operation(
                session,
                project,
                "agent_memory",
                existing.public_id,
                {
                    "project_public_id": project.public_id,
                    "scope": existing.scope,
                    "kind": existing.kind,
                    "content": existing.content,
                    "importance": existing.importance,
                    "source": existing.source_json,
                },
                base_version=previous_version,
            )
        session.commit()
        session.refresh(existing)
        return existing
    memory = AgentMemory(
        project_id=scoped_project_id,
        conversation_id=None if payload.scope == "global" else payload.conversation_id,
        scope=payload.scope,
        kind=payload.kind,
        content=payload.content.strip(),
        importance=payload.importance,
        fingerprint=fingerprint,
        source_json=source or {},
    )
    session.add(memory)
    project = session.get(Project, project_id)
    if project is not None and project.agent_history_sync:
        from app.services.local_sync import record_local_operation

        conversation = (
            session.get(AgentConversation, memory.conversation_id)
            if memory.conversation_id
            else None
        )
        record_local_operation(
            session,
            project,
            "agent_memory",
            memory.public_id,
            {
                "project_public_id": project.public_id,
                "conversation_public_id": conversation.public_id if conversation else None,
                "scope": memory.scope,
                "kind": memory.kind,
                "content": memory.content,
                "importance": memory.importance,
                "source": memory.source_json,
            },
            base_version=0,
        )
    session.commit()
    session.refresh(memory)
    return memory


def list_memories(session: Session, project_id: int, *, limit: int = 100) -> list[AgentMemory]:
    return list(
        session.exec(
            select(AgentMemory)
            .where(or_(AgentMemory.project_id == project_id, AgentMemory.project_id.is_(None)))
            .order_by(AgentMemory.importance.desc(), AgentMemory.updated_at.desc())
            .limit(limit)
        ).all()
    )


def retrieve_memories(
    session: Session,
    project_id: int,
    query: str,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    candidates = list_memories(session, project_id, limit=200)
    ranked: list[tuple[float, AgentMemory]] = []
    for memory in candidates:
        memory_tokens = _tokens(memory.content)
        overlap = len(query_tokens & memory_tokens)
        coverage = overlap / max(len(query_tokens), 1)
        global_bonus = 0.04 if memory.scope == "global" else 0
        score = coverage * 0.72 + memory.importance * 0.24 + global_bonus
        if overlap or memory.importance >= 0.8:
            ranked.append((score, memory))
    ranked.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
    selected = ranked[:limit]
    now = utc_now()
    for _score, memory in selected:
        memory.last_used_at = now
        session.add(memory)
    if selected:
        session.commit()
    return [
        {
            "memory_id": memory.memory_id,
            "scope": memory.scope,
            "kind": memory.kind,
            "content": memory.content,
            "importance": memory.importance,
            "score": round(score, 3),
        }
        for score, memory in selected
    ]


def delete_memory(session: Session, project_id: int, memory_id: str) -> bool:
    memory = session.get(AgentMemory, memory_id)
    if memory is None or memory.project_id not in {None, project_id}:
        return False
    project = session.get(Project, project_id)
    if project is not None and project.agent_history_sync:
        from app.services.local_sync import record_local_operation

        record_local_operation(
            session,
            project,
            "agent_memory",
            memory.public_id,
            {"project_public_id": project.public_id},
            operation="delete",
            base_version=memory.version,
        )
    session.delete(memory)
    session.commit()
    return True


def capture_explicit_memory(
    session: Session,
    project_id: int,
    conversation_id: str,
    message: str,
) -> AgentMemory | None:
    lowered = message.lower()
    if not any(marker in lowered for marker in ("记住", "请记得", "remember", "以后都")):
        return None
    scope = (
        "global"
        if any(marker in lowered for marker in ("跨项目", "所有项目", "全局"))
        else "project"
    )
    return create_memory(
        session,
        project_id,
        AgentMemoryCreate(
            content=message,
            scope=scope,
            kind="preference",
            importance=0.85,
            conversation_id=conversation_id,
        ),
        source={"type": "explicit_user_instruction", "conversation_id": conversation_id},
    )
