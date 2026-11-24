from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import now
from app.errors import DomainError
from app.workflow_models import Notification


def notify(session: Session, user_id: int, kind: str, message: str, subject_id: int) -> None:
    session.add(
        Notification(
            user_id=user_id,
            kind=kind,
            message=message,
            subject_id=subject_id,
            created_at=now(session),
        )
    )


def list_notifications(session: Session, user_id: int) -> list[Notification]:
    query = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
    )
    return list(session.scalars(query))


def mark_read(session: Session, user_id: int, notification_id: int) -> None:
    notification = session.scalar(
        select(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user_id)
        .with_for_update()
    )
    if notification is None:
        raise DomainError(404, "notification_not_found", "Notification not found.")
    if notification.read_at is None:
        notification.read_at = now(session)
