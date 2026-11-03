"""Pruebas de extremo a extremo del flujo principal de la API."""

from __future__ import annotations

API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n"


def _crear_piso(cliente, codigo_piso="P01"):
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": codigo_piso, "orden": 1})
    cliente.post(f"{API}/edificios/CADI/pisos/{codigo_piso}/tramos", json={"codigo": "T2"})


def test_salud(cliente):
    respuesta = cliente.get("/salud")
    assert respuesta.status_code == 200
    assert respuesta.json()["base_datos"] == "ok"


def test_catalogo_cargado(cliente):
    respuesta = cliente.get(f"{API}/catalogo/tipos")
    assert respuesta.status_code == 200
    codigos = {t["codigo"] for t in respuesta.json()}
    assert {"SW", "AP", "PP", "R", "UPS"} <= codigos


def test_ficha_de_switch_declara_atributos_obligatorios(cliente):
    respuesta = cliente.get(f"{API}/catalogo/tipos/SW/ficha")
    assert respuesta.status_code == 200
    obligatorios = {a["clave"] for a in respuesta.json() if a["obligatorio"]}
    assert "vlan_gestion" in obligatorios
    assert "puertos_totales" in obligatorios


def test_alta_genera_codigo_segun_el_sop(cliente):
    _crear_piso(cliente)
    respuesta = cliente.post(
        f"{API}/elementos",
        json={"tipo": "R", "edificio": "CADI", "piso": "P01", "tramo": "T2", "etiqueta": "Rack-04"},
    )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["codigo"] == "CADI-R01-P01-T2"


def test_correlativo_avanza_por_tipo_edificio_y_piso(cliente):
    _crear_piso(cliente)
    primero = cliente.post(
        f"{API}/elementos", json={"tipo": "SW", "edificio": "CADI", "piso": "P01", "tramo": "T2"}
    ).json()
    segundo = cliente.post(
        f"{API}/elementos", json={"tipo": "SW", "edificio": "CADI", "piso": "P01", "tramo": "T2"}
    ).json()
    assert primero["codigo"] == "CADI-SW01-P01-T2"
    assert segundo["codigo"] == "CADI-SW02-P01-T2"


def test_atributo_fuera_de_ficha_es_rechazado(cliente):
    _crear_piso(cliente)
    respuesta = cliente.post(
        f"{API}/elementos",
        json={
            "tipo": "AP",
            "edificio": "CADI",
            "piso": "P01",
            "atributos": {"color_de_la_carcasa": "blanco"},
        },
    )
    assert respuesta.status_code == 422


def test_atributo_mal_tipado_es_rechazado(cliente):
    _crear_piso(cliente)
    respuesta = cliente.post(
        f"{API}/elementos",
        json={
            "tipo": "SW",
            "edificio": "CADI",
            "piso": "P01",
            "atributos": {"puertos_totales": "cuarenta y ocho"},
        },
    )
    assert respuesta.status_code == 422


def test_completitud_y_reporte_de_incompletos(cliente):
    _crear_piso(cliente)
    creado = cliente.post(
        f"{API}/elementos", json={"tipo": "UPS", "edificio": "CADI", "piso": "P01"}
    ).json()

    assert creado["completitud"]["completo"] is False
    claves = {f["clave"] for f in creado["completitud"]["faltantes"]}
    assert "coordenadas" in claves
    assert "capacidad_va" in claves

    reporte = cliente.get(f"{API}/reportes/elementos-incompletos?edificio=CADI").json()
    assert creado["codigo"] in {i["codigo"] for i in reporte["items"]}


def test_actualizacion_parcial_fusiona_la_ficha_y_deja_historial(cliente):
    _crear_piso(cliente)
    codigo = cliente.post(
        f"{API}/elementos", json={"tipo": "SW", "edificio": "CADI", "piso": "P01"}
    ).json()["codigo"]

    cliente.patch(f"{API}/elementos/{codigo}", json={"atributos": {"puertos_totales": 48}})
    detalle = cliente.patch(
        f"{API}/elementos/{codigo}",
        json={"atributos": {"puertos_ocupados": 30}, "usuario": "fmercado"},
    ).json()

    assert detalle["atributos"] == {"puertos_totales": 48, "puertos_ocupados": 30}

    historial = cliente.get(f"{API}/elementos/{codigo}/historial").json()
    campos = [h["campo"] for h in historial]
    assert campos.count("atributos") == 2
    assert "alta" in campos


