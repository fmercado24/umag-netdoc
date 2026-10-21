"""Recintos de las láminas y ubicación automática de los elementos."""

from __future__ import annotations

import pytest

from app.scripts import cargar_planos, importar_edificio
from app.scripts.extraer_recintos import (
    Lectura,
    como_numero,
    es_el_numero_esperado,
    interpretar_lecturas,
    interpretar_racks,
)
from app.servicios.planos import quitar_caracteres_de_control
from app.servicios.recintos import (
    SEPARACION,
    FilaRecinto,
    escribir_recintos,
    huella_lamina,
    leer_recintos,
    normalizar_numero,
    numero_de_recinto,
    similitud,
)

API = "/api/v1"
ENCABEZADO = "Elemento,Etiqueta,Tipo,Ubicación,Estado Operativo,Estado Condición,Notas,Rack,Foto\n"
ENCABEZADO_PD = (
    "Elemento,Etiqueta,Tipo,Ubicación (Hacia dónde va el cable),Estado Operativo,"
    "Estado Condición,Notas\n"
)
ANCHO, ALTO = 1000, 800


def _al_lado(x: float, pasos: int = 1) -> float:
    """Donde va un equipo junto al centro de un recinto (ver DESPLAZAMIENTOS)."""
    return round(x + pasos * ANCHO * SEPARACION, 1)


@pytest.mark.parametrize(
    ("texto", "piso", "esperado"),
    [
        ("Oficina 1083", "P01", "1083"),
        ("oficina 1083.2", "P01", "1083.2"),
        ("Oficina 1083,2", "P01", "1083.2"),
        # Dos números: vale el del piso.
        ("Oficina 1039/2018", "P01", "1039"),
        ("Box Oficina 8 1047", "P01", "1047"),
        ("Sala 3 0019", "P00", "0019"),
        ("Exclusa 0017", "P00", "0017"),
        # 2022 es un recinto del segundo piso: en el tercero es un error.
        ("Box Fisiopatología 2022", "P03", None),
        ("Sala Eléctrica", "P02", None),
        ("Bodega 12345", "P01", None),
        ("Sala 1001", "PXX", None),
        (None, "P01", None),
    ],
)
def test_numero_de_recinto_es_el_del_piso(texto, piso, esperado):
    assert numero_de_recinto(texto, piso) == esperado


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("1083", "1083"), (" 1083,2 ", "1083.2"), ("0017", "0017"), ("108", None), ("sala", None)],
)
def test_normalizar_numero(valor, esperado):
    assert normalizar_numero(valor) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("1082", "1082"), ("OO17", "0017"), ("1O8l", "1081"), ("1083.2", "1083.2"), ("D02", None), ("12.8", None)],
)
def test_como_numero_corrige_las_confusiones_del_ocr(texto, esperado):
    assert como_numero(texto) == esperado


@pytest.mark.parametrize(
    ("planilla", "lamina", "esperado"),
    [
        # El OCR equivoca letras: igual son el mismo recinto.
        ("Administración Oficina Médica 3006", "ADMNISTRACIQN OFIQINA MEICA", 1.0),
        ("Sala de Reuniones 3029", "REUNIOINES", 0.5),
        ("Recepción 1063", "SECRETARÍA RECEPCIÓN", 0.5),
        ("Sala Eléctrica", "SALA DE LAVADO", 1 / 3),
        ("Box 1 1025", "BAÑO", 0.0),
        (None, "OFICINA", 0.0),
    ],
)
def test_similitud_de_nombres_tolera_errores_del_ocr(planilla, lamina, esperado):
    assert similitud(planilla, lamina) == pytest.approx(esperado)


def _lectura(texto, x, y, ancho=15, alto=6):
    return Lectura(texto, x, y, x + ancho, y + alto)


def test_interpretar_lecturas_toma_nombre_numero_y_punto_bajo_el_rotulo():
    lecturas = [
        _lectura("SECRETARÍA", 92, 100, ancho=40),
        _lectura("RECEPCIÓN", 94, 108, ancho=36),
        _lectura("1082", 104, 116),
        # La misma lectura desde el pedazo vecino y un rótulo repetido al lado.
        _lectura("1082", 104.5, 116),
        _lectura("SALA", 300, 300, ancho=20),
        _lectura("1060", 302, 308),
        _lectura("1060", 318, 309),
        # Del segundo piso, una cota de otro tamaño y un rótulo de punto de datos.
        _lectura("2015", 500, 500),
        _lectura("1999", 600, 600, alto=20),
        _lectura("D02", 700, 700),
    ]
    recintos, avisos = interpretar_lecturas(lecturas, "P01")

    por_numero = {r.numero: r for r in recintos}
    assert set(por_numero) == {"1082", "1060"}
    recepcion = por_numero["1082"]
    assert recepcion.nombre == "SECRETARÍA RECEPCIÓN"
    # Centrado bajo el número, a un alto de rótulo de distancia.
    assert (recepcion.x, recepcion.y) == (111.8, 128.0)
    assert por_numero["1060"].nombre == "SALA"
    assert avisos == []


