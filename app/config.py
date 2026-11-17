import os

from sqlalchemy import URL, make_url


def get_database_url() -> URL:
    configured_url = os.getenv("DATABASE_URL")
    if configured_url:
        url = make_url(configured_url)
        if url.get_backend_name() != "postgresql":
            raise ValueError("DATABASE_URL must point to PostgreSQL.")
        return url.set(drivername="postgresql+psycopg")
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise ValueError("Set DB_PASSWORD in the local .env file or environment.")
    return URL.create(
        "postgresql+psycopg",
        username=os.getenv("DB_USER", "clinic_app"),
        password=password,
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "clinic_db"),
    )
