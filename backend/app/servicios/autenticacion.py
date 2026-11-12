"""Acceso al sistema: el administrador y los demás usuarios, definidos en la
configuración.

* **Contraseñas.** Sus hashes Argon2id viven en ``.env``, fuera del repositorio
  (``app.scripts.definir_clave`` y ``app.scripts.usuarios``). Sin el del
  administrador nadie puede ingresar.
* **Alcance.** Un usuario puede estar limitado a un edificio: lo hacen cumplir
  ``app.servicios.proteccion`` y ``app.api.deps``.
* **Intentos.** Cada equipo tiene ``ingreso_intentos`` por ventana de
  ``ingreso_bloqueo_minutos``, y entre todos ``ingreso_intentos_globales``. El
  límite es por equipo para que cualquiera con acceso a la pantalla de ingreso
  no pueda dejar afuera al administrador con tres intentos malos.
* **Sesiones.** Se guardan en la base (``app.models.acceso``): salir o cambiar
  la contraseña las invalida de inmediato, y vencen por inactividad y por
  duración total. La cookie lleva un token aleatorio y la base solo su SHA-256.
  De cada una se sabe de quién es; sus permisos se leen de la configuración.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import configuracion
from app.db.session import SesionLocal
from app.models import IntentoIngreso, SesionAcceso

registro = logging.getLogger(__name__)

#: Parámetros por omisión de argon2-cffi: Argon2id con 64 MiB (RFC 9106).
_hasher = PasswordHasher()

#: Cada cuántos segundos se anota el uso de una sesión: una escritura por cada
#: tesela del plano no aporta nada al vencimiento por inactividad.
_ANOTAR_USO_CADA = 60


@dataclass(frozen=True)
class Acceso:
    """Quién hace una petición y hasta dónde llega."""

    usuario: str
    #: Código del único edificio que puede ver y modificar; nulo, todos.
    edificio: str | None = None


class AdministradorSinConfigurar(Exception):
    """No hay una contraseña válida en la configuración."""


class CredencialesInvalidas(Exception):
    def __init__(self, quedan: int) -> None:
        super().__init__(f"Quedan {quedan} intentos")
        self.quedan = quedan


class IngresoBloqueado(Exception):
    def __init__(self, segundos: float) -> None:
        super().__init__(f"Bloqueado por {segundos:.0f} s")
        self.segundos = segundos


def cifrar_clave(clave: str) -> str:
    """El hash Argon2id que se guarda en la configuración para esa contraseña."""
    return _hasher.hash(clave)


def _es_argon2id(valor: str) -> bool:
    try:
        return extract_parameters(valor).type is Type.ID
    except InvalidHashError:
        return False


def clave_definida() -> bool:
    return _es_argon2id(configuracion.admin_clave_hash)


def _es_el_administrador(usuario: str) -> bool:
    return hmac.compare_digest(usuario.encode(), configuracion.admin_usuario.encode())


def acceso_de(usuario: str) -> Acceso | None:
    """Lo que puede hacer ese usuario hoy, o None si ya no existe."""
    if _es_el_administrador(usuario):
        return Acceso(configuracion.admin_usuario)
    definido = configuracion.usuarios.get(usuario)
    if definido is None:
        return None
    return Acceso(usuario, definido.edificio.upper() if definido.edificio else None)


def credenciales_validas(usuario: str, clave: str) -> bool:
    if _es_el_administrador(usuario):
        guardado = configuracion.admin_clave_hash
    else:
        definido = configuracion.usuarios.get(usuario)
        guardado = definido.clave_hash if definido else None
    conocido = guardado is not None and _es_argon2id(guardado)
    # Siempre se verifica una clave, aunque el usuario no exista (entonces, contra
    # la del administrador): así tarda lo mismo y no revela qué usuarios hay.
    try:
        clave_correcta = _hasher.verify(guardado if conocido else configuracion.admin_clave_hash, clave)
    except (VerificationError, InvalidHashError):
        clave_correcta = False
    return clave_correcta and conocido


def autenticar(bd: Session, usuario: str, clave: str, cliente: str) -> str:
    """Verifica las credenciales respetando el límite de intentos.

    Devuelve el token de la sesión nueva o lanza ``CredencialesInvalidas``,
    ``IngresoBloqueado`` o ``AdministradorSinConfigurar``.
    """
    if not clave_definida():
        raise AdministradorSinConfigurar

    ahora = time.time()
    limite = configuracion.ingreso_intentos
    ventana = configuracion.ingreso_bloqueo_minutos * 60

    # El intento se anota y confirma antes de verificar la clave, y se cuenta
    # después: así, en peticiones simultáneas cada una ve a las demás y nadie
    # consigue más verificaciones que el límite. Verificar es lo caro (64 MiB),
    # de modo que el límite también protege a la API de quedarse sin memoria.
    bd.execute(delete(IntentoIngreso).where(IntentoIngreso.ocurrido_en <= ahora - ventana))
    intento = IntentoIngreso(cliente=cliente, ocurrido_en=ahora)
    bd.add(intento)
    bd.flush()
    id_intento = intento.id
    bd.commit()

    del_cliente = list(
        bd.scalars(
            select(IntentoIngreso.ocurrido_en)
            .where(IntentoIngreso.cliente == cliente)
            .order_by(IntentoIngreso.ocurrido_en)
        )
    )
    total, primero = bd.execute(
        select(func.count(), func.min(IntentoIngreso.ocurrido_en)).select_from(IntentoIngreso)
    ).one()

    if len(del_cliente) > limite or total > configuracion.ingreso_intentos_globales:
        # No cuenta como intento: insistir durante el bloqueo no lo alarga.
        bd.execute(delete(IntentoIngreso).where(IntentoIngreso.id == id_intento))
        bd.commit()
        libre_en = del_cliente[0] if len(del_cliente) > limite else primero
        registro.warning("Ingreso bloqueado por demasiados intentos: %s", cliente)
        raise IngresoBloqueado(libre_en + ventana - ahora)

    if not credenciales_validas(usuario, clave):
        registro.warning("Ingreso fallido (%d de %d): %s", len(del_cliente), limite, cliente)
        quedan = limite - len(del_cliente)
        if quedan > 0:
            raise CredencialesInvalidas(quedan)
        raise IngresoBloqueado(del_cliente[0] + ventana - ahora)

    bd.execute(delete(IntentoIngreso).where(IntentoIngreso.cliente == cliente))
    token = abrir_sesion(bd, cliente, ahora, usuario=usuario)
    bd.commit()
    registro.info("Ingreso de %s: %s", usuario, cliente)
    return token


def _huella(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def abrir_sesion(
    bd: Session, cliente: str, ahora: float | None = None, *, usuario: str | None = None
) -> str:
    """Sin ``usuario``, la del administrador."""
    ahora = time.time() if ahora is None else ahora
    inactividad = configuracion.sesion_inactividad_minutos * 60
    bd.execute(
        delete(SesionAcceso).where(
            or_(SesionAcceso.vence_en <= ahora, SesionAcceso.ultimo_uso <= ahora - inactividad)
        )
    )
    token = secrets.token_urlsafe(32)
    bd.add(
        SesionAcceso(
            token_hash=_huella(token),
            usuario=usuario or configuracion.admin_usuario,
            cliente=cliente,
            creada_en=ahora,
            ultimo_uso=ahora,
            vence_en=ahora + configuracion.sesion_horas * 3600,
        )
    )
    return token


def sesion_vigente(token: str) -> Acceso | None:
    """De quién es la sesión, o None si no vale.

    Consulta la base: llamarla desde un hilo, no desde el bucle de eventos. Las
    teselas de un plano llegan de a muchas a la vez: con sentencias directas no
    pasa nada si otra petición ya borró o actualizó la misma fila.
    """
    ahora = time.time()
    esta_sesion = SesionAcceso.token_hash == _huella(token)
    with SesionLocal() as bd:
        fila = bd.execute(
            select(SesionAcceso.usuario, SesionAcceso.ultimo_uso, SesionAcceso.vence_en).where(
                esta_sesion
            )
        ).first()
        if fila is None:
            return None
        inactividad = configuracion.sesion_inactividad_minutos * 60
        # El usuario pudo quitarse después de ingresar.
        acceso = acceso_de(fila.usuario)
        if acceso is None or fila.vence_en <= ahora or fila.ultimo_uso <= ahora - inactividad:
            bd.execute(delete(SesionAcceso).where(esta_sesion))
            bd.commit()
            return None
        if ahora - fila.ultimo_uso >= _ANOTAR_USO_CADA:
            bd.execute(update(SesionAcceso).where(esta_sesion).values(ultimo_uso=ahora))
            bd.commit()
        return acceso


def cerrar_sesion(bd: Session, token: str | None) -> None:
    if token:
        bd.execute(delete(SesionAcceso).where(SesionAcceso.token_hash == _huella(token)))


def cerrar_todas_las_sesiones(bd: Session) -> None:
    bd.execute(delete(SesionAcceso))


def cerrar_sesiones_de(bd: Session, usuario: str) -> None:
    bd.execute(delete(SesionAcceso).where(SesionAcceso.usuario == usuario))


def levantar_bloqueos(bd: Session) -> None:
    bd.execute(delete(IntentoIngreso))


def token_monitoreo_valido(token: str | None, authorization: str | None) -> bool:
    """El token llega en ``X-NetDoc-Token`` o como ``Authorization: Bearer``."""
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    esperado = configuracion.monitoreo_token
    return bool(esperado and token) and hmac.compare_digest(token.encode(), esperado.encode())
