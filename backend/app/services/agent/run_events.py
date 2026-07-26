from __future__ import annotations

from typing import Any

from sqlmodel import Session, func, select

from app.models.entities import AgentConversation, AgentRun, AgentRunEvent, Project
from app.schemas.agent import AgentRunEventRead


def event_to_read(event: AgentRunEvent) -> AgentRunEventRead:
    return AgentRunEventRead(
        event_id=event.event_id,
        run_id=event.run_id,
        conversation_id=event.conversation_id,
        project_id=event.project_id,
        sequence=event.sequence,
        event_type=event.event_type,
        payload=event.payload_json,
        created_at=event.created_at,
    )


def append_event(
    session: Session,
    run: AgentRun,
    sequence: int,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> AgentRunEvent:
    """Insert one run event row (plus its local-sync operation) and commit.

    Shared by the session-bound ``RunEventEmitter`` and the thread-safe shared event bus
    used by parallel trace sub-agents, so both paths stay behaviorally identical.
    """

    event = AgentRunEvent(
        run_id=run.run_id,
        conversation_id=run.conversation_id,
        project_id=run.project_id,
        sequence=sequence,
        event_type=event_type,
        payload_json=payload or {},
    )
    session.add(event)
    project = session.get(Project, run.project_id)
    if project is not None and project.agent_history_sync:
        from app.services.local_sync import agent_event_payload, record_local_operation

        record_local_operation(
            session,
            project,
            "agent_run_event",
            event.public_id,
            {
                "project_public_id": project.public_id,
                "run_public_id": run.public_id,
                "conversation_public_id": session.exec(
                    select(AgentConversation.public_id).where(
                        AgentConversation.conversation_id == event.conversation_id
                    )
                ).first(),
                "sequence": event.sequence,
                "event_type": event.event_type,
                "payload": agent_event_payload(event.payload_json),
                "created_at": event.created_at.isoformat(),
            },
            base_version=0,
        )
    session.commit()
    session.refresh(event)
    return event


class RunEventEmitter:
    def __init__(self, session: Session, run: AgentRun) -> None:
        self.session = session
        self.run = run
        current = session.exec(
            select(func.max(AgentRunEvent.sequence)).where(AgentRunEvent.run_id == run.run_id)
        ).one()
        self.sequence = int(current or 0)

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> AgentRunEvent:
        self.sequence += 1
        return append_event(self.session, self.run, self.sequence, event_type, payload)


def list_run_events(
    session: Session,
    project_id: int,
    run_id: str,
    *,
    after: int = 0,
) -> list[AgentRunEventRead]:
    events = session.exec(
        select(AgentRunEvent)
        .where(
            AgentRunEvent.project_id == project_id,
            AgentRunEvent.run_id == run_id,
            AgentRunEvent.sequence > after,
        )
        .order_by(AgentRunEvent.sequence.asc())
    ).all()
    return [event_to_read(event) for event in events]
