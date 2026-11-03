"""Copia los datos de una base a otra con el mismo esquema.

    python -m app.scripts.copiar_base --origen URL --destino URL [--reemplazar]

Sirve para pasar de SQLite a PostgreSQL, o al revés, y para traer los datos de
otro equipo. El destino debe tener las migraciones aplicadas y estar vacío, salvo
con ``--reemplazar``. No copia sesiones ni intentos de ingreso: son de cada
instalación. Todo ocurre en una transacción: si algo falla, el destino queda
como estaba.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app import models as _modelos  # noqa: F401  (puebla el metadata)
from app.db.base import Base

#: Son de cada instalación: en otra, una sesión o un bloqueo no significan nada.
TABLAS_PROPIAS = frozenset({"sesion_acceso", "intento_ingreso"})


class DestinoConDatos(RuntimeError):
    pass


def _en_utc(conexion) -> None:
    """SQLite guarda las marcas en UTC y sin zona: PostgreSQL debe leerlas así."""
    if conexion.dialect.name == "postgresql":
        conexion.execute(text("SET LOCAL TIME ZONE 'UTC'"))


def _columnas_hacia_si_misma(tabla) -> list[str]:
    return [
        columna.name
        for columna in tabla.columns
        if any(fk.column.table is tabla for fk in columna.foreign_keys)
    ]


def copiar(origen_url: str, destino_url: str, *, reemplazar: bool = False) -> dict[str, int]:
    """Devuelve cuántas filas se copiaron por tabla."""
    tablas = [t for t in Base.metadata.sorted_tables if t.name not in TABLAS_PROPIAS]
    origen = create_engine(origen_url)
    destino = create_engine(destino_url)
    copiadas: dict[str, int] = {}
    try:
        with origen.connect() as lectura, destino.begin() as escritura:
            _en_utc(lectura)
            _en_utc(escritura)

            existentes = sum(
                escritura.scalar(select(func.count()).select_from(t)) or 0 for t in tablas
            )
            if existentes and not reemplazar:
                raise DestinoConDatos(
                    f"El destino ya tiene {existentes} filas. Use --reemplazar para borrarlas."
                )
            for tabla in reversed(Base.metadata.sorted_tables):
                escritura.execute(tabla.delete())

            for tabla in tablas:
                filas = [dict(f._mapping) for f in lectura.execute(select(tabla))]
                copiadas[tabla.name] = len(filas)
                if not filas:
                    continue
                # Un elemento puede apuntar a otro de la misma tabla (su rack), que
                # quizá aún no esté: esas columnas se llenan en un segundo paso.
                propias = _columnas_hacia_si_misma(tabla)
                escritura.execute(
                    tabla.insert(), [{**f, **dict.fromkeys(propias)} for f in filas]
                )
                llave = tabla.primary_key.columns.values()[0]
                for fila in filas:
                    valores = {c: fila[c] for c in propias if fila[c] is not None}
                    if valores:
                        escritura.execute(
                            tabla.update().where(llave == fila[llave.name]).values(**valores)
                        )

            # Las filas traen su id: PostgreSQL debe seguir contando después del mayor.
            if escritura.dialect.name == "postgresql":
                for tabla in Base.metadata.sorted_tables:
                    llaves = tabla.primary_key.columns.values()
                    if len(llaves) == 1 and llaves[0].autoincrement is not False:
                        escritura.execute(
                            text(
                                "SELECT setval(pg_get_serial_sequence(:tabla, :columna), "
                                f'COALESCE((SELECT MAX("{llaves[0].name}") FROM "{tabla.name}"), 0) + 1, '
                                "false) WHERE pg_get_serial_sequence(:tabla, :columna) IS NOT NULL"
                            ),
                            {"tabla": tabla.name, "columna": llaves[0].name},
                        )
    finally:
        origen.dispose()
        destino.dispose()
    return copiadas


def _sin_clave(url: str) -> str:
    """Para mostrarla: la contraseña de la URL no debe quedar en la terminal."""
    return make_url(url).render_as_string()


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    argumentos.add_argument("--origen", required=True, help="URL de la base de origen")
    argumentos.add_argument("--destino", required=True, help="URL de la base de destino")
    argumentos.add_argument("--reemplazar", action="store_true", help="Borra lo que tenga el destino")
    opciones = argumentos.parse_args()

    for nombre, url in (("origen", opciones.origen), ("destino", opciones.destino)):
        motor = create_engine(url)
        try:
            if "elemento" not in inspect(motor).get_table_names():
                print(f"Error: {_sin_clave(url)} no tiene el esquema: aplique las migraciones.", file=sys.stderr)
                return 1
        except SQLAlchemyError:
            print(f"Error: no se pudo abrir la base de {nombre}: {_sin_clave(url)}", file=sys.stderr)
            return 1
        finally:
            motor.dispose()

    try:
        copiadas = copiar(opciones.origen, opciones.destino, reemplazar=opciones.reemplazar)
    except DestinoConDatos as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"De {_sin_clave(opciones.origen)} a {_sin_clave(opciones.destino)}:")
    print(f"{sum(copiadas.values())} filas en {len(copiadas)} tablas")
    print(f"{copiadas.get('elemento', 0)} elementos, {copiadas.get('plano', 0)} planos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
