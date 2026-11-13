"""Otros usuarios además del administrador, y el que solo tiene acceso a un edificio."""

from __future__ import annotations

import io
import json
import subprocess

import pytest
from dotenv import dotenv_values
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.core.config import Configuracion, UsuarioAdicional, configuracion
from app.db.session import SesionLocal
from app.main import app
from app.models import IntentoIngreso, SesionAcceso
from app.scripts import usuarios
from app.servicios import autenticacion
from app.servicios.autenticacion import abrir_sesion, cifrar_clave
from app.servicios.proteccion import COOKIE_HTTP
from tests.conftest import EQUIPO_LOCAL

API = "/api/v1"
INGRESO = f"{API}/auth/ingresar"

# Inventadas: las reales no están en el repositorio.
CLAVE_ADMIN = "clave-del-administrador"
CLAVE = "clave-del-otro-usuario"
HASH = cifrar_clave(CLAVE)
#: Sin límite de edificio, y limitado a PRO («propio»). AJE es el «ajeno».
OTRO = "otro-admin"
LIMITADO = "solo-pro"
USUARIOS = {
    OTRO: UsuarioAdicional(clave_hash=HASH),
    LIMITADO: UsuarioAdicional(clave_hash=HASH, edificio="PRO"),
}
SVG = "<svg xmlns='http://www.w3.org/2000/svg'/>"


def _con_sesion_de(usuario: str | None) -> TestClient:
    with SesionLocal() as bd:
        token = abrir_sesion(bd, "pruebas", usuario=usuario)
        bd.commit()
    return TestClient(app, client=EQUIPO_LOCAL, cookies={COOKIE_HTTP: token})


@pytest.fixture(autouse=True)
def usuarios_definidos(monkeypatch):
    monkeypatch.setattr(configuracion, "admin_clave_hash", cifrar_clave(CLAVE_ADMIN))
    monkeypatch.setattr(configuracion, "usuarios", dict(USUARIOS))
    with SesionLocal() as bd:
        bd.execute(delete(IntentoIngreso))
        bd.commit()


@pytest.fixture(scope="module")
def datos() -> dict:
    """Dos edificios con lo mismo: lo de AJE lleva «AJE» en todo lo que se muestra."""
    admin = _con_sesion_de(None)
    ids = {}
    for edificio in ("PRO", "AJE"):
        admin.post(f"{API}/edificios", json={"codigo": edificio, "nombre": f"Edificio {edificio}"})
        admin.post(f"{API}/edificios/{edificio}/pisos", json={"codigo": "P01", "orden": 1})
        base = {"edificio": edificio, "piso": "P01"}
        rack = admin.post(f"{API}/elementos", json={"tipo": "R", **base}).json()
        switch = admin.post(
            f"{API}/elementos",
            json={"tipo": "SW", "estado_operativo": "inactivo", "padre_codigo": rack["codigo"], **base},
        ).json()
        vlan = admin.post(
            f"{API}/vlans", json={"numero": 77, "nombre": f"VLAN-{edificio}", "edificio": edificio}
        ).json()
        admin.post(
            f"{API}/enlaces",
            json={
                "origen_codigo": rack["codigo"],
                "destino_codigo": switch["codigo"],
                "etiqueta": f"ENLACE-{edificio}",
            },
        )
        ids[edificio] = {"rack": rack["id"], "switch": switch["id"], "vlan": vlan["id"]}
        teselas = configuracion.dir_media / "teselas" / f"{edificio}-P01-v1" / "0" / "0"
        teselas.mkdir(parents=True, exist_ok=True)
        (teselas / "0.png").write_bytes(b"png")
        (configuracion.dir_planos / f"{edificio}-P01-v1.svg").write_text(SVG, encoding="utf-8")
        (configuracion.dir_fotografias / f"{edificio}-SW01-P01_1.jpg").write_bytes(b"jpg")
    ids["campus"] = admin.post(f"{API}/vlans", json={"numero": 78, "nombre": "VLAN-CAMPUS"}).json()["id"]
    return ids


@pytest.fixture
def limitado(datos) -> TestClient:
    return _con_sesion_de(LIMITADO)


@pytest.fixture
def otro(datos) -> TestClient:
    return _con_sesion_de(OTRO)


# --- Ingreso: la misma protección que el administrador ---------------------------------


