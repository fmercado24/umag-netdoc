"""Cargar los planos de un edificio vacío desde el visor.

Solo para un edificio sin planos ni elementos: es el primer paso para empezar a
documentarlo. Lo que ya tiene planos se actualiza desde la terminal
(``app.scripts.cargar_planos``), donde se ve qué pasa con los elementos ya
ubicados sobre la versión anterior.

Los planos de un edificio grande no caben en un solo envío (los del CADI suman
unos 150 MB), así que se hace en dos pasos:

1. **Cada plano se sube por separado** y queda en espera, en
   ``media/pendientes/<EDIFICIO>/``, con el nombre de la nomenclatura. Se revisa
   al recibirlo: el nombre (que dice el piso y el tramo), que sea un SVG válido
   y que declare su tamaño. Subir otra vez el mismo nombre lo reemplaza.
2. **Al confirmar**, se crean de una vez los pisos y tramos que nombran, y los
   planos quedan vigentes. Desde ahí el edificio ya no está vacío.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import configuracion
from app.models import Edificio, Elemento, Piso, Plano, Tramo
from app.servicios.planos import (
    NOMENCLATURA,
    FormatoNoAdmitido,
    NombreLamina,
    NombreLaminaInvalido,
    SvgInvalido,
    dimensiones_svg,
    guardar_plano,
    interpretar_nombre_lamina,
    nombre_lamina,
    sanear_svg,
)

#: Los mismos nombres que pone el importador a los pisos que crea.
NOMBRES_PISO = {
    "P00": "Subterráneo",
    "P01": "Primer piso",
    "P02": "Segundo piso",
    "P03": "Tercer piso",
    "P04": "Cuarto piso",
    "P05": "Quinto piso",
    "P06": "Sexto piso",
}


class CargaNoPermitida(Exception):
    """El edificio ya tiene planos o elementos."""


@dataclass(frozen=True)
class Revision:
    """Lo que dice el nombre de un archivo, antes de subirlo."""

    archivo: str
    #: Nombre con que se guardará; nulo si el archivo se rechaza.
    nombre: str | None = None
    piso: str | None = None
    tramo: str | None = None
    #: «Piso 1, tramo 1», «Piso 2 completo», «Subterráneo».
    destino: str | None = None
    #: Por qué se rechaza; nulo si se acepta.
    error: str | None = None
    #: El nombre que debería tener, si se pudo deducir del original.
    sugerencia: str | None = None


@dataclass(frozen=True)
class Pendiente:
    """Un plano subido que espera a confirmarse."""

    nombre: str
    piso: str
    tramo: str | None
    destino: str
    ancho_px: int
    alto_px: int
    bytes: int


def describir_destino(piso: str, tramo: str | None) -> str:
    numero = int(piso[1:])
    nombre = "Subterráneo" if numero == 0 else f"Piso {numero}"
    if tramo:
        return f"{nombre}, tramo {tramo[1:]}"
    return nombre if numero == 0 else f"{nombre} completo"


def motivo_para_no_cargar(sesion: Session, edificio: Edificio) -> str | None:
    """Por qué no se pueden cargar planos desde el visor, o None si se puede."""
    elementos = sesion.scalar(
        select(func.count(Elemento.id)).where(Elemento.edificio_id == edificio.id)
    )
    planos = sesion.scalar(
        select(func.count(Plano.id)).join(Piso).where(Piso.edificio_id == edificio.id)
    )
    if not elementos and not planos:
        return None
    tiene = " y ".join(
        texto
        for cantidad, texto in ((planos, f"{planos} plano(s)"), (elementos, f"{elementos} elemento(s)"))
        if cantidad
    )
    return (
        f"{edificio.codigo} ya tiene {tiene}: desde el visor solo se cargan los planos de un "
        "edificio vacío. Para agregar o reemplazar planos, use app.scripts.cargar_planos "
        "(guía de edificio nuevo, sección 4)."
    )


def exigir_vacio(sesion: Session, edificio: Edificio) -> None:
    motivo = motivo_para_no_cargar(sesion, edificio)
    if motivo:
        raise CargaNoPermitida(motivo)


def nomenclatura(edificio: Edificio) -> str:
    """La nomenclatura con los ejemplos de ese edificio, no los del CADI."""
    return NOMENCLATURA.replace("cadi", edificio.codigo.lower())


def ejemplos(edificio: Edificio) -> dict:
    """Cómo deben llamarse los archivos de ese edificio."""
    codigo = edificio.codigo
    return {
        "nomenclatura": nomenclatura(edificio),
        "ejemplos": [
            {"nombre": nombre_lamina(codigo, "P01", "T1"), "destino": describir_destino("P01", "T1")},
            {"nombre": nombre_lamina(codigo, "P01", "T2"), "destino": describir_destino("P01", "T2")},
            {"nombre": nombre_lamina(codigo, "P02"), "destino": "Piso 2, si no se divide en tramos"},
            {"nombre": nombre_lamina(codigo, "P00"), "destino": describir_destino("P00", None)},
        ],
        #: Un edificio con un solo plano, de un piso y sin tramos.
        "unico": nombre_lamina(codigo, "P01"),
    }


def _interpretar(edificio: Edificio, archivo: str) -> NombreLamina:
    """Lanza ``NombreLaminaInvalido`` o ``FormatoNoAdmitido``.

    Con un nombre deducible, el mensaje no lo repite: se entrega aparte, en
    ``sugerencia``, para mostrarlo como «Debe llamarse …».
    """
    try:
        lamina = interpretar_nombre_lamina(archivo, edificio=edificio.codigo)
    except NombreLaminaInvalido as exc:
        if exc.sugerencia:
            raise NombreLaminaInvalido(
                f"«{archivo}» no sigue la nomenclatura: debe llamarse «{exc.sugerencia}»",
                exc.sugerencia,
            ) from exc
        if "no sigue la nomenclatura" in str(exc):
            raise NombreLaminaInvalido(
                f"«{archivo}» no sigue la nomenclatura {nomenclatura(edificio)}"
            ) from exc
        raise
    if lamina.extension != ".svg":
        raise FormatoNoAdmitido(
            f"«{archivo}» es {lamina.extension}: los planos se cargan en SVG, que se puede "
            "acercar sin perder nitidez (guía de edificio nuevo, sección 4)"
        )
    return lamina


def revisar(edificio: Edificio, archivo: str) -> Revision:
    try:
        lamina = _interpretar(edificio, archivo)
    except NombreLaminaInvalido as exc:
        if exc.sugerencia:
            return Revision(archivo, error=f"«{archivo}» no sigue la nomenclatura.", sugerencia=exc.sugerencia)
        return Revision(archivo, error=str(exc))
    except FormatoNoAdmitido as exc:
        return Revision(archivo, error=str(exc))
    return Revision(
        archivo,
        nombre=nombre_lamina(edificio.codigo, lamina.piso, lamina.tramo),
        piso=lamina.piso,
        tramo=lamina.tramo,
        destino=describir_destino(lamina.piso, lamina.tramo),
    )


def _carpeta(codigo_edificio: str):
    return configuracion.dir_planos_pendientes / codigo_edificio.upper()


def _ficha(ruta) -> Pendiente | None:
    try:
        return Pendiente(**json.loads(ruta.with_suffix(".json").read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def listar(edificio: Edificio) -> list[Pendiente]:
    carpeta = _carpeta(edificio.codigo)
    if not carpeta.is_dir():
        return []
    pendientes = [_ficha(ruta) for ruta in carpeta.glob("*.svg")]
    return sorted((p for p in pendientes if p), key=lambda p: (p.piso, p.tramo or ""))


def agregar(sesion: Session, edificio: Edificio, archivo: str, contenido: bytes) -> Pendiente:
    """Revisa el plano y lo deja en espera. Lanza ``CargaNoPermitida``,
    ``NombreLaminaInvalido``, ``FormatoNoAdmitido`` o ``SvgInvalido``."""
    exigir_vacio(sesion, edificio)
    lamina = _interpretar(edificio, archivo)
    contenido = sanear_svg(contenido)
    try:
        ancho, alto = dimensiones_svg(contenido)
    except ValueError as exc:
        raise SvgInvalido(f"«{archivo}»: {exc}") from exc

    nombre = nombre_lamina(edificio.codigo, lamina.piso, lamina.tramo)
    pendiente = Pendiente(
        nombre=nombre,
        piso=lamina.piso,
        tramo=lamina.tramo,
        destino=describir_destino(lamina.piso, lamina.tramo),
        ancho_px=ancho,
        alto_px=alto,
        bytes=len(contenido),
    )
    carpeta = _carpeta(edificio.codigo)
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / nombre).write_bytes(contenido)
    (carpeta / nombre).with_suffix(".json").write_text(
        json.dumps(asdict(pendiente), ensure_ascii=False), encoding="utf-8"
    )
    return pendiente


def quitar(edificio: Edificio, archivo: str) -> bool:
    """Saca un plano de la espera. El nombre se vuelve a armar con la
    nomenclatura: el que llega no se usa como ruta."""
    try:
        lamina = _interpretar(edificio, archivo)
    except (NombreLaminaInvalido, FormatoNoAdmitido):
        return False
    ruta = _carpeta(edificio.codigo) / nombre_lamina(edificio.codigo, lamina.piso, lamina.tramo)
    existia = ruta.exists()
    ruta.unlink(missing_ok=True)
    ruta.with_suffix(".json").unlink(missing_ok=True)
    return existia


def descartar_todo(codigo_edificio: str) -> None:
    """Recibe el código, no el edificio: se llama cuando la sesión ya se cerró."""
    carpeta = _carpeta(codigo_edificio)
    if not carpeta.is_dir():
        return
    for ruta in carpeta.iterdir():
        if ruta.suffix in (".svg", ".json"):
            ruta.unlink(missing_ok=True)
    try:
        carpeta.rmdir()
    except OSError:
        pass


@dataclass
class Resultado:
    pisos: list[str]
    tramos: list[str]
    planos: list[Plano]


def confirmar(sesion: Session, edificio: Edificio) -> Resultado:
    """Crea los pisos y tramos que nombran los planos en espera y los deja
    vigentes. Los archivos en espera se borran después, con ``descartar_todo``,
    cuando lo nuevo ya quedó guardado."""
    exigir_vacio(sesion, edificio)
    pendientes = listar(edificio)
    if not pendientes:
        raise CargaNoPermitida("No hay planos en espera: súbalos antes de confirmar.")

    pisos: dict[str, Piso] = {
        p.codigo: p for p in sesion.scalars(select(Piso).where(Piso.edificio_id == edificio.id))
    }
    resultado = Resultado(pisos=[], tramos=[], planos=[])
    for pendiente in pendientes:
        piso = pisos.get(pendiente.piso)
        if piso is None:
            piso = Piso(
                edificio=edificio,
                codigo=pendiente.piso,
                nombre=NOMBRES_PISO.get(pendiente.piso),
                orden=int(pendiente.piso[1:]),
            )
            sesion.add(piso)
            sesion.flush()
            pisos[piso.codigo] = piso
            resultado.pisos.append(piso.codigo)
        tramo = None
        if pendiente.tramo:
            tramo = next((t for t in piso.tramos if t.codigo == pendiente.tramo), None)
            if tramo is None:
                tramo = Tramo(piso=piso, codigo=pendiente.tramo, nombre=f"Tramo {pendiente.tramo[1:]}")
                sesion.add(tramo)
                sesion.flush()
                resultado.tramos.append(f"{piso.codigo}-{tramo.codigo}")
        contenido = (_carpeta(edificio.codigo) / pendiente.nombre).read_bytes()
        resultado.planos.append(
            guardar_plano(
                sesion,
                piso,
                tramo,
                pendiente.nombre,
                contenido,
                ancho_px=pendiente.ancho_px,
                alto_px=pendiente.alto_px,
            )
        )
    return resultado
