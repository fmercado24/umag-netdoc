"""Interoperabilidad con otros inventarios: ids externos, exportación y cambios."""

from __future__ import annotations

import csv
import io

API = "/api/v1"


def _piso(cliente, codigo):
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": codigo, "orden": 1})


def _crear(cliente, piso, tipo="SW", **extra):
    return cliente.post(
        f"{API}/elementos", json={"tipo": tipo, "edificio": "CADI", "piso": piso, **extra}
    ).json()["codigo"]


def test_ids_externos_se_asignan_buscan_y_quitan(cliente):
    _piso(cliente, "P23")
    uno, otro = _crear(cliente, "P23"), _crear(cliente, "P23")

    lista = cliente.put(
        f"{API}/elementos/{uno}/externos/netbox",
        json={"id_externo": "481", "url": "https://netbox.umag.cl/dcim/devices/481/"},
    ).json()
    assert [(x["sistema"], x["id_externo"]) for x in lista] == [("netbox", "481")]

    # Un id externo apunta a un solo elemento.
    repetido = cliente.put(f"{API}/elementos/{otro}/externos/netbox", json={"id_externo": "481"})
    assert repetido.status_code == 409

    encontrado = cliente.get(f"{API}/integraciones/externos/netbox/481").json()
    assert encontrado["codigo"] == uno
    assert cliente.get(f"{API}/elementos/{uno}").json()["externos"][0]["id_externo"] == "481"

    assert cliente.put(f"{API}/elementos/{uno}/externos/Net Box", json={"id_externo": "1"}).status_code == 422

    assert cliente.delete(f"{API}/elementos/{uno}/externos/netbox").status_code == 204
    assert cliente.get(f"{API}/integraciones/externos/netbox/481").status_code == 404


def test_inventario_v1_en_json_y_csv(cliente):
    _piso(cliente, "P24")
    codigo = _crear(
        cliente,
        "P24",
        tipo="AP",
        marca="Ubiquiti",
        direccion_ip="10.24.0.5",
        atributos={"ssids": ["UMAG"]},
    )
    cliente.put(f"{API}/elementos/{codigo}/externos/glpi", json={"id_externo": "NE-77"})

    datos = cliente.get(f"{API}/integraciones/inventario?tipo=AP&limite=5000").json()
    assert datos["esquema"] == "netdoc.inventario/v1"
    registro = next(r for r in datos["elementos"] if r["codigo"] == codigo)
    assert registro["tipo"]["codigo"] == "AP"
    assert registro["ubicacion"]["piso"] == "P24"
    assert registro["red"]["direccion_ip"] == "10.24.0.5"
    assert registro["equipo"]["marca"] == "Ubiquiti"
    assert registro["externos"] == {"glpi": {"id": "NE-77", "url": None}}
    assert registro["atributos"] == {"ssids": ["UMAG"]}

    respuesta = cliente.get(f"{API}/integraciones/inventario?tipo=AP&formato=csv&limite=5000")
    assert respuesta.headers["content-type"].startswith("text/csv")
    filas = list(csv.DictReader(io.StringIO(respuesta.text)))
    assert int(respuesta.headers["x-total-count"]) == len(filas)
    fila = next(f for f in filas if f["codigo"] == codigo)
    assert (fila["piso"], fila["direccion_ip"], fila["externos"]) == ("P24", "10.24.0.5", '{"glpi": "NE-77"}')

    # Incremental: nada fue modificado en el futuro.
    futuro = cliente.get(f"{API}/integraciones/inventario?modificado_desde=2999-01-01T00:00:00Z").json()
    assert futuro["total"] == 0


def test_inventario_da_a_lo_montado_la_posicion_de_su_rack(cliente):
    _piso(cliente, "P25")
    rack = _crear(cliente, "P25", tipo="R")
    switch = _crear(cliente, "P25", padre_codigo=rack)
    plano = cliente.post(
        f"{API}/edificios/CADI/pisos/P25/plano",
        files={"archivo": ("cadi-p25.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        data={"ancho_px": "100", "alto_px": "50"},
    ).json()["id"]
    cliente.patch(f"{API}/elementos/{rack}/posicion", json={"plano_id": plano, "pos_x": 40, "pos_y": 20})

    registros = cliente.get(f"{API}/integraciones/inventario?limite=5000").json()["elementos"]
    ubicacion = next(r["ubicacion"] for r in registros if r["codigo"] == switch)
    assert (ubicacion["contenedor"], ubicacion["montado"]) == (rack, True)
    assert (ubicacion["plano_id"], ubicacion["x"], ubicacion["y"]) == (plano, 40, 20)


def test_registro_de_cambios_con_cursor(cliente):
    _piso(cliente, "P26")
    codigo = _crear(cliente, "P26")
    ultimo = cliente.get(f"{API}/integraciones/cambios?desde=0&limite=5000").json()["ultimo_id"]

    cliente.patch(f"{API}/elementos/{codigo}", json={"etiqueta": "SW-NUEVO", "marca": "Cisco"})
    lote = cliente.get(f"{API}/integraciones/cambios?desde={ultimo}&limite=1").json()
    assert lote["hay_mas"] is True
    assert lote["cambios"][0]["codigo"] == codigo

    resto = cliente.get(f"{API}/integraciones/cambios?desde={lote['ultimo_id']}").json()
    assert resto["hay_mas"] is False
    campos = {c["campo"] for c in lote["cambios"] + resto["cambios"]}
    assert campos == {"etiqueta", "marca"}
