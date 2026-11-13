"""Motor, fábrica de sesiones y dependencia de FastAPI.

Varias personas usan NetDoc a la vez. Las lecturas se atienden en paralelo; las
peticiones que escriben, de a una (``tomar_turno_de_escritura``): así ninguna
decide con datos que otra está cambiando, como el correlativo que le toca a un
elemento nuevo.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import configuracion

#: Segundos que una petición espera a que otra termine de escribir antes de
#: rendirse (la API responde entonces 503: ver ``app.main``).
ESPERA_DE_TURNO = 30

#: Identifica el turno de escritura de NetDoc entre los bloqueos de PostgreSQL.
_CLAVE_DE_TURNO = 7_316_001


def _crear_motor() -> Engine:
    # Tantas conexiones como hilos atienden peticiones (40): cada tesela de un
    # plano consulta la sesión, y llegan de a decenas por persona.
    kwargs: dict = {"pool_pre_ping": True, "future": True, "pool_size": 20, "max_overflow": 20}
    if configuracion.es_sqlite:
        # check_same_thread: para poder usarse desde los hilos de FastAPI.
        # timeout: lo que espera si otra conexión está escribiendo.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": ESPERA_DE_TURNO}
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


def tomar_turno_de_escritura(sesion: Session) -> None:
    """Espera a que termine la petición que esté escribiendo y toma su lugar.

    Debe ser lo primero que haga la sesión. El turno se entrega solo, al
    confirmar o deshacer la transacción. Mientras tanto las lecturas siguen
    atendiéndose, y ven los datos como estaban antes de esta petición.
    """
    if configuracion.es_sqlite:
        sesion.execute(text("BEGIN IMMEDIATE"))
    elif sesion.get_bind().dialect.name == "postgresql":
        sesion.execute(text(f"SET LOCAL lock_timeout = '{ESPERA_DE_TURNO}s'"))
        sesion.execute(text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": _CLAVE_DE_TURNO})


#: En SQLite, las peticiones trabajan con la base de a ``sqlite_a_la_vez`` (una);
#: las demás esperan unos milisegundos. El módulo ``sqlite3`` suelta y retoma el
#: candado del intérprete en cada fila que lee: con varios hilos leyendo a la vez
#: se lo disputan y todo se vuelve cientos de veces más lento (medido con los
#: datos del CADI: el plano tarda 8 ms solo y 1,6 s pedido por ocho personas a la
#: vez; de a una, 60 ms). PostgreSQL no lo necesita: entrega las filas de una vez.
#: No es reentrante: una ruta debe usar una sola sesión.
_paso = (
    threading.BoundedSemaphore(max(1, configuracion.sqlite_a_la_vez))
    if configuracion.es_sqlite
    else nullcontext()
)


@contextmanager
def sesion_de_trabajo(*, escribe: bool = False) -> Iterator[Session]:
    """La sesión de una petición: confirma al terminar bien y deshace si falla.

    Con ``escribe``, primero espera el turno de escritura, y lo hace antes de
    ocupar el paso: si el turno lo tiene una importación larga, quienes solo
    consultan siguen siendo atendidos.
    """
    sesion = SesionLocal()
    try:
        if escribe:
            tomar_turno_de_escritura(sesion)
        with _paso:
            yield sesion
            sesion.commit()
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI para lo que no necesita turno, como el ingreso."""
    with sesion_de_trabajo() as sesion:
        yield sesion
