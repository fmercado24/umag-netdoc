"""Motor, fábrica de sesiones y dependencia de FastAPI."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import configuracion


def _crear_motor() -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if configuracion.es_sqlite:
        # SQLite necesita esto para poder usarse desde los hilos de FastAPI.
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(configuracion.database_url, **kwargs)


motor = _crear_motor()
SesionLocal = sessionmaker(bind=motor, autoflush=False, autocommit=False, future=True)


@event.listens_for(Engine, "connect")
def _activar_claves_foraneas(dbapi_connection, connection_record) -> None:
    """SQLite ignora las FOREIGN KEY salvo que se activen por conexión."""
    if configuracion.es_sqlite:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def obtener_sesion() -> Iterator[Session]:
    sesion = SesionLocal()
    try:
        yield sesion
        sesion.commit()
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()
