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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

RE_CODIGO = re.compile(
    r"^(?P<edificio>[A-Z]{2,5})"
    r"-(?P<tipo>[A-Z]+)(?P<correlativo>\d{1,3})?"
    r"-(?P<piso>P\d{2}|PXX)"
    r"(?:-(?P<tramo>T\d{1,2}))?"
    r"(?:-(?P<detalle>.+))?$"
)

RE_NUMERO = re.compile(r"(\d+)")


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


def siguiente_correlativo(
    sesion: Session, *, edificio_id: int, tipo_elemento_id: int, piso_id: int
) -> int:
    """Correlativo siguiente para el trío tipo + edificio + piso.

    SOP sección 8.5: el correlativo crece en orden de documentación y un
    código nunca se reutiliza, por lo que también se consideran los elementos
    dados de baja.
    """
    from app.models import Elemento  # import local: evita ciclo de importación

    maximo = sesion.scalar(
        select(func.max(Elemento.correlativo)).where(
            Elemento.edificio_id == edificio_id,
            Elemento.tipo_elemento_id == tipo_elemento_id,
            Elemento.piso_id == piso_id,
        )
    )
    return (maximo or 0) + 1