def test_un_numero_repetido_lejos_se_resuelve_con_los_nombres_de_las_planillas():
    lecturas = [
        _lectura("FECHA", 900, 700, ancho=25),
        _lectura("2019", 902, 708),
        _lectura("BOX DE ATENCION 2", 100, 100, ancho=60),
        _lectura("2019", 120, 108),
    ]
    recintos, avisos = interpretar_lecturas(
        lecturas, "P02", {"2019": {"Box de atención 2 2019"}}
    )
    assert [(r.numero, r.nombre) for r in recintos] == [("2019", "BOX DE ATENCION 2")]
    assert "aparece 2 veces" in avisos[0]


def test_rotulos_de_racks():
    lecturas = [
        _lectura("RACK 08", 100, 100, ancho=30),
        _lectura("RACK 08", 100.5, 100, ancho=30),
        _lectura("Rack 11", 300, 300, ancho=28),
        _lectura("RACK 1O", 500, 500, ancho=30),
        # La simbología y un rótulo sin número no son racks.
        _lectura("RACK DE COMUNICACIONES", 700, 700, ancho=90),
        _lectura("RACK", 800, 800, ancho=20),
    ]
    racks, avisos = interpretar_racks(lecturas)
    assert [(r.numero, r.nombre, r.x, r.y) for r in racks] == [
        ("R08", "RACK 08", 115.2, 103.0),
        ("R10", "RACK 10", 515.0, 503.0),
        ("R11", "RACK 11", 314.0, 303.0),
    ]
    assert avisos == []


@pytest.mark.parametrize(
    ("texto", "esperado", "resultado"),
    [
        ("1061", "1061", True),
        # Lo que deja leer la X que cruza el rótulo «HALL 1061».
        ("161", "1061", True),
        ("TQ61", "1061", True),
        ("1062", "1061", False),
        ("61", "1061", False),
        ("10611", "1061", False),
    ],
)
def test_releer_acepta_solo_el_numero_esperado(texto, esperado, resultado):
    assert es_el_numero_esperado(texto, esperado) is resultado


def test_csv_de_recintos_ida_y_vuelta(tmp_path):
    ruta = tmp_path / "ing-recintos.csv"
    filas = [
        FilaRecinto("ing-p01.svg", "1020", "OFICINA", 500.0, 400.0, "abc"),
        FilaRecinto("ing-p01.svg", "1010", None, 100.25, 100.0, "abc"),
    ]
    escribir_recintos(ruta, filas)
    leidas, avisos = leer_recintos(ruta)
    assert avisos == []
    assert [(f.numero, f.nombre, f.x) for f in leidas] == [
        ("1010", None, 100.2),
        ("1020", "OFICINA", 500.0),
    ]

    with ruta.open("a", encoding="utf-8") as archivo:
        archivo.write("ing-p01.svg,sala,,1,2,abc\n")
    assert "ilegible" in leer_recintos(ruta)[1][0]


# --------------------------------------------------------------------------
# De punta a punta: planillas + lámina + recintos → elementos ubicados
# --------------------------------------------------------------------------
def _lamina(carpeta, nombre, texto="plano"):
    carpeta.mkdir(parents=True, exist_ok=True)
    contenido = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ANCHO} {ALTO}">'
        f"<text>{texto}</text></svg>"
    ).encode()
    (carpeta / nombre).write_bytes(contenido)
    return huella_lamina(quitar_caracteres_de_control(contenido))


