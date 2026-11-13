"""Punto de entrada: la API y el visor compilado, en un mismo origen.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError

from app.api.v1.router import router_v1
from app.core.config import configuracion
from app.servicios.metricas import medir_peticiones, respuesta_metricas
from app.servicios.proteccion import proteger

DESCRIPCION = """
API del sistema de documentación visual interactiva de infraestructura de red
de la Universidad de Magallanes.

Implementa la metodología definida en **SOP-DSI-RED-001**: taxonomía de
elementos, convención de nomenclatura, fichas de atributos por tipo,
georreferenciación sobre planos y actualización continua del estado.
"""

# uvicorn solo configura sus propios registros; sin esto no se verían los
# ingresos de app.servicios.autenticacion.
registro = logging.getLogger("app")
if not registro.handlers:
    _salida = logging.StreamHandler()
    _salida.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    registro.addHandler(_salida)
    registro.setLevel(logging.INFO)

# /docs es la página de Swagger UI que se compila con el visor: la de FastAPI
# trae su JavaScript de un CDN, y correría con la sesión del administrador.
app = FastAPI(
    title=configuracion.nombre_app,
    description=DESCRIPCION,
    version=configuracion.version,
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
)

app.middleware("http")(proteger)
app.middleware("http")(medir_peticiones)


@app.exception_handler(RequestValidationError)
async def datos_invalidos(_: Request, error: RequestValidationError) -> Response:
    """Como el de FastAPI, pero sin devolver lo recibido: podría ser la contraseña, y
    un carácter inválido en ella reventaría la respuesta (json.dumps sí lo admite)."""
    detalle = [{k: e[k] for k in ("type", "loc", "msg")} for e in error.errors()]
    return Response(json.dumps({"detail": detalle}), 422, media_type="application/json")


# Las escrituras van de a una (app.db.session), así que estos casos no deberían
# darse entre peticiones; quedan para lo que escriba por fuera de la API, como una
# importación en curso. En vez de un error interno, algo que se pueda entender.
@app.exception_handler(IntegrityError)
@app.exception_handler(StaleDataError)
async def cambio_simultaneo(_: Request, error: Exception) -> Response:
    registro.warning("Cambio simultáneo rechazado: %s", str(error).splitlines()[0][:200])
    return JSONResponse(
        {"detail": "Otra persona acaba de registrar o cambiar lo mismo. Revisa cómo quedó y vuelve a intentarlo."},
        status_code=409,
    )


@app.exception_handler(OperationalError)
async def base_ocupada(_: Request, error: OperationalError) -> Response:
    texto = str(error.orig).lower()
    if "locked" not in texto and "lock timeout" not in texto and "lock_timeout" not in texto:
        raise error
    registro.warning("Sin turno para escribir tras la espera: %s", texto[:200])
    return JSONResponse(
        {"detail": "NetDoc está ocupado con otro cambio. Vuelve a intentarlo en unos segundos."},
        status_code=503,
        headers={"Retry-After": "5"},
    )


# Planos y fotografías de evidencia.
app.mount("/media", StaticFiles(directory=configuracion.dir_media), name="media")
# Recursos del visor. Si no está compilado, responde 404 en vez de impedir el arranque.
app.mount(
    "/assets", StaticFiles(directory=configuracion.dir_visor / "assets", check_dir=False), name="assets"
)

app.include_router(router_v1)


def _pagina_del_visor(nombre: str) -> Response:
    pagina = configuracion.dir_visor / nombre
    if not pagina.is_file():
        return JSONResponse(
            {"detail": "El visor no está compilado: ejecute ./iniciar.sh o npm run build en frontend/"},
            status_code=503,
        )
    return FileResponse(pagina)


@app.get("/", include_in_schema=False)
def visor() -> Response:
    return _pagina_del_visor("index.html")


@app.get("/docs", include_in_schema=False)
def documentacion() -> Response:
    return _pagina_del_visor("docs.html")


@app.get("/metrics", tags=["estado"], response_class=Response)
def metricas() -> Response:
    """Métricas en formato Prometheus: inventario, estado y servicio."""
    return respuesta_metricas()


@app.get("/salud", tags=["estado"])
def salud() -> dict:
    """Verificación de vida, usada por el monitoreo de la DSI. Es pública: el
    detalle de un error, que puede traer datos de la conexión, solo va al registro."""
    from sqlalchemy import text

    from app.db.session import motor

    try:
        with motor.connect() as conexion:
            conexion.execute(text("SELECT 1"))
        base_datos = "ok"
    except Exception:  # pragma: no cover - depende del entorno
        registro.exception("La base de datos no responde")
        base_datos = "error"

    return {"estado": "ok" if base_datos == "ok" else "degradado", "base_datos": base_datos}
