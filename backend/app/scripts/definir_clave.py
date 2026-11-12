"""Define la contraseña del administrador y cierra todas sus sesiones.

    python -m app.scripts.definir_clave                pide una contraseña nueva
    python -m app.scripts.definir_clave --si-falta     solo si aún no hay una (iniciar.sh)
    python -m app.scripts.definir_clave --desbloquear  levanta el bloqueo por intentos fallidos,
                                                       sin cambiar la contraseña

Su hash se guarda en ``.env``, en la raíz del repositorio (o en el archivo que
indique ``NETDOC_ARCHIVO_ENV``): no se versiona y queda legible solo para su
dueño. Con NetDoc corriendo, hay que reiniciarlo para que tome la contraseña
nueva. En un servidor se usa ``sudo netdoc clave``, que ya lo reinicia.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import DIR_PROYECTO, configuracion
from app.db.session import SesionLocal
from app.servicios.autenticacion import (
    cerrar_todas_las_sesiones,
    cifrar_clave,
    clave_definida,
    levantar_bloqueos,
)

#: En el servidor, /etc/netdoc/netdoc.env (lo indica instalar-servidor.sh).
ARCHIVO_ENV = Path(os.environ.get("NETDOC_ARCHIVO_ENV") or DIR_PROYECTO / ".env")
VARIABLE = "NETDOC_ADMIN_CLAVE_HASH"

#: OWASP ASVS exige 8 como mínimo y recomienda 15 o más.
LARGO_MINIMO = 8
LARGO_RECOMENDADO = 15


class ClaveRechazada(ValueError):
    pass


def validar_clave(clave: str, usuario: str) -> None:
    if len(clave) < LARGO_MINIMO:
        raise ClaveRechazada(f"Debe tener al menos {LARGO_MINIMO} caracteres.")
    if usuario.lower() in clave.lower():
        raise ClaveRechazada("No puede contener el nombre de usuario.")


def guardar_variable(variable: str, valor: str, archivo: Path = ARCHIVO_ENV) -> None:
    """Reemplaza la variable en ``archivo`` sin tocar las demás líneas."""
    if "'" in valor or "\n" in valor:
        raise ValueError(f"{variable} no puede llevar comillas simples ni saltos de línea")
    lineas = archivo.read_text(encoding="utf-8").splitlines() if archivo.exists() else []
    lineas = [linea for linea in lineas if not linea.startswith(f"{variable}=")]
    # Entre comillas simples: un hash lleva "$", que docker compose interpretaría.
    lineas.append(f"{variable}='{valor}'")

    # mkstemp lo crea legible solo para su dueño; os.replace no deja a medias.
    descriptor, temporal = tempfile.mkstemp(dir=archivo.parent, prefix=".env-")
    with os.fdopen(descriptor, "w", encoding="utf-8") as salida:
        salida.write("\n".join(lineas) + "\n")
    os.replace(temporal, archivo)


def guardar_hash(valor: str, archivo: Path = ARCHIVO_ENV) -> None:
    guardar_variable(VARIABLE, valor, archivo)


def _pedir_clave() -> str:
    while True:
        clave = getpass.getpass("Nueva contraseña: ")
        try:
            validar_clave(clave, configuracion.admin_usuario)
        except ClaveRechazada as exc:
            print(exc)
            continue
        if getpass.getpass("Repítela: ") == clave:
            return clave
        print("No coinciden.")


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    modo = argumentos.add_mutually_exclusive_group()
    modo.add_argument("--si-falta", action="store_true", help="Solo si aún no hay una")
    modo.add_argument("--desbloquear", action="store_true", help="Levanta el bloqueo por intentos")
    opciones = argumentos.parse_args()

    if opciones.desbloquear:
        with SesionLocal() as bd:
            levantar_bloqueos(bd)
            bd.commit()
        print("Ingreso desbloqueado.")
        return 0
    if opciones.si_falta and clave_definida():
        return 0
    if not sys.stdin.isatty():
        print(
            f"No hay contraseña de administrador y esta terminal no permite pedirla. "
            f"Ejecute en una terminal: python -m app.scripts.definir_clave "
            f"(el usuario es {configuracion.admin_usuario}).",
            file=sys.stderr,
        )
        return 1

    print(f"Contraseña del administrador {configuracion.admin_usuario}.")
    clave = _pedir_clave()
    if len(clave) < LARGO_RECOMENDADO:
        print(f"Aviso: lo recomendado son {LARGO_RECOMENDADO} caracteres o más.")
    guardar_hash(cifrar_clave(clave))
    print(f"Guardada en {ARCHIVO_ENV} (solo su hash).")

    try:
        with SesionLocal() as bd:
            cerrar_todas_las_sesiones(bd)
            levantar_bloqueos(bd)
            bd.commit()
    except SQLAlchemyError:
        print("Aviso: no se pudieron cerrar las sesiones (¿falta aplicar las migraciones?).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
