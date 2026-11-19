"""Todo dato se guarda de una sola forma, venga del visor, de la API o de una planilla."""

from __future__ import annotations

import pytest

from app.models import DefinicionAtributo, TipoDato
from app.scripts import importar_edificio
from app.scripts.importar_edificio import normalizar_prefijo
from app.servicios.validacion import NORMALIZAR, limpiar_texto, normalizar_atributo

API = "/api/v1"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("0045123", "0045123"),
        ("0045 123", "0045123"),
        ("0045 123", "0045123"),
        (" 39644233 111030 ", "39644233111030"),
        ("0045-123", "0045123"),
        ("0045.123", "0045123"),
        ("39644233111030.0", "39644233111030"),
    ],
)
def test_inventario_sin_espacios_ni_separadores(texto, esperado):
    assert NORMALIZAR["numero_inventario"](texto) == esperado


@pytest.mark.parametrize(("texto", "motivo"), [("INV-77", "solo cifras"), ("3,96442E+13", "notación científica")])
def test_inventario_que_no_se_puede_arreglar(texto, motivo):
    with pytest.raises(ValueError, match=motivo):
        NORMALIZAR["numero_inventario"](texto)


@pytest.mark.parametrize(
    "texto", ["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "aabb.ccdd.eeff", "AABBCCDDEEFF", "aa bb cc dd ee ff"]
)
def test_mac_en_cualquier_formato(texto):
    assert NORMALIZAR["direccion_mac"](texto) == "AA:BB:CC:DD:EE:FF"


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [(" 10.40.0. 2 ", "10.40.0.2"), ("010.040.000.002", "10.40.0.2"), ("10,40,0,2", "10.40.0.2")],
)
def test_ip_con_espacios_comas_o_ceros(texto, esperado):
    assert NORMALIZAR["direccion_ip"](texto) == esperado


def test_ip_y_mac_imposibles_se_rechazan():
    with pytest.raises(ValueError):
        NORMALIZAR["direccion_ip"]("10.0.0.300")
    with pytest.raises(ValueError):
        NORMALIZAR["direccion_mac"]("zz:bb:cc:dd:ee:ff")


def test_serie_en_mayusculas_y_sin_espacios():
    assert NORMALIZAR["numero_serie"](" foc 2345y0ab ") == "FOC2345Y0AB"


def test_textos_limpios():
    assert limpiar_texto("  Sala de   Comunicaciones​ ") == "Sala de Comunicaciones"
    assert limpiar_texto("   ") is None
    assert limpiar_texto(" primera  línea \r\n\r\n\r\n segunda ", multilinea=True) == "primera línea\n\nsegunda"


def _definicion(tipo, opciones=None):
    return DefinicionAtributo(clave="x", etiqueta="X", tipo_dato=tipo, opciones=opciones)


@pytest.mark.parametrize(
    ("tipo", "opciones", "texto", "esperado"),
    [
        (TipoDato.NUMERO, None, "24", 24),
        (TipoDato.NUMERO, None, " 12,5 ", 12.5),
        (TipoDato.NUMERO, None, "1500 VA", 1500),
        (TipoDato.NUMERO, None, "cuarenta", "cuarenta"),  # queda para que la validación lo rechace
        (TipoDato.BOOLEANO, None, "Sí", True),
        (TipoDato.BOOLEANO, None, "no", False),
        (TipoDato.LISTA, None, "UMAG, eduroam ; Invitados", ["UMAG", "eduroam", "Invitados"]),
        (TipoDato.FECHA, None, "17-11-2026", "2026-11-17"),
        (TipoDato.ENUM, ["cerrado", "abierto", "mural"], "Cerrado", "cerrado"),
        (TipoDato.ENUM, ["acceso", "distribucion", "nucleo"], "Núcleo", "nucleo"),
        (TipoDato.ENUM, ["cerrado", "abierto", "mural"], "cerrdo", "cerrado"),
        (TipoDato.TEXTO, None, "  Ubiquiti   UniFi ", "Ubiquiti UniFi"),
    ],
)
def test_atributos_de_la_ficha(tipo, opciones, texto, esperado):
    assert normalizar_atributo(_definicion(tipo, opciones), texto) == esperado


@pytest.mark.parametrize(("texto", "esperado"), [("/16", "/16"), ("16", "/16"), ("255.255.0.0", "/16"), ("x", "")])
def test_prefijo_de_vlan(texto, esperado):
    assert normalizar_prefijo(texto) == esperado


def test_alta_por_la_api_guarda_todo_normalizado(cliente):
    # Un edificio propio: la base es de toda la sesión de pruebas.
    assert cliente.post(f"{API}/edificios", json={"codigo": "LEVD", "nombre": "Prueba"}).status_code == 201
    cliente.post(f"{API}/edificios/LEVD/pisos", json={"codigo": "P01", "orden": 1})
    respuesta = cliente.post(
        f"{API}/elementos",
        json={
            "tipo": "SW",
            "edificio": "LEVD",
            "piso": "P01",
            "etiqueta": "  SW   DATOS ",
            "marca": "Cisco ",
            "numero_serie": "foc 123",
            "numero_inventario": "0045 123",
            "direccion_mac": "aabb.ccdd.eeff",
            "direccion_ip": "010.040.000.009",
            "observaciones": "  revisar  el uplink  ",
            "atributos": {"puertos_totales": "24", "poe": "sí", "capa": "Núcleo"},
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    elemento = respuesta.json()
    assert (elemento["etiqueta"], elemento["marca"], elemento["observaciones"]) == ("SW DATOS", "Cisco", "revisar el uplink")
    assert (elemento["numero_serie"], elemento["numero_inventario"]) == ("FOC123", "0045123")
    assert (elemento["direccion_mac"], elemento["direccion_ip"]) == ("AA:BB:CC:DD:EE:FF", "10.40.0.9")
    assert elemento["atributos"] == {"puertos_totales": 24, "poe": True, "capa": "nucleo"}


def test_vlans_de_la_planilla_normalizadas(cliente, tmp_path, capsys):
    assert cliente.post(f"{API}/edificios", json={"codigo": "LEVC", "nombre": "Prueba"}).status_code == 201
    (tmp_path / "levc-p01.csv").write_text(
        "Elemento,Etiqueta,Tipo,Ubicación\nCisco,SW-1,Switch,Sala 1\n", encoding="utf-8"
    )
    (tmp_path / "levc-vlans.csv").write_text(
        "numero,nombre,gateway,prefijo,servicio\n"
        "VLAN 3, DATOS ,010.050.000.001,255.255.0.0,Datos\n"
        "2,TELEFONIA,10.51.0.1,16,Telefonía\n"
        "7,OTRA,10.52.0.1,/24,impresoras\n",
        encoding="utf-8",
    )
    importar_edificio.main(["LEVC", "--datos", str(tmp_path)])
    assert "servicio «impresoras» desconocido" in capsys.readouterr().out
    vlans = {v["numero"]: v for v in cliente.get(f"{API}/vlans?edificio=LEVC").json()}
    assert (vlans[3]["nombre"], vlans[3]["subred"]) == ("DATOS", "10.50.0.1/16")
    assert vlans[2]["subred"] == "10.51.0.1/16"
