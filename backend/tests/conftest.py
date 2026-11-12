"""Configuración de las pruebas.

La base de datos se redirige a un archivo SQLite temporal **antes** de
importar la aplicación, para que el motor se construya ya apuntando ahí.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_DIR_TEMPORAL = tempfile.mkdtemp(prefix="netdoc-tests-")
# NETDOC_PRUEBAS_DATABASE_URL: para correrlas contra otra base, como PostgreSQL. Se
# vacía al empezar y al terminar: debe ser una base solo para esto.
os.environ["NETDOC_DATABASE_URL"] = os.environ.get("NETDOC_PRUEBAS_DATABASE_URL") or (
    f"sqlite:///{Path(_DIR_TEMPORAL) / 'prueba.db'}"
)
os.environ["NETDOC_DIR_MEDIA"] = str(Path(_DIR_TEMPORAL) / "media")
os.environ["NETDOC_DIR_VISOR"] = str(Path(_DIR_TEMPORAL) / "visor")
os.environ["NETDOC_MONITOREO_TOKEN"] = "token-de-prueba"
# Los usuarios reales viven en .env, que la configuración también lee.
os.environ["NETDOC_USUARIOS"] = "{}"
# Dibujar teselas toma un proceso aparte por plano: solo las pruebas de
# teselas lo activan.
os.environ["NETDOC_TESELAS"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app import models as _modelos  # noqa: E402,F401  (puebla el metadata)
from app.db.base import Base  # noqa: E402
from app.db.session import SesionLocal, motor  # noqa: E402
from app.main import app  # noqa: E402
from app.scripts.cargar_catalogo import cargar_edificios, cargar_tipos  # noqa: E402
from app.servicios.autenticacion import abrir_sesion  # noqa: E402
from app.servicios.proteccion import COOKIE_HTTP  # noqa: E402

#: Desde otros equipos, la API solo atiende por HTTPS.
EQUIPO_LOCAL = ("127.0.0.1", 50000)


@pytest.fixture(scope="session", autouse=True)
def base_de_datos():
    Base.metadata.drop_all(motor)
    Base.metadata.create_all(motor)
    with SesionLocal() as sesion:
        cargar_edificios(sesion)
        cargar_tipos(sesion)
        sesion.commit()
    yield
    Base.metadata.drop_all(motor)


@pytest.fixture
def cliente(base_de_datos) -> TestClient:
    """Con la sesión del administrador ya iniciada."""
    with SesionLocal() as bd:
        token = abrir_sesion(bd, "pruebas")
        bd.commit()
    return TestClient(app, client=EQUIPO_LOCAL, cookies={COOKIE_HTTP: token})


@pytest.fixture
def anonimo(base_de_datos) -> TestClient:
    return TestClient(app, client=EQUIPO_LOCAL)


@pytest.fixture
def sesion():
    with SesionLocal() as s:
        yield s