def test_otro_usuario_ingresa_con_su_contrasena(anonimo):
    respuesta = anonimo.post(INGRESO, json={"usuario": OTRO, "clave": CLAVE})
    assert respuesta.status_code == 200
    assert respuesta.json() == {"usuario": OTRO, "edificio": None}
    assert "httponly" in respuesta.headers["set-cookie"].lower()
    assert anonimo.get(f"{API}/auth/sesion").json() == {"usuario": OTRO, "edificio": None}
    assert anonimo.get(f"{API}/edificios").status_code == 200


def test_el_limitado_sabe_al_ingresar_cual_es_su_edificio(anonimo):
    respuesta = anonimo.post(INGRESO, json={"usuario": LIMITADO, "clave": CLAVE})
    assert respuesta.json() == {"usuario": LIMITADO, "edificio": "PRO"}
    assert anonimo.get(f"{API}/auth/sesion").json() == {"usuario": LIMITADO, "edificio": "PRO"}


@pytest.mark.parametrize(
    "usuario, clave",
    [
        (OTRO, "incorrecta"),
        (OTRO, CLAVE_ADMIN),  # la de otro usuario no sirve…
        ("admin-netdoc", CLAVE),  # …ni la suya para entrar como el administrador
        (OTRO.upper(), CLAVE),
        ("no-existe", CLAVE),
    ],
)
def test_cada_contrasena_sirve_solo_para_su_usuario(anonimo, usuario, clave):
    respuesta = anonimo.post(INGRESO, json={"usuario": usuario, "clave": clave})
    assert respuesta.status_code == 401
    assert "Usuario o contraseña incorrectos" in respuesta.json()["detail"]


def test_el_administrador_sigue_ingresando(anonimo):
    respuesta = anonimo.post(INGRESO, json={"usuario": "admin-netdoc", "clave": CLAVE_ADMIN})
    assert respuesta.json() == {"usuario": "admin-netdoc", "edificio": None}


def test_el_limite_de_intentos_es_el_mismo(anonimo):
    malas = {"usuario": OTRO, "clave": "incorrecta"}
    assert [anonimo.post(INGRESO, json=malas).status_code for _ in range(3)] == [401, 401, 429]
    # Bloqueado el equipo, tampoco entra con la correcta ni como otro usuario.
    assert anonimo.post(INGRESO, json={"usuario": OTRO, "clave": CLAVE}).status_code == 429
    assert anonimo.post(INGRESO, json={"usuario": LIMITADO, "clave": CLAVE}).status_code == 429


def test_probar_varios_usuarios_no_da_mas_intentos(anonimo):
    codigos = [
        anonimo.post(INGRESO, json={"usuario": usuario, "clave": "incorrecta"}).status_code
        for usuario in ("admin-netdoc", OTRO, LIMITADO, "no-existe")
    ]
    assert codigos == [401, 401, 429, 429]


def test_la_clave_se_verifica_aunque_el_usuario_no_exista(monkeypatch):
    # Si no, responder más rápido delataría qué usuarios existen.
    verificadas = []
    real = autenticacion._hasher.verify
    monkeypatch.setattr(
        autenticacion,
        "_hasher",
        type("Contador", (), {"verify": lambda self, h, c: verificadas.append(h) or real(h, c)})(),
    )
    assert not autenticacion.credenciales_validas("no-existe", CLAVE)
    assert not autenticacion.credenciales_validas(OTRO, "incorrecta")
    assert autenticacion.credenciales_validas(OTRO, CLAVE)
    assert len(verificadas) == 3


@pytest.mark.parametrize("valor", ["", "texto-plano", "$argon2i$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2g"])
def test_un_usuario_sin_hash_argon2id_no_ingresa(anonimo, monkeypatch, valor):
    monkeypatch.setattr(configuracion, "usuarios", {OTRO: UsuarioAdicional(clave_hash=valor)})
    for clave in (CLAVE, valor, CLAVE_ADMIN):
        with SesionLocal() as bd:
            bd.execute(delete(IntentoIngreso))
            bd.commit()
        assert anonimo.post(INGRESO, json={"usuario": OTRO, "clave": clave}).status_code == 401


def test_sin_la_contrasena_del_administrador_nadie_ingresa(anonimo, monkeypatch):
    monkeypatch.setattr(configuracion, "admin_clave_hash", "")
    assert anonimo.post(INGRESO, json={"usuario": OTRO, "clave": CLAVE}).status_code == 503


def test_la_sesion_guarda_de_quien_es(anonimo):
    anonimo.post(INGRESO, json={"usuario": LIMITADO, "clave": CLAVE})
    with SesionLocal() as bd:
        assert bd.scalar(select(SesionAcceso.usuario).order_by(SesionAcceso.id.desc())) == LIMITADO


