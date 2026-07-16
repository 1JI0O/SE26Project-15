from __future__ import annotations

from typing import Any

from sqlmodel import Session, func, select

from app.models.entities import AgentRun, AgentRunEvent
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
        event = AgentRunEvent(
            run_id=self.run.run_id,
            conversation_id=self.run.conversation_id,
            project_id=self.run.project_id,
            sequence=self.sequence,
            event_type=event_type,
            payload_json=payload or {},
        )
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return event


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
