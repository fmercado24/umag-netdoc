"""Teselas de los planos: la lámina pre-dibujada para que el visor se mueva fluido."""

from __future__ import annotations

import pytest

from app.core.config import configuracion
from app.servicios.teselas import (
    asegurar_teselas,
    dir_teselas,
    generar_teselas,
    leer_teselas,
    zoom_maximo,
)

API = "/api/v1"

SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 300 200">'
    b'<rect width="300" height="200" fill="white"/>'
    b'<rect x="0" y="0" width="10" height="10" fill="red"/></svg>'
)


@pytest.fixture
def con_teselas(monkeypatch):
    monkeypatch.setattr(configuracion, "teselas", True)


@pytest.mark.parametrize(
    ("ancho_px", "zoom"),
    [
        (2854, 2),  # láminas del CADI: ~11 400 px en el nivel más detallado
        (6740, 0),
        (300, 4),  # tope: 16 px por unidad
        (100_000, -2),  # tope: 1/4 de px por unidad
    ],
)
def test_zoom_maximo_apunta_a_unos_doce_mil_pixeles(ancho_px, zoom):
    assert zoom_maximo(ancho_px) == zoom


def test_genera_la_piramide_alineada_con_las_unidades_del_plano():
    import pyvips

    archivo = "planos/PRUEBA-P01-v1.svg"
    (configuracion.dir_media / archivo).write_bytes(SVG)
    info = generar_teselas(archivo, 300)

    # 300 unidades a 16 px por unidad: 4800 px, 19 teselas → 6 niveles.
    assert (info.zoom_max, info.niveles, info.tamano) == (4, 6, 256)
    assert info.url == "teselas/PRUEBA-P01-v1/{z}/{y}/{x}.webp"
    assert leer_teselas(archivo) == info
    carpeta = dir_teselas(archivo)
    assert not carpeta.with_name(carpeta.name + ".generando").exists()

    # El width/height del SVG (600×400) no cuenta: cada unidad del viewBox
    # mide 2**zoom_max píxeles, así que el cuadro rojo de 10 unidades ocupa
    # 160 px desde la esquina superior izquierda de la primera tesela.
    tesela = pyvips.Image.new_from_file(str(carpeta / "5" / "0" / "0.webp"))
    assert tesela.getpoint(150, 150)[:3] == pytest.approx([255, 0, 0], abs=40)
    assert tesela.getpoint(170, 170)[:3] == pytest.approx([255, 255, 255], abs=40)
    # Y hay tesela para todo el plano, aunque esté en blanco.
    assert (carpeta / "5" / "12" / "18.webp").exists()


def test_una_imagen_no_se_agranda_mas_alla_de_su_resolucion():
    import pyvips

    archivo = "planos/PRUEBA-P02-v1.png"
    pyvips.Image.black(400, 200).invert().write_to_file(str(configuracion.dir_media / archivo))
    # 100 unidades en 400 px: el nivel más detallado es su resolución propia.
    assert generar_teselas(archivo, 100).zoom_max == 2


def test_api_entrega_las_teselas_del_plano(cliente, con_teselas):
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": "P34", "orden": 34})
    respuesta = cliente.post(
        f"{API}/edificios/CADI/pisos/P34/plano",
        files={"archivo": ("cadi-p34.svg", SVG, "image/svg+xml")},
        data={"ancho_px": "300", "alto_px": "200"},
    )
    assert respuesta.status_code == 201, respuesta.text
    # Se generan después de responder (en la prueba, antes de volver).
    plano = cliente.get(f"{API}/edificios/CADI/pisos/P34/plano").json()
    assert plano["teselas"]["zoom_max"] == 4
    assert cliente.get(f"/media/{plano['teselas']['url'].format(z=0, x=0, y=0)}").status_code == 200


def test_sin_teselas_el_plano_se_muestra_igual(cliente, con_teselas):
    # Un archivo que libvips no sabe leer: el visor usa la lámina original.
    archivo = "planos/PRUEBA-P03-v1.png"
    (configuracion.dir_media / archivo).write_bytes(b"no es un png")
    assert asegurar_teselas(archivo, 100) is None
    assert leer_teselas(archivo) is None


def test_desactivadas_no_se_generan(monkeypatch):
    monkeypatch.setattr(configuracion, "teselas", False)
    archivo = "planos/PRUEBA-P04-v1.svg"
    (configuracion.dir_media / archivo).write_bytes(SVG)
    assert asegurar_teselas(archivo, 300) is None
    assert not dir_teselas(archivo).exists()