def test_quitar_un_usuario_deja_sin_efecto_su_sesion(otro, monkeypatch):
    assert otro.get(f"{API}/edificios").status_code == 200
    monkeypatch.setattr(configuracion, "usuarios", {})
    assert otro.get(f"{API}/edificios").status_code == 401


def test_limitar_a_un_usuario_vale_para_la_sesion_que_ya_tenia(otro, monkeypatch):
    assert otro.get(f"{API}/edificios/AJE").status_code == 200
    monkeypatch.setattr(
        configuracion, "usuarios", {OTRO: UsuarioAdicional(clave_hash=HASH, edificio="PRO")}
    )
    assert otro.get(f"{API}/edificios/AJE").status_code == 403


def test_salir_cierra_solo_la_propia_sesion(otro, limitado):
    assert otro.post(f"{API}/auth/salir").status_code == 204
    assert otro.get(f"{API}/auth/sesion").status_code == 401
    assert limitado.get(f"{API}/auth/sesion").status_code == 200


# --- Sin límite de edificio: como el administrador -------------------------------------


def test_el_otro_administrador_ve_y_modifica_todos_los_edificios(otro):
    codigos = {e["codigo"] for e in otro.get(f"{API}/edificios").json()}
    assert {"PRO", "AJE", "CADI"} <= codigos
    assert otro.get(f"{API}/elementos/AJE-SW01-P01").status_code == 200
    assert otro.patch(f"{API}/elementos/AJE-SW01-P01", json={"marca": "AJE"}).status_code == 200
    assert otro.get("/media/planos/AJE-P01-v1.svg").status_code == 200
    assert otro.get("/openapi.json").status_code == 200


# --- Limitado a un edificio ------------------------------------------------------------


def test_en_su_edificio_trabaja_como_un_administrador(limitado):
    assert [e["codigo"] for e in limitado.get(f"{API}/edificios").json()] == ["PRO"]
    assert limitado.get(f"{API}/edificios/PRO/pisos").status_code == 200
    assert limitado.get(f"{API}/elementos/mapa?edificio=PRO&piso=P01").status_code == 200
    assert limitado.get(f"{API}/reportes/resumen?edificio=PRO").status_code == 200

    creado = limitado.post(f"{API}/elementos", json={"tipo": "AP", "edificio": "PRO", "piso": "P01"})
    assert creado.status_code == 201, creado.text
    codigo = creado.json()["codigo"]
    assert limitado.patch(f"{API}/elementos/{codigo}", json={"marca": "Ubiquiti"}).status_code == 200
    assert limitado.delete(f"{API}/elementos/{codigo}").status_code == 200
    assert limitado.post(f"{API}/elementos/{codigo}/restaurar").status_code == 200
    assert limitado.post(f"{API}/edificios/PRO/pisos", json={"codigo": "P02", "orden": 2}).status_code in (201, 409)
    assert limitado.get(f"{API}/catalogo/tipos").status_code == 200


def test_sus_listados_solo_traen_su_edificio(limitado, cliente):
    for ruta in (f"{API}/elementos?limite=1000", f"{API}/reportes/fuera-de-servicio", f"{API}/enlaces"):
        assert "AJE" in cliente.get(ruta).text, ruta  # el administrador sí los ve
        propio = limitado.get(ruta)
        assert propio.status_code == 200
        assert "PRO" in propio.text and "AJE" not in propio.text and "CADI-" not in propio.text, ruta


def test_ve_las_vlan_de_su_edificio_y_las_de_campus(limitado):
    assert {v["nombre"] for v in limitado.get(f"{API}/vlans").json()} == {"VLAN-PRO", "VLAN-CAMPUS"}
    assert [v["nombre"] for v in limitado.get(f"{API}/vlans?edificio=PRO").json()] == ["VLAN-PRO"]


def test_no_asigna_la_vlan_de_otro_edificio(limitado, datos):
    def asignar(vlan):
        return limitado.post(f"{API}/elementos/PRO-SW01-P01/vlans", json={"vlan_id": vlan})

    assert asignar(datos["AJE"]["vlan"]).status_code == 404
    assert asignar(datos["PRO"]["vlan"]).status_code == 200
    assert asignar(datos["campus"]).status_code == 200


