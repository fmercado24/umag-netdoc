"""Los demás usuarios de NetDoc, además del administrador.

    python -m app.scripts.usuarios                                    los lista
    python -m app.scripts.usuarios agregar NOMBRE [--edificio CADI]   pide su contraseña
    python -m app.scripts.usuarios clave NOMBRE                       la cambia y cierra sus sesiones
    python -m app.scripts.usuarios quitar NOMBRE

Con ``--edificio`` solo puede ver y modificar ese edificio; sin él, todos, como el
administrador. Con ``--generar`` (en ``agregar`` y ``clave``) la contraseña la
elige el programa y la muestra una sola vez. Si la entrada no es una terminal, la
contraseña se lee de ella.

Tienen la misma protección que el administrador: solo se guarda el hash Argon2id
de la contraseña, en ``.env`` (o en el archivo que indique ``NETDOC_ARCHIVO_ENV``),
con el mismo límite de intentos y las mismas sesiones. Con NetDoc corriendo, hay
que reiniciarlo para que tome los cambios. En un servidor se usa
``sudo netdoc usuario …``, que ya lo reinicia.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import UsuarioAdicional, configuracion
from app.db.session import SesionLocal
from app.models import Edificio
from app.scripts.definir_clave import (
    ARCHIVO_ENV,
    LARGO_RECOMENDADO,
    ClaveRechazada,
    guardar_variable,
    validar_clave,
)
from app.servicios.autenticacion import cerrar_sesiones_de, cifrar_clave

VARIABLE = "NETDOC_USUARIOS"

#: Minúsculas, para que no haya dos que solo se distingan por una mayúscula.
RE_NOMBRE = re.compile(r"[a-z][a-z0-9._-]{2,31}")

#: Sin los caracteres que se confunden al copiarlos a mano: 0 y O, 1, l e I.
_ALFABETO = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class UsuarioRechazado(ValueError):
    pass


def generar_clave() -> str:
    """Cuatro grupos de cinco caracteres al azar: unos 116 bits."""
    return "-".join("".join(secrets.choice(_ALFABETO) for _ in range(5)) for _ in range(4))


def validar_nombre(nombre: str) -> None:
    if not RE_NOMBRE.fullmatch(nombre):
        raise UsuarioRechazado(
            "El nombre debe tener de 3 a 32 caracteres: minúsculas, números, punto y "
            "guiones, empezando con una letra."
        )
    if nombre == configuracion.admin_usuario:
        raise UsuarioRechazado(f"{nombre} es el administrador: su contraseña se cambia aparte.")


def _edificio_existente(codigo: str) -> str:
    """El código como está en la base: un edificio mal escrito dejaría al usuario sin ver nada."""
    try:
        with SesionLocal() as bd:
            conocidos = list(bd.scalars(select(Edificio.codigo).order_by(Edificio.codigo)))
    except SQLAlchemyError as exc:
        raise UsuarioRechazado("No se pudo consultar los edificios en la base de datos.") from exc
    if codigo.upper() not in conocidos:
        raise UsuarioRechazado(
            f"No existe el edificio {codigo.upper()}. Los que hay: {', '.join(conocidos) or 'ninguno'}."
        )
    return codigo.upper()


def guardar_usuarios(usuarios: dict[str, UsuarioAdicional]) -> None:
    valor = json.dumps(
        {nombre: u.model_dump(exclude_none=True) for nombre, u in sorted(usuarios.items())},
        separators=(",", ":"),
    )
    guardar_variable(VARIABLE, valor, ARCHIVO_ENV)
    # Para lo que reste de este proceso; la API lo toma al reiniciarse.
    configuracion.usuarios = dict(usuarios)


def _pedir_clave(nombre: str, generar: bool) -> tuple[str, bool]:
    """La contraseña y si hay que mostrarla."""
    if generar:
        return generar_clave(), True
    if not sys.stdin.isatty():
        clave = sys.stdin.readline().rstrip("\r\n")
        validar_clave(clave, nombre)
        return clave, False
    while True:
        clave = getpass.getpass(f"Contraseña de {nombre}: ")
        try:
            validar_clave(clave, nombre)
        except ClaveRechazada as exc:
            print(exc)
            continue
        if getpass.getpass("Repítela: ") == clave:
            return clave, False
        print("No coinciden.")


def _cerrar_sesiones(nombre: str) -> None:
    try:
        with SesionLocal() as bd:
            cerrar_sesiones_de(bd, nombre)
            bd.commit()
    except SQLAlchemyError:
        print("Aviso: no se pudieron cerrar sus sesiones (¿falta aplicar las migraciones?).")


def _definir(nombre: str, edificio: str | None, generar: bool) -> None:
    clave, mostrar = _pedir_clave(nombre, generar)
    guardar_usuarios(
        {**configuracion.usuarios, nombre: UsuarioAdicional(clave_hash=cifrar_clave(clave), edificio=edificio)}
    )
    if mostrar:
        print(f"Contraseña de {nombre}: {clave}")
        print("No se guarda en ningún lado y no se puede volver a mostrar: anótala ahora.")
    elif len(clave) < LARGO_RECOMENDADO:
        print(f"Aviso: lo recomendado son {LARGO_RECOMENDADO} caracteres o más.")


def _alcance(usuario: UsuarioAdicional) -> str:
    return f"solo {usuario.edificio}" if usuario.edificio else "todos los edificios"


def listar() -> None:
    print(f"{configuracion.admin_usuario:<24} administrador, todos los edificios")
    for nombre, usuario in sorted(configuracion.usuarios.items()):
        print(f"{nombre:<24} {_alcance(usuario)}")


def agregar(nombre: str, edificio: str | None, generar: bool) -> None:
    validar_nombre(nombre)
    if nombre in configuracion.usuarios:
        raise UsuarioRechazado(f"{nombre} ya existe. Para cambiar su contraseña: clave {nombre}")
    if edificio:
        edificio = _edificio_existente(edificio)
    _definir(nombre, edificio, generar)
    print(f"Usuario {nombre} agregado ({_alcance(configuracion.usuarios[nombre])}).")


def cambiar_clave(nombre: str, generar: bool) -> None:
    actual = _existente(nombre)
    _definir(nombre, actual.edificio, generar)
    _cerrar_sesiones(nombre)
    print(f"Contraseña de {nombre} cambiada.")


def quitar(nombre: str) -> None:
    _existente(nombre)
    guardar_usuarios({n: u for n, u in configuracion.usuarios.items() if n != nombre})
    _cerrar_sesiones(nombre)
    print(f"Usuario {nombre} quitado.")


def _existente(nombre: str) -> UsuarioAdicional:
    try:
        return configuracion.usuarios[nombre]
    except KeyError:
        raise UsuarioRechazado(f"No existe el usuario {nombre}.") from None


def main(argumentos: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ordenes = analizador.add_subparsers(dest="orden")
    ordenes.add_parser("listar", help="Los usuarios y a qué tienen acceso")
    nuevo = ordenes.add_parser("agregar", help="Crea un usuario")
    nuevo.add_argument("nombre")
    nuevo.add_argument("--edificio", help="El único edificio que podrá ver y modificar")
    nuevo.add_argument("--generar", action="store_true", help="Elige la contraseña y la muestra")
    clave = ordenes.add_parser("clave", help="Cambia la contraseña de un usuario")
    clave.add_argument("nombre")
    clave.add_argument("--generar", action="store_true", help="Elige la contraseña y la muestra")
    ordenes.add_parser("quitar", help="Elimina un usuario").add_argument("nombre")
    opciones = analizador.parse_args(argumentos)

    try:
        if opciones.orden == "agregar":
            agregar(opciones.nombre, opciones.edificio, opciones.generar)
        elif opciones.orden == "clave":
            cambiar_clave(opciones.nombre, opciones.generar)
        elif opciones.orden == "quitar":
            quitar(opciones.nombre)
        else:
            listar()
            return 0
    except (UsuarioRechazado, ClaveRechazada) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Guardado en {ARCHIVO_ENV} (solo los hashes). Reinicia NetDoc para que lo tome.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