def _edificio_con_recintos(tmp_path, codigo="CERE"):
    prefijo = codigo.lower()
    (tmp_path / f"{prefijo}-p01.csv").write_text(
        ENCABEZADO
        + "Rack 24U,RACK-01,Racks,Sala de Comunicaciones 1010,Operativo,Excelente,,Rack-01,\n"
        + "Cisco CBS250,SW-A,Switches,Sala de Comunicaciones 1010,Operativo,Excelente,,Rack-01,\n"
        + "UniFi AP,AP-01,Access Points,Pasillo 1012,Operativo,Excelente,,Rack-01,\n"
        + "Tripp Lite,UPS-1,UPS,Bodega,Operativo,Excelente,,,\n",
        encoding="utf-8",
    )
    (tmp_path / f"{prefijo}-puntos-de-datos.csv").write_text(
        ENCABEZADO_PD
        + "Roseta Oficina 1020,P01-R1-D01,Punto de datos,Piso 1,Operativo,Excelente,\n"
        + "Roseta Oficina 1020,P01-R1-D02,Punto de datos,Piso 1,Operativo,Excelente,\n"
        + "Roseta Oficina 1020,P01-R1-T01,Punto de datos,Piso 1,Operativo,Excelente,\n"
        + "Roseta Laboratorio 1030.2,P01-R1-D03,Punto de datos,Piso 1,Operativo,Excelente,\n"
        + "Roseta Recepción 1099,P01-R1-D04,Punto de datos,Piso 1,Operativo,Excelente,\n",
        encoding="utf-8",
    )
    huella = _lamina(tmp_path / "planos", f"{prefijo}-p01.svg")
    escribir_recintos(
        tmp_path / f"{prefijo}-recintos.csv",
        [
            FilaRecinto(f"{prefijo}-p01.svg", "1010", "SALA DE COMUNICACIONES", 100, 100, huella),
            FilaRecinto(f"{prefijo}-p01.svg", "1012", "PASILLO", 300, 100, huella),
            FilaRecinto(f"{prefijo}-p01.svg", "1020", "OFICINA", 500, 400, huella),
            FilaRecinto(f"{prefijo}-p01.svg", "1030", "LABORATORIO", 700, 600, huella),
            FilaRecinto(f"{prefijo}-p01.svg", "1050", "SECRETARÍA RECEPCIÓN", 800, 700, huella),
        ],
    )
    importar_edificio.main([codigo, "--datos", str(tmp_path)])
    cargar_planos.main([codigo, "--planos", str(tmp_path / "planos")])


def _posiciones(cliente, codigo="CERE"):
    mapa = cliente.get(f"{API}/elementos/mapa", params={"edificio": codigo, "piso": "P01"}).json()
    return {
        e["codigo"]: (e["pos_x"], e["pos_y"]) if e["ubicado"] else None
        for e in mapa["elementos"]
        if not e["montado"]
    }


def test_al_cargar_la_lamina_cada_elemento_queda_en_su_recinto(cliente, tmp_path, capsys):
    _edificio_con_recintos(tmp_path)
    salida = capsys.readouterr().out
    posiciones = _posiciones(cliente)

    # Los puntos de datos de la oficina, en el mismo punto: el visor los agrupa.
    for codigo in ("CERE-PD-P01-R01-D01", "CERE-PD-P01-R01-D02", "CERE-PD-P01-R01-T01"):
        assert posiciones[codigo] == (500, 400)
    # El rack, al lado del centro del recinto; el AP conectado, en su pasillo.
    assert posiciones["CERE-R01-P01"] == (_al_lado(100), 100)
    assert posiciones["CERE-AP01-P01"] == (_al_lado(300), 100)
    # Una subdivisión sin rótulo propio cae en su sala.
    assert posiciones["CERE-PD-P01-R01-D03"] == (700, 600)
    # Sin número, o con uno que no está en la lámina: sin ubicar y en el informe.
    assert posiciones["CERE-UPS01-P01"] is None
    assert posiciones["CERE-PD-P01-R01-D04"] is None
    assert "Ubicados en su recinto: 6" in salida
    assert "«Bodega»: CERE-UPS01-P01" in salida
    assert "«Recepción 1099»: CERE-PD-P01-R01-D04 → en la lámina: 1050 (SECRETARÍA RECEPCIÓN)" in salida

    switch = cliente.get(f"{API}/elementos/CERE-SW01-P01").json()
    assert switch["montado"] and switch["numero_recinto"] == "1010"
    rack = cliente.get(f"{API}/elementos/CERE-R01-P01").json()
    assert rack["recinto_en_plano"]["nombre"] == "SALA DE COMUNICACIONES"
    historial = cliente.get(f"{API}/elementos/CERE-R01-P01/historial").json()
    assert any("recinto 1010 (SALA DE COMUNICACIONES)" in (h["comentario"] or "") for h in historial)

    recintos = cliente.get(f"{API}/edificios/CERE/pisos/P01/recintos").json()
    assert [r["numero"] for r in recintos] == ["1010", "1012", "1020", "1030", "1050"]

    # Arrancar de nuevo no mueve nada: lo ubicado conserva su lugar.
    cargar_planos.main(["CERE", "--planos", str(tmp_path / "planos")])
    assert _posiciones(cliente) == posiciones