def test_codigo_no_se_reutiliza_tras_la_baja(cliente):
    _crear_piso(cliente)
    creado = cliente.post(
        f"{API}/elementos", json={"tipo": "PBX", "edificio": "CADI", "piso": "P01"}
    ).json()

    baja = cliente.delete(f"{API}/elementos/{creado['codigo']}").json()
    assert baja["activo"] is False
    assert baja["estado_operativo"] == "retirado"

    repetido = cliente.post(
        f"{API}/elementos",
        json={"tipo": "PBX", "edificio": "CADI", "piso": "P01", "codigo": creado["codigo"]},
    )
    assert repetido.status_code == 409


def test_posicion_requiere_un_plano_del_piso(cliente):
    _crear_piso(cliente)
    codigo = cliente.post(
        f"{API}/elementos", json={"tipo": "AP", "edificio": "CADI", "piso": "P01"}
    ).json()["codigo"]

    respuesta = cliente.patch(
        f"{API}/elementos/{codigo}/posicion", json={"plano_id": 999, "pos_x": 10, "pos_y": 10}
    )
    assert respuesta.status_code == 400


def test_mapa_devuelve_elementos_y_pendientes(cliente):
    _crear_piso(cliente, "P02")
    cliente.post(f"{API}/elementos", json={"tipo": "AP", "edificio": "CADI", "piso": "P02"})

    mapa = cliente.get(f"{API}/elementos/mapa?edificio=CADI&piso=P02").json()
    assert mapa["plano"] is None
    assert mapa["total"] == 1
    assert mapa["sin_posicionar"] == 1


def test_plano_svg_se_sanea_antes_de_guardarse(cliente):
    # Los SVG exportados desde PDF traen caracteres de control en los id.
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
        b'<text id="PEND. 12\x00">PEND. 12</text></svg>'
    )
    _crear_piso(cliente, "P05")
    respuesta = cliente.post(
        f"{API}/edificios/CADI/pisos/P05/plano",
        files={"archivo": ("cadi-p05.svg", svg, "image/svg+xml")},
        data={"ancho_px": "100", "alto_px": "50"},
    )
    assert respuesta.status_code == 201, respuesta.text

    servido = cliente.get(f"/media/{respuesta.json()['archivo']}").content
    assert b"\x00" not in servido
    assert b'id="PEND. 12"' in servido


def test_nuevo_plano_no_sobrescribe_el_archivo_del_historico(cliente):
    _crear_piso(cliente, "P06")
    archivos = [
        cliente.post(
            f"{API}/edificios/CADI/pisos/P06/plano",
            files={"archivo": ("cadi-p06.png", contenido, "image/png")},
            data={"ancho_px": "100", "alto_px": "50"},
        ).json()["archivo"]
        for contenido in (PNG + b"version-1", PNG + b"version-2")
    ]
    assert archivos[0] != archivos[1]
    assert cliente.get(f"/media/{archivos[0]}").content == PNG + b"version-1"


def test_nuevo_plano_no_repite_un_numero_de_version_existente(cliente):
    # Tras borrar versiones antiguas, el conteo de planos repite el número de
    # una versión que sigue en disco: la nueva va después de la mayor.
    from app.core.config import configuracion

    _crear_piso(cliente, "P11")
    ocupado = configuracion.dir_planos / "CADI-P11-v3-cadi_11vo_piso.png"
    ocupado.write_bytes(b"version-vigente")

    archivo = _cargar_plano(cliente, "P11")["archivo"]
    assert archivo == "planos/CADI-P11-v4.png"
    assert ocupado.read_bytes() == b"version-vigente"
    assert _cargar_plano(cliente, "P11", contenido=PNG + b"otra")["archivo"] == "planos/CADI-P11-v5.png"


def test_plano_svg_mal_formado_es_rechazado(cliente):
    _crear_piso(cliente, "P05")
    respuesta = cliente.post(
        f"{API}/edificios/CADI/pisos/P05/plano",
        files={"archivo": ("cadi-p05.svg", b"<svg><g></svg>", "image/svg+xml")},
        data={"ancho_px": "100", "alto_px": "50"},
    )
    assert respuesta.status_code == 422


