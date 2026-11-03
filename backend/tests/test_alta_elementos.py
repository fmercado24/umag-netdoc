"""Alta de elementos desde el visor: switches, racks y puntos de datos nuevos."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Elemento, Enlace

API = "/api/v1"


def _piso(cliente, piso, *tramos):
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": piso, "orden": 40})
    for tramo in tramos:
        cliente.post(f"{API}/edificios/CADI/pisos/{piso}/tramos", json={"codigo": tramo})


def _alta(cliente, **datos):
    return cliente.post(f"{API}/elementos", json={"edificio": "CADI", **datos})


def _rack(cliente, piso, tramo="T1"):
    return _alta(cliente, tipo="R", piso=piso, tramo=tramo).json()["codigo"]


def test_un_switch_nuevo_toma_el_correlativo_siguiente(cliente):
    _piso(cliente, "P40", "T1")
    assert _alta(cliente, tipo="SW", piso="P40", tramo="T1").json()["codigo"] == "CADI-SW01-P40-T1"
    respuesta = _alta(cliente, tipo="SW", piso="P40", tramo="T1", marca="Cisco", modelo="C9200")
    assert respuesta.status_code == 201
    creado = respuesta.json()
    assert creado["codigo"] == "CADI-SW02-P40-T1"
    assert (creado["marca"], creado["modelo"]) == ("Cisco", "C9200")


def test_un_equipo_dado_de_baja_no_libera_su_numero(cliente):
    _piso(cliente, "P41", "T1")
    codigo = _alta(cliente, tipo="SW", piso="P41", tramo="T1").json()["codigo"]
    cliente.delete(f"{API}/elementos/{codigo}")
    assert _alta(cliente, tipo="SW", piso="P41", tramo="T1").json()["codigo"] == "CADI-SW02-P41-T1"


def test_el_alta_queda_en_el_historial_con_quien_la_registro(cliente):
    _piso(cliente, "P42", "T1")
    respuesta = cliente.post(
        f"{API}/elementos?usuario=Tecnico",
        json={"tipo": "AP", "edificio": "CADI", "piso": "P42", "tramo": "T1"},
    )
    historial = cliente.get(f"{API}/elementos/{respuesta.json()['codigo']}/historial").json()
    alta = next(h for h in historial if h["campo"] == "alta")
    assert alta["usuario"] == "Tecnico"


def test_un_punto_de_datos_toma_su_codigo_del_rack_y_el_puerto(cliente, sesion):
    _piso(cliente, "P43", "T1", "T2")
    rack = _rack(cliente, "P43")  # CADI-R01-P43-T1

    respuesta = _alta(cliente, tipo="PD", piso="P43", tramo="T2", rack_origen=rack, puerto="d17")
    assert respuesta.status_code == 201, respuesta.text
    punto = respuesta.json()

    # Lo mismo que deja el importador con el rótulo «P43-T2-R1-D17».
    assert punto["codigo"] == "CADI-PD-P43-T2-R01-D17"
    assert punto["etiqueta"] == "P43-T2-R1-D17"
    assert punto["atributos"]["puerto_origen"] == "P43-T2-R1-D17"
    assert punto["atributos"]["servicio"] == "datos"
    assert punto["padre_codigo"] is None  # el rack es su origen, no su contenedor

    enlace = sesion.scalar(select(Enlace).where(Enlace.destino_id == punto["id"]))
    assert enlace.puerto_origen == "D17"
    assert sesion.get(Elemento, enlace.origen_id).codigo == rack


def test_el_servicio_sale_del_prefijo_salvo_que_se_indique_otro(cliente):
    _piso(cliente, "P44", "T1")
    rack = _rack(cliente, "P44")
    telefono = _alta(cliente, tipo="PD", piso="P44", tramo="T1", rack_origen=rack, puerto="T03")
    assert telefono.json()["atributos"]["servicio"] == "telefonia"

    otro = _alta(
        cliente,
        tipo="PD",
        piso="P44",
        tramo="T1",
        rack_origen=rack,
        puerto="D01",
        etiqueta="Toma recepción",
        atributos={"servicio": "video"},
    ).json()
    assert otro["atributos"]["servicio"] == "video"
    assert otro["etiqueta"] == "Toma recepción"


def test_el_mismo_puerto_no_se_puede_dar_de_alta_dos_veces(cliente):
    _piso(cliente, "P45", "T1")
    rack = _rack(cliente, "P45")
    datos = {"tipo": "PD", "piso": "P45", "tramo": "T1", "rack_origen": rack, "puerto": "D01"}
    assert _alta(cliente, **datos).status_code == 201
    repetido = _alta(cliente, **datos)
    assert repetido.status_code == 409
    assert "ya está en uso" in repetido.json()["detail"]


def test_un_punto_sin_puerto_conocido_no_choca_con_otro(cliente):
    # Antes, dos puntos de datos sin rack recibían el mismo código y el segundo fallaba.
    _piso(cliente, "P46", "T1")
    primero = _alta(cliente, tipo="PD", piso="P46", tramo="T1")
    segundo = _alta(cliente, tipo="PD", piso="P46", tramo="T1")
    assert primero.json()["codigo"] == "CADI-PD-P46-T1-SIN-ROTULO-01"
    assert segundo.json()["codigo"] == "CADI-PD-P46-T1-SIN-ROTULO-02"


def test_rack_y_puerto_van_juntos(cliente):
    _piso(cliente, "P47", "T1")
    rack = _rack(cliente, "P47")
    sin_puerto = _alta(cliente, tipo="PD", piso="P47", tramo="T1", rack_origen=rack)
    assert sin_puerto.status_code == 422
    assert sin_puerto.json()["detail"][0]["loc"] == ["body", "puerto"]
    sin_rack = _alta(cliente, tipo="PD", piso="P47", tramo="T1", puerto="D01")
    assert sin_rack.status_code == 422
    assert sin_rack.json()["detail"][0]["loc"] == ["body", "rack_origen"]


def test_el_puerto_no_admite_caracteres_que_romperian_el_codigo(cliente):
    _piso(cliente, "P48", "T1")
    rack = _rack(cliente, "P48")
    malo = _alta(cliente, tipo="PD", piso="P48", tramo="T1", rack_origen=rack, puerto="D 1/2")
    assert malo.status_code == 422


def test_el_rack_de_origen_debe_ser_un_rack(cliente):
    _piso(cliente, "P49", "T1")
    switch = _alta(cliente, tipo="SW", piso="P49", tramo="T1").json()["codigo"]
    malo = _alta(cliente, tipo="PD", piso="P49", tramo="T1", rack_origen=switch, puerto="D01")
    assert malo.status_code == 422
    assert "no es un rack" in malo.json()["detail"]


def test_un_equipo_montado_en_un_rack_se_ve_a_traves_de_el(cliente):
    _piso(cliente, "P50", "T1")
    rack = _rack(cliente, "P50")
    switch = _alta(
        cliente, tipo="SW", piso="P50", tramo="T1", padre_codigo=rack, unidad_rack=12
    ).json()
    assert switch["montado"] is True
    assert switch["unidad_rack"] == 12
    assert [h["codigo"] for h in cliente.get(f"{API}/elementos/{rack}").json()["hijos"]] == [
        switch["codigo"]
    ]


def test_la_ficha_se_valida_pero_se_puede_completar_despues(cliente):
    _piso(cliente, "P51", "T1")
    # Un switch recién comprado aún no tiene sus obligatorios: el alta no los exige.
    sin_ficha = _alta(cliente, tipo="SW", piso="P51", tramo="T1").json()
    assert sin_ficha["completitud"]["completo"] is False

    malo = _alta(cliente, tipo="SW", piso="P51", tramo="T1", atributos={"puertos_totales": "muchos"})
    assert malo.status_code == 422


def test_proximo_codigo_anticipa_el_del_alta_sin_crear_nada(cliente):
    _piso(cliente, "P52", "T1")
    consulta = {"tipo": "SW", "edificio": "CADI", "piso": "P52", "tramo": "T1"}

    primero = cliente.get(f"{API}/elementos/proximo-codigo", params=consulta).json()
    assert primero == {"codigo": "CADI-SW01-P52-T1", "disponible": True, "eliminado": False}
    assert cliente.get(f"{API}/elementos/proximo-codigo", params=consulta).json() == primero

    assert _alta(cliente, tipo="SW", piso="P52", tramo="T1").json()["codigo"] == primero["codigo"]
    assert cliente.get(f"{API}/elementos/proximo-codigo", params=consulta).json()["codigo"] == (
        "CADI-SW02-P52-T1"
    )


def test_proximo_codigo_avisa_si_ese_puerto_ya_esta_documentado(cliente):
    _piso(cliente, "P53", "T1")
    rack = _rack(cliente, "P53")
    consulta = {
        "tipo": "PD",
        "edificio": "CADI",
        "piso": "P53",
        "tramo": "T1",
        "rack_origen": rack,
        "puerto": "d09",
    }
    url = f"{API}/elementos/proximo-codigo"
    assert cliente.get(url, params=consulta).json() == {
        "codigo": "CADI-PD-P53-T1-R01-D09",
        "disponible": True,
        "eliminado": False,
    }
    _alta(cliente, tipo="PD", piso="P53", tramo="T1", rack_origen=rack, puerto="D09")
    assert cliente.get(url, params=consulta).json()["disponible"] is False


def test_proximo_codigo_exige_sesion(anonimo):
    assert anonimo.get(f"{API}/elementos/proximo-codigo?tipo=SW&edificio=CADI&piso=P01").status_code == 401
