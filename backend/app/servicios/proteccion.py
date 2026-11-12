"""Filtro y cabeceras de seguridad por los que pasa toda petición.

``proteger`` rechaza lo que no esté exceptuado aquí, de modo que una ruta nueva
nace protegida. El navegador habla con un solo origen (la API sirve el visor),
así que no hay CORS: nada de otro sitio puede leer respuestas ni, con la
comprobación de origen, enviar escrituras.
"""

from __future__ import annotations

import ipaddress
import posixpath
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import configuracion
from app.servicios.autenticacion import Acceso, sesion_vigente, token_monitoreo_valido

#: El prefijo ``__Host-`` obliga al navegador a exigir HTTPS, y evita que otro
#: subdominio pueda fijarla.
COOKIE_HTTP = "netdoc_sesion"
COOKIE_HTTPS = "__Host-netdoc_sesion"

#: Accesibles sin sesión: la pantalla de ingreso con sus recursos (no llevan
#: datos), la verificación de vida y los webhooks, que validan el token de
#: monitoreo por su cuenta.
RUTAS_PUBLICAS = frozenset(
    {
        "/",
        "/salud",
        "/api/v1/auth/ingresar",
        "/api/v1/integraciones/monitoreo/estado",
        "/api/v1/integraciones/alertmanager",
    }
)
PREFIJOS_PUBLICOS = ("/assets/",)

#: Lo que leen otros sistemas (Prometheus, NetBox, GLPI). No pueden iniciar
#: sesión, así que les basta el token de monitoreo.
PREFIJOS_CON_TOKEN = ("/metrics", "/api/v1/integraciones/")

#: Lo que puede pedir un usuario limitado a un edificio: las rutas que filtran por
#: él (``app.api.deps``). El resto muestra datos de todos los edificios, así que
#: una ruta nueva nace cerrada para ese usuario hasta que se agregue aquí.
PREFIJOS_CON_ALCANCE = (
    "/api/v1/auth/",
    "/api/v1/catalogo/",
    "/api/v1/edificios",
    "/api/v1/elementos",
    "/api/v1/enlaces",
    "/api/v1/reportes/",
    "/api/v1/vlans",
)

METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Tamaño máximo de un cuerpo que no sea la carga de un archivo con sesión.
MAX_CUERPO = 1024 * 1024

CABECERAS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
}

