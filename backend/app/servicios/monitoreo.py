"""Estado operativo informado por las herramientas de monitoreo (SOP §11.3).

Lo comparten el webhook genérico, que usa Zabbix, y el de Alertmanager
(Prometheus): cada uno traduce su evento a "up" o "down" y lo aplica aquí,
así las reglas son las mismas venga de donde venga el evento. Un elemento
en mantenimiento planificado no cambia, para no registrar falsos positivos
durante una intervención. Una caída menor al umbral configurado no escala a
falla.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import configuracion
from app.models import Elemento, EstadoOperativo, OrigenCambio
from app.servicios.codigos import elemento_por_codigo
from app.servicios.historial import registrar_cambios

#: Traducción de lo que reporta la herramienta de monitoreo.
MAPA_ESTADOS: dict[str, EstadoOperativo] = {
    "up": EstadoOperativo.ACTIVO,
    "ok": EstadoOperativo.ACTIVO,
    "activo": EstadoOperativo.ACTIVO,
    "resolved": EstadoOperativo.ACTIVO,
    "down": EstadoOperativo.EN_FALLA,
    "problem": EstadoOperativo.EN_FALLA,
    "en_falla": EstadoOperativo.EN_FALLA,
    "firing": EstadoOperativo.EN_FALLA,
    "unknown": EstadoOperativo.INACTIVO,
    "inactivo": EstadoOperativo.INACTIVO,
}


class EstadoNoReconocido(ValueError):
    pass


@dataclass
class ResultadoEvento:
    codigo: str
    estado_operativo: str
    actualizado: bool
    motivo: str | None = None


def ip_de_instancia(instancia: str | None) -> str | None:
    """IP de una etiqueta ``instance`` de Prometheus: "10.0.0.1:9100",
    "10.0.0.1" o "[fe80::1]:161". Un nombre de host no se resuelve."""
    if not instancia:
        return None
    texto = instancia.strip()
    if texto.startswith("["):
        texto = texto[1 : texto.find("]")]
    elif texto.count(":") == 1:
        texto = texto.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(texto))
    except ValueError:
        return None


def buscar_elemento(
    sesion: Session, codigo: str | None = None, direccion_ip: str | None = None
) -> Elemento | None:
    """Elemento activo por código y, si no aparece, por IP de gestión.

    Un host que se creó a mano en Zabbix no se llama como el código: el
    evento trae su nombre y su IP, y la IP es la que lo encuentra.
    """
    activos = select(Elemento).where(Elemento.activo.is_(True))
    if codigo:
        elemento = elemento_por_codigo(sesion, codigo.strip().upper())
        if elemento is not None and elemento.activo:
            return elemento
    if direccion_ip:
        return sesion.scalars(activos.where(Elemento.direccion_ip == direccion_ip)).unique().first()
    return None


def aplicar_evento(
    sesion: Session,
    elemento: Elemento,
    estado: str,
    *,
    fuente: str,
    minutos_caido: int | None = None,
    comentario: str | None = None,
) -> ResultadoEvento:
    """Aplica un evento de monitoreo y lo deja en el historial del elemento."""
    nuevo_estado = MAPA_ESTADOS.get(estado.strip().lower())
    if nuevo_estado is None:
        raise EstadoNoReconocido(
            f"Estado no reconocido: '{estado}'. Admitidos: {', '.join(MAPA_ESTADOS)}"
        )

    if elemento.estado_operativo is EstadoOperativo.EN_MANTENIMIENTO:
        return ResultadoEvento(
            elemento.codigo,
            elemento.estado_operativo.value,
            False,
            "El elemento está en mantenimiento planificado; se ignora el evento",
        )

    # "down" solo escala a falla tras el umbral configurado (SOP 11.3).
    if (
        nuevo_estado is EstadoOperativo.EN_FALLA
        and minutos_caido is not None
        and minutos_caido < configuracion.monitoreo_minutos_falla
    ):
        return ResultadoEvento(
            elemento.codigo,
            elemento.estado_operativo.value,
            False,
            f"Caída de {minutos_caido} min bajo el umbral de "
            f"{configuracion.monitoreo_minutos_falla} min",
        )

    entradas = registrar_cambios(
        sesion,
        elemento,
        {"estado_operativo": nuevo_estado},
        origen=OrigenCambio.MONITOREO,
        usuario=fuente,
        comentario=comentario or f"Evento de monitoreo: {estado}",
    )
    sesion.flush()
    return ResultadoEvento(elemento.codigo, elemento.estado_operativo.value, bool(entradas))