def test_completar_el_numero_en_el_visor_lo_ubica(cliente, tmp_path):
    _edificio_con_recintos(tmp_path, "PAT")

    respuesta = cliente.patch(f"{API}/elementos/PAT-UPS01-P01", json={"numero_recinto": "1010"})
    assert respuesta.status_code == 200, respuesta.text
    ups = respuesta.json()
    # El primer lugar junto al rack ya está ocupado: va al otro lado.
    assert (ups["pos_x"], ups["pos_y"]) == (_al_lado(100, -1), 100)
    assert ups["recinto_en_plano"]["numero"] == "1010"

    # Una ubicación con su número también sirve.
    pd = cliente.patch(
        f"{API}/elementos/PAT-PD-P01-R01-D04", json={"ubicacion_descriptiva": "Laboratorio 1030"}
    ).json()
    assert (pd["numero_recinto"], pd["pos_x"], pd["pos_y"]) == ("1030", 700, 600)

    # Un número que no es del piso se rechaza junto al campo.
    error = cliente.patch(f"{API}/elementos/PAT-UPS01-P01", json={"numero_recinto": "2010"})
    assert error.status_code == 422
    assert error.json()["detail"][0]["loc"] == ["body", "numero_recinto"]

    # Uno del piso que no está en las láminas conserva la posición y la ficha avisa.
    otro = cliente.patch(f"{API}/elementos/PAT-UPS01-P01", json={"numero_recinto": "1077"}).json()
    assert (otro["pos_x"], otro["recinto_en_plano"]) == (_al_lado(100, -1), None)


def test_ubicar_en_su_recinto_lo_devuelve_tras_moverlo_a_mano(cliente, tmp_path):
    _edificio_con_recintos(tmp_path, "DSI")
    rack = cliente.get(f"{API}/elementos/DSI-R01-P01").json()
    cliente.patch(
        f"{API}/elementos/DSI-R01-P01/posicion",
        json={"plano_id": rack["plano_id"], "pos_x": 20, "pos_y": 30},
    )

    de_vuelta = cliente.post(f"{API}/elementos/DSI-R01-P01/ubicar-en-recinto").json()
    assert (de_vuelta["pos_x"], de_vuelta["pos_y"]) == (_al_lado(100), 100)

    sin_numero = cliente.post(f"{API}/elementos/DSI-UPS01-P01/ubicar-en-recinto")
    assert sin_numero.status_code == 400
    montado = cliente.post(f"{API}/elementos/DSI-SW01-P01/ubicar-en-recinto")
    assert montado.status_code == 400


def test_recintos_de_otra_version_de_la_lamina_no_se_usan(cliente, tmp_path, capsys):
    (tmp_path / "ciga-p01.csv").write_text(
        ENCABEZADO + "Rack 24U,RACK-01,Racks,Sala 1010,Operativo,Excelente,,Rack-01,\n",
        encoding="utf-8",
    )
    _lamina(tmp_path / "planos", "ciga-p01.svg", texto="versión nueva")
    escribir_recintos(
        tmp_path / "ciga-recintos.csv",
        [FilaRecinto("ciga-p01.svg", "1010", "SALA", 100, 100, "huella-de-otra")],
    )
    importar_edificio.main(["CIGA", "--datos", str(tmp_path)])
    cargar_planos.main(["CIGA", "--planos", str(tmp_path / "planos")])

    salida = capsys.readouterr().out
    assert "se leyó de otra versión de «ciga-p01.svg»" in salida
    assert "python -m app.scripts.extraer_recintos CIGA" in salida
    assert cliente.get(f"{API}/edificios/CIGA/pisos/P01/recintos").json() == []
    assert _posiciones(cliente, "CIGA") == {"CIGA-R01-P01": None}


