"""Monitoreo activo: métricas de Prometheus, descubrimiento y Alertmanager."""

from __future__ import annotations

import pytest

from app.servicios.monitoreo import ip_de_instancia

API = "/api/v1"
TOKEN = {"Authorization": "Bearer token-de-prueba"}


def _switch(cliente, piso, **extra):
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": piso, "orden": 1})
    return cliente.post(
        f"{API}/elementos", json={"tipo": "SW", "edificio": "CADI", "piso": piso, **extra}
    ).json()["codigo"]


def _alerta(estado, **etiquetas):
    return {
        "version": "4",
        "status": estado,
        "alerts": [
            {
                "status": estado,
                "labels": {"alertname": "NetDocSinRespuesta", **etiquetas},
                "annotations": {"summary": "No responde a ping"},
            }
        ],
    }


def test_metricas_de_inventario_en_formato_prometheus(cliente):
    codigo = _switch(cliente, "P20", estado_operativo="en_falla")

    respuesta = cliente.get("/metrics")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/plain")
    texto = respuesta.text
    assert "netdoc_base_datos_disponible 1.0" in texto
    assert f'netdoc_elemento_estado{{codigo="{codigo}"' in texto
    linea = next(l for l in texto.splitlines() if l.startswith(f'netdoc_elemento_estado{{codigo="{codigo}"'))
    assert linea.endswith(" 3.0")  # en falla
    assert 'netdoc_elementos{edificio="CADI",estado_operativo="en_falla",piso="P20",tipo="SW"} 1.0' in texto


def test_objetivos_para_prometheus_salen_del_inventario(cliente):
    con_ip = _switch(cliente, "P21", direccion_ip="10.21.0.1")
    _switch(cliente, "P21")  # sin IP: no se vigila
    retirado = _switch(cliente, "P21", direccion_ip="10.21.0.2")
    cliente.delete(f"{API}/elementos/{retirado}")

    grupos = cliente.get(f"{API}/integraciones/prometheus/objetivos?tipo=SW").json()
    del_piso = [g for g in grupos if g["labels"]["netdoc_piso"] == "P21"]
    assert del_piso == [
        {
            "targets": ["10.21.0.1"],
            "labels": {
                "netdoc_codigo": con_ip,
                "netdoc_tipo": "SW",
                "netdoc_edificio": "CADI",
                "netdoc_piso": "P21",
                "netdoc_tramo": "",
                "netdoc_criticidad": "",
            },
        }
    ]
    assert cliente.get(f"{API}/integraciones/prometheus/objetivos?tipo=AP").json() == [
        g for g in cliente.get(f"{API}/integraciones/prometheus/objetivos").json()
        if g["labels"]["netdoc_tipo"] == "AP"
    ]


def test_alertmanager_pone_en_falla_y_recupera(cliente):
    codigo = _switch(cliente, "P22", direccion_ip="10.22.0.1")
    url = f"{API}/integraciones/alertmanager"

    assert cliente.post(url, json=_alerta("firing", netdoc_codigo=codigo)).status_code == 401

    caida = cliente.post(url, json=_alerta("firing", netdoc_codigo=codigo), headers=TOKEN).json()
    assert caida["resultados"][0]["estado_operativo"] == "en_falla"

    # Sin la etiqueta netdoc_codigo, se reconoce por la IP de "instance".
    vuelta = cliente.post(url, json=_alerta("resolved", instance="10.22.0.1:9115"), headers=TOKEN)
    assert vuelta.json()["resultados"][0]["estado_operativo"] == "activo"

    historial = cliente.get(f"{API}/elementos/{codigo}/historial").json()
    assert any(h["usuario"] == "alertmanager" and "NetDocSinRespuesta" in h["comentario"] for h in historial)


def test_alertmanager_informa_sin_fallar_lo_que_no_reconoce(cliente):
    respuesta = cliente.post(
        f"{API}/integraciones/alertmanager",
        json=_alerta("firing", instance="nodo-desconocido:9100"),
        headers=TOKEN,
    )
    # Alertmanager reintenta los errores: lo no aplicable se informa con 200.
    assert respuesta.status_code == 200
    assert respuesta.json()["resultados"][0]["actualizado"] is False


@pytest.mark.parametrize(
    ("instancia", "ip"),
    [
        ("10.0.0.1:9100", "10.0.0.1"),
        ("10.0.0.1", "10.0.0.1"),
        ("[fe80::1]:161", "fe80::1"),
        ("switch-core:161", None),
        (None, None),
    ],
)
def test_ip_de_la_etiqueta_instance(instancia, ip):
    assert ip_de_instancia(instancia) == ip


def test_webhook_encuentra_por_ip_un_host_creado_a_mano(cliente):
    # En Zabbix el host se llama distinto que el código: la IP lo identifica.
    codigo = _switch(cliente, "P28", direccion_ip="10.28.0.1")
    respuesta = cliente.post(
        f"{API}/integraciones/monitoreo/estado",
        json={"codigo": "sw-core-manual", "direccion_ip": "10.28.0.1", "estado": "down"},
        headers={"X-NetDoc-Token": "token-de-prueba"},
    ).json()
    assert (respuesta["codigo"], respuesta["estado_operativo"]) == (codigo, "en_falla")
