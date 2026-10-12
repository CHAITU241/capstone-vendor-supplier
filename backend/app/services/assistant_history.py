"""Persistent, supplier-scoped chat history with strict audience separation."""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import AssistantMessage


def conversation_history(
    db: Session, supplier_id: uuid.UUID, audience: str, *, limit: int = 12,
) -> list[AssistantMessage]:
    recent = list(db.scalars(
        select(AssistantMessage)
        .where(
            AssistantMessage.supplier_id == supplier_id,
            AssistantMessage.audience == audience,
        )
        .order_by(AssistantMessage.sequence.desc())
        .limit(limit)
    ).all())
    return list(reversed(recent))


def save_exchange(
    db: Session,
    supplier_id: uuid.UUID,
    audience: str,
    question: str,
    answer: str,
    citations: list[dict] | None = None,
) -> None:
    last_sequence = db.scalar(
        select(func.max(AssistantMessage.sequence)).where(
            AssistantMessage.supplier_id == supplier_id,
            AssistantMessage.audience == audience,
        )
    ) or 0
    db.add_all([
        AssistantMessage(
            supplier_id=supplier_id, audience=audience, role="user",
            content=question, sequence=last_sequence + 1,
        ),
        AssistantMessage(
            supplier_id=supplier_id, audience=audience, role="assistant",
            content=answer, citations=citations or [], sequence=last_sequence + 2,
        ),
    ])
    db.commit()


def clear_history(db: Session, supplier_id: uuid.UUID, audience: str) -> None:
    db.execute(delete(AssistantMessage).where(
        AssistantMessage.supplier_id == supplier_id,
        AssistantMessage.audience == audience,
    ))
    db.commit()