def test_rack_sobre_su_rotulo_y_lo_de_su_sala_junto_a_el(cliente, tmp_path, capsys):
    # La sala eléctrica no tiene número en la lámina, pero el rack sí está rotulado.
    (tmp_path / "vraf-p01.csv").write_text(
        ENCABEZADO
        + "RACK-05,RACK-05,Racks,Sala Eléctrica,Operativo,Excelente,,Rack-05,\n"
        + "EdgeSwitch24,SW-COM,Switches,Sala Eléctrica,Operativo,Excelente,,Rack-05,\n"
        + "UniFi AP,AP-01,Access Points,Sala Eléctrica,Operativo,Excelente,,Rack-05,\n"
        + "Tripp Lite,UPS-1,UPS,Sala Eléctrica,Operativo,Excelente,,,\n"
        + "Tripp Lite,UPS-2,UPS,Bodega,Operativo,Excelente,,,\n",
        encoding="utf-8",
    )
    huella = _lamina(tmp_path / "planos", "vraf-p01.svg")
    escribir_recintos(
        tmp_path / "vraf-recintos.csv",
        [
            FilaRecinto("vraf-p01.svg", "R05", "RACK 05", 400, 300, huella),
            FilaRecinto("vraf-p01.svg", "1010", "OFICINA", 100, 100, huella),
        ],
    )
    importar_edificio.main(["VRAF", "--datos", str(tmp_path)])
    capsys.readouterr()
    cargar_planos.main(["VRAF", "--planos", str(tmp_path / "planos")])
    salida = capsys.readouterr().out

    posiciones = _posiciones(cliente, "VRAF")
    assert posiciones["VRAF-R05-P01"] == (400, 300)
    # El AP conectado al rack y la UPS de la misma sala, a sus lados.
    assert posiciones["VRAF-AP01-P01"] == (_al_lado(400), 300)
    assert posiciones["VRAF-UPS01-P01"] == (_al_lado(400, -1), 300)
    assert posiciones["VRAF-UPS02-P01"] is None
    assert "Ubicados en su recinto: 1" in salida
    assert "Ubicados junto a otro elemento de su sala, que no tiene número en la lámina: 2" in salida

    rack = cliente.get(f"{API}/elementos/VRAF-R05-P01").json()
    assert rack["recinto_en_plano"]["numero"] == "R05"
    historial = cliente.get(f"{API}/elementos/VRAF-UPS01-P01/historial").json()
    assert any("junto a VRAF-R05-P01" in (h["comentario"] or "") for h in historial)


def test_un_punto_de_datos_nuevo_se_suma_al_grupo_de_su_sala(cliente, tmp_path):
    _edificio_con_recintos(tmp_path, "CAS")
    # Se vuelve a leer la lámina y el punto de la oficina 1020 se corre un poco.
    ruta = tmp_path / "cas-recintos.csv"
    filas, _ = leer_recintos(ruta)
    escribir_recintos(
        ruta, [f if f.numero != "1020" else f.__class__(**{**f.__dict__, "x": 500.4}) for f in filas]
    )
    # Llega un punto de datos más de esa oficina.
    with (tmp_path / "cas-puntos-de-datos.csv").open("a", encoding="utf-8") as archivo:
        archivo.write("Roseta Oficina 1020,P01-R1-D09,Punto de datos,Piso 1,Operativo,Excelente,\n")
    importar_edificio.main(["CAS", "--datos", str(tmp_path), "--agregar"])

    recintos = cliente.get(f"{API}/edificios/CAS/pisos/P01/recintos").json()
    assert next(r for r in recintos if r["numero"] == "1020")["pos_x"] == 500.4
    posiciones = _posiciones(cliente, "CAS")
    assert posiciones["CAS-PD-P01-R01-D09"] == posiciones["CAS-PD-P01-R01-D01"] == (500, 400)


def test_al_ubicar_a_mano_un_rack_lo_de_su_sala_queda_junto_a_el(cliente, tmp_path):
    # Ni la sala ni el rack se leyeron en la lámina: quedan esperando.
    (tmp_path / "feum-p01.csv").write_text(
        ENCABEZADO
        + "RACK-08,RACK-08,Racks,Sala Eléctrica 1083,Operativo,Excelente,,Rack-08,\n"
        + "UniFi AP,AP-01,Access Points,Sala Eléctrica 1083,Operativo,Excelente,,Rack-08,\n",
        encoding="utf-8",
    )
    huella = _lamina(tmp_path / "planos", "feum-p01.svg")
    escribir_recintos(
        tmp_path / "feum-recintos.csv", [FilaRecinto("feum-p01.svg", "1010", "OFICINA", 100, 100, huella)]
    )
    importar_edificio.main(["FEUM", "--datos", str(tmp_path)])
    cargar_planos.main(["FEUM", "--planos", str(tmp_path / "planos")])
    assert _posiciones(cliente, "FEUM") == {"FEUM-R08-P01": None, "FEUM-AP01-P01": None}

    plano_id = cliente.get(f"{API}/elementos/mapa", params={"edificio": "FEUM", "piso": "P01"}).json()["plano"]["id"]
    cliente.patch(
        f"{API}/elementos/FEUM-R08-P01/posicion", json={"plano_id": plano_id, "pos_x": 600, "pos_y": 500}
    )
    assert _posiciones(cliente, "FEUM") == {
        "FEUM-R08-P01": (600, 500),
        "FEUM-AP01-P01": (_al_lado(600), 500),
    }