def test_un_elemento_ajeno_no_se_alcanza_por_su_id(limitado, datos):
    assert limitado.get(f"{API}/elementos/{datos['PRO']['switch']}").status_code == 200
    ajeno = limitado.get(f"{API}/elementos/{datos['AJE']['switch']}")
    assert ajeno.status_code == 404
    # Igual que uno que no existe: no revela que está en otro edificio.
    assert ajeno.json()["detail"].startswith("No existe el elemento")


def test_no_puede_relacionar_lo_suyo_con_lo_ajeno(limitado):
    propio = f"{API}/elementos/PRO-SW01-P01"
    assert limitado.patch(propio, json={"padre_codigo": "AJE-R01-P01"}).status_code == 404
    enlace = {"origen_codigo": "PRO-R01-P01", "destino_codigo": "AJE-SW01-P01"}
    assert limitado.post(f"{API}/enlaces", json=enlace).status_code == 404
    punto = {"tipo": "PD", "edificio": "PRO", "piso": "P01", "rack_origen": "AJE-R01-P01", "puerto": "D01"}
    assert limitado.post(f"{API}/elementos", json=punto).status_code == 404


def test_sus_archivos_son_solo_los_de_su_edificio(limitado, cliente):
    for carpeta, archivo in (
        ("planos", "{}-P01-v1.svg"),
        ("teselas", "{}-P01-v1/0/0/0.png"),
        ("fotografias", "{}-SW01-P01_1.jpg"),
    ):
        assert limitado.get(f"/media/{carpeta}/{archivo.format('PRO')}").status_code == 200
        assert limitado.get(f"/media/{carpeta}/{archivo.format('pro')}").status_code in (200, 404)
        assert cliente.get(f"/media/{carpeta}/{archivo.format('AJE')}").status_code == 200
        ajeno = limitado.get(f"/media/{carpeta}/{archivo.format('AJE')}")
        assert ajeno.status_code == 403
        assert "PRO" in ajeno.json()["detail"]


@pytest.mark.parametrize(
    "ruta",
    [
        "/media/planos/PRO-x/../AJE-P01-v1.svg",
        "/media/planos/PRO-x/%2e%2e/AJE-P01-v1.svg",
        "/media/planos/PRO-x/..%2fAJE-P01-v1.svg",
        # Un «?» o «#» codificado no corta la ruta que se revisa.
        "/media/planos/PRO-x%3F/../AJE-P01-v1.svg",
        "/media/planos/PRO-x%23/../AJE-P01-v1.svg",
        "/media/planos/./AJE-P01-v1.svg",
        "/media/planos//AJE-P01-v1.svg",
        "/media/PRO-x/../planos/AJE-P01-v1.svg",
        "/media/teselas/PRO-P01-v1/../AJE-P01-v1/0/0/0.png",
        "/media/planos",
        "/media/",
        "/media/planos/",
    ],
)
def test_un_nombre_con_rodeos_no_entrega_el_archivo_de_otro_edificio(limitado, ruta):
    respuesta = limitado.get(ruta)
    assert respuesta.status_code in (403, 404), respuesta.status_code
    assert SVG not in respuesta.text and respuesta.content != b"png"


def test_el_rodeo_si_resuelve_para_quien_tiene_acceso(cliente, datos):
    # Lo que hace necesaria la prueba anterior: el servidor de archivos resuelve los «..».
    assert cliente.get("/media/planos/PRO-x/%2e%2e/AJE-P01-v1.svg").text == SVG
    assert cliente.get("/media/planos/PRO-x%3F/../AJE-P01-v1.svg").text == SVG


