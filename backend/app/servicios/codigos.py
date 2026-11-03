"""Convención de nomenclatura (SOP-DSI-RED-001, sección 8).

Estructura del código::

    <UBICACIÓN GENERAL>-<EQUIPO>-<UBICACIÓN ESPECÍFICA>[-<DETALLE/PUERTO>]

Ejemplos del SOP::

    CADI-R04-P01-T2              Rack N°4 del CADI, Piso 1 Tramo 2
    CADI-PD-P01-T3-R01-T20       Punto de datos conectado al puerto 20 del
                                 patch panel de teléfono del Rack N°1
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select, true
from sqlalchemy.orm import Session

RE_CODIGO = re.compile(
    r"^(?P<edificio>[A-Z]{2,5})"
    r"-(?P<tipo>[A-Z]+)(?P<correlativo>\d{1,3})?"
    r"-(?P<piso>P\d{2}|PXX)"
    r"(?:-(?P<tramo>T\d{1,2}))?"
    r"(?:-(?P<detalle>.+))?$"
)

RE_NUMERO = re.compile(r"(\d+)")

#: Prefijo del rótulo de un punto de datos → servicio que presta.
#: Solo se mapean los prefijos respaldados por la leyenda de VLANs y por los
#: rótulos de los switches (SW-COM / SW-TEL / SW CCTV). El resto se reporta.
SERVICIOS_POR_PREFIJO: dict[str, str] = {"D": "datos", "T": "telefonia", "C": "cctv"}

#: Detalle del código de un punto de datos cuyo puerto de origen no se conoce.
PREFIJO_SIN_ROTULO = "SIN-ROTULO-"


class CodigoInvalido(ValueError):
    """El código no cumple la convención de la sección 8 del SOP."""


@dataclass(frozen=True)
class CodigoDescompuesto:
    edificio: str
    tipo: str
    correlativo: int | None
    piso: str
    tramo: str | None
    detalle: str | None


def normalizar_piso(valor: str | int) -> str:
    """``1`` / ``"Piso 1"`` / ``"p01"`` → ``"P01"``; exterior → ``"PXX"``."""
    if isinstance(valor, int):
        return f"P{valor:02d}"
    texto = valor.strip().upper()
    if texto in {"PXX", "EXTERIOR"}:
        return "PXX"
    coincidencia = RE_NUMERO.search(texto)
    if not coincidencia:
        raise CodigoInvalido(f"No se pudo interpretar el piso: {valor!r}")
    return f"P{int(coincidencia.group(1)):02d}"


def normalizar_tramo(valor: str | int | None) -> str | None:
    """``2`` / ``"Tramo 2"`` / ``"t2"`` → ``"T2"``."""
    if valor is None:
        return None
    if isinstance(valor, int):
        return f"T{valor}"
    texto = valor.strip().upper()
    if not texto:
        return None
    coincidencia = RE_NUMERO.search(texto)
    if not coincidencia:
        raise CodigoInvalido(f"No se pudo interpretar el tramo: {valor!r}")
    return f"T{int(coincidencia.group(1))}"


def construir_codigo(
    *,
    edificio: str,
    tipo: str,
    piso: str | int,
    correlativo: int | None = None,
    tramo: str | int | None = None,
    detalle: str | None = None,
) -> str:
    """Arma el código único de un elemento."""
    equipo = tipo.strip().upper()
    if correlativo is not None:
        equipo = f"{equipo}{correlativo:02d}"

    partes = [edificio.strip().upper(), equipo, normalizar_piso(piso)]
    tramo_norm = normalizar_tramo(tramo)
    if tramo_norm:
        partes.append(tramo_norm)
    if detalle:
        partes.append(detalle.strip().upper())
    return "-".join(partes)


def descomponer_codigo(codigo: str) -> CodigoDescompuesto:
    """Operación inversa de :func:`construir_codigo`."""
    coincidencia = RE_CODIGO.match(codigo.strip().upper())
    if not coincidencia:
        raise CodigoInvalido(f"El código {codigo!r} no sigue la convención del SOP sección 8")
    datos = coincidencia.groupdict()
    return CodigoDescompuesto(
        edificio=datos["edificio"],
        tipo=datos["tipo"],
        correlativo=int(datos["correlativo"]) if datos["correlativo"] else None,
        piso=datos["piso"],
        tramo=datos["tramo"],
        detalle=datos["detalle"],
    )


def correlativos_usados(
    sesion: Session,
    *,
    edificio_id: int,
    tipo_elemento_id: int,
    piso_id: int,
    salvo: int | None = None,
) -> set[int]:
    """Correlativos ya usados en el trío tipo + edificio + piso.

    SOP sección 8.5: un código nunca se reutiliza, así que también cuentan los
    elementos dados de baja y los códigos de los que se trasladaron a otro lugar.
    ``salvo`` no cuenta los de ese elemento: el suyo puede recuperarlo.
    """
    from app.models import (  # import local: evita ciclo de importación
        Edificio,
        Elemento,
        HistorialElemento,
        Piso,
        TipoElemento,
    )

    usados = {
        c
        for c in sesion.scalars(
            select(Elemento.correlativo).where(
                Elemento.edificio_id == edificio_id,
                Elemento.tipo_elemento_id == tipo_elemento_id,
                Elemento.piso_id == piso_id,
                Elemento.id != salvo if salvo is not None else true(),
            )
        )
        if c is not None
    }
    edificio = sesion.get(Edificio, edificio_id).codigo
    tipo = sesion.get(TipoElemento, tipo_elemento_id).codigo
    piso = sesion.get(Piso, piso_id).codigo
    anteriores = sesion.scalars(
        select(HistorialElemento.valor_anterior).where(
            HistorialElemento.campo == "codigo",
            HistorialElemento.valor_anterior.like(f"{edificio}-{tipo}%-{piso}%"),
            HistorialElemento.elemento_id != salvo if salvo is not None else true(),
        )
    )
    for codigo in anteriores:
        try:
            partes = descomponer_codigo(codigo)
        except CodigoInvalido:
            continue
        if partes.tipo == tipo and partes.piso == piso and partes.correlativo is not None:
            usados.add(partes.correlativo)
    return usados


def siguiente_correlativo(
    sesion: Session, *, edificio_id: int, tipo_elemento_id: int, piso_id: int
) -> int:
    """Correlativo siguiente para el trío tipo + edificio + piso."""
    usados = correlativos_usados(
        sesion, edificio_id=edificio_id, tipo_elemento_id=tipo_elemento_id, piso_id=piso_id
    )
    return max(usados, default=0) + 1


def codigo_ocupado(sesion: Session, codigo: str, *, salvo: int | None = None) -> bool:
    """Si lo tiene o lo tuvo un elemento; ``salvo`` puede recuperar el suyo."""
    from app.models import (  # import local: evita ciclo de importación
        Elemento,
        HistorialElemento,
    )

    duenos = set(sesion.scalars(select(Elemento.id).where(Elemento.codigo == codigo)))
    duenos |= set(
        sesion.scalars(
            select(HistorialElemento.elemento_id).where(
                HistorialElemento.campo == "codigo", HistorialElemento.valor_anterior == codigo
            )
        )
    )
    return bool(duenos - {salvo})


def elemento_por_codigo(sesion: Session, codigo: str):
    """El elemento con ese código o, si se trasladó, el que lo tenía: lo que aún
    use el código anterior (un host de Zabbix, un enlace guardado) sigue funcionando."""
    from app.models import (  # import local: evita ciclo de importación
        Elemento,
        HistorialElemento,
    )

    elemento = sesion.scalar(select(Elemento).where(Elemento.codigo == codigo))
    if elemento is not None:
        return elemento
    return sesion.scalar(
        select(Elemento)
        .join(HistorialElemento, HistorialElemento.elemento_id == Elemento.id)
        .where(HistorialElemento.campo == "codigo", HistorialElemento.valor_anterior == codigo)
        .order_by(HistorialElemento.id.desc())
        .limit(1)
    )


#: El rótulo físico de un punto de datos: ``P01-T2-R4-D17``, o ``P01-R4-D17`` en los
#: edificios sin tramos. En el subterráneo empieza con SUB en vez del piso: ``SUB-R11-D05``.
RE_ROTULO_PD = re.compile(r"^(?:P0?(\d+)|SUB)(?:-T(\d+))?-R0?(\d+)-(.+)$", re.IGNORECASE)


def detalle_de_puerto(numero_rack: int, puerto: str) -> str:
    """El detalle que identifica a un punto de datos: ``R04-D17``."""
    return f"R{numero_rack:02d}-{puerto.strip().upper()}"


def rotulo_de_puerto(piso: str, tramo: str | None, numero_rack: int, puerto: str) -> str:
    """El rótulo físico de las planillas: ``P01-T2-R4-D17``."""
    return "-".join(filter(None, [piso, tramo, f"R{numero_rack}", puerto.strip().upper()]))


def siguiente_sin_rotulo(sesion: Session, prefijo_codigo: str) -> str:
    """El detalle ``SIN-ROTULO-NN`` que sigue a los ya usados con ese prefijo.

    Como los correlativos, también cuenta a los dados de baja: un código nunca
    se reutiliza (SOP sección 8.5).
    """
    from app.models import (
        Elemento,  # import local: evita ciclo de importación
        HistorialElemento,  # import local: evita ciclo de importación
    )

    base = f"{prefijo_codigo}-{PREFIJO_SIN_ROTULO}"
    usados = [
        *sesion.scalars(select(Elemento.codigo).where(Elemento.codigo.startswith(base))),
        *sesion.scalars(
            select(HistorialElemento.valor_anterior).where(
                HistorialElemento.campo == "codigo",
                HistorialElemento.valor_anterior.startswith(base),
            )
        ),
    ]
    numeros = [
        int(sufijo)
        for sufijo in (codigo.removeprefix(base) for codigo in usados)
        if sufijo.isdecimal()
    ]
    return f"{PREFIJO_SIN_ROTULO}{max(numeros, default=0) + 1:02d}"
