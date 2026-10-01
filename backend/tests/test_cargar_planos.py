"""Pruebas del script que carga las láminas desde data/<código>/planos."""

from __future__ import annotations

import pytest

from app.scripts.cargar_planos import cargar
from app.servicios.planos import (
    NOMENCLATURA,
    NombreLaminaInvalido,
    interpretar_nombre_lamina,
)

API = "/api/v1"

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200"><text id="a\x01">x</text></svg>'


def _svg(ancho: int, alto: int, texto: str = "x") -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ancho} {alto}">'
        f"<text>{texto}</text></svg>"
    ).encode()


@pytest.mark.parametrize(
    ("nombre", "esperado"),
    [
        ("cadi-p01-t1.svg", ("CADI", "P01", "T1", ".svg")),
        ("cadi-p04.svg", ("CADI", "P04", None, ".svg")),
        ("cadi-p00.svg", ("CADI", "P00", None, ".svg")),
        ("ING-P10-T3.SVG", ("ING", "P10", "T3", ".svg")),
        ("ing-p02-t12.png", ("ING", "P02", "T12", ".png")),
    ],
)
def test_nombre_estandar_dice_edificio_piso_y_tramo(nombre, esperado):
    lamina = interpretar_nombre_lamina(nombre)
    assert (lamina.edificio, lamina.piso, lamina.tramo, lamina.extension) == esperado


@pytest.mark.parametrize(
    ("nombre", "edificio", "sugerencia"),
    [
        # Como llegaron las láminas del CADI.
        ("cadi 1er piso tramo 1.svg", None, "cadi-p01-t1.svg"),
        ("cadi 1er piso  tramo 2.svg", None, "cadi-p01-t2.svg"),
        ("cadi 4to piso.svg", None, "cadi-p04.svg"),
        ("cadi subterraneo.svg", None, "cadi-p00.svg"),
        ("CADI Subterráneo tramo 1.svg", None, "cadi-p00-t1.svg"),
        # Casi estándar: piso de un dígito, tramo con cero, otros separadores.
        ("cadi-p1-t1.svg", None, "cadi-p01-t1.svg"),
        ("CADI_P01_T01.svg", None, "cadi-p01-t1.svg"),
        ("cadi p03.svg", None, "cadi-p03.svg"),
        # Sin el edificio en el nombre: se toma el de la carpeta.
        ("planta 2do piso.svg", "ING", "ing-p02.svg"),
        ("p01-t2.svg", "ING", "ing-p01-t2.svg"),
        ("p01-t2.svg", None, None),
        ("leyenda.svg", "ING", None),
        ("cadi-p01-t1", None, None),
    ],
)
def test_nombre_fuera_del_estandar_se_rechaza_con_sugerencia(nombre, edificio, sugerencia):
    with pytest.raises(NombreLaminaInvalido) as error:
        interpretar_nombre_lamina(nombre, edificio=edificio)
    assert error.value.sugerencia == sugerencia
    assert "no sigue la nomenclatura" in str(error.value)


def test_lamina_de_otro_edificio_se_rechaza_sin_sugerencia():
    with pytest.raises(NombreLaminaInvalido) as error:
        interpretar_nombre_lamina("ing-p01-t1.svg", edificio="CADI")
    assert str(error.value) == "«ing-p01-t1.svg» es una lámina del edificio ING, no de CADI"
    assert error.value.sugerencia is None


def test_carga_solo_las_laminas_pendientes(cliente, sesion, tmp_path):
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": "P12", "orden": 12})
    cliente.post(f"{API}/edificios/CADI/pisos/P12/tramos", json={"codigo": "T1"})
    (tmp_path / "cadi-p12-t1.svg").write_bytes(SVG)
    (tmp_path / "cadi-p99.svg").write_bytes(SVG)

    resultado = cargar(sesion, tmp_path, "CADI")
    sesion.commit()
    assert (resultado.nuevos, resultado.actualizados) == (1, 0)
    assert resultado.omitidos == ["«cadi-p99.svg»: el piso P99 no existe en el sistema"]

    plano = cliente.get(f"{API}/edificios/CADI/pisos/P12/plano?tramo=T1").json()
    assert (plano["ancho_px"], plano["alto_px"]) == (300, 200)
    assert b"\x01" not in cliente.get(f"/media/{plano['archivo']}").content

    # Una segunda pasada no duplica el plano ya vigente.
    resultado = cargar(sesion, tmp_path, "CADI")
    assert (resultado.nuevos, resultado.actualizados) == (0, 0)


def test_la_carpeta_solo_carga_laminas_con_la_nomenclatura(cliente, sesion, tmp_path):
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": "P33", "orden": 33})
    (tmp_path / "cadi 33vo piso.svg").write_bytes(SVG)
    (tmp_path / "ing-p33.svg").write_bytes(SVG)
    (tmp_path / "cadi-p33.pdf").write_bytes(b"%PDF")
    (tmp_path / "leyenda.svg").write_bytes(SVG)
    # Se ignoran: lo que deja preparar_laminas, Windows y los ocultos.
    (tmp_path / "originales").mkdir()
    (tmp_path / "originales" / "cadi 33vo piso.svg").write_bytes(SVG)
    (tmp_path / "cadi-p33.svg:Zone.Identifier").write_bytes(b"[ZoneTransfer]")
    (tmp_path / ".cadi-p33.svg.swp").write_bytes(b"")

    resultado = cargar(sesion, tmp_path, "CADI")
    assert (resultado.nuevos, resultado.renombrables) == (0, 1)
    fuera = "no sigue la nomenclatura " + NOMENCLATURA
    assert resultado.omitidos == [
        f"«cadi 33vo piso.svg» {fuera}: renómbrela «cadi-p33.svg»",
        "«cadi-p33.pdf»: desde la carpeta solo se cargan láminas SVG (guía, sección 4)",
        "«ing-p33.svg» es una lámina del edificio ING, no de CADI",
        f"«leyenda.svg» {fuera}",
    ]

    (tmp_path / "cadi 33vo piso.svg").rename(tmp_path / "cadi-p33.svg")
    resultado = cargar(sesion, tmp_path, "CADI")
    sesion.commit()
    assert resultado.nuevos == 1
    plano = cliente.get(f"{API}/edificios/CADI/pisos/P33/plano").json()
    assert plano["nombre"] == "CADI P33 · Piso completo"
    assert plano["archivo"] == "planos/CADI-P33-v1.svg"