# --- Cada ruta, pedida por el usuario limitado contra el edificio ajeno ---------------------
#: Plano válido para la carga: se rechaza antes de mirarlo.
_PLANO = {"files": {"archivo": ("aje-p01.svg", SVG, "image/svg+xml")}, "data": {"ancho_px": "10", "alto_px": "10"}}
_FOTO = {"files": {"archivo": ("foto.jpg", b"jpg", "image/jpeg")}}
_E = f"{API}/elementos/AJE-SW01-P01"
_I = f"{API}/integraciones"
#: «sin-ajeno»: responde, pero sin nada del otro edificio. «global»: no es de ningún edificio.
CASOS = [
    ("GET", "/", None, {}, "global"),
    ("GET", "/salud", "/salud", {}, "global"),
    ("GET", "/docs", "/docs", {}, 403),
    ("GET", "/metrics", "/metrics", {}, 403),
    ("POST", f"{API}/auth/ingresar", None, {}, "global"),
    ("GET", f"{API}/auth/sesion", f"{API}/auth/sesion", {}, "sin-ajeno"),
    ("POST", f"{API}/auth/salir", None, {}, "global"),
    ("GET", f"{API}/catalogo/tipos", f"{API}/catalogo/tipos", {}, "global"),
    ("GET", f"{API}/catalogo/tipos/{{codigo}}", f"{API}/catalogo/tipos/SW", {}, "global"),
    ("GET", f"{API}/catalogo/tipos/{{codigo}}/ficha", f"{API}/catalogo/tipos/SW/ficha", {}, "global"),
    ("GET", f"{API}/catalogo/enumeraciones", f"{API}/catalogo/enumeraciones", {}, "global"),
    ("POST", f"{API}/catalogo/tipos", f"{API}/catalogo/tipos", {"json": {"codigo": "NVO", "nombre": "Nuevo", "categoria": "activo"}}, 403),
    ("GET", f"{API}/edificios", f"{API}/edificios", {}, "sin-ajeno"),
    ("POST", f"{API}/edificios", f"{API}/edificios", {"json": {"codigo": "NVO", "nombre": "Nuevo"}}, 403),
    ("GET", f"{API}/edificios/{{codigo}}", f"{API}/edificios/AJE", {}, 403),
    ("GET", f"{API}/edificios/{{codigo}}/novedades", f"{API}/edificios/AJE/novedades", {}, 403),
    ("GET", f"{API}/edificios/{{codigo}}/carga-de-planos", f"{API}/edificios/AJE/carga-de-planos", {}, 403),
    ("POST", f"{API}/edificios/{{codigo}}/carga-de-planos", f"{API}/edificios/AJE/carga-de-planos", {"files": {"archivo": ("aje-p02.svg", SVG, "image/svg+xml")}}, 403),
    ("DELETE", f"{API}/edificios/{{codigo}}/carga-de-planos/{{archivo}}", f"{API}/edificios/AJE/carga-de-planos/aje-p02.svg", {}, 403),
    ("POST", f"{API}/edificios/{{codigo}}/carga-de-planos/confirmar", f"{API}/edificios/AJE/carga-de-planos/confirmar", {}, 403),
    ("DELETE", f"{API}/edificios/{{codigo}}/planos", f"{API}/edificios/AJE/planos?confirmar=AJE", {}, 403),
    ("GET", f"{API}/edificios/{{codigo}}/pisos", f"{API}/edificios/AJE/pisos", {}, 403),
    ("POST", f"{API}/edificios/{{codigo}}/pisos", f"{API}/edificios/AJE/pisos", {"json": {"codigo": "P09", "orden": 9}}, 403),
    ("POST", f"{API}/edificios/{{codigo}}/pisos/{{codigo_piso}}/tramos", f"{API}/edificios/AJE/pisos/P01/tramos", {"json": {"codigo": "T9"}}, 403),
    ("GET", f"{API}/edificios/{{codigo}}/pisos/{{codigo_piso}}/plano", f"{API}/edificios/AJE/pisos/P01/plano", {}, 403),
    ("GET", f"{API}/edificios/{{codigo}}/pisos/{{codigo_piso}}/recintos", f"{API}/edificios/AJE/pisos/P01/recintos", {}, 403),
    ("POST", f"{API}/edificios/{{codigo}}/pisos/{{codigo_piso}}/plano", f"{API}/edificios/AJE/pisos/P01/plano", _PLANO, 403),
    ("GET", f"{API}/elementos", f"{API}/elementos?limite=1000", {}, "sin-ajeno"),
    ("GET", f"{API}/elementos", f"{API}/elementos?edificio=AJE", {}, 403),
    ("GET", f"{API}/elementos", f"{API}/elementos?rack=AJE-R01-P01", {}, "sin-ajeno"),
    ("GET", f"{API}/elementos", f"{API}/elementos?q=AJE&solo_activos=false", {}, "sin-ajeno"),
    ("POST", f"{API}/elementos", f"{API}/elementos", {"json": {"tipo": "SW", "edificio": "AJE", "piso": "P01"}}, 403),
    ("GET", f"{API}/elementos/mapa", f"{API}/elementos/mapa?edificio=AJE&piso=P01", {}, 403),
    ("GET", f"{API}/elementos/proximo-codigo", f"{API}/elementos/proximo-codigo?tipo=SW&edificio=AJE&piso=P01", {}, 403),
    ("GET", f"{API}/elementos/{{id_o_codigo}}", _E, {}, 404),
    ("PATCH", f"{API}/elementos/{{id_o_codigo}}", _E, {"json": {"marca": "x"}}, 404),
    ("DELETE", f"{API}/elementos/{{id_o_codigo}}", _E, {}, 404),
    ("PUT", f"{API}/elementos/{{id_o_codigo}}/externos/{{sistema}}", f"{_E}/externos/zabbix", {"json": {"id_externo": "1"}}, 404),
    ("DELETE", f"{API}/elementos/{{id_o_codigo}}/externos/{{sistema}}", f"{_E}/externos/zabbix", {}, 404),
    ("GET", f"{API}/elementos/{{id_o_codigo}}/historial", f"{_E}/historial", {}, 404),
    ("PATCH", f"{API}/elementos/{{id_o_codigo}}/posicion", f"{_E}/posicion", {"json": {"plano_id": 1, "pos_x": 1, "pos_y": 1}}, 404),
    ("GET", f"{API}/elementos/{{id_o_codigo}}/traslado", f"{_E}/traslado?piso=P01", {}, 404),
    ("POST", f"{API}/elementos/{{id_o_codigo}}/trasladar", f"{_E}/trasladar", {"json": {"piso": "P01"}}, 404),
    ("POST", f"{API}/elementos/{{id_o_codigo}}/ubicar-en-recinto", f"{_E}/ubicar-en-recinto", {}, 404),
    ("POST", f"{API}/elementos/{{id_o_codigo}}/restaurar", f"{_E}/restaurar", {}, 404),
    ("POST", f"{API}/elementos/{{id_o_codigo}}/fotografias", f"{_E}/fotografias", _FOTO, 404),
    ("POST", f"{API}/elementos/{{id_o_codigo}}/vlans", f"{_E}/vlans", {"json": {"vlan_id": 1}}, 404),
    ("GET", f"{API}/vlans", f"{API}/vlans", {}, "sin-ajeno"),
    ("GET", f"{API}/vlans", f"{API}/vlans?edificio=AJE", {}, 403),
    ("POST", f"{API}/vlans", f"{API}/vlans", {"json": {"numero": 90, "nombre": "x", "edificio": "AJE"}}, 403),
    ("POST", f"{API}/vlans", f"{API}/vlans", {"json": {"numero": 91, "nombre": "de campus"}}, 403),
    ("GET", f"{API}/enlaces", f"{API}/enlaces", {}, "sin-ajeno"),
    ("GET", f"{API}/enlaces", f"{API}/enlaces?elemento=AJE-R01-P01", {}, 404),
    ("POST", f"{API}/enlaces", f"{API}/enlaces", {"json": {"origen_codigo": "AJE-R01-P01"}}, 404),
    ("GET", f"{API}/reportes/resumen", f"{API}/reportes/resumen?edificio=AJE", {}, 403),
    ("GET", f"{API}/reportes/elementos-incompletos", f"{API}/reportes/elementos-incompletos?edificio=AJE", {}, 403),
    ("GET", f"{API}/reportes/fuera-de-servicio", f"{API}/reportes/fuera-de-servicio", {}, "sin-ajeno"),
    ("GET", f"{API}/reportes/fuera-de-servicio", f"{API}/reportes/fuera-de-servicio?edificio=AJE", {}, 403),
    # Lo que leen otros sistemas es de todos los edificios: no es para este usuario.
    ("GET", f"{_I}/inventario", f"{_I}/inventario", {}, 403),
    ("GET", f"{_I}/cambios", f"{_I}/cambios", {}, 403),
    ("GET", f"{_I}/externos/{{sistema}}/{{id_externo}}", f"{_I}/externos/zabbix/1", {}, 403),
    ("GET", f"{_I}/prometheus/objetivos", f"{_I}/prometheus/objetivos", {}, 403),
    # Los avisos de monitoreo no usan la sesión: exigen su token.
    ("POST", f"{_I}/monitoreo/estado", f"{_I}/monitoreo/estado", {"json": {"codigo": "AJE-SW01-P01", "estado": "caido"}}, 401),
    ("POST", f"{_I}/alertmanager", f"{_I}/alertmanager", {"json": {"status": "firing", "alerts": []}}, 401),
]


