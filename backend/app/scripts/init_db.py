"""Crea el esquema en la base configurada.

    python -m app.scripts.init_db [--recrear]

Atajo para desarrollo. En despliegue el esquema se gestiona con Alembic
(``alembic upgrade head``).
"""

from __future__ import annotations

import argparse

from app import models as _modelos  # noqa: F401  (registra los modelos en el metadata)
from app.core.config import configuracion
from app.db.base import Base
from app.db.session import motor


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea el esquema de la base de datos")
    parser.add_argument(
        "--recrear",
        action="store_true",
        help="Elimina las tablas existentes antes de crearlas (¡destructivo!)",
    )
    args = parser.parse_args()

    print(f"Base de datos: {configuracion.database_url}")

    if args.recrear:
        respuesta = input("Esto borra todos los datos. Escriba 'si' para continuar: ")
        if respuesta.strip().lower() != "si":
            print("Cancelado.")
            return
        Base.metadata.drop_all(motor)
        print("Tablas eliminadas.")

    Base.metadata.create_all(motor)
    print(f"Esquema creado: {len(Base.metadata.tables)} tablas.")


if __name__ == "__main__":
    main()
