"""Métricas en formato Prometheus (``GET /metrics``).

Dos grupos:

* **Inventario**, leído de la base en cada consulta: cuántos elementos hay por
  edificio, piso, tipo y estado; el estado de cada uno; la completitud de las
  fichas y lo que falta ubicar en el plano. Es lo que alimenta los paneles de
  Grafana (``deploy/grafana``).
* **Servicio**: latencia y volumen de la API por ruta, más las del proceso.

Con varios procesos de uvicorn/gunicorn las métricas HTTP son por proceso; para
sumarlas hay que usar el modo multiproceso de ``prometheus_client``
(``PROMETHEUS_MULTIPROC_DIR``). Las de inventario salen de la base y valen
desde cualquier proceso.
"""

from __future__ import annotations

import time
from collections import defaultdict

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    GCCollector,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount

from app.core.config import configuracion
from app.db.session import SesionLocal
from app.models import (
    Edificio,
    Elemento,
    EstadoOperativo,
    HistorialElemento,
    Piso,
    TipoElemento,
)
from app.servicios.validacion import evaluar_completitud

#: Valor numérico del estado operativo, de mejor a peor: los umbrales de
#: Grafana y las alertas pueden comparar ("> 1" = no disponible).
CODIGO_ESTADO: dict[EstadoOperativo, int] = {
    EstadoOperativo.ACTIVO: 0,
    EstadoOperativo.EN_MANTENIMIENTO: 1,
    EstadoOperativo.INACTIVO: 2,
    EstadoOperativo.EN_FALLA: 3,
}


class ColectorInventario:
    """Arma las métricas de inventario al momento de cada consulta."""

    def describe(self):
        # Sin esto el registro llamaría a collect() al registrarse, antes de
        # que exista la base.
        return []

    def collect(self):
        disponible = GaugeMetricFamily(
            "netdoc_base_datos_disponible", "1 si la base respondió al armar las métricas"
        )
        try:
            with SesionLocal() as sesion:
                familias = list(self._inventario(sesion))
        except Exception:  # noqa: BLE001  (sin base, las métricas de servicio siguen)
            disponible.add_metric([], 0)
            yield disponible
            return
        disponible.add_metric([], 1)
        yield disponible
        yield from familias

    def _inventario(self, sesion):
        info = GaugeMetricFamily(
            "netdoc_info", "Versión de NetDoc y motor de base", labels=["version", "motor"]
        )
        info.add_metric(
            [configuracion.version, "sqlite" if configuracion.es_sqlite else "postgresql"], 1
        )
        yield info

        conteo = GaugeMetricFamily(
            "netdoc_elementos",
            "Elementos documentados vigentes",
            labels=["edificio", "piso", "tipo", "estado_operativo"],
        )
        filas = sesion.execute(
            select(
                Edificio.codigo,
                Piso.codigo,
                TipoElemento.codigo,
                Elemento.estado_operativo,
                func.count(Elemento.id),
            )
            .join(Edificio, Elemento.edificio_id == Edificio.id)
            .join(Piso, Elemento.piso_id == Piso.id)
            .join(TipoElemento, Elemento.tipo_elemento_id == TipoElemento.id)
            .where(Elemento.activo.is_(True))
            .group_by(Edificio.codigo, Piso.codigo, TipoElemento.codigo, Elemento.estado_operativo)
        )
        for edificio, piso, tipo, estado, cantidad in filas:
            conteo.add_metric([edificio, piso, tipo, estado.value], cantidad)
        yield conteo

        estado = GaugeMetricFamily(
            "netdoc_elemento_estado",
            "Estado operativo de cada elemento: 0 activo, 1 en mantenimiento, "
            "2 inactivo, 3 en falla (los retirados no se informan)",
            labels=["codigo", "tipo", "edificio", "piso", "tramo"],
        )
        completitud = defaultdict(list)
        sin_ubicar = defaultdict(int)
        elementos = sesion.scalars(select(Elemento).where(Elemento.activo.is_(True))).unique()
        for e in elementos:
            if e.estado_operativo in CODIGO_ESTADO:
                estado.add_metric(
                    [e.codigo, e.tipo.codigo, e.edificio.codigo, e.piso.codigo, e.tramo_codigo or ""],
                    CODIGO_ESTADO[e.estado_operativo],
                )
            completitud[e.edificio.codigo].append(evaluar_completitud(e).porcentaje)
            if not e.montado and not e.tiene_coordenadas:
                sin_ubicar[(e.edificio.codigo, e.piso.codigo)] += 1
        yield estado

        promedio = GaugeMetricFamily(
            "netdoc_completitud_porcentaje",
            "Completitud promedio de las fichas (SOP §9), de 0 a 100",
            labels=["edificio"],
        )
        for edificio, valores in completitud.items():
            promedio.add_metric([edificio], sum(valores) / len(valores))
        yield promedio

        pendientes = GaugeMetricFamily(
            "netdoc_elementos_sin_ubicar",
            "Elementos con marcador propio que aún no tienen posición en el plano",
            labels=["edificio", "piso"],
        )
        for (edificio, piso), cantidad in sorted(sin_ubicar.items()):
            pendientes.add_metric([edificio, piso], cantidad)
        yield pendientes

        ultimo = sesion.scalar(select(func.max(HistorialElemento.registrado_en)))
        if ultimo is not None:
            cambio = GaugeMetricFamily(
                "netdoc_ultimo_cambio_timestamp_seconds",
                "Momento del último cambio registrado en el historial (epoch)",
            )
            cambio.add_metric([], ultimo.timestamp())
            yield cambio


registro = CollectorRegistry()
registro.register(ColectorInventario())
ProcessCollector(registry=registro)
PlatformCollector(registry=registro)
GCCollector(registry=registro)

DURACION_HTTP = Histogram(
    "netdoc_http_duracion_segundos",
    "Duración de las peticiones a la API",
    labelnames=["metodo", "ruta", "codigo"],
    registry=registro,
)


def plantilla_de_ruta(request: Request) -> str:
    """``/api/v1/elementos/{id_o_codigo}`` en vez de la URL concreta, para no
    crear una serie por cada elemento. Se arma desde la URL porque FastAPI
    guarda la ruta sin el prefijo de su router."""
    ruta = request.scope.get("route")
    if ruta is None:
        # Starlette no marca los Mount (/media): un archivo por plano o foto.
        for montaje in request.app.routes:
            if isinstance(montaje, Mount) and request.url.path.startswith(montaje.path + "/"):
                return f"{montaje.path}/{{path}}"
        return "sin_ruta"
    nombres = {str(valor): nombre for nombre, valor in request.path_params.items()}
    return "/".join(
        f"{{{nombres[s]}}}" if s in nombres else s for s in request.url.path.split("/")
    )


async def medir_peticiones(request: Request, call_next):
    inicio = time.perf_counter()
    respuesta = await call_next(request)
    DURACION_HTTP.labels(
        request.method, plantilla_de_ruta(request), str(respuesta.status_code)
    ).observe(time.perf_counter() - inicio)
    return respuesta


def respuesta_metricas() -> Response:
    return Response(generate_latest(registro), media_type=CONTENT_TYPE_LATEST)