def test_la_tabla_cubre_todas_las_rutas():
    # Si falla: hay una ruta nueva. Agréguela a CASOS con lo que debe responderle a un
    # usuario limitado a un edificio cuando pide lo de otro.
    # Las de la API salen de su esquema; las que no figuran en él («/», «/docs»), de la aplicación.
    existentes = {
        (metodo.upper(), ruta) for ruta, metodos in app.openapi()["paths"].items() for metodo in metodos
    } | {(metodo, ruta.path) for ruta in app.routes if isinstance(ruta, APIRoute) for metodo in ruta.methods}
    assert len(existentes) > 50
    assert existentes == {(metodo, plantilla) for metodo, plantilla, *_ in CASOS}


@pytest.mark.parametrize(
    "metodo, url, opciones, esperado",
    [pytest.param(*caso[:1], *caso[2:], id=f"{caso[0]} {caso[2]}") for caso in CASOS if caso[2]],
)
def test_ninguna_ruta_entrega_ni_cambia_lo_de_otro_edificio(limitado, cliente, metodo, url, opciones, esperado):
    respuesta = limitado.request(metodo, url, **opciones)
    if esperado == "global":
        assert respuesta.status_code == 200
    elif esperado == "sin-ajeno":
        assert respuesta.status_code == 200
        assert "AJE" not in respuesta.text
    else:
        assert respuesta.status_code == esperado, respuesta.text
        # El rechazo puede repetir el código que se pidió, y nada más de ese edificio.
        assert "AJE" not in respuesta.text.replace("AJE-SW01-P01", "").replace("AJE-R01-P01", "")
    # Nada de lo ajeno cambió.
    switch = cliente.get(_E).json()
    assert (switch["activo"], switch["estado_operativo"], switch["padre_codigo"]) == (True, "inactivo", "AJE-R01-P01")


