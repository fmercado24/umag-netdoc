"""Punto de entrada de la API.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router_v1
from app.core.config import configuracion
from app.servicios.metricas import medir_peticiones, respuesta_metricas

DESCRIPCION = """
API del sistema de documentación visual interactiva de infraestructura de red
de la Universidad de Magallanes.

Implementa la metodología definida en **SOP-DSI-RED-001**: taxonomía de
elementos, convención de nomenclatura, fichas de atributos por tipo,
georreferenciación sobre planos y actualización continua del estado.
"""

app = FastAPI(
    title=configuracion.nombre_app,
    description=DESCRIPCION,
    version=configuracion.version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=configuracion.lista_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(medir_peticiones)

# Planos y fotografías de evidencia.
app.mount("/media", StaticFiles(directory=configuracion.dir_media), name="media")

app.include_router(router_v1)


@app.get("/", tags=["estado"])
def raiz() -> dict:
    return {
        "aplicacion": configuracion.nombre_app,
        "version": configuracion.version,
        "documentacion": "/docs",
        "api": "/api/v1",
    }


@app.get("/metrics", tags=["estado"], response_class=Response)
def metricas() -> Response:
    """Métricas en formato Prometheus: inventario, estado y servicio."""
    return respuesta_metricas()


@app.get("/salud", tags=["estado"])
def salud() -> dict:
    """Verificación de vida, usada por el monitoreo de la DSI."""
    from sqlalchemy import text

    from app.db.session import motor

    try:
        with motor.connect() as conexion:
            conexion.execute(text("SELECT 1"))
        base_datos = "ok"
    except Exception as exc:  # pragma: no cover - depende del entorno
        base_datos = f"error: {exc}"

    return {
        "estado": "ok" if base_datos == "ok" else "degradado",
        "entorno": configuracion.entorno,
        "base_datos": base_datos,
    }
