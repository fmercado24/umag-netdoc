"""Ingreso y salida (ver ``app.servicios.autenticacion``)."""

from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import SesionBD
from app.core.config import configuracion
from app.servicios.autenticacion import (
    Acceso,
    AdministradorSinConfigurar,
    CredencialesInvalidas,
    IngresoBloqueado,
    acceso_de,
    autenticar,
    cerrar_sesion,
)
from app.servicios.proteccion import es_https, identificar_cliente, nombre_cookie

router = APIRouter(prefix="/auth", tags=["acceso"])


class Credenciales(BaseModel):
    usuario: str = Field(max_length=100)
    clave: str = Field(max_length=1024)


class SesionActiva(BaseModel):
    usuario: str
    #: El único edificio al que tiene acceso; nulo, todos.
    edificio: str | None = None


def _sesion_de(acceso: Acceso) -> SesionActiva:
    return SesionActiva(usuario=acceso.usuario, edificio=acceso.edificio)


def _plural(cantidad: int, palabra: str) -> str:
    return f"{cantidad} {palabra}" + ("" if cantidad == 1 else "s")


@router.post("/ingresar", response_model=SesionActiva)
def ingresar(datos: Credenciales, request: Request, response: Response, bd: SesionBD):
    try:
        token = autenticar(bd, datos.usuario, datos.clave, identificar_cliente(request))
    except AdministradorSinConfigurar as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No hay una contraseña de administrador definida: ejecute en el servidor "
            "python -m app.scripts.definir_clave",
        ) from exc
    except CredencialesInvalidas as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"Usuario o contraseña incorrectos. {_plural(exc.quedan, 'intento')} antes del bloqueo.",
        ) from exc
    except IngresoBloqueado as exc:
        segundos = max(1, math.ceil(exc.segundos))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Demasiados intentos fallidos. Se podrá volver a intentar en "
            f"{_plural(math.ceil(segundos / 60), 'minuto')}.",
            headers={"Retry-After": str(segundos)},
        ) from exc

    # Strict: el navegador no la envía en nada que parta de otro sitio.
    response.set_cookie(
        nombre_cookie(request),
        token,
        max_age=configuracion.sesion_horas * 3600,
        path="/",
        httponly=True,
        samesite="strict",
        secure=es_https(request),
    )
    return _sesion_de(acceso_de(datos.usuario) or Acceso(datos.usuario))


@router.get("/sesion", response_model=SesionActiva)
def sesion_actual(request: Request):
    """Para llegar aquí, ``proteger`` ya validó la cookie."""
    return _sesion_de(request.state.acceso)


@router.post("/salir", status_code=status.HTTP_204_NO_CONTENT)
def salir(request: Request, response: Response, bd: SesionBD):
    nombre = nombre_cookie(request)
    cerrar_sesion(bd, request.cookies.get(nombre))
    bd.commit()  # ya invalidada al responder, no después
    response.delete_cookie(
        nombre, path="/", httponly=True, samesite="strict", secure=es_https(request)
    )