def test_el_openapi_tampoco_es_para_el_limitado(limitado):
    assert limitado.get("/openapi.json").status_code == 403


# --- python -m app.scripts.usuarios ----------------------------------------------------


@pytest.fixture
def archivo_env(monkeypatch, tmp_path, datos):
    archivo = tmp_path / ".env"
    archivo.write_text("NETDOC_ADMIN_CLAVE_HASH='no-se-toca'\nOTRA=1\n", encoding="utf-8")
    monkeypatch.setattr(usuarios, "ARCHIVO_ENV", archivo)
    monkeypatch.setattr(configuracion, "usuarios", {})
    return archivo


def _escribir(monkeypatch, texto: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(texto))


def _guardados(archivo) -> dict:
    return json.loads(dotenv_values(archivo)["NETDOC_USUARIOS"])


def test_agregar_guarda_solo_el_hash_y_no_toca_lo_demas(archivo_env, monkeypatch, capsys):
    _escribir(monkeypatch, "una-clave-cualquiera\n")
    assert usuarios.main(["agregar", "nuevo.usuario"]) == 0

    texto = archivo_env.read_text(encoding="utf-8")
    assert "una-clave-cualquiera" not in texto
    assert "una-clave-cualquiera" not in capsys.readouterr().out
    valores = dotenv_values(archivo_env)
    assert (valores["NETDOC_ADMIN_CLAVE_HASH"], valores["OTRA"]) == ("no-se-toca", "1")
    assert archivo_env.stat().st_mode & 0o077 == 0
    guardado = _guardados(archivo_env)["nuevo.usuario"]
    assert guardado["clave_hash"].startswith("$argon2id$")
    assert "edificio" not in guardado


def test_lo_guardado_es_lo_que_lee_la_api_y_el_instalador(archivo_env, monkeypatch):
    _escribir(monkeypatch, "una-clave-cualquiera\n")
    usuarios.main(["agregar", "uno"])
    _escribir(monkeypatch, "otra-clave-cualquiera\n")
    usuarios.main(["agregar", "dos", "--edificio", "pro"])

    # La API, desde el archivo…
    monkeypatch.delenv("NETDOC_USUARIOS")
    leidos = Configuracion(_env_file=archivo_env).usuarios
    assert set(leidos) == {"uno", "dos"}
    assert (leidos["uno"].edificio, leidos["dos"].edificio) == (None, "PRO")
    monkeypatch.setattr(configuracion, "usuarios", leidos)
    assert autenticacion.credenciales_validas("dos", "otra-clave-cualquiera")
    assert not autenticacion.credenciales_validas("dos", "una-clave-cualquiera")

    # …y el servidor, que lo carga con «source» (instalar-servidor.sh, netdoc).
    orden = f"set -a; source '{archivo_env}'; printf %s \"$NETDOC_USUARIOS\""
    salida = subprocess.run(["bash", "-c", orden], capture_output=True, text=True, check=True).stdout
    assert json.loads(salida) == json.loads(dotenv_values(archivo_env)["NETDOC_USUARIOS"])


