"""Acceso: credenciales, límite de intentos y sesiones del administrador."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update

from app.core.config import configuracion
from app.db.session import SesionLocal
from app.main import app
from app.models import IntentoIngreso, SesionAcceso
from app.servicios import autenticacion
from app.servicios.autenticacion import (
    abrir_sesion,
    cerrar_todas_las_sesiones,
    cifrar_clave,
    clave_definida,
    credenciales_validas,
)
from app.servicios.proteccion import COOKIE_HTTP, COOKIE_HTTPS
from tests.conftest import EQUIPO_LOCAL

API = "/api/v1"
INGRESO = f"{API}/auth/ingresar"
CLAVE = "clave-de-prueba"
HASH = cifrar_clave(CLAVE)
BUENAS = {"usuario": "admin-netdoc", "clave": CLAVE}
MALAS = {"usuario": "admin-netdoc", "clave": "incorrecta"}


@pytest.fixture(autouse=True)
def administrador(monkeypatch):
    """Una clave conocida (la real no está en el repositorio) y sin intentos previos."""
    monkeypatch.setattr(configuracion, "admin_clave_hash", HASH)
    with SesionLocal() as bd:
        bd.execute(delete(IntentoIngreso))
        bd.commit()


def _desde(ip: str) -> TestClient:
    return TestClient(app, base_url="https://netdoc.umag.cl", client=(ip, 50000))


def _intentos() -> int:
    with SesionLocal() as bd:
        return bd.scalar(select(func.count()).select_from(IntentoIngreso))


def _envejecer_intentos(segundos: float) -> None:
    with SesionLocal() as bd:
        bd.execute(update(IntentoIngreso).values(ocurrido_en=IntentoIngreso.ocurrido_en - segundos))
        bd.commit()


def _token_con(**columnas) -> str:
    with SesionLocal() as bd:
        token = abrir_sesion(bd, "pruebas")
        bd.commit()
        bd.execute(update(SesionAcceso).values(**columnas))
        bd.commit()
    return token


def _usa(cliente: TestClient, token: str) -> int:
    cliente.cookies.set(COOKIE_HTTP, token)
    return cliente.get(f"{API}/edificios").status_code


# --- Credenciales ------------------------------------------------------------
def test_el_usuario_por_omision_es_el_administrador():
    assert type(configuracion).model_fields["admin_usuario"].default == "admin-netdoc"


def test_la_contrasena_no_tiene_valor_por_omision_en_el_codigo():
    # Si falla: el hash debe vivir en .env, nunca en el repositorio.
    assert type(configuracion).model_fields["admin_clave_hash"].default == ""


def test_ingreso_correcto_abre_la_aplicacion(anonimo):
    assert anonimo.get(f"{API}/edificios").status_code == 401

    respuesta = anonimo.post(INGRESO, json=BUENAS)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"usuario": "admin-netdoc", "edificio": None}

    cookie = respuesta.headers["set-cookie"].lower()
    assert cookie.startswith(f"{COOKIE_HTTP}=")
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie
    assert "secure" not in cookie  # en este equipo se atiende por http

    assert anonimo.get(f"{API}/auth/sesion").json() == {"usuario": "admin-netdoc", "edificio": None}
    assert anonimo.get(f"{API}/edificios").status_code == 200


def test_sobre_https_la_cookie_es_secure_y_con_prefijo_host():
    cliente = _desde("10.0.0.5")
    respuesta = cliente.post(INGRESO, json=BUENAS)
    cookie = respuesta.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_HTTPS}=")
    assert "secure" in cookie.lower()
    assert "domain" not in cookie.lower()
    assert cliente.get(f"{API}/auth/sesion").status_code == 200


@pytest.mark.parametrize(
    "usuario, clave",
    [
        ("admin-netdoc", "incorrecta"),
        ("admin-netdoc", ""),
        ("otro", CLAVE),
        ("", ""),
        ("administración", "contraseña"),  # no ASCII: se rechaza, no revienta
    ],
)
def test_credenciales_incorrectas(anonimo, usuario, clave):
    respuesta = anonimo.post(INGRESO, json={"usuario": usuario, "clave": clave})
    assert respuesta.status_code == 401
    assert "set-cookie" not in respuesta.headers
    assert anonimo.get(f"{API}/edificios").status_code == 401


def test_el_mensaje_no_distingue_si_fallo_el_usuario_o_la_clave(anonimo):
    usuario = anonimo.post(INGRESO, json={"usuario": "otro", "clave": CLAVE}).json()["detail"]
    clave = anonimo.post(INGRESO, json=MALAS).json()["detail"]
    assert usuario.split(".")[0] == clave.split(".")[0] == "Usuario o contraseña incorrectos"


def test_caracteres_invalidos_se_rechazan_sin_reventar(anonimo):
    respuesta = anonimo.post(
        INGRESO,
        content=b'{"usuario": "\\ud800", "clave": "\\ud800"}',
        headers={"Content-Type": "application/json"},
    )
    assert respuesta.status_code == 422


def test_un_error_de_validacion_no_devuelve_lo_recibido(anonimo):
    respuesta = anonimo.post(INGRESO, json={"usuario": "admin-netdoc", "clave": "secreta" * 200})
    assert respuesta.status_code == 422
    assert respuesta.json()["detail"][0]["loc"] == ["body", "clave"]
    assert "secreta" not in respuesta.text


def test_sin_contrasena_definida_nadie_ingresa(anonimo, monkeypatch):
    monkeypatch.setattr(configuracion, "admin_clave_hash", "")
    assert not clave_definida()
    respuesta = anonimo.post(INGRESO, json={"usuario": "admin-netdoc", "clave": ""})
    assert respuesta.status_code == 503
    assert "definir_clave" in respuesta.json()["detail"]
    assert _intentos() == 0


@pytest.mark.parametrize(
    "valor",
    [
        "basura",
        "$",
        "$argon2id$",
        "00112233445566778899aabbccddeeff.0011223344556677",  # el formato scrypt anterior
        "$argon2i$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2g",  # otra variante de Argon2
    ],
)
def test_un_hash_que_no_es_argon2id_no_sirve(anonimo, monkeypatch, valor):
    monkeypatch.setattr(configuracion, "admin_clave_hash", valor)
    assert not clave_definida()
    assert anonimo.post(INGRESO, json=BUENAS).status_code == 503


def test_la_clave_se_guarda_como_argon2id_con_sal():
    uno, otro = cifrar_clave(CLAVE), cifrar_clave(CLAVE)
    assert uno.startswith("$argon2id$")
    assert CLAVE not in uno
    assert uno != otro


def test_credenciales_validas_compara_usuario_y_clave():
    assert credenciales_validas("admin-netdoc", CLAVE)
    assert not credenciales_validas("admin-netdoc", "otra")
    assert not credenciales_validas("otro", CLAVE)


# --- Límite de intentos ------------------------------------------------------
def test_el_tercer_intento_fallido_bloquea(anonimo):
    primero = anonimo.post(INGRESO, json=MALAS)
    assert primero.status_code == 401
    assert "2 intentos antes del bloqueo" in primero.json()["detail"]

    segundo = anonimo.post(INGRESO, json=MALAS)
    assert segundo.status_code == 401
    assert "1 intento antes del bloqueo" in segundo.json()["detail"]

    tercero = anonimo.post(INGRESO, json=MALAS)
    assert tercero.status_code == 429
    assert "15 minutos" in tercero.json()["detail"]
    assert 890 <= int(tercero.headers["retry-after"]) <= 900


def test_durante_el_bloqueo_ni_la_clave_correcta_sirve(anonimo, monkeypatch):
    for _ in range(3):
        anonimo.post(INGRESO, json=MALAS)

    llamadas = []
    monkeypatch.setattr(
        autenticacion, "credenciales_validas", lambda *a: llamadas.append(a) or True
    )
    respuesta = anonimo.post(INGRESO, json=BUENAS)
    assert respuesta.status_code == 429
    assert "set-cookie" not in respuesta.headers
    assert llamadas == []  # ni siquiera se gasta en verificarla


def test_insistir_durante_el_bloqueo_no_lo_alarga(anonimo):
    for _ in range(3):
        anonimo.post(INGRESO, json=MALAS)
    for _ in range(5):
        assert anonimo.post(INGRESO, json=MALAS).status_code == 429
    assert _intentos() == 3


def test_el_bloqueo_termina_al_pasar_la_ventana(anonimo):
    for _ in range(3):
        anonimo.post(INGRESO, json=MALAS)
    _envejecer_intentos(configuracion.ingreso_bloqueo_minutos * 60 - 30)
    assert anonimo.post(INGRESO, json=BUENAS).status_code == 429

    _envejecer_intentos(31)
    assert anonimo.post(INGRESO, json=BUENAS).status_code == 200


def test_el_ingreso_correcto_reinicia_la_cuenta(anonimo):
    anonimo.post(INGRESO, json=MALAS)
    anonimo.post(INGRESO, json=MALAS)
    assert anonimo.post(INGRESO, json=BUENAS).status_code == 200
    assert _intentos() == 0
    assert "2 intentos" in anonimo.post(INGRESO, json=MALAS).json()["detail"]


def test_reiniciar_la_api_no_borra_el_bloqueo(anonimo):
    # La cuenta vive en la base, no en el proceso.
    for _ in range(3):
        anonimo.post(INGRESO, json=MALAS)
    assert TestClient(app, client=EQUIPO_LOCAL).post(INGRESO, json=BUENAS).status_code == 429


def test_un_equipo_bloqueado_no_deja_afuera_a_los_demas():
    for _ in range(3):
        _desde("10.0.0.5").post(INGRESO, json=MALAS)
    assert _desde("10.0.0.5").post(INGRESO, json=BUENAS).status_code == 429
    assert _desde("10.0.0.6").post(INGRESO, json=BUENAS).status_code == 200


def test_rotar_la_ipv6_dentro_de_su_red_no_da_mas_intentos():
    for ip in ("2001:db8:1:1::a", "2001:db8:1:1::b", "2001:db8:1:1::c"):
        _desde(ip).post(INGRESO, json=MALAS)
    assert _desde("2001:db8:1:1::d").post(INGRESO, json=BUENAS).status_code == 429
    assert _desde("2001:db8:1:2::a").post(INGRESO, json=BUENAS).status_code == 200


def test_un_ataque_repartido_tambien_tiene_limite(monkeypatch):
    monkeypatch.setattr(configuracion, "ingreso_intentos_globales", 4)
    for n in range(4):
        assert _desde(f"10.0.1.{n}").post(INGRESO, json=MALAS).status_code == 401
    assert _desde("10.0.1.200").post(INGRESO, json=BUENAS).status_code == 429


def test_peticiones_simultaneas_no_consiguen_mas_verificaciones(monkeypatch):
    verificaciones = []

    def verificar(usuario, clave):
        verificaciones.append(clave)
        time.sleep(0.05)
        return False

    monkeypatch.setattr(autenticacion, "credenciales_validas", verificar)
    with ThreadPoolExecutor(max_workers=12) as hilos:
        codigos = list(
            hilos.map(
                lambda _: TestClient(app, client=EQUIPO_LOCAL).post(INGRESO, json=MALAS).status_code,
                range(12),
            )
        )
    assert len(verificaciones) <= 3
    assert set(codigos) <= {401, 429}
    assert 429 in codigos


# --- Sesiones ----------------------------------------------------------------
def test_la_base_guarda_la_huella_del_token_no_el_token(anonimo):
    anonimo.post(INGRESO, json=BUENAS)
    token = anonimo.cookies[COOKIE_HTTP]
    assert len(token) >= 43  # 256 bits en base64
    with SesionLocal() as bd:
        guardados = bd.scalars(select(SesionAcceso.token_hash)).all()
    assert token not in guardados
    assert autenticacion._huella(token) in guardados


def test_cada_ingreso_crea_un_token_nuevo(anonimo):
    anonimo.post(INGRESO, json=BUENAS)
    primero = anonimo.cookies[COOKIE_HTTP]
    otro = TestClient(app, client=EQUIPO_LOCAL)
    otro.post(INGRESO, json=BUENAS)
    assert otro.cookies[COOKIE_HTTP] != primero


def test_salir_invalida_el_token_en_el_servidor(anonimo):
    anonimo.post(INGRESO, json=BUENAS)
    token = anonimo.cookies[COOKIE_HTTP]

    respuesta = anonimo.post(f"{API}/auth/salir")
    assert respuesta.status_code == 204
    assert f'{COOKIE_HTTP}=""' in respuesta.headers["set-cookie"]

    # Aunque alguien hubiera copiado la cookie, ya no vale.
    copia = TestClient(app, client=EQUIPO_LOCAL)
    assert _usa(copia, token) == 401


def test_cambiar_la_contrasena_cierra_todas_las_sesiones(anonimo):
    anonimo.post(INGRESO, json=BUENAS)
    assert anonimo.get(f"{API}/edificios").status_code == 200
    with SesionLocal() as bd:
        cerrar_todas_las_sesiones(bd)
        bd.commit()
    assert anonimo.get(f"{API}/edificios").status_code == 401


def test_la_sesion_vence_por_inactividad(anonimo):
    limite = time.time() - configuracion.sesion_inactividad_minutos * 60
    assert _usa(anonimo, _token_con(ultimo_uso=limite - 1)) == 401
    assert _usa(anonimo, _token_con(ultimo_uso=limite + 30)) == 200


def test_la_sesion_vence_por_duracion_total_aunque_se_use(anonimo):
    assert _usa(anonimo, _token_con(vence_en=time.time() - 1)) == 401


def test_el_uso_renueva_la_inactividad_sin_escribir_en_cada_peticion(anonimo):
    hace_dos_minutos = time.time() - 120
    token = _token_con(ultimo_uso=hace_dos_minutos)
    assert _usa(anonimo, token) == 200

    filtro = SesionAcceso.token_hash == autenticacion._huella(token)
    with SesionLocal() as bd:
        anotado = bd.scalar(select(SesionAcceso.ultimo_uso).where(filtro))
    assert anotado > hace_dos_minutos + 100

    assert _usa(anonimo, token) == 200
    with SesionLocal() as bd:
        assert bd.scalar(select(SesionAcceso.ultimo_uso).where(filtro)) == anotado


@pytest.mark.parametrize(
    "columnas, codigo",
    [
        ({"ultimo_uso": 1.0}, 401),  # varias borran la misma sesión vencida
        ({"ultimo_uso": time.time() - 120}, 200),  # varias anotan el uso de la misma
    ],
)
def test_muchas_peticiones_a_la_vez_con_la_misma_sesion(columnas, codigo):
    # Las teselas de un plano llegan así; TestClient propaga cualquier error interno.
    token = _token_con(**columnas)

    def pedir(_):
        cliente = TestClient(app, client=EQUIPO_LOCAL, cookies={COOKIE_HTTP: token})
        return cliente.get(f"{API}/auth/sesion").status_code

    with ThreadPoolExecutor(max_workers=12) as hilos:
        assert set(hilos.map(pedir, range(24))) == {codigo}


@pytest.mark.parametrize("token", ["basura", ".", "x" * 43, "9999999999.firma-falsa"])
def test_token_inventado_se_rechaza(anonimo, token):
    assert _usa(anonimo, token) == 401


def test_cookie_no_ascii_se_rechaza_sin_reventar(anonimo):
    cookie = f"{COOKIE_HTTP}=ñandú".encode("latin-1")
    assert anonimo.get(f"{API}/edificios", headers={"Cookie": cookie}).status_code == 401