_CSP_PAGINA = (
    "default-src 'self'; script-src 'self'; {estilos}; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)
#: Los marcadores de Leaflet llevan su color en un atributo ``style``.
CSP_VISOR = _CSP_PAGINA.format(estilos="style-src 'self'; style-src-attr 'unsafe-inline'")
#: Swagger UI inserta hojas de estilo en la página.
CSP_DOCS = _CSP_PAGINA.format(estilos="style-src 'self' 'unsafe-inline'")
#: Un SVG abierto directamente es un documento que puede traer scripts: el
#: ``sandbox`` impide que corran con la sesión del administrador.
CSP_MEDIA = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
CSP_API = "default-src 'none'; frame-ancestors 'none'"


def es_https(request: Request) -> bool:
    return request.url.scheme == "https"


def nombre_cookie(request: Request) -> str:
    return COOKIE_HTTPS if es_https(request) else COOKIE_HTTP


def _ip_cliente(request: Request) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        ip = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError:
        return None
    return (ip.ipv4_mapped or ip) if ip.version == 6 else ip


def identificar_cliente(request: Request) -> str:
    """A quién se le cuentan los intentos: una red IPv6 /64 es un solo equipo."""
    ip = _ip_cliente(request)
    if ip is None:
        return (request.client.host if request.client else "desconocido")[:45]
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _es_local(request: Request) -> bool:
    ip = _ip_cliente(request)
    return ip is not None and ip.is_loopback


def _viene_de_otro_sitio(request: Request) -> bool:
    if request.method in METODOS_SEGUROS:
        return False
    sitio = request.headers.get("sec-fetch-site")
    if sitio:
        return sitio not in {"same-origin", "none"}
    # Navegadores que no envían Sec-Fetch-Site. Sin Origin no es un navegador:
    # no lleva la cookie por su cuenta, así que no hay falsificación posible.
    origen = request.headers.get("origin")
    return bool(origen) and urlsplit(origen).netloc != request.headers.get("host")


def _rechazo(codigo: int, detalle: str) -> Response:
    return JSONResponse({"detail": detalle}, status_code=codigo)


def _dentro_de_su_alcance(ruta: str, edificio: str) -> bool:
    """Si un usuario limitado a ``edificio`` puede pedir esa ruta."""
    if ruta.startswith("/media/"):
        # Planos, teselas y fotografías se llaman como su edificio: CADI-P01-T1-v1.svg.
        # Una ruta con «..» nombraría un archivo y entregaría otro.
        partes = ruta.split("/")
        return (
            posixpath.normpath(ruta) == ruta
            and len(partes) >= 4
            and partes[3].upper().startswith(f"{edificio.upper()}-")
        )
    return ruta.startswith(PREFIJOS_CON_ALCANCE)


def _revisar_cuerpo(request: Request, con_sesion: bool) -> Response | None:
    """El cuerpo se rechaza antes de leerlo: sin esto, cualquiera podría agotar
    la memoria con un envío enorme a la pantalla de ingreso."""
    if request.method in METODOS_SEGUROS:
        return None
    if "transfer-encoding" in request.headers:
        return _rechazo(411, "La petición debe indicar Content-Length")
    es_carga = con_sesion and request.headers.get("content-type", "").startswith(
        "multipart/form-data"
    )
    maximo = configuracion.carga_max_mb * 1024 * 1024 if es_carga else MAX_CUERPO
    largo = request.headers.get("content-length", "0")
    if len(largo) > 15 or not largo.isdecimal() or int(largo) > maximo:
        return _rechazo(413, f"La petición supera el máximo de {maximo // (1024 * 1024)} MB")
    return None


def _ruta(request: Request) -> str:
    """La ruta tal como la verán las rutas y el servidor de archivos.

    ``request.url.path`` la corta en un «?» o «#» que venga codificado (%3F, %23):
    se revisaría una ruta y se atendería otra.
    """
    return request.scope["path"]


async def _filtrar(request: Request, call_next) -> Response:
    ruta = _ruta(request)
    if not es_https(request) and ruta != "/salud" and not _es_local(request):
        return _rechazo(403, "Desde otros equipos, NetDoc solo atiende por HTTPS")
    if _viene_de_otro_sitio(request):
        return _rechazo(403, "Petición de otro sitio rechazada")

    acceso: Acceso | None = None
    if ruta not in RUTAS_PUBLICAS and not ruta.startswith(PREFIJOS_PUBLICOS):
        token = request.cookies.get(nombre_cookie(request))
        if token:
            acceso = await run_in_threadpool(sesion_vigente, token)
        if acceso is None and not (
            ruta.startswith(PREFIJOS_CON_TOKEN)
            and token_monitoreo_valido(
                request.headers.get("X-NetDoc-Token"), request.headers.get("Authorization")
            )
        ):
            return _rechazo(401, "Debe iniciar sesión")
        if acceso and acceso.edificio and not _dentro_de_su_alcance(ruta, acceso.edificio):
            return _rechazo(403, f"Su usuario solo tiene acceso al edificio {acceso.edificio}")
    # Para las rutas: quién pide y hasta dónde llega (app.api.deps).
    request.state.acceso = acceso

    return _revisar_cuerpo(request, acceso is not None) or await call_next(request)


def _politicas(ruta: str) -> tuple[str, str]:
    """Content-Security-Policy y Cache-Control de la ruta."""
    if ruta == "/":
        return CSP_VISOR, "no-cache"
    if ruta == "/docs":
        return CSP_DOCS, "no-cache"
    if ruta.startswith("/assets/"):
        # Su nombre lleva la huella del contenido: nunca cambian.
        return CSP_API, "public, max-age=31536000, immutable"
    if ruta.startswith("/media/"):
        # Con no-cache, un plano guardado por el navegador no se vuelve a
        # mostrar sin pasar por la API, que comprueba la sesión.
        return CSP_MEDIA, "private, no-cache"
    return CSP_API, "no-store"


async def proteger(request: Request, call_next) -> Response:
    respuesta = await _filtrar(request, call_next)
    csp, cache = _politicas(_ruta(request))
    respuesta.headers["Content-Security-Policy"] = csp
    respuesta.headers["Cache-Control"] = cache
    respuesta.headers.update(CABECERAS)
    if es_https(request):
        respuesta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return respuesta