def test_generar_muestra_una_contrasena_larga_una_sola_vez(archivo_env, capsys, monkeypatch):
    assert usuarios.main(["agregar", "generado", "--generar"]) == 0
    salida = capsys.readouterr().out
    clave = next(linea.split(": ")[1] for linea in salida.splitlines() if linea.startswith("Contraseña de"))
    assert len(clave) >= 20 and clave not in archivo_env.read_text(encoding="utf-8")
    assert autenticacion.credenciales_validas("generado", clave)
    assert len({usuarios.generar_clave() for _ in range(50)}) == 50


@pytest.mark.parametrize("nombre", ["ab", "Mayusculas", "con espacio", "9empieza", "admin-netdoc", "a" * 33, "comilla'"])
def test_rechaza_los_nombres_invalidos(archivo_env, monkeypatch, capsys, nombre):
    _escribir(monkeypatch, "una-clave-cualquiera\n")
    assert usuarios.main(["agregar", nombre]) == 1
    assert "NETDOC_USUARIOS" not in archivo_env.read_text(encoding="utf-8")


@pytest.mark.parametrize("clave", ["corta", "", "lleva-el-nombre-nuevo-adentro"])
def test_la_contrasena_cumple_las_mismas_reglas_que_la_del_administrador(archivo_env, monkeypatch, clave):
    _escribir(monkeypatch, clave + "\n")
    assert usuarios.main(["agregar", "nuevo"]) == 1
    assert "NETDOC_USUARIOS" not in archivo_env.read_text(encoding="utf-8")


def test_el_edificio_debe_existir(archivo_env, monkeypatch, capsys):
    _escribir(monkeypatch, "una-clave-cualquiera\n")
    assert usuarios.main(["agregar", "nuevo", "--edificio", "NOHAY"]) == 1
    assert "No existe el edificio NOHAY" in capsys.readouterr().err


def test_no_se_agrega_dos_veces(archivo_env, monkeypatch):
    _escribir(monkeypatch, "una-clave-cualquiera\n")
    assert usuarios.main(["agregar", "nuevo"]) == 0
    _escribir(monkeypatch, "otra-clave-cualquiera\n")
    assert usuarios.main(["agregar", "nuevo"]) == 1
    assert autenticacion.credenciales_validas("nuevo", "una-clave-cualquiera")


def _sesiones(usuario: str) -> int:
    with SesionLocal() as bd:
        return bd.scalar(select(func.count()).select_from(SesionAcceso).where(SesionAcceso.usuario == usuario))


def test_cambiar_la_clave_conserva_su_edificio_y_cierra_solo_sus_sesiones(archivo_env, monkeypatch):
    _escribir(monkeypatch, "una-clave-cualquiera\n")
    usuarios.main(["agregar", "nuevo", "--edificio", "PRO"])
    _escribir(monkeypatch, "otra-clave-cualquiera\n")
    usuarios.main(["agregar", "vecino"])
    _con_sesion_de("nuevo"), _con_sesion_de("vecino")

    _escribir(monkeypatch, "la-clave-cambiada\n")
    assert usuarios.main(["clave", "nuevo"]) == 0
    assert configuracion.usuarios["nuevo"].edificio == "PRO"
    assert autenticacion.credenciales_validas("nuevo", "la-clave-cambiada")
    assert not autenticacion.credenciales_validas("nuevo", "una-clave-cualquiera")
    assert (_sesiones("nuevo"), _sesiones("vecino")) == (0, 1)


def test_quitar_lo_borra_y_cierra_sus_sesiones(archivo_env, monkeypatch, capsys):
    _escribir(monkeypatch, "una-clave-cualquiera\n")
    usuarios.main(["agregar", "nuevo"])
    _con_sesion_de("nuevo")
    assert usuarios.main(["quitar", "nuevo"]) == 0
    assert _guardados(archivo_env) == {}
    assert _sesiones("nuevo") == 0
    assert usuarios.main(["quitar", "nuevo"]) == 1
    assert usuarios.main(["clave", "nuevo"]) == 1


def test_listar_no_muestra_los_hashes(archivo_env, monkeypatch, capsys):
    _escribir(monkeypatch, "una-clave-cualquiera\n")
    usuarios.main(["agregar", "nuevo", "--edificio", "PRO"])
    capsys.readouterr()
    assert usuarios.main([]) == 0
    salida = capsys.readouterr().out
    assert "admin-netdoc" in salida and "nuevo" in salida and "solo PRO" in salida
    assert "argon2" not in salida
