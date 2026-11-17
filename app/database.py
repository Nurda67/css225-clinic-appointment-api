from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

CLINIC_TZ = timezone(timedelta(hours=5))


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(
        self,
        url: URL,
        *,
        clock: Callable[[], datetime] | None = None,
        schema: str | None = None,
    ) -> None:
        connection_options: dict[str, object] = {"connect_timeout": 5}
        if schema is not None:
            if not schema.isidentifier() or not schema.isascii():
                raise ValueError("Invalid database schema name.")
            connection_options["options"] = f"-csearch_path={schema}"
        self.engine = create_engine(
            url, pool_pre_ping=True, connect_args=connection_options, hide_parameters=True
        )
        self.session_factory = sessionmaker(
            self.engine, expire_on_commit=False, info={"clock": clock}
        )

    def dispose(self) -> None:
        self.engine.dispose()


def now(session: Session) -> datetime:
    clock = session.info.get("clock")
    current = clock() if clock is not None else datetime.now(CLINIC_TZ)
    return current.astimezone(CLINIC_TZ)