def test_el_contenido_del_plano_debe_corresponder_a_su_extension(cliente):
    _crear_piso(cliente, "P35")
    respuesta = cliente.post(
        f"{API}/edificios/CADI/pisos/P35/plano",
        files={"archivo": ("cadi-p35.png", b"<script>alert(1)</script>", "image/png")},
        data={"ancho_px": "100", "alto_px": "50"},
    )
    assert respuesta.status_code == 415
    assert "no corresponde" in respuesta.json()["detail"]


def test_un_xml_que_no_es_svg_se_rechaza(cliente):
    _crear_piso(cliente, "P36")
    respuesta = cliente.post(
        f"{API}/edificios/CADI/pisos/P36/plano",
        files={"archivo": ("cadi-p36.svg", b"<html><body/></html>", "image/svg+xml")},
        data={"ancho_px": "100", "alto_px": "50"},
    )
    assert respuesta.status_code == 422
    assert "no un SVG" in respuesta.json()["detail"]


def test_la_url_de_un_id_externo_solo_admite_http(cliente):
    _crear_piso(cliente, "P37")
    codigo = cliente.post(
        f"{API}/elementos", json={"tipo": "SW", "edificio": "CADI", "piso": "P37"}
    ).json()["codigo"]
    ruta = f"{API}/elementos/{codigo}/externos/netbox"

    malo = cliente.put(ruta, json={"id_externo": "1", "url": "javascript:alert(document.cookie)"})
    assert malo.status_code == 422
    bueno = cliente.put(ruta, json={"id_externo": "1", "url": "https://netbox.umag.cl/dcim/1"})
    assert bueno.status_code == 200