def _piso_con_elementos_ubicados(cliente, sesion, carpeta, codigo_piso, lamina):
    """Piso con un tramo, su lámina cargada y dos elementos ubicados en ella."""
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": codigo_piso, "orden": 30})
    cliente.post(f"{API}/edificios/CADI/pisos/{codigo_piso}/tramos", json={"codigo": "T1"})
    (carpeta / lamina).write_bytes(_svg(300, 200))
    cargar(sesion, carpeta, "CADI")
    sesion.commit()
    plano = cliente.get(f"{API}/edificios/CADI/pisos/{codigo_piso}/plano?tramo=T1").json()
    codigos = []
    for x in (40, 250):
        codigo = cliente.post(
            f"{API}/elementos",
            json={"tipo": "AP", "edificio": "CADI", "piso": codigo_piso, "tramo": "T1"},
        ).json()["codigo"]
        respuesta = cliente.patch(
            f"{API}/elementos/{codigo}/posicion",
            json={"plano_id": plano["id"], "pos_x": x, "pos_y": 100},
        )
        assert respuesta.status_code == 200, respuesta.text
        codigos.append(codigo)
    return plano, codigos


def test_lamina_modificada_del_mismo_tamano_conserva_las_posiciones(cliente, sesion, tmp_path):
    lamina = "cadi-p30-t1.svg"
    anterior, codigos = _piso_con_elementos_ubicados(cliente, sesion, tmp_path, "P30", lamina)

    (tmp_path / lamina).write_bytes(_svg(300, 200, "corregida"))
    resultado = cargar(sesion, tmp_path, "CADI")
    sesion.commit()
    assert (resultado.nuevos, resultado.actualizados) == (0, 1)
    assert resultado.sin_ubicar == {}

    nuevo = cliente.get(f"{API}/edificios/CADI/pisos/P30/plano?tramo=T1").json()
    assert nuevo["id"] != anterior["id"]
    for codigo, x in zip(codigos, (40, 250), strict=True):
        elemento = cliente.get(f"{API}/elementos/{codigo}").json()
        assert (elemento["plano_id"], elemento["pos_x"], elemento["pos_y"]) == (nuevo["id"], x, 100)

    # Sin cambios en el archivo, la siguiente pasada no hace nada.
    assert cargar(sesion, tmp_path, "CADI").actualizados == 0


def test_lamina_de_otro_tamano_deja_los_elementos_sin_ubicar(cliente, sesion, tmp_path):
    lamina = "cadi-p31-t1.svg"
    anterior, codigos = _piso_con_elementos_ubicados(cliente, sesion, tmp_path, "P31", lamina)

    (tmp_path / lamina).write_bytes(_svg(800, 600))
    resultado = cargar(sesion, tmp_path, "CADI")
    sesion.commit()
    assert resultado.actualizados == 1
    assert resultado.sin_ubicar == {"CADI P31 · Tramo 1": sorted(codigos)}

    for codigo in codigos:
        elemento = cliente.get(f"{API}/elementos/{codigo}").json()
        assert (elemento["plano_id"], elemento["pos_x"], elemento["pos_y"]) == (None, None, None)
    # Las coordenadas anteriores quedan en el historial.
    historial = cliente.get(f"{API}/elementos/{codigos[0]}/historial").json()
    anteriores = {h["campo"]: h["valor_anterior"] for h in historial if h["origen"] == "sistema"}
    assert anteriores == {"plano_id": str(anterior["id"]), "pos_x": "40.0", "pos_y": "100.0"}

    mapa = cliente.get(f"{API}/elementos/mapa?edificio=CADI&piso=P31&tramo=T1").json()
    assert (mapa["plano"]["ancho_px"], mapa["plano"]["alto_px"]) == (800, 600)
    assert mapa["sin_posicionar"] == 2


def test_no_reemplaza_una_version_subida_despues_desde_el_visor(cliente, sesion, tmp_path):
    lamina = "cadi-p32-t1.svg"
    _, codigos = _piso_con_elementos_ubicados(cliente, sesion, tmp_path, "P32", lamina)
    subida = cliente.post(
        f"{API}/edificios/CADI/pisos/P32/plano",
        files={"archivo": ("cadi-p32-t1.svg", _svg(300, 200, "desde el visor"), "image/svg+xml")},
        data={"ancho_px": "300", "alto_px": "200", "tramo": "T1"},
    ).json()
    # La carga por la API también traslada las posiciones (mismo tamaño).
    assert cliente.get(f"{API}/elementos/{codigos[0]}").json()["plano_id"] == subida["id"]

    # El archivo de la carpeta es el de la versión anterior: no se vuelve a él.
    resultado = cargar(sesion, tmp_path, "CADI")
    assert (resultado.nuevos, resultado.actualizados) == (0, 0)
    vigente = cliente.get(f"{API}/edificios/CADI/pisos/P32/plano?tramo=T1").json()
    assert vigente["id"] == subida["id"]
