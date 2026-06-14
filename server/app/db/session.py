"""SQLAlchemy session + engine.

Soporta SQLite (dev local) y Postgres (Supabase / cualquier psql).
Detección por el prefijo del DSN. Pool config distinto según motor.

⚠️ Compatibilidad con PgBouncer transaction mode (Supabase Transaction Pooler):
las prepared statements de psycopg fallan en transaction-mode pooling porque
PgBouncer resetea el estado de la conexión entre transactions. Por eso
deshabilitamos prepared statements con `prepare_threshold=None` en el evento
`connect` cuando el motor es Postgres. Sin esto, el server explotaría tras
~5 ejecuciones del mismo query con: 'prepared statement "_pg3_X" does not exist'.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings


def _is_postgres(db_url: str) -> bool:
    return db_url.startswith("postgres://") or db_url.startswith("postgresql")


def _build_engine():
    """Crea engine con config apropiada según el motor."""
    db_url = settings.db_url

    # SQLAlchemy 2 prefiere `postgresql+psycopg://` para psycopg v3.
    # Supabase / cualquier URL `postgres://` o `postgresql://` la traducimos.
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif db_url.startswith("postgresql://") and "+psycopg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

    if db_url.startswith("sqlite"):
        # Dev local: SQLite, sin pool, mismo thread no constraint (FastAPI usa multi-thread).
        return create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            future=True,
        )

    # Postgres: pool razonable para Cloud Run.
    # - pool_pre_ping: evita "connection has been closed" cuando Supabase cierra idle.
    # - pool_recycle: re-abre conexiones cada 30min.
    eng = create_engine(
        db_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )

    # Disable psycopg prepared statements: incompatibles con PgBouncer transaction mode.
    @event.listens_for(eng, "connect")
    def _disable_prepared_statements(dbapi_conn, _record):
        try:
            dbapi_conn.prepare_threshold = None
        except AttributeError:
            # No es psycopg v3 (improbable, pero defensivo). Ignorar.
            pass

    return eng


engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