def _cargar_plano(cliente, codigo_piso, tramo=None, contenido=PNG + b"lamina"):
    datos = {"ancho_px": "100", "alto_px": "50"}
    if tramo:
        datos["tramo"] = tramo
    nombre = f"cadi-{codigo_piso}" + (f"-{tramo}" if tramo else "") + ".png"
    respuesta = cliente.post(
        f"{API}/edificios/CADI/pisos/{codigo_piso}/plano",
        files={"archivo": (nombre.lower(), contenido, "image/png")},
        data=datos,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def test_plano_exige_la_nomenclatura_y_que_corresponda_al_destino(cliente):
    _crear_piso_con_dos_tramos(cliente, "P27")

    def subir(nombre, tramo="T1"):
        return cliente.post(
            f"{API}/edificios/CADI/pisos/P27/plano",
            files={"archivo": (nombre, PNG, "image/png")},
            data={"ancho_px": "100", "alto_px": "50", "tramo": tramo},
        )

    fuera = subir("planta 27 piso tramo 1.png")
    assert fuera.status_code == 422
    assert "renómbrela «cadi-p27-t1.png»" in fuera.json()["detail"]
    otro_tramo = subir("cadi-p27-t2.png")
    assert otro_tramo.status_code == 422
    assert otro_tramo.json()["detail"] == (
        "«cadi-p27-t2.png» es la lámina de CADI P27-T2, no de CADI P27-T1"
    )
    assert subir("ing-p27-t1.png").status_code == 422

    aceptado = subir("CADI-P27-T1.PNG")
    assert aceptado.status_code == 201, aceptado.text
    assert aceptado.json()["nombre"] == "CADI P27 · Tramo 1"


def _crear_piso_con_dos_tramos(cliente, codigo_piso):
    _crear_piso(cliente, codigo_piso)
    cliente.post(f"{API}/edificios/CADI/pisos/{codigo_piso}/tramos", json={"codigo": "T1"})


def test_laminas_de_distintos_tramos_siguen_vigentes(cliente):
    _crear_piso_con_dos_tramos(cliente, "P07")
    t1 = _cargar_plano(cliente, "P07", "T1")
    t2 = _cargar_plano(cliente, "P07", "T2")
    t1_nueva = _cargar_plano(cliente, "P07", "T1", PNG + b"lamina-v2")

    piso = next(p for p in cliente.get(f"{API}/edificios/CADI/pisos").json() if p["codigo"] == "P07")
    assert {p["id"] for p in piso["planos_vigentes"]} == {t1_nueva["id"], t2["id"]}
    assert t1_nueva["archivo"] != t1["archivo"]

    plano_t2 = cliente.get(f"{API}/edificios/CADI/pisos/P07/plano?tramo=T2").json()
    assert plano_t2["id"] == t2["id"]
    assert plano_t2["tramo_codigo"] == "T2"


def test_tramo_sin_lamina_propia_usa_el_plano_del_piso(cliente):
    _crear_piso(cliente, "P08")
    completo = _cargar_plano(cliente, "P08")

    plano = cliente.get(f"{API}/edificios/CADI/pisos/P08/plano?tramo=T2").json()
    assert plano["id"] == completo["id"]
    assert plano["tramo_id"] is None

    mapa = cliente.get(f"{API}/elementos/mapa?edificio=CADI&piso=P08&tramo=T2").json()
    assert mapa["plano"]["id"] == completo["id"]


def test_mapa_por_tramo_filtra_elementos_y_ubica_segun_la_lamina(cliente):
    _crear_piso_con_dos_tramos(cliente, "P09")
    en_t1 = cliente.post(
        f"{API}/elementos", json={"tipo": "AP", "edificio": "CADI", "piso": "P09", "tramo": "T1"}
    ).json()["codigo"]
    cliente.post(f"{API}/elementos", json={"tipo": "AP", "edificio": "CADI", "piso": "P09", "tramo": "T2"})
    lamina_t1 = _cargar_plano(cliente, "P09", "T1")
    _cargar_plano(cliente, "P09", "T2")

    respuesta = cliente.patch(
        f"{API}/elementos/{en_t1}/posicion",
        json={"plano_id": lamina_t1["id"], "pos_x": 10, "pos_y": 10},
    )
    assert respuesta.status_code == 200, respuesta.text

    mapa_t1 = cliente.get(f"{API}/elementos/mapa?edificio=CADI&piso=P09&tramo=T1").json()
    assert mapa_t1["plano"]["id"] == lamina_t1["id"]
    assert [(e["codigo"], e["ubicado"]) for e in mapa_t1["elementos"]] == [(en_t1, True)]
    assert mapa_t1["sin_posicionar"] == 0

    mapa_t2 = cliente.get(f"{API}/elementos/mapa?edificio=CADI&piso=P09&tramo=T2").json()
    assert mapa_t2["total"] == 1
    assert mapa_t2["sin_posicionar"] == 1

    # Sin plano del piso completo no hay lámina que mostrar, pero el listado
    # sigue reconociendo al elemento que ya tiene coordenadas.
    mapa_piso = cliente.get(f"{API}/elementos/mapa?edificio=CADI&piso=P09").json()
    assert mapa_piso["plano"] is None
    assert mapa_piso["total"] == 2
    assert mapa_piso["sin_posicionar"] == 1


def test_posicion_rechaza_la_lamina_de_otro_tramo(cliente):
    _crear_piso_con_dos_tramos(cliente, "P10")
    en_t2 = cliente.post(
        f"{API}/elementos", json={"tipo": "AP", "edificio": "CADI", "piso": "P10", "tramo": "T2"}
    ).json()["codigo"]
    lamina_t1 = _cargar_plano(cliente, "P10", "T1")

    respuesta = cliente.patch(
        f"{API}/elementos/{en_t2}/posicion",
        json={"plano_id": lamina_t1["id"], "pos_x": 10, "pos_y": 10},
    )
    assert respuesta.status_code == 400
    assert "tramo T1" in respuesta.json()["detail"]


def _rack_con_switch_y_ap(cliente, codigo_piso):
    _crear_piso(cliente, codigo_piso)
    ubicacion = {"edificio": "CADI", "piso": codigo_piso, "tramo": "T2"}
    rack = cliente.post(f"{API}/elementos", json={"tipo": "R", **ubicacion}).json()["codigo"]
    switch = cliente.post(
        f"{API}/elementos", json={"tipo": "SW", "padre_codigo": rack, **ubicacion}
    ).json()["codigo"]
    ap = cliente.post(
        f"{API}/elementos", json={"tipo": "AP", "padre_codigo": rack, **ubicacion}
    ).json()["codigo"]
    return rack, switch, ap


def test_equipo_montado_se_ubica_a_traves_de_su_rack(cliente):
    rack, switch, ap = _rack_con_switch_y_ap(cliente, "P13")
    plano = _cargar_plano(cliente, "P13")["id"]

    def ubicar(codigo):
        return cliente.patch(
            f"{API}/elementos/{codigo}/posicion",
            json={"plano_id": plano, "pos_x": 10, "pos_y": 10},
        )

    rechazo = ubicar(switch)
    assert rechazo.status_code == 400
    assert rack in rechazo.json()["detail"]
    # El AP solo se conecta al rack: se ubica donde realmente está.
    assert ubicar(ap).status_code == 200
    assert ubicar(rack).status_code == 200

    mapa = cliente.get(f"{API}/elementos/mapa?edificio=CADI&piso=P13").json()
    por_codigo = {e["codigo"]: e for e in mapa["elementos"]}
    assert por_codigo[switch]["montado"] is True
    assert por_codigo[switch]["ubicado"] is True
    assert por_codigo[ap]["montado"] is False
    assert mapa["sin_posicionar"] == 0

    detalle = cliente.get(f"{API}/elementos/{switch}").json()
    assert "coordenadas" not in {f["clave"] for f in detalle["completitud"]["faltantes"]}


def test_montado_no_admite_coordenadas_propias_pero_si_borrarlas(cliente):
    _, switch, _ = _rack_con_switch_y_ap(cliente, "P14")
    plano = _cargar_plano(cliente, "P14")["id"]

    con_coordenadas = cliente.patch(
        f"{API}/elementos/{switch}", json={"plano_id": plano, "pos_x": 5, "pos_y": 5}
    )
    assert con_coordenadas.status_code == 400

    sin_coordenadas = cliente.patch(
        f"{API}/elementos/{switch}", json={"plano_id": None, "pos_x": None, "pos_y": None}
    )
    assert sin_coordenadas.status_code == 200


def test_ficha_del_rack_lista_montados_antes_que_conectados(cliente):
    rack, switch, ap = _rack_con_switch_y_ap(cliente, "P15")

    hijos = cliente.get(f"{API}/elementos/{rack}").json()["hijos"]
    assert [(h["codigo"], h["montado"]) for h in hijos] == [(switch, True), (ap, False)]
    assert hijos[0]["tipo_nombre"] == "Switch"
    assert hijos[0]["color_estado"]


def test_elemento_se_dibuja_en_la_lamina_de_otro_tramo(cliente):
    _crear_piso_con_dos_tramos(cliente, "P16")
    ap = cliente.post(
        f"{API}/elementos", json={"tipo": "AP", "edificio": "CADI", "piso": "P16", "tramo": "T2"}
    ).json()["codigo"]
    lamina_t1 = _cargar_plano(cliente, "P16", "T1")["id"]
    lamina_t2 = _cargar_plano(cliente, "P16", "T2")["id"]

    def codigos(tramo):
        mapa = cliente.get(f"{API}/elementos/mapa?edificio=CADI&piso=P16&tramo={tramo}").json()
        return {e["codigo"] for e in mapa["elementos"]}

    assert ap in codigos("T2")
    detalle = cliente.patch(f"{API}/elementos/{ap}", json={"tramo_lamina": "T1"}).json()
    assert (detalle["tramo_codigo"], detalle["tramo_lamina_codigo"]) == ("T2", "T1")
    assert ap in codigos("T1") and ap not in codigos("T2")

    def ubicar(plano):
        return cliente.patch(
            f"{API}/elementos/{ap}/posicion", json={"plano_id": plano, "pos_x": 5, "pos_y": 5}
        )

    assert ubicar(lamina_t2).status_code == 400
    assert ubicar(lamina_t1).status_code == 200

    # Volver a su propia lámina borra la posición, que era sobre la otra.
    detalle = cliente.patch(f"{API}/elementos/{ap}", json={"tramo_lamina": "T2"}).json()
    assert detalle["tramo_lamina_codigo"] == "T2"
    assert detalle["pos_x"] is None and detalle["plano_id"] is None


def test_edicion_valida_y_normaliza_ip_y_mac(cliente):
    _crear_piso(cliente, "P17")
    codigo = cliente.post(
        f"{API}/elementos", json={"tipo": "SW", "edificio": "CADI", "piso": "P17"}
    ).json()["codigo"]

    ip_mala = cliente.patch(f"{API}/elementos/{codigo}", json={"direccion_ip": "10.0.0.300"})
    assert ip_mala.status_code == 422
    assert ip_mala.json()["detail"][0]["loc"][-1] == "direccion_ip"

    detalle = cliente.patch(
        f"{API}/elementos/{codigo}",
        json={"direccion_ip": " 10.34.0.20 ", "direccion_mac": "aa-bb-cc-dd-ee-0f"},
    ).json()
    assert (detalle["direccion_ip"], detalle["direccion_mac"]) == ("10.34.0.20", "AA:BB:CC:DD:EE:0F")

    # Un campo vaciado en el formulario llega como texto vacío: borra el dato.
    detalle = cliente.patch(f"{API}/elementos/{codigo}", json={"direccion_mac": ""}).json()
    assert detalle["direccion_mac"] is None


def test_cambiar_de_rack_exige_un_contenedor_del_mismo_piso(cliente):
    rack, _, ap = _rack_con_switch_y_ap(cliente, "P18")
    _, otro_rack_switch, _ = _rack_con_switch_y_ap(cliente, "P19")
    plano = _cargar_plano(cliente, "P18")["id"]
    suelto = cliente.post(
        f"{API}/elementos", json={"tipo": "SW", "edificio": "CADI", "piso": "P18"}
    ).json()["codigo"]
    cliente.patch(
        f"{API}/elementos/{suelto}/posicion", json={"plano_id": plano, "pos_x": 5, "pos_y": 5}
    )

    no_contenedor = cliente.patch(f"{API}/elementos/{suelto}", json={"padre_codigo": ap})
    assert no_contenedor.status_code == 400
    otro_piso = cliente.patch(
        f"{API}/elementos/{otro_rack_switch}", json={"padre_codigo": rack}
    )
    assert otro_piso.status_code == 400

    # Al montarlo en el rack deja de tener posición propia.
    detalle = cliente.patch(f"{API}/elementos/{suelto}", json={"padre_codigo": rack}).json()
    assert detalle["montado"] is True
    assert detalle["pos_x"] is None and detalle["plano_id"] is None


def test_monitoreo_actualiza_estado_con_token(cliente):
    _crear_piso(cliente, "P04")
    codigo = cliente.post(
        f"{API}/elementos",
        json={"tipo": "SW", "edificio": "CADI", "piso": "P04", "direccion_ip": "10.34.0.10"},
    ).json()["codigo"]

    sin_token = cliente.post(
        f"{API}/integraciones/monitoreo/estado", json={"codigo": codigo, "estado": "down"}
    )
    assert sin_token.status_code == 401

    respuesta = cliente.post(
        f"{API}/integraciones/monitoreo/estado",
        json={"codigo": codigo, "estado": "down", "minutos_caido": 30},
        headers={"X-NetDoc-Token": "token-de-prueba"},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["estado_operativo"] == "en_falla"

    historial = cliente.get(f"{API}/elementos/{codigo}/historial").json()
    assert any(h["origen"] == "monitoreo" for h in historial)


def test_monitoreo_respeta_el_mantenimiento_planificado(cliente):
    _crear_piso(cliente, "P04")
    codigo = cliente.post(
        f"{API}/elementos",
        json={"tipo": "SW", "edificio": "CADI", "piso": "P04", "estado_operativo": "en_mantenimiento"},
    ).json()["codigo"]

    respuesta = cliente.post(
        f"{API}/integraciones/monitoreo/estado",
        json={"codigo": codigo, "estado": "down", "minutos_caido": 120},
        headers={"X-NetDoc-Token": "token-de-prueba"},
    ).json()

    assert respuesta["actualizado"] is False
    assert respuesta["estado_operativo"] == "en_mantenimiento"


def test_filtros_de_listado(cliente):
    _crear_piso(cliente, "P03")
    cliente.post(
        f"{API}/elementos",
        json={"tipo": "SW", "edificio": "CADI", "piso": "P03", "etiqueta": "SW-CORE-BIOINFO"},
    )

    por_tipo = cliente.get(f"{API}/elementos?edificio=CADI&piso=P03&tipo=SW").json()
    assert por_tipo["total"] == 1

    por_busqueda = cliente.get(f"{API}/elementos?q=BIOINFO").json()
    assert por_busqueda["total"] == 1

    vacio = cliente.get(f"{API}/elementos?edificio=CADI&piso=P03&tipo=UPS").json()
    assert vacio["total"] == 0
