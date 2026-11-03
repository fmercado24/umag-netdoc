"""Eliminar, restaurar y trasladar elementos, y lo que al editarlos cambia su código."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Elemento, Enlace, Piso, Plano
from app.servicios.monitoreo import buscar_elemento

API = "/api/v1"


def _piso(cliente, piso, *tramos):
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": piso, "orden": 60})
    for tramo in tramos:
        cliente.post(f"{API}/edificios/CADI/pisos/{piso}/tramos", json={"codigo": tramo})


def _alta(cliente, **datos):
    respuesta = cliente.post(f"{API}/elementos", json={"edificio": "CADI", **datos})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["codigo"]


def _trasladar(cliente, codigo, **datos):
    return cliente.post(f"{API}/elementos/{codigo}/trasladar", json=datos)


def _previo(cliente, codigo, **consulta):
    respuesta = cliente.get(f"{API}/elementos/{codigo}/traslado", params=consulta)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _ver(cliente, codigo):
    respuesta = cliente.get(f"{API}/elementos/{codigo}")
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _lamina(sesion, piso, tramo_id=None):
    plano = Plano(
        piso_id=sesion.scalar(select(Piso.id).where(Piso.codigo == piso)),
        tramo_id=tramo_id,
        nombre=f"Lámina {piso}",
        archivo=f"{piso}.png",
        ancho_px=1000,
        alto_px=1000,
    )
    sesion.add(plano)
    sesion.commit()
    return plano.id


# --- El código ---------------------------------------------------------------


def test_en_el_mismo_piso_cambia_solo_el_tramo(cliente):
    _piso(cliente, "P60", "T1", "T2")
    _alta(cliente, tipo="SW", piso="P60", tramo="T1")
    codigo = _alta(cliente, tipo="SW", piso="P60", tramo="T1")
    assert codigo == "CADI-SW02-P60-T1"

    previo = _previo(cliente, codigo, piso="P60", tramo="T2")
    assert previo["codigo_nuevo"] == "CADI-SW02-P60-T2"
    assert previo["conflicto"] is None
    assert _ver(cliente, codigo)["tramo_codigo"] == "T1"  # El previo no cambia nada.

    movido = _trasladar(cliente, codigo, piso="P60", tramo="T2").json()
    assert movido["codigo"] == "CADI-SW02-P60-T2"
    assert (movido["piso_codigo"], movido["tramo_codigo"]) == ("P60", "T2")


def test_en_otro_piso_conserva_su_numero_si_esta_libre(cliente):
    _piso(cliente, "P61", "T1")
    _piso(cliente, "P62", "T1")
    _alta(cliente, tipo="SW", piso="P61", tramo="T1")
    _alta(cliente, tipo="SW", piso="P61", tramo="T1")
    codigo = _alta(cliente, tipo="SW", piso="P61", tramo="T1")
    assert codigo == "CADI-SW03-P61-T1"

    movido = _trasladar(cliente, codigo, piso="P62", tramo="T1").json()
    assert movido["codigo"] == "CADI-SW03-P62-T1"


def test_en_otro_piso_toma_el_siguiente_si_su_numero_esta_ocupado(cliente):
    _piso(cliente, "P63", "T1")
    _piso(cliente, "P64", "T1", "T2")
    codigo = _alta(cliente, tipo="SW", piso="P63", tramo="T1")
    # El correlativo es por piso: lo ocupa aunque esté en otro tramo.
    _alta(cliente, tipo="SW", piso="P64", tramo="T2")

    movido = _trasladar(cliente, codigo, piso="P64", tramo="T1").json()
    assert movido["codigo"] == "CADI-SW02-P64-T1"


def test_el_codigo_anterior_queda_reservado_y_sigue_encontrando_al_elemento(cliente, sesion):
    _piso(cliente, "P65", "T1")
    _piso(cliente, "P66", "T1")
    codigo = _alta(cliente, tipo="SW", piso="P65", tramo="T1", direccion_ip="10.70.0.1")
    _trasladar(cliente, codigo, piso="P66", tramo="T1")

    # Ni el correlativo siguiente, ni pidiéndolo a mano, ni en el previo.
    assert _alta(cliente, tipo="SW", piso="P65", tramo="T1") == "CADI-SW02-P65-T1"
    repetido = cliente.post(
        f"{API}/elementos",
        json={"edificio": "CADI", "tipo": "SW", "piso": "P65", "tramo": "T1", "codigo": codigo},
    )
    assert repetido.status_code == 409

    assert _ver(cliente, codigo)["codigo"] == "CADI-SW01-P66-T1"
    # Zabbix puede seguir avisando con el código que conoce.
    assert buscar_elemento(sesion, codigo, None).codigo == "CADI-SW01-P66-T1"


def test_puede_volver_a_su_codigo_anterior(cliente):
    _piso(cliente, "P67", "T1")
    _piso(cliente, "P68", "T1")
    codigo = _alta(cliente, tipo="SW", piso="P67", tramo="T1")
    assert _trasladar(cliente, codigo, piso="P68", tramo="T1").status_code == 200
    vuelta = _trasladar(cliente, "CADI-SW01-P68-T1", piso="P67", tramo="T1")
    assert vuelta.status_code == 200, vuelta.text
    assert vuelta.json()["codigo"] == codigo
    # El del otro piso sigue reservado.
    assert _alta(cliente, tipo="SW", piso="P68", tramo="T1") == "CADI-SW02-P68-T1"


def test_un_punto_de_datos_conserva_su_rotulo(cliente):
    _piso(cliente, "P69", "T1", "T2")
    rack = _alta(cliente, tipo="R", piso="P69", tramo="T1")
    punto = _alta(cliente, tipo="PD", piso="P69", tramo="T1", rack_origen=rack, puerto="D17")
    assert punto == "CADI-PD-P69-T1-R01-D17"
    assert _trasladar(cliente, punto, piso="P69", tramo="T2").json()["codigo"] == (
        "CADI-PD-P69-T2-R01-D17"
    )


def test_un_punto_de_datos_no_pisa_a_otro_con_el_mismo_rotulo(cliente):
    _piso(cliente, "P70", "T1", "T2")
    rack = _alta(cliente, tipo="R", piso="P70", tramo="T1")
    datos = {"tipo": "PD", "piso": "P70", "rack_origen": rack, "puerto": "D05"}
    punto = _alta(cliente, tramo="T1", **datos)
    _alta(cliente, tramo="T2", **datos)

    previo = _previo(cliente, punto, piso="P70", tramo="T2")
    assert previo["codigo_nuevo"] is None
    assert "CADI-PD-P70-T2-R01-D05" in previo["conflicto"]
    respuesta = _trasladar(cliente, punto, piso="P70", tramo="T2")
    assert respuesta.status_code == 409
    assert _ver(cliente, punto)["tramo_codigo"] == "T1"


def test_un_punto_sin_rotulo_toma_el_siguiente_del_destino(cliente):
    _piso(cliente, "P71", "T1", "T2")
    _alta(cliente, tipo="PD", piso="P71", tramo="T2")
    punto = _alta(cliente, tipo="PD", piso="P71", tramo="T1")
    assert punto == "CADI-PD-P71-T1-SIN-ROTULO-01"
    assert _trasladar(cliente, punto, piso="P71", tramo="T2").json()["codigo"] == (
        "CADI-PD-P71-T2-SIN-ROTULO-02"
    )


# --- A dónde puede ir --------------------------------------------------------


def test_trasladarlo_a_donde_ya_esta_no_hace_nada(cliente):
    _piso(cliente, "P72", "T1")
    codigo = _alta(cliente, tipo="SW", piso="P72", tramo="T1")
    assert "ya está" in _previo(cliente, codigo, piso="P72", tramo="T1")["conflicto"]
    assert _trasladar(cliente, codigo, piso="P72", tramo="T1").status_code == 409


def test_solo_dentro_de_su_edificio(cliente):
    _piso(cliente, "P73", "T1")
    cliente.post(f"{API}/edificios", json={"codigo": "OTRO", "nombre": "Otro edificio"})
    cliente.post(f"{API}/edificios/OTRO/pisos", json={"codigo": "P99", "orden": 1})
    codigo = _alta(cliente, tipo="SW", piso="P73", tramo="T1")
    assert _trasladar(cliente, codigo, piso="P99").status_code == 404
    assert _trasladar(cliente, codigo, piso="P73", tramo="T9").status_code == 404


def test_un_piso_con_tramos_exige_indicarlo(cliente):
    _piso(cliente, "P74", "T1", "T2")
    _piso(cliente, "P75")
    codigo = _alta(cliente, tipo="SW", piso="P75")
    respuesta = _trasladar(cliente, codigo, piso="P74")
    assert respuesta.status_code == 422
    assert respuesta.json()["detail"][0]["loc"][-1] == "tramo"


def test_lo_eliminado_no_se_traslada(cliente):
    _piso(cliente, "P76", "T1", "T2")
    codigo = _alta(cliente, tipo="SW", piso="P76", tramo="T1")
    cliente.delete(f"{API}/elementos/{codigo}")
    assert _trasladar(cliente, codigo, piso="P76", tramo="T2").status_code == 409


def test_trasladar_y_su_previo_exigen_sesion(anonimo, cliente):
    _piso(cliente, "P77", "T1", "T2")
    codigo = _alta(cliente, tipo="SW", piso="P77", tramo="T1")
    consulta = f"{API}/elementos/{codigo}/traslado?piso=P77&tramo=T2"
    assert anonimo.get(consulta).status_code == 401
    assert anonimo.post(f"{API}/elementos/{codigo}/trasladar", json={"piso": "P77"}).status_code == 401
    assert anonimo.post(f"{API}/elementos/{codigo}/restaurar").status_code == 401
    assert anonimo.delete(f"{API}/elementos/{codigo}").status_code == 401


# --- Racks y lo que tienen ---------------------------------------------------


def test_un_rack_se_lleva_lo_montado_a_cualquier_profundidad(cliente):
    _piso(cliente, "P78", "T1")
    _piso(cliente, "P79", "T2")
    _alta(cliente, tipo="SW", piso="P79", tramo="T2")  # Ocupa el SW01 del destino.
    rack = _alta(cliente, tipo="R", piso="P78", tramo="T1")
    switch = _alta(cliente, tipo="SW", piso="P78", tramo="T1", padre_codigo=rack, unidad_rack=7)
    otro = _alta(cliente, tipo="SW", piso="P78", tramo="T1", padre_codigo=rack)

    previo = _previo(cliente, rack, piso="P79", tramo="T2")
    assert previo["codigo_nuevo"] == "CADI-R01-P79-T2"
    assert previo["arrastrados"] == [
        {"codigo_actual": switch, "codigo_nuevo": "CADI-SW02-P79-T2"},
        {"codigo_actual": otro, "codigo_nuevo": "CADI-SW03-P79-T2"},
    ]

    movido = _trasladar(cliente, rack, piso="P79", tramo="T2", usuario="Tecnico").json()
    assert movido["codigo"] == "CADI-R01-P79-T2"
    assert {h["codigo"] for h in movido["hijos"]} == {"CADI-SW02-P79-T2", "CADI-SW03-P79-T2"}
    montado = _ver(cliente, switch)
    assert montado["codigo"] == "CADI-SW02-P79-T2"
    assert (montado["piso_codigo"], montado["tramo_codigo"]) == ("P79", "T2")
    assert montado["padre_codigo"] == "CADI-R01-P79-T2"
    assert montado["unidad_rack"] == 7

    historial = cliente.get(f"{API}/elementos/{montado['codigo']}/historial").json()
    entrada = next(h for h in historial if h["campo"] == "traslado")
    assert (entrada["valor_anterior"], entrada["valor_nuevo"]) == ("P78-T1", "P79-T2")
    assert entrada["usuario"] == "Tecnico"
    assert entrada["comentario"] == "Se trasladó con CADI-R01-P79-T2, donde está montado"


def test_lo_conectado_se_desconecta_solo_si_el_rack_cambia_de_piso(cliente):
    _piso(cliente, "P80", "T1", "T2")
    _piso(cliente, "P81", "T1")
    rack = _alta(cliente, tipo="R", piso="P80", tramo="T1")
    interior = _alta(cliente, tipo="R", piso="P80", tramo="T1", padre_codigo=rack)
    del_rack = _alta(cliente, tipo="AP", piso="P80", tramo="T1", padre_codigo=rack)
    # Conectado a lo que está montado en él: tampoco viaja con el rack.
    del_interior = _alta(cliente, tipo="AP", piso="P80", tramo="T1", padre_codigo=interior)

    # En el mismo piso, el cable sigue llegando.
    rack = _trasladar(cliente, rack, piso="P80", tramo="T2").json()["codigo"]
    assert _ver(cliente, del_rack)["padre_codigo"] == rack
    assert _ver(cliente, del_rack)["tramo_codigo"] == "T1"

    previo = _previo(cliente, rack, piso="P81", tramo="T1")
    assert sorted(previo["desconectados"]) == sorted([del_rack, del_interior])
    assert _trasladar(cliente, rack, piso="P81", tramo="T1").status_code == 200

    for codigo in (del_rack, del_interior):
        punto = _ver(cliente, codigo)
        assert punto["padre_codigo"] is None
        assert (punto["codigo"], punto["piso_codigo"]) == (codigo, "P80")


def test_un_equipo_montado_sale_de_su_rack_al_irse(cliente):
    _piso(cliente, "P82", "T1", "T2")
    rack = _alta(cliente, tipo="R", piso="P82", tramo="T1")
    switch = _alta(cliente, tipo="SW", piso="P82", tramo="T1", padre_codigo=rack, unidad_rack=4)

    assert _previo(cliente, switch, piso="P82", tramo="T2")["pierde_rack"] is True
    movido = _trasladar(cliente, switch, piso="P82", tramo="T2").json()
    assert movido["padre_codigo"] is None
    assert movido["unidad_rack"] is None
    assert movido["montado"] is False


def test_un_ap_sigue_conectado_si_cambia_de_tramo(cliente):
    _piso(cliente, "P83", "T1", "T2")
    rack = _alta(cliente, tipo="R", piso="P83", tramo="T1")
    ap = _alta(cliente, tipo="AP", piso="P83", tramo="T1", padre_codigo=rack)
    assert _previo(cliente, ap, piso="P83", tramo="T2")["pierde_rack"] is False
    assert _trasladar(cliente, ap, piso="P83", tramo="T2").json()["padre_codigo"] == rack


def test_se_puede_indicar_su_rack_en_el_destino(cliente):
    _piso(cliente, "P84", "T1")
    _piso(cliente, "P85", "T1")
    rack_origen = _alta(cliente, tipo="R", piso="P84", tramo="T1")
    rack_destino = _alta(cliente, tipo="R", piso="P85", tramo="T1")
    switch = _alta(cliente, tipo="SW", piso="P84", tramo="T1", padre_codigo=rack_origen, unidad_rack=2)

    otro_piso = _trasladar(cliente, switch, piso="P85", tramo="T1", padre_codigo=rack_origen)
    assert otro_piso.status_code == 422
    assert otro_piso.json()["detail"][0]["loc"][-1] == "padre_codigo"

    movido = _trasladar(
        cliente, switch, piso="P85", tramo="T1", padre_codigo=rack_destino, unidad_rack=9
    ).json()
    assert movido["padre_codigo"] == rack_destino
    assert movido["unidad_rack"] == 9


def test_montado_debe_estar_en_el_tramo_de_su_rack(cliente):
    _piso(cliente, "P97", "T1", "T2")
    rack = _alta(cliente, tipo="R", piso="P97", tramo="T1")
    switch = _alta(cliente, tipo="SW", piso="P97", tramo="T2")
    ap = _alta(cliente, tipo="AP", piso="P97", tramo="T1", padre_codigo=rack)

    # El switch va a T2 y el rack está en T1. Un AP, en cambio, solo se conecta.
    otro_tramo = _alta(cliente, tipo="SW", piso="P97", tramo="T1")
    respuesta = _trasladar(cliente, otro_tramo, piso="P97", tramo="T2", padre_codigo=rack)
    assert respuesta.status_code == 422
    assert respuesta.json()["detail"][0]["loc"][-1] == "padre_codigo"
    assert _trasladar(cliente, ap, piso="P97", tramo="T2", padre_codigo=rack).status_code == 200
    # A T1, donde está el rack, sí.
    assert _trasladar(cliente, switch, piso="P97", tramo="T1", padre_codigo=rack).status_code == 200


def test_un_rack_no_puede_montarse_en_si_mismo_ni_en_lo_que_contiene(cliente):
    _piso(cliente, "P86", "T1", "T2")
    rack = _alta(cliente, tipo="R", piso="P86", tramo="T1")
    otro = _alta(cliente, tipo="R", piso="P86", tramo="T1", padre_codigo=rack)
    for padre in (rack, otro):
        respuesta = _trasladar(cliente, rack, piso="P86", tramo="T2", padre_codigo=padre)
        assert respuesta.status_code == 422, padre
    assert _ver(cliente, rack)["tramo_codigo"] == "T1"


# --- En el plano ---------------------------------------------------------------


def test_su_marcador_solo_sigue_valiendo_en_la_misma_lamina(cliente, sesion):
    _piso(cliente, "P87", "T1", "T2")  # Una sola lámina para el piso entero.
    _piso(cliente, "P88")
    lamina = _lamina(sesion, "P87")
    _lamina(sesion, "P88")
    codigo = _alta(cliente, tipo="SW", piso="P87", tramo="T1")
    posicion = cliente.patch(
        f"{API}/elementos/{codigo}/posicion", json={"pos_x": 10, "pos_y": 20, "plano_id": lamina}
    )
    assert posicion.status_code == 200, posicion.text

    assert _previo(cliente, codigo, piso="P87", tramo="T2")["conserva_posicion"] is True
    movido = _trasladar(cliente, codigo, piso="P87", tramo="T2").json()
    assert (movido["pos_x"], movido["pos_y"]) == (10, 20)

    assert _previo(cliente, movido["codigo"], piso="P88")["conserva_posicion"] is False
    movido = _trasladar(cliente, movido["codigo"], piso="P88").json()
    assert (movido["pos_x"], movido["pos_y"], movido["plano_id"]) == (None, None, None)


def test_el_recinto_se_borra_al_cambiar_de_piso_y_se_valida_el_nuevo(cliente):
    _piso(cliente, "P07", "T1")
    _piso(cliente, "P08", "T1", "T2")
    codigo = _alta(
        cliente,
        tipo="AP",
        piso="P07",
        tramo="T1",
        numero_recinto="7083",
        ubicacion_descriptiva="Oficina",
    )
    malo = _trasladar(cliente, codigo, piso="P08", tramo="T1", numero_recinto="7083")
    assert malo.status_code == 422
    assert _ver(cliente, codigo)["numero_recinto"] == "7083"

    movido = _trasladar(cliente, codigo, piso="P08", tramo="T1").json()
    assert (movido["numero_recinto"], movido["ubicacion_descriptiva"]) == (None, None)

    con_sala = _trasladar(
        cliente,
        movido["codigo"],
        piso="P08",
        tramo="T2",
        numero_recinto="8045",
        ubicacion_descriptiva="Laboratorio",
    ).json()
    assert (con_sala["numero_recinto"], con_sala["ubicacion_descriptiva"]) == ("8045", "Laboratorio")

    # En el mismo piso se conserva si no se dice otra cosa.
    otro_tramo = _trasladar(cliente, con_sala["codigo"], piso="P08", tramo="T1").json()
    assert (otro_tramo["numero_recinto"], otro_tramo["ubicacion_descriptiva"]) == (
        "8045",
        "Laboratorio",
    )


def test_el_historial_explica_el_traslado(cliente):
    _piso(cliente, "P89", "T1", "T2")
    codigo = _alta(cliente, tipo="SW", piso="P89", tramo="T1")
    _trasladar(
        cliente, codigo, piso="P89", tramo="T2", usuario="Tecnico", comentario="Remodelación"
    )
    historial = cliente.get(f"{API}/elementos/{codigo}/historial").json()
    entrada = next(h for h in historial if h["campo"] == "traslado")
    assert (entrada["valor_anterior"], entrada["valor_nuevo"]) == ("P89-T1", "P89-T2")
    assert entrada["comentario"] == "Traslado de P89-T1 a P89-T2: Remodelación"
    cambio = next(h for h in historial if h["campo"] == "codigo")
    assert (cambio["valor_anterior"], cambio["valor_nuevo"]) == (codigo, "CADI-SW01-P89-T2")


# --- Eliminar y restaurar --------------------------------------------------------


def test_un_rack_con_equipos_montados_no_se_elimina(cliente):
    _piso(cliente, "P90", "T1")
    rack = _alta(cliente, tipo="R", piso="P90", tramo="T1")
    switch = _alta(cliente, tipo="SW", piso="P90", tramo="T1", padre_codigo=rack)

    respuesta = cliente.delete(f"{API}/elementos/{rack}")
    assert respuesta.status_code == 409
    assert switch in respuesta.json()["detail"]
    assert _ver(cliente, rack)["activo"] is True

    # Ya vacío, sí.
    assert cliente.delete(f"{API}/elementos/{switch}").status_code == 200
    assert cliente.delete(f"{API}/elementos/{rack}").status_code == 200


def test_eliminar_un_rack_desconecta_lo_conectado(cliente):
    _piso(cliente, "P91", "T1")
    rack = _alta(cliente, tipo="R", piso="P91", tramo="T1")
    ap = _alta(cliente, tipo="AP", piso="P91", tramo="T1", padre_codigo=rack)

    assert cliente.delete(f"{API}/elementos/{rack}", params={"usuario": "Tecnico"}).status_code == 200
    punto = _ver(cliente, ap)
    assert punto["activo"] is True
    assert punto["padre_codigo"] is None
    historial = cliente.get(f"{API}/elementos/{ap}/historial").json()
    entrada = next(h for h in historial if h["campo"] == "padre_id")
    assert rack in entrada["comentario"]
    assert entrada["usuario"] == "Tecnico"


def test_no_se_elimina_dos_veces(cliente):
    _piso(cliente, "P92", "T1")
    codigo = _alta(cliente, tipo="SW", piso="P92", tramo="T1")
    assert cliente.delete(f"{API}/elementos/{codigo}").status_code == 200
    assert cliente.delete(f"{API}/elementos/{codigo}").status_code == 409


def test_lo_eliminado_sale_del_mapa_y_se_puede_listar(cliente):
    _piso(cliente, "P93")
    queda = _alta(cliente, tipo="SW", piso="P93")
    eliminado = _alta(cliente, tipo="SW", piso="P93")
    cliente.delete(f"{API}/elementos/{eliminado}", params={"motivo": "Se quemó"})

    activos = cliente.get(f"{API}/elementos", params={"edificio": "CADI", "piso": "P93"}).json()
    assert [e["codigo"] for e in activos["items"]] == [queda]
    listado = cliente.get(
        f"{API}/elementos", params={"edificio": "CADI", "piso": "P93", "solo_eliminados": True}
    ).json()
    assert [e["codigo"] for e in listado["items"]] == [eliminado]

    historial = cliente.get(f"{API}/elementos/{eliminado}/historial").json()
    assert any(h["comentario"] == "Se quemó" for h in historial)


def test_restaurar_lo_devuelve_con_su_codigo_y_su_estado(cliente):
    _piso(cliente, "P94")
    codigo = _alta(cliente, tipo="SW", piso="P94", estado_operativo="en_mantenimiento")
    cliente.delete(f"{API}/elementos/{codigo}")
    assert _ver(cliente, codigo)["estado_operativo"] == "retirado"

    respuesta = cliente.post(f"{API}/elementos/{codigo}/restaurar", params={"usuario": "Tecnico"})
    assert respuesta.status_code == 200, respuesta.text
    vuelto = respuesta.json()
    assert (vuelto["codigo"], vuelto["activo"]) == (codigo, True)
    assert vuelto["estado_operativo"] == "en_mantenimiento"
    assert cliente.post(f"{API}/elementos/{codigo}/restaurar").status_code == 409


def test_restaurar_no_lo_monta_en_un_rack_que_ya_no_esta_ahi(cliente):
    _piso(cliente, "P95", "T1", "T2")
    rack = _alta(cliente, tipo="R", piso="P95", tramo="T1")
    sigue = _alta(cliente, tipo="SW", piso="P95", tramo="T1", padre_codigo=rack, unidad_rack=3)
    se_fue = _alta(cliente, tipo="SW", piso="P95", tramo="T1", padre_codigo=rack, unidad_rack=4)

    # Sigue en su rack: vuelve a él.
    cliente.delete(f"{API}/elementos/{sigue}")
    assert cliente.post(f"{API}/elementos/{sigue}/restaurar").json()["padre_codigo"] == rack

    # Mientras estaba eliminado, el rack se trasladó.
    cliente.delete(f"{API}/elementos/{se_fue}")
    rack = _trasladar(cliente, rack, piso="P95", tramo="T2").json()["codigo"]
    vuelto = cliente.post(f"{API}/elementos/{se_fue}/restaurar").json()
    assert vuelto["padre_codigo"] is None
    assert vuelto["unidad_rack"] is None


def test_restaurar_vuelve_a_conectar_lo_que_se_desconecto_al_eliminarlo(cliente):
    _piso(cliente, "P50", "T1")
    _piso(cliente, "P51", "T1")
    rack = _alta(cliente, tipo="R", piso="P50", tramo="T1")
    vuelve = _alta(cliente, tipo="AP", piso="P50", tramo="T1", padre_codigo=rack)
    se_fue = _alta(cliente, tipo="AP", piso="P50", tramo="T1", padre_codigo=rack)
    otro_rack = _alta(cliente, tipo="R", piso="P50", tramo="T1")
    conectado_a_otro = _alta(cliente, tipo="UPS", piso="P50", tramo="T1", padre_codigo=rack)

    cliente.delete(f"{API}/elementos/{rack}")
    # Mientras tanto, uno cambió de piso y otro se conectó a otro rack.
    se_fue = _trasladar(cliente, se_fue, piso="P51", tramo="T1").json()["codigo"]
    cliente.patch(f"{API}/elementos/{conectado_a_otro}", json={"padre_codigo": otro_rack})

    assert cliente.post(f"{API}/elementos/{rack}/restaurar").status_code == 200
    assert _ver(cliente, vuelve)["padre_codigo"] == rack
    assert _ver(cliente, se_fue)["padre_codigo"] is None
    assert _ver(cliente, conectado_a_otro)["padre_codigo"] == otro_rack

    # Una segunda baja y restauración no resucita desconexiones anteriores.
    cliente.patch(f"{API}/elementos/{vuelve}", json={"padre_codigo": None})
    cliente.delete(f"{API}/elementos/{rack}")
    cliente.post(f"{API}/elementos/{rack}/restaurar")
    assert _ver(cliente, vuelve)["padre_codigo"] is None


def test_un_equipo_retirado_a_mano_vuelve_retirado(cliente):
    _piso(cliente, "P52", "T1")
    codigo = _alta(cliente, tipo="SW", piso="P52", tramo="T1")
    cliente.patch(f"{API}/elementos/{codigo}", json={"estado_operativo": "retirado"})
    cliente.delete(f"{API}/elementos/{codigo}")
    assert cliente.post(f"{API}/elementos/{codigo}/restaurar").json()["estado_operativo"] == "retirado"


def test_un_rack_eliminado_no_recibe_equipos(cliente):
    _piso(cliente, "P53", "T1", "T2")
    rack = _alta(cliente, tipo="R", piso="P53", tramo="T1")
    switch = _alta(cliente, tipo="SW", piso="P53", tramo="T1")
    otro = _alta(cliente, tipo="SW", piso="P53", tramo="T2")
    cliente.delete(f"{API}/elementos/{rack}")

    datos = {"edificio": "CADI", "piso": "P53", "tramo": "T1"}
    con_rack = cliente.post(f"{API}/elementos", json={"tipo": "SW", "padre_codigo": rack, **datos})
    assert con_rack.status_code == 409
    punto = cliente.post(
        f"{API}/elementos", json={"tipo": "PD", "rack_origen": rack, "puerto": "D01", **datos}
    )
    assert punto.status_code == 409
    assert cliente.patch(f"{API}/elementos/{switch}", json={"padre_codigo": rack}).status_code == 409
    respuesta = _trasladar(cliente, otro, piso="P53", tramo="T1", padre_codigo=rack)
    assert respuesta.status_code == 422


def test_el_usuario_y_el_motivo_tienen_un_largo_maximo(cliente):
    _piso(cliente, "P54", "T1", "T2")
    codigo = _alta(cliente, tipo="SW", piso="P54", tramo="T1")
    largo = "x" * 121
    assert _trasladar(cliente, codigo, piso="P54", tramo="T2", usuario=largo).status_code == 422
    assert cliente.delete(f"{API}/elementos/{codigo}", params={"usuario": largo}).status_code == 422
    assert cliente.delete(f"{API}/elementos/{codigo}", params={"motivo": "x" * 1001}).status_code == 422


def test_el_proximo_codigo_avisa_si_es_de_un_elemento_eliminado(cliente):
    _piso(cliente, "P96", "T1")
    rack = _alta(cliente, tipo="R", piso="P96", tramo="T1")
    consulta = {
        "tipo": "PD",
        "edificio": "CADI",
        "piso": "P96",
        "tramo": "T1",
        "rack_origen": rack,
        "puerto": "D01",
    }
    punto = _alta(cliente, tipo="PD", piso="P96", tramo="T1", rack_origen=rack, puerto="D01")
    url = f"{API}/elementos/proximo-codigo"
    assert cliente.get(url, params=consulta).json()["eliminado"] is False

    cliente.delete(f"{API}/elementos/{punto}")
    respuesta = cliente.get(url, params=consulta).json()
    assert respuesta == {"codigo": punto, "disponible": False, "eliminado": True}


# --- Editar lo que forma parte del código ------------------------------------------


def _piso_edi(cliente, piso, *tramos):
    cliente.post(f"{API}/edificios", json={"codigo": "EDI", "nombre": "Edificio de prueba"})
    cliente.post(f"{API}/edificios/EDI/pisos", json={"codigo": piso, "orden": 1})
    for tramo in tramos:
        cliente.post(f"{API}/edificios/EDI/pisos/{piso}/tramos", json={"codigo": tramo})


def _alta_edi(cliente, **datos):
    return _alta(cliente, edificio="EDI", **datos)


def _editar(cliente, codigo, **datos):
    return cliente.patch(f"{API}/elementos/{codigo}", json=datos)


def _enlaces_hacia(sesion, codigo):
    sesion.expire_all()
    punto = sesion.scalar(select(Elemento).where(Elemento.codigo == codigo))
    return sesion.scalars(select(Enlace).where(Enlace.destino_id == punto.id)).all()


def test_editar_el_tramo_actualiza_el_codigo(cliente):
    _piso_edi(cliente, "P30", "T1", "T2")
    codigo = _alta_edi(cliente, tipo="SW", piso="P30", tramo="T1")

    respuesta = _editar(cliente, codigo, tramo="T2", etiqueta="SW-A", usuario="Tecnico")
    assert respuesta.status_code == 200, respuesta.text
    editado = respuesta.json()
    assert editado["codigo"] == "EDI-SW01-P30-T2"
    assert (editado["tramo_codigo"], editado["etiqueta"]) == ("T2", "SW-A")

    # El anterior queda reservado y sigue llevando al elemento.
    assert _ver(cliente, codigo)["codigo"] == "EDI-SW01-P30-T2"
    assert _alta_edi(cliente, tipo="SW", piso="P30", tramo="T1") == "EDI-SW02-P30-T1"
    historial = cliente.get(f"{API}/elementos/{editado['codigo']}/historial").json()
    entrada = next(h for h in historial if h["campo"] == "codigo")
    assert (entrada["valor_anterior"], entrada["usuario"]) == (codigo, "Tecnico")


def test_editar_el_tramo_de_un_rack_se_lleva_lo_montado(cliente):
    _piso_edi(cliente, "P31", "T1", "T2")
    rack = _alta_edi(cliente, tipo="R", piso="P31", tramo="T1")
    switch = _alta_edi(cliente, tipo="SW", piso="P31", tramo="T1", padre_codigo=rack)

    assert _editar(cliente, rack, tramo="T2").json()["codigo"] == "EDI-R01-P31-T2"
    montado = _ver(cliente, switch)
    assert montado["codigo"] == "EDI-SW01-P31-T2"
    assert montado["padre_codigo"] == "EDI-R01-P31-T2"


def test_editar_al_mismo_tramo_no_es_un_traslado(cliente):
    _piso_edi(cliente, "P32", "T1")
    codigo = _alta_edi(cliente, tipo="SW", piso="P32", tramo="T1")
    assert _editar(cliente, codigo, tramo="T1", etiqueta="SW-A").status_code == 200
    historial = cliente.get(f"{API}/elementos/{codigo}/historial").json()
    assert not any(h["campo"] in ("traslado", "codigo") for h in historial)


def test_editar_el_tramo_rechaza_lo_que_rechaza_un_traslado(cliente):
    _piso_edi(cliente, "P33", "T1", "T2")
    rack = _alta_edi(cliente, tipo="R", piso="P33", tramo="T1")
    datos = {"tipo": "PD", "piso": "P33", "rack_origen": rack, "puerto": "D05"}
    punto = _alta_edi(cliente, tramo="T1", **datos)
    _alta_edi(cliente, tramo="T2", **datos)

    assert _editar(cliente, punto, tramo="T2", etiqueta="otra").status_code == 409
    sin_tramo = _editar(cliente, punto, tramo=None)
    assert sin_tramo.status_code == 422
    assert sin_tramo.json()["detail"][0]["loc"][-1] == "tramo"
    # Una edición rechazada no deja nada a medias.
    visto = _ver(cliente, punto)
    assert (visto["tramo_codigo"], visto["etiqueta"]) == ("T1", "P33-T1-R1-D05")


def test_montarlo_en_un_rack_de_otro_tramo_lo_lleva_a_ese_tramo(cliente):
    _piso_edi(cliente, "P34", "T1", "T2")
    rack = _alta_edi(cliente, tipo="R", piso="P34", tramo="T2")
    switch = _alta_edi(cliente, tipo="SW", piso="P34", tramo="T1")

    editado = _editar(cliente, switch, padre_codigo=rack, unidad_rack=7).json()
    assert editado["codigo"] == "EDI-SW01-P34-T2"
    assert (editado["padre_codigo"], editado["unidad_rack"]) == (rack, 7)
    assert editado["tramo_codigo"] == "T2"


def test_un_ap_conectado_a_un_rack_de_otro_tramo_no_cambia(cliente):
    _piso_edi(cliente, "P35", "T1", "T2")
    rack = _alta_edi(cliente, tipo="R", piso="P35", tramo="T2")
    ap = _alta_edi(cliente, tipo="AP", piso="P35", tramo="T1")
    editado = _editar(cliente, ap, padre_codigo=rack).json()
    assert (editado["codigo"], editado["tramo_codigo"], editado["padre_codigo"]) == (ap, "T1", rack)


def test_el_alta_no_monta_en_un_rack_de_otro_lugar(cliente):
    _piso_edi(cliente, "P36", "T1", "T2")
    _piso_edi(cliente, "P37", "T1")
    rack = _alta_edi(cliente, tipo="R", piso="P36", tramo="T1")
    datos = {"edificio": "EDI", "padre_codigo": rack}
    otro_tramo = cliente.post(f"{API}/elementos", json={"tipo": "SW", "piso": "P36", "tramo": "T2", **datos})
    assert otro_tramo.status_code == 422
    otro_piso = cliente.post(f"{API}/elementos", json={"tipo": "AP", "piso": "P37", "tramo": "T1", **datos})
    assert otro_piso.status_code == 422
    # Un AP solo se conecta: basta con que esté en el piso.
    assert _alta_edi(cliente, tipo="AP", piso="P36", tramo="T2", padre_codigo=rack)


def test_completar_un_punto_sin_rotulo_actualiza_todo_lo_que_depende_del_puerto(cliente, sesion):
    _piso_edi(cliente, "P38", "T1")
    rack = _alta_edi(cliente, tipo="R", piso="P38", tramo="T1")
    punto = _alta_edi(cliente, tipo="PD", piso="P38", tramo="T1", etiqueta="Sin etiqueta")
    assert punto == "EDI-PD-P38-T1-SIN-ROTULO-01"

    respuesta = _editar(cliente, punto, rack_origen=rack, puerto="d17", usuario="Tecnico")
    assert respuesta.status_code == 200, respuesta.text
    editado = respuesta.json()
    assert editado["codigo"] == "EDI-PD-P38-T1-R01-D17"
    assert editado["etiqueta"] == "P38-T1-R1-D17"
    assert editado["atributos"]["puerto_origen"] == "P38-T1-R1-D17"
    assert editado["atributos"]["servicio"] == "datos"
    assert (editado["rack_origen_codigo"], editado["puerto_en_rack"]) == (rack, "D17")

    enlaces = _enlaces_hacia(sesion, editado["codigo"])
    assert [(e.origen.codigo, e.puerto_origen, e.etiqueta) for e in enlaces] == [
        (rack, "D17", "P38-T1-R1-D17")
    ]

    # El anterior sigue llevando a él, y el próximo sin rótulo no lo reutiliza.
    assert _ver(cliente, punto)["codigo"] == editado["codigo"]
    assert _alta_edi(cliente, tipo="PD", piso="P38", tramo="T1") == "EDI-PD-P38-T1-SIN-ROTULO-02"


def test_cambiar_el_puerto_mueve_el_enlace_en_vez_de_duplicarlo(cliente, sesion):
    _piso_edi(cliente, "P39", "T1")
    rack = _alta_edi(cliente, tipo="R", piso="P39", tramo="T1")
    otro = _alta_edi(cliente, tipo="R", piso="P39", tramo="T1")
    punto = _alta_edi(cliente, tipo="PD", piso="P39", tramo="T1", rack_origen=rack, puerto="D01")

    editado = _editar(cliente, punto, rack_origen=otro, puerto="T03").json()
    assert editado["codigo"] == "EDI-PD-P39-T1-R02-T03"
    # El rótulo y el servicio siguen al puerto.
    assert editado["etiqueta"] == "P39-T1-R2-T03"
    assert editado["atributos"]["servicio"] == "telefonia"
    enlaces = _enlaces_hacia(sesion, editado["codigo"])
    assert [(e.origen.codigo, e.puerto_origen) for e in enlaces] == [(otro, "T03")]


def test_cambiar_el_puerto_respeta_lo_escrito_a_mano(cliente):
    _piso_edi(cliente, "P46", "T1")
    rack = _alta_edi(cliente, tipo="R", piso="P46", tramo="T1")
    punto = _alta_edi(
        cliente,
        tipo="PD",
        piso="P46",
        tramo="T1",
        rack_origen=rack,
        puerto="D01",
        etiqueta="Roseta recepción",
        atributos={"servicio": "video"},
    )
    editado = _editar(cliente, punto, rack_origen=rack, puerto="T02").json()
    assert editado["codigo"] == "EDI-PD-P46-T1-R01-T02"
    assert editado["etiqueta"] == "Roseta recepción"
    assert editado["atributos"]["servicio"] == "video"


def test_no_se_puede_tomar_un_puerto_ya_documentado(cliente):
    _piso_edi(cliente, "P47", "T1")
    rack = _alta_edi(cliente, tipo="R", piso="P47", tramo="T1")
    _alta_edi(cliente, tipo="PD", piso="P47", tramo="T1", rack_origen=rack, puerto="D01")
    punto = _alta_edi(cliente, tipo="PD", piso="P47", tramo="T1", rack_origen=rack, puerto="D02")

    respuesta = _editar(cliente, punto, rack_origen=rack, puerto="D01", etiqueta="otra")
    assert respuesta.status_code == 409
    assert "EDI-PD-P47-T1-R01-D01" in respuesta.json()["detail"]
    visto = _ver(cliente, punto)
    assert (visto["codigo"], visto["etiqueta"]) == (punto, "P47-T1-R1-D02")


def test_un_punto_puede_volver_a_un_puerto_que_tuvo(cliente):
    _piso_edi(cliente, "P48", "T1")
    rack = _alta_edi(cliente, tipo="R", piso="P48", tramo="T1")
    punto = _alta_edi(cliente, tipo="PD", piso="P48", tramo="T1", rack_origen=rack, puerto="D01")
    nuevo = _editar(cliente, punto, rack_origen=rack, puerto="D02").json()["codigo"]
    assert _editar(cliente, nuevo, rack_origen=rack, puerto="D01").json()["codigo"] == punto


def test_el_rack_y_el_puerto_van_juntos_y_solo_en_un_punto_de_datos(cliente):
    _piso_edi(cliente, "P49", "T1")
    rack = _alta_edi(cliente, tipo="R", piso="P49", tramo="T1")
    punto = _alta_edi(cliente, tipo="PD", piso="P49", tramo="T1")
    switch = _alta_edi(cliente, tipo="SW", piso="P49", tramo="T1")

    falta_puerto = _editar(cliente, punto, rack_origen=rack)
    assert falta_puerto.status_code == 422
    assert falta_puerto.json()["detail"][0]["loc"][-1] == "puerto"
    falta_rack = _editar(cliente, punto, puerto="D01")
    assert falta_rack.json()["detail"][0]["loc"][-1] == "rack_origen"
    assert _editar(cliente, switch, rack_origen=rack, puerto="D01").status_code == 422
    assert _editar(cliente, punto, rack_origen=rack, puerto="D 01").status_code == 422


def test_el_rotulo_escrito_en_la_ficha_tambien_actualiza_el_codigo(cliente):
    _piso_edi(cliente, "P55", "T1")
    _alta_edi(cliente, tipo="R", piso="P55", tramo="T1")
    punto = _alta_edi(cliente, tipo="PD", piso="P55", tramo="T1")

    editado = _editar(cliente, punto, atributos={"puerto_origen": "p55-t1-r1-c07"}).json()
    assert editado["codigo"] == "EDI-PD-P55-T1-R01-C07"
    assert editado["atributos"]["puerto_origen"] == "P55-T1-R1-C07"
    assert editado["atributos"]["servicio"] == "cctv"


def test_un_rotulo_que_no_se_entiende_no_cambia_el_codigo(cliente):
    _piso_edi(cliente, "P56", "T1")
    punto = _alta_edi(cliente, tipo="PD", piso="P56", tramo="T1")
    editado = _editar(cliente, punto, atributos={"puerto_origen": "patch panel 3"}).json()
    assert editado["codigo"] == punto
    assert editado["atributos"]["puerto_origen"] == "patch panel 3"


def test_el_proximo_codigo_no_le_estorba_al_que_lo_edita(cliente):
    _piso_edi(cliente, "P57", "T1")
    rack = _alta_edi(cliente, tipo="R", piso="P57", tramo="T1")
    punto = _alta_edi(cliente, tipo="PD", piso="P57", tramo="T1", rack_origen=rack, puerto="D01")
    id_punto = _ver(cliente, punto)["id"]
    consulta = {
        "tipo": "PD",
        "edificio": "EDI",
        "piso": "P57",
        "tramo": "T1",
        "rack_origen": rack,
        "puerto": "D01",
    }
    url = f"{API}/elementos/proximo-codigo"
    assert cliente.get(url, params=consulta).json()["disponible"] is False
    assert cliente.get(url, params={**consulta, "para": id_punto}).json()["disponible"] is True
    otro = _alta_edi(cliente, tipo="PD", piso="P57", tramo="T1")
    id_otro = _ver(cliente, otro)["id"]
    assert cliente.get(url, params={**consulta, "para": id_otro}).json()["disponible"] is False
