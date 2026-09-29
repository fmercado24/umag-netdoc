"""Entorno de migraciones de Alembic."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models as _modelos  # noqa: F401  (puebla Base.metadata)
from app.core.config import configuracion
from app.db.base import Base

config = context.config
# Una URL explícita (la que fija app.scripts.migrar o una prueba) tiene
# prioridad; si no, la de la configuración de la aplicación.
URL = config.get_main_option("sqlalchemy.url") or configuracion.database_url
ES_SQLITE = URL.startswith("sqlite")
config.set_main_option("sqlalchemy.url", URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=ES_SQLITE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if ES_SQLITE:
            # En modo batch SQLite recrea la tabla: la borra y la vuelve a
            # crear. Con las claves foráneas activas ese borrado arrastraría en
            # cascada las filas que la referencian (historial, fotografías…).
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite no soporta ALTER TABLE completo: Alembic recrea la tabla.
            render_as_batch=ES_SQLITE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
