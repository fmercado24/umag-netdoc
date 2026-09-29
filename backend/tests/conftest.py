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
os.environ["NETDOC_DATABASE_URL"] = f"sqlite:///{Path(_DIR_TEMPORAL) / 'prueba.db'}"
os.environ["NETDOC_DIR_MEDIA"] = str(Path(_DIR_TEMPORAL) / "media")
os.environ["NETDOC_MONITOREO_TOKEN"] = "token-de-prueba"

from fastapi.testclient import TestClient  # noqa: E402

from app import models as _modelos  # noqa: E402,F401  (puebla el metadata)
from app.db.base import Base  # noqa: E402
from app.db.session import SesionLocal, motor  # noqa: E402
from app.main import app  # noqa: E402
from app.scripts.cargar_catalogo import cargar_edificios, cargar_tipos  # noqa: E402


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
    return TestClient(app)


@pytest.fixture
def sesion():
    with SesionLocal() as s:
        yield s
