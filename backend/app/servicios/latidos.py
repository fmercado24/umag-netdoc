"""Latido de las herramientas de monitoreo (requisito RNF5, SOP 11.3).

Zabbix y Alertmanager avisan a NetDoc solo cuando un equipo cae o se recupera.
Si la herramienta misma deja de funcionar, no llega nada, y ese silencio se
confunde con una red sin fallas. Por eso cada aviso que llega con el token
deja la hora en que se supo de su fuente, y las herramientas mandan además un
latido periódico aunque no haya novedades: Alertmanager, con una alerta que
siempre está activa (``NetDocLatido``, en ``deploy/prometheus/reglas.yml``);
Zabbix, con un problema que siempre está abierto (``deploy/zabbix/README.md``).

Una fuente de la que se supo alguna vez y que lleva más de
``NETDOC_MONITOREO_LATIDO_MINUTOS`` sin noticias queda «sin latido»: el visor
lo advierte y ``/metrics`` lo expone. Una fuente que nunca informó no se vigila,
para que una instalación sin monitoreo no muestre avisos.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import configuracion
from app.models import LatidoMonitoreo

#: Nombre de una fuente: el de la herramienta, en minúsculas.
RE_FUENTE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
#: Nombre de la alerta de Alertmanager que solo hace de latido.
ALERTA_LATIDO = "NetDocLatido"
NOMBRES = {"zabbix": "Zabbix", "alertmanager": "Alertmanager"}


def ahora() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _utc(momento: dt.datetime) -> dt.datetime:
    # SQLite devuelve la hora sin zona; se guardó en UTC.
    return momento if momento.tzinfo else momento.replace(tzinfo=dt.timezone.utc)


def registrar_contacto(sesion: Session, fuente: str, momento: dt.datetime | None = None) -> None:
    """Anota que se supo de la fuente.

    No confirma la transacción, para no soltar el turno de escritura de la
    petición: quien llama debe responder sus errores sin lanzar excepciones (un
    aviso de un equipo que no está documentado también prueba que la
    herramienta funciona, y debe quedar).
    """
    momento = momento or ahora()
    latido = sesion.get(LatidoMonitoreo, fuente)
    if latido is None:
        sesion.add(LatidoMonitoreo(fuente=fuente, ultimo_contacto=momento))
    elif _utc(latido.ultimo_contacto) < momento:
        latido.ultimo_contacto = momento
    sesion.flush()


@dataclass
class EstadoLatido:
    fuente: str
    nombre: str
    ultimo_contacto: dt.datetime
    minutos_sin_noticias: int
    al_dia: bool


def estado_latidos(sesion: Session, momento: dt.datetime | None = None) -> list[EstadoLatido]:
    momento = momento or ahora()
    plazo = configuracion.monitoreo_latido_minutos
    estados = []
    for latido in sesion.scalars(select(LatidoMonitoreo).order_by(LatidoMonitoreo.fuente)):
        ultimo = _utc(latido.ultimo_contacto)
        minutos = max(0, int((momento - ultimo).total_seconds() // 60))
        estados.append(
            EstadoLatido(
                fuente=latido.fuente,
                nombre=NOMBRES.get(latido.fuente, latido.fuente),
                ultimo_contacto=ultimo,
                minutos_sin_noticias=minutos,
                al_dia=plazo <= 0 or minutos < plazo,
            )
        )
    return estados


def fuentes_sin_latido(sesion: Session, momento: dt.datetime | None = None) -> list[dict]:
    """Lo que el visor advierte: las fuentes que dejaron de informar."""
    return [
        {"fuente": e.fuente, "nombre": e.nombre, "minutos": e.minutos_sin_noticias}
        for e in estado_latidos(sesion, momento)
        if not e.al_dia
    ]
