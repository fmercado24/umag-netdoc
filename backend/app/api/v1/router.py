"""Agrupa los routers de la versión 1 de la API."""

from fastapi import APIRouter

from app.api.v1 import (
    autenticacion,
    catalogo,
    edificios,
    elementos,
    integraciones,
    inventario,
    reportes,
    vlans,
)

router_v1 = APIRouter(prefix="/api/v1")
router_v1.include_router(autenticacion.router)
router_v1.include_router(catalogo.router)
router_v1.include_router(edificios.router)
router_v1.include_router(elementos.router)
router_v1.include_router(vlans.router)
router_v1.include_router(reportes.router)
router_v1.include_router(integraciones.router)
router_v1.include_router(inventario.router)
