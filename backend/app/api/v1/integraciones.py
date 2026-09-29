"""Integración con el monitoreo activo (SOP sección 11.3).

* ``POST /monitoreo/estado`` — webhook genérico; lo usa Zabbix
  (``deploy/zabbix/``) o cualquier herramienta que pueda hacer un POST.
* ``POST /alertmanager`` — webhook de Alertmanager, para el stack Prometheus.
* ``GET /prometheus/objetivos`` — descubrimiento de servicios HTTP de
  Prometheus: el inventario le dice qué IP vigilar y con qué etiquetas.

Las escrituras exigen el token de ``NETDOC_MONITOREO_TOKEN``, en la cabecera
``X-NetDoc-Token`` o como ``Authorization: Bearer``.
"""

from __future__ import annotations

import datetime as dt
import hmac

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import SesionBD
from app.core.config import configuracion
from app.models import Edificio, Elemento, EstadoOperativo, TipoElemento
from app.schemas.elemento import EstadoMonitoreo
from app.servicios.monitoreo import (
    EstadoNoReconocido,
    aplicar_evento,
    buscar_elemento,
    ip_de_instancia,
)

router = APIRouter(prefix="/integraciones", tags=["integraciones: monitoreo"])


def _verificar_token(token: str | None, authorization: str | None) -> None:
    if not configuracion.monitoreo_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "La integración de monitoreo está deshabilitada: defina NETDOC_MONITOREO_TOKEN",
        )
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token or not hmac.compare_digest(token, configuracion.monitoreo_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de monitoreo inválido")


@router.post("/monitoreo/estado")
def sincronizar_estado(
    datos: EstadoMonitoreo,
    sesion: SesionBD,
    x_netdoc_token: str | None = Header(default=None, alias="X-NetDoc-Token"),
    authorization: str | None = Header(default=None),
):
    """Sincroniza el estado operativo de un elemento identificado por código
    o por dirección IP de gestión."""
    _verificar_token(x_netdoc_token, authorization)

    if not datos.codigo and not datos.direccion_ip:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Debe indicarse 'codigo' o 'direccion_ip' para identificar el elemento",
        )

    elemento = buscar_elemento(sesion, datos.codigo, datos.direccion_ip)
    if elemento is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No hay un elemento documentado para {datos.codigo or datos.direccion_ip}",
        )

    try:
        resultado = aplicar_evento(
            sesion,
            elemento,
            datos.estado,
            fuente="monitoreo",
            minutos_caido=datos.minutos_caido,
            comentario=datos.comentario,
        )
    except EstadoNoReconocido as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    respuesta = {
        "codigo": resultado.codigo,
        "estado_operativo": resultado.estado_operativo,
        "actualizado": resultado.actualizado,
    }
    if resultado.motivo:
        respuesta["motivo"] = resultado.motivo
    return respuesta


# --------------------------------------------------------------------------
# Prometheus + Alertmanager
# --------------------------------------------------------------------------
class AlertaAlertmanager(BaseModel):
    status: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: dt.datetime | None = None  # noqa: N815  (nombre del formato de Alertmanager)


class NotificacionAlertmanager(BaseModel):
    """Formato ``webhook_config`` de Alertmanager (versión 4)."""

    version: str | None = None
    status: str
    alerts: list[AlertaAlertmanager] = Field(default_factory=list)


@router.post("/alertmanager")
def recibir_alertmanager(
    datos: NotificacionAlertmanager,
    sesion: SesionBD,
    x_netdoc_token: str | None = Header(default=None, alias="X-NetDoc-Token"),
    authorization: str | None = Header(default=None),
):
    """Aplica las alertas de disponibilidad de Prometheus.

    El elemento se identifica por la etiqueta ``netdoc_codigo`` (la agrega el
    descubrimiento de ``/prometheus/objetivos``) o, si falta, por la IP de
    ``instance``. Una alerta activa lo deja "en falla" y una resuelta,
    "activo": el ``for`` de la regla hace de umbral del SOP 11.3. Siempre
    responde 200, porque Alertmanager reintenta los errores; lo que no se pudo
    aplicar se informa en ``resultados``.
    """
    _verificar_token(x_netdoc_token, authorization)

    resultados = []
    for alerta in datos.alerts:
        nombre = alerta.labels.get("alertname", "alerta")
        codigo = alerta.labels.get("netdoc_codigo")
        ip = ip_de_instancia(alerta.labels.get("instance"))
        elemento = buscar_elemento(sesion, codigo, ip)
        if elemento is None:
            resultados.append(
                {
                    "alerta": nombre,
                    "actualizado": False,
                    "motivo": f"Sin elemento documentado para {codigo or ip or 'la alerta'}",
                }
            )
            continue

        resumen = alerta.annotations.get("summary")
        resultado = aplicar_evento(
            sesion,
            elemento,
            "down" if alerta.status == "firing" else "up",
            fuente="alertmanager",
            comentario=f"Alertmanager: {nombre}" + (f" — {resumen}" if resumen else ""),
        )
        resultados.append({"alerta": nombre, **resultado.__dict__})

    return {"procesadas": len(datos.alerts), "resultados": resultados}


@router.get("/prometheus/objetivos")
def objetivos_prometheus(
    sesion: SesionBD,
    edificio: str | None = None,
    tipo: list[str] | None = Query(default=None, description="Códigos de tipo, p. ej. SW"),
):
    """Descubrimiento HTTP de Prometheus (``http_sd_configs``).

    Un grupo por elemento con IP de gestión, con etiquetas ``netdoc_*`` que
    viajan a las series y alertas. Así el inventario decide qué se vigila y
    Alertmanager puede avisar el código del elemento de vuelta a NetDoc. Los
    retirados no se vigilan.
    """
    consulta = (
        select(Elemento)
        .join(Edificio, Elemento.edificio_id == Edificio.id)
        .join(TipoElemento, Elemento.tipo_elemento_id == TipoElemento.id)
        .where(
            Elemento.activo.is_(True),
            Elemento.direccion_ip.is_not(None),
            Elemento.estado_operativo != EstadoOperativo.RETIRADO,
        )
        .order_by(Elemento.codigo)
    )
    if edificio:
        consulta = consulta.where(Edificio.codigo == edificio.upper())
    if tipo:
        consulta = consulta.where(TipoElemento.codigo.in_([t.upper() for t in tipo]))

    return [
        {
            "targets": [e.direccion_ip],
            "labels": {
                "netdoc_codigo": e.codigo,
                "netdoc_tipo": e.tipo.codigo,
                "netdoc_edificio": e.edificio.codigo,
                "netdoc_piso": e.piso.codigo,
                "netdoc_tramo": e.tramo_codigo or "",
                "netdoc_criticidad": e.criticidad.value if e.criticidad else "",
            },
        }
        for e in sesion.scalars(consulta).unique()
    ]
