"""Lleva el esquema de la base a la última migración.

    python -m app.scripts.migrar

Es lo que corre ``iniciar.sh`` al arrancar. En una base nueva crea todo con las
migraciones de Alembic, igual en SQLite que en PostgreSQL. Una base creada
antes de que existieran (con ``init_db`` y ajustes a mano) ya tiene el esquema
de la revisión base: se la marca en esa revisión y se aplican las siguientes.

Para cambiar el modelo: editar ``app/models``, generar la migración con
``alembic revision --autogenerate -m "<qué cambia>"``, revisarla y correr este
script. La prueba ``test_migraciones`` falla si un modelo cambia sin migración.
"""

from __future__ import annotations

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.core.config import DIR_BACKEND, configuracion

#: Revisión cuyo esquema tienen las bases anteriores a las migraciones.
REVISION_BASE = "0001"


def configuracion_alembic(url: str) -> Config:
    config = Config(str(DIR_BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(DIR_BACKEND / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def migrar(url: str) -> None:
    config = configuracion_alembic(url)
    motor = create_engine(url)
    try:
        tablas = set(inspect(motor).get_table_names())
    finally:
        motor.dispose()

    if "alembic_version" not in tablas and "elemento" in tablas:
        print(f"Base anterior a las migraciones: se marca en la revisión {REVISION_BASE}.")
        command.stamp(config, REVISION_BASE)
    command.upgrade(config, "head")


def main() -> None:
    print(f"Base de datos: {configuracion.database_url}")
    migrar(configuracion.database_url)
    print("Esquema al día.")


if __name__ == "__main__":
    main()
