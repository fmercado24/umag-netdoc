"""Latido del monitoreo (requisito RNF5): el silencio de Zabbix o Alertmanager
no se confunde con una red sin fallas."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import delete

from app.core.config import configuracion
from app.db.session import SesionLocal
from app.models import LatidoMonitoreo
from app.servicios import latidos

API = "/api/v1"
TOKEN = {"Authorization": "Bearer token-de-prueba"}
LATIDO = f"{API}/integraciones/monitoreo/latido"
NOVEDADES = f"{API}/edificios/CADI/novedades"


@pytest.fixture(autouse=True)
def sin_latidos():
    """La base es de toda la sesión de pruebas: otras ya avisaron como Zabbix."""
    with SesionLocal() as sesion:
        sesion.execute(delete(LatidoMonitoreo))
        sesion.commit()
    yield


def _dentro_de(monkeypatch, minutos: int) -> None:
    despues = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutos)
    monkeypatch.setattr(latidos, "ahora", lambda: despues)


def _sin_latido(cliente):
    respuesta = cliente.get(NOVEDADES)
    assert respuesta.status_code == 200
    return respuesta.json()["monitoreo_sin_latido"]


def test_sin_monitoreo_no_hay_aviso(cliente, monkeypatch):
    # Una instalación que nunca recibió avisos no muestra nada, por mucho que pase.
    _dentro_de(monkeypatch, 600)
    assert _sin_latido(cliente) == []


def test_el_latido_exige_el_token(cliente):
    assert cliente.post(LATIDO, json={}).status_code == 401
    assert cliente.post(LATIDO, json={}, headers={"X-NetDoc-Token": "otro"}).status_code == 401


def test_avisa_cuando_una_herramienta_deja_de_informar(cliente, monkeypatch):
    respuesta = cliente.post(LATIDO, headers=TOKEN)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"fuente": "zabbix", "registrado": True}
    assert _sin_latido(cliente) == []

    _dentro_de(monkeypatch, 14)
    assert _sin_latido(cliente) == []  # dentro del plazo de 15 minutos

    _dentro_de(monkeypatch, 40)
    assert _sin_latido(cliente) == [{"fuente": "zabbix", "nombre": "Zabbix", "minutos": 40}]

    # Vuelve a informar: el aviso desaparece.
    monkeypatch.undo()
    cliente.post(LATIDO, json={"fuente": "zabbix"}, headers=TOKEN)
    assert _sin_latido(cliente) == []


def test_un_aviso_de_un_equipo_no_documentado_tambien_es_latido(cliente, monkeypatch):
    respuesta = cliente.post(
        f"{API}/integraciones/monitoreo/estado",
        json={"codigo": "CADI-SW99-P99", "estado": "down"},
        headers=TOKEN,
    )
    assert respuesta.status_code == 404
    assert "CADI-SW99-P99" in respuesta.json()["detail"]

    _dentro_de(monkeypatch, 20)
    assert [f["fuente"] for f in _sin_latido(cliente)] == ["zabbix"]


def test_la_alerta_de_latido_de_alertmanager_no_toca_elementos(cliente, monkeypatch):
    notificacion = {
        "version": "4",
        "status": "firing",
        "alerts": [{"status": "firing", "labels": {"alertname": "NetDocLatido"}, "annotations": {}}],
    }
    respuesta = cliente.post(f"{API}/integraciones/alertmanager", json=notificacion, headers=TOKEN)
    assert respuesta.status_code == 200
    assert respuesta.json()["resultados"] == [{"alerta": "NetDocLatido", "latido": True}]

    _dentro_de(monkeypatch, 30)
    assert _sin_latido(cliente) == [{"fuente": "alertmanager", "nombre": "Alertmanager", "minutos": 30}]


def test_cada_fuente_por_separado(cliente, monkeypatch):
    cliente.post(LATIDO, json={"fuente": "zabbix"}, headers=TOKEN)
    _dentro_de(monkeypatch, 30)
    cliente.post(LATIDO, json={"fuente": "otro-monitor"}, headers=TOKEN)
    assert [f["fuente"] for f in _sin_latido(cliente)] == ["zabbix"]


def test_un_latido_viejo_no_retrocede_la_hora(cliente):
    with SesionLocal() as sesion:
        reciente = dt.datetime.now(dt.timezone.utc)
        latidos.registrar_contacto(sesion, "zabbix", reciente)
        latidos.registrar_contacto(sesion, "zabbix", reciente - dt.timedelta(hours=1))
        sesion.commit()
        [estado] = latidos.estado_latidos(sesion, reciente)
    assert estado.minutos_sin_noticias == 0
    assert estado.al_dia


def test_el_plazo_en_cero_desactiva_el_aviso(cliente, monkeypatch):
    cliente.post(LATIDO, headers=TOKEN)
    monkeypatch.setattr(configuracion, "monitoreo_latido_minutos", 0)
    _dentro_de(monkeypatch, 600)
    assert _sin_latido(cliente) == []


def test_la_fuente_se_valida(cliente):
    respuesta = cliente.post(LATIDO, json={"fuente": "zabbix server!"}, headers=TOKEN)
    assert respuesta.status_code == 422
    assert cliente.post(LATIDO, json={"fuente": " Zabbix "}, headers=TOKEN).json()["fuente"] == "zabbix"


def test_las_metricas_exponen_el_latido(cliente, monkeypatch):
    cliente.post(LATIDO, headers=TOKEN)
    texto = cliente.get("/metrics").text
    assert 'netdoc_monitoreo_al_dia{fuente="zabbix"} 1.0' in texto
    assert 'netdoc_monitoreo_ultimo_contacto_timestamp_seconds{fuente="zabbix"}' in texto

    _dentro_de(monkeypatch, 60)
    assert 'netdoc_monitoreo_al_dia{fuente="zabbix"} 0.0' in cliente.get("/metrics").text
