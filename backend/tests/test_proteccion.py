"""Filtro de peticiones y cabeceras de seguridad de ``app.servicios.proteccion``."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import configuracion
from app.main import app
from app.servicios.proteccion import CSP_DOCS, CSP_MEDIA, CSP_VISOR, MAX_CUERPO
from tests.conftest import EQUIPO_LOCAL

API = "/api/v1"
TOKEN = {"Authorization": "Bearer token-de-prueba"}
VISOR = "http://localhost:8000"


@pytest.fixture
def archivo_en_media():
    ruta = configuracion.dir_planos / "prueba-proteccion.svg"
    ruta.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    yield "/media/planos/prueba-proteccion.svg"
    ruta.unlink()


@pytest.fixture
def visor_compilado():
    configuracion.dir_visor.joinpath("assets").mkdir(parents=True, exist_ok=True)
    indice = configuracion.dir_visor / "index.html"
    docs = configuracion.dir_visor / "docs.html"
    recurso = configuracion.dir_visor / "assets" / "index-abc.js"
    indice.write_text("<!doctype html><title>NetDoc</title>", encoding="utf-8")
    docs.write_text("<!doctype html><title>API</title>", encoding="utf-8")
    recurso.write_text("console.log(1)", encoding="utf-8")
    yield
    for ruta in (indice, docs, recurso):
        ruta.unlink()


# --- Qué exige sesión --------------------------------------------------------
@pytest.mark.parametrize(
    "ruta",
    [
        "/docs",
        "/openapi.json",
        "/metrics",
        "/media/planos/cadi-p01.svg",
        f"{API}/auth/sesion",
        f"{API}/edificios",
        f"{API}/catalogo/tipos",
        f"{API}/elementos",
        f"{API}/integraciones/inventario",
        f"{API}/integraciones/cambios",
        f"{API}/integraciones/prometheus/objetivos",
        f"{API}/ruta-que-no-existe",
        "/ruta-que-no-existe",
    ],
)
def test_sin_sesion_todo_se_rechaza(anonimo, ruta):
    assert anonimo.get(ruta).status_code == 401


def test_sin_sesion_tampoco_se_escribe(anonimo):
    assert anonimo.post(f"{API}/elementos", json={"tipo": "SW"}).status_code == 401
    assert anonimo.patch(f"{API}/elementos/1", json={}).status_code == 401
    assert anonimo.delete(f"{API}/elementos/1").status_code == 401


def test_el_archivo_existente_tampoco_se_sirve_sin_sesion(anonimo, cliente, archivo_en_media):
    assert anonimo.get(archivo_en_media).status_code == 401
    assert cliente.get(archivo_en_media).status_code == 200


def test_la_verificacion_de_vida_no_expone_detalles(anonimo, monkeypatch):
    assert anonimo.get("/salud").json() == {"estado": "ok", "base_datos": "ok"}

    from app.db import session

    def fallar():
        raise RuntimeError("postgresql://netdoc:secreto@db")

    monkeypatch.setattr(session.motor, "connect", fallar)
    respuesta = anonimo.get("/salud")
    assert respuesta.json() == {"estado": "degradado", "base_datos": "error"}
    assert "secreto" not in respuesta.text


# --- Visor -------------------------------------------------------------------
def test_la_pantalla_de_ingreso_es_publica(anonimo, visor_compilado):
    assert "NetDoc" in anonimo.get("/").text
    assert anonimo.get("/assets/index-abc.js").status_code == 200


def test_la_documentacion_exige_sesion(anonimo, cliente, visor_compilado):
    assert anonimo.get("/docs").status_code == 401
    assert anonimo.get("/openapi.json").status_code == 401
    assert cliente.get("/docs").status_code == 200
    assert cliente.get("/openapi.json").status_code == 200


def test_el_visor_sin_compilar_lo_avisa(anonimo):
    respuesta = anonimo.get("/")
    assert respuesta.status_code == 503
    assert "npm run build" in respuesta.json()["detail"]


def test_los_archivos_de_fuera_de_assets_no_se_exponen(anonimo, visor_compilado):
    assert anonimo.get("/assets/../index.html").status_code in (401, 404)
    assert anonimo.get("/assets/%2e%2e/docs.html").status_code in (401, 404)
    assert anonimo.get("/docs.html").status_code == 401


# --- Cabeceras ---------------------------------------------------------------
@pytest.mark.parametrize("ruta", ["/salud", f"{API}/edificios", "/ruta-que-no-existe"])
def test_toda_respuesta_lleva_las_cabeceras_de_seguridad(anonimo, ruta):
    # También los rechazos.
    cabeceras = anonimo.get(ruta).headers
    assert cabeceras["x-content-type-options"] == "nosniff"
    assert cabeceras["x-frame-options"] == "DENY"
    assert cabeceras["referrer-policy"] == "no-referrer"
    assert cabeceras["cross-origin-resource-policy"] == "same-origin"
    assert cabeceras["cross-origin-opener-policy"] == "same-origin"
    assert "camera=()" in cabeceras["permissions-policy"]
    assert "frame-ancestors 'none'" in cabeceras["content-security-policy"]


def test_la_politica_de_la_pagina_no_admite_scripts_de_afuera(anonimo, cliente, visor_compilado):
    assert anonimo.get("/").headers["content-security-policy"] == CSP_VISOR
    assert cliente.get("/docs").headers["content-security-policy"] == CSP_DOCS
    for politica in (CSP_VISOR, CSP_DOCS):
        assert "script-src 'self';" in politica
        assert "'unsafe-eval'" not in politica
        assert "http" not in politica


def test_un_svg_abierto_directamente_no_puede_ejecutar_scripts(cliente, archivo_en_media):
    cabeceras = cliente.get(archivo_en_media).headers
    assert cabeceras["content-security-policy"] == CSP_MEDIA
    assert "sandbox" in CSP_MEDIA
    assert "script-src" not in CSP_MEDIA
    assert "default-src 'none'" in CSP_MEDIA


def test_lo_que_exige_sesion_no_queda_en_caches(cliente, archivo_en_media, visor_compilado):
    assert cliente.get(f"{API}/edificios").headers["cache-control"] == "no-store"
    assert cliente.get(archivo_en_media).headers["cache-control"] == "private, no-cache"
    assert "immutable" in cliente.get("/assets/index-abc.js").headers["cache-control"]
    assert cliente.get("/").headers["cache-control"] == "no-cache"


def test_hsts_solo_por_https(anonimo):
    assert "strict-transport-security" not in anonimo.get("/salud").headers
    seguro = TestClient(app, base_url="https://netdoc.umag.cl", client=EQUIPO_LOCAL)
    assert "max-age=31536000" in seguro.get("/salud").headers["strict-transport-security"]


# --- Otros sitios ------------------------------------------------------------
def test_no_hay_cors_para_nadie(anonimo, cliente):
    otro_sitio = {"Origin": "https://malicioso.example"}
    assert "access-control-allow-origin" not in cliente.get(f"{API}/edificios", headers=otro_sitio).headers

    previa = anonimo.options(
        f"{API}/edificios", headers={**otro_sitio, "Access-Control-Request-Method": "DELETE"}
    )
    assert previa.status_code == 401
    assert "access-control-allow-origin" not in previa.headers


@pytest.mark.parametrize(
    "cabeceras",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},  # Grafana o Adminer en otro puerto
        {"Origin": "https://malicioso.example"},
        {"Origin": "http://localhost:3000"},
        {"Sec-Fetch-Site": "cross-site", "Origin": "http://testserver"},
    ],
)
def test_una_escritura_desde_otro_sitio_se_rechaza(cliente, cabeceras):
    respuesta = cliente.post(f"{API}/elementos", json={}, headers=cabeceras)
    assert respuesta.status_code == 403
    assert "otro sitio" in respuesta.json()["detail"]


@pytest.mark.parametrize(
    "cabeceras",
    [
        {"Sec-Fetch-Site": "same-origin"},
        {"Origin": "http://testserver"},  # navegador sin Sec-Fetch-Site
        {},  # curl, Prometheus: no envían la cookie por su cuenta
    ],
)
def test_una_escritura_del_mismo_origen_pasa_el_filtro(cliente, cabeceras):
    # 422: llegó al endpoint, que rechaza el cuerpo vacío.
    assert cliente.post(f"{API}/elementos", json={}, headers=cabeceras).status_code == 422


def test_el_ingreso_tambien_exige_el_mismo_origen(anonimo):
    respuesta = anonimo.post(
        f"{API}/auth/ingresar",
        json={"usuario": "x", "clave": "y"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert respuesta.status_code == 403


def test_una_lectura_de_otro_sitio_no_lleva_la_cookie_pero_no_se_filtra_aqui(cliente):
    # SameSite=Strict la deja fuera en el navegador; sin cookie responde 401.
    respuesta = cliente.get(f"{API}/edificios", headers={"Sec-Fetch-Site": "cross-site"})
    assert respuesta.status_code == 200


# --- Desde otros equipos, solo HTTPS -----------------------------------------
@pytest.mark.parametrize("ruta", ["/", f"{API}/auth/ingresar", "/metrics", f"{API}/edificios"])
def test_desde_otro_equipo_sin_https_se_rechaza(ruta):
    remoto = TestClient(app, client=("10.0.0.9", 50000))
    respuesta = remoto.get(ruta, headers=TOKEN)
    assert respuesta.status_code == 403
    assert "HTTPS" in respuesta.json()["detail"]


def test_el_ingreso_sin_https_desde_otro_equipo_ni_mira_la_clave():
    remoto = TestClient(app, client=("10.0.0.9", 50000))
    respuesta = remoto.post(f"{API}/auth/ingresar", json={"usuario": "x", "clave": "y"})
    assert respuesta.status_code == 403


def test_desde_otro_equipo_con_https_se_atiende():
    remoto = TestClient(app, base_url="https://netdoc.umag.cl", client=("10.0.0.9", 50000))
    assert remoto.get(f"{API}/edificios").status_code == 401  # pasó el filtro: pide sesión
    assert remoto.get("/metrics", headers=TOKEN).status_code == 200


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
def test_este_equipo_se_atiende_sin_https(host):
    assert TestClient(app, client=(host, 50000)).get(f"{API}/edificios").status_code == 401


def test_la_verificacion_de_vida_responde_a_un_balanceador_sin_https():
    assert TestClient(app, client=("10.0.0.9", 50000)).get("/salud").status_code == 200


# --- Tamaño de las peticiones ------------------------------------------------
def test_un_cuerpo_enorme_en_el_ingreso_se_rechaza_sin_leerlo(anonimo):
    respuesta = anonimo.post(
        f"{API}/auth/ingresar",
        content=b"x",
        headers={"Content-Type": "application/json", "Content-Length": str(MAX_CUERPO + 1)},
    )
    assert respuesta.status_code == 413


def test_un_cuerpo_sin_largo_conocido_se_rechaza(anonimo):
    def trozos():
        yield b'{"usuario": "x", "clave": "y"}'

    respuesta = anonimo.post(
        f"{API}/auth/ingresar", content=trozos(), headers={"Content-Type": "application/json"}
    )
    assert respuesta.status_code == 411


def test_una_carga_sin_sesion_no_tiene_el_limite_de_los_archivos(anonimo):
    # Un multipart a una ruta pública no llega al límite grande.
    respuesta = anonimo.post(
        f"{API}/integraciones/alertmanager",
        content=b"x",
        headers={
            "Content-Type": "multipart/form-data; boundary=x",
            "Content-Length": str(MAX_CUERPO + 1),
        },
    )
    assert respuesta.status_code == 413


def test_una_carga_con_sesion_tiene_su_propio_limite(cliente, monkeypatch):
    monkeypatch.setattr(configuracion, "carga_max_mb", 1)
    grande = {"archivo": ("cadi-p01.png", b"x" * (2 * MAX_CUERPO), "image/png")}
    datos = {"ancho_px": "10", "alto_px": "10"}
    respuesta = cliente.post(f"{API}/edificios/CADI/pisos/P01/plano", files=grande, data=datos)
    assert respuesta.status_code == 413
    assert "1 MB" in respuesta.json()["detail"]
