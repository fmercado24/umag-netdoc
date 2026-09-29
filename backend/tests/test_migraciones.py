"""Las migraciones de Alembic deben producir exactamente el esquema de los modelos."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app import models as _modelos  # noqa: F401  (puebla el metadata)
from app.db.base import Base
from app.scripts.migrar import REVISION_BASE, configuracion_alembic, migrar


def _diferencias(url: str) -> list:
    motor = create_engine(url)
    try:
        with motor.connect() as conexion:
            contexto = MigrationContext.configure(conexion, opts={"compare_type": True})
            return compare_metadata(contexto, Base.metadata)
    finally:
        motor.dispose()


def test_un_cambio_de_modelo_exige_su_migracion(tmp_path):
    # Si falla: falta "alembic revision --autogenerate" para el cambio del modelo.
    url = f"sqlite:///{tmp_path / 'nueva.db'}"
    migrar(url)
    assert _diferencias(url) == []


def test_una_base_anterior_a_las_migraciones_se_marca_sin_recrearse(tmp_path):
    # Una base de antes de las migraciones tiene el esquema de la revisión
    # base, sin la tabla de versión (así quedó la base real del CADI).
    url = f"sqlite:///{tmp_path / 'antigua.db'}"
    command.upgrade(configuracion_alembic(url), REVISION_BASE)
    motor = create_engine(url)
    with motor.begin() as conexion:
        conexion.execute(text("DROP TABLE alembic_version"))
        conexion.execute(text("INSERT INTO edificio (codigo, nombre, activo) VALUES ('X', 'X', 1)"))
    motor.dispose()

    migrar(url)

    motor = create_engine(url)
    with motor.connect() as conexion:
        assert "alembic_version" in inspect(conexion).get_table_names()
        assert conexion.execute(text("SELECT count(*) FROM edificio")).scalar() == 1
        version = conexion.execute(text("SELECT version_num FROM alembic_version")).scalar()
    motor.dispose()
    assert version > REVISION_BASE  # y se aplicaron las migraciones siguientes
    assert _diferencias(url) == []
