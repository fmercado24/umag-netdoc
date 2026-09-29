"""Pruebas del script que carga las láminas del CADI desde data/cadi/planos."""

from __future__ import annotations

import pytest

from app.scripts.cargar_planos import cargar, ubicar_lamina

API = "/api/v1"

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200"><text id="a\x01">x</text></svg>'


@pytest.mark.parametrize(
    ("nombre", "esperado"),
    [
        ("cadi 1er piso tramo 1.svg", ("P01", "T1")),
        ("cadi 1er piso  tramo 2.svg", ("P01", "T2")),
        ("cadi 2do piso tramo 2.svg", ("P02", "T2")),
        ("cadi 4to piso.svg", ("P04", None)),
        ("cadi subterraneo.svg", ("P00", None)),
        ("CADI Subterráneo tramo 1.svg", ("P00", "T1")),
        ("leyenda.svg", None),
        # Forma compacta, como las planillas.
        ("ing-p01-t2.svg", ("P01", "T2")),
        ("ing-p04.svg", ("P04", None)),
        ("ing-p00.svg", ("P00", None)),
        ("ING-P10-T3.svg", ("P10", "T3")),
    ],
)
def test_ubicar_lamina_por_nombre(nombre, esperado):
    assert ubicar_lamina(nombre) == esperado


def test_carga_solo_las_laminas_pendientes(cliente, sesion, tmp_path):
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": "P12", "orden": 12})
    cliente.post(f"{API}/edificios/CADI/pisos/P12/tramos", json={"codigo": "T1"})
    (tmp_path / "cadi 12vo piso tramo 1.svg").write_bytes(SVG)
    (tmp_path / "cadi 99vo piso.svg").write_bytes(SVG)

    cargados, omitidos = cargar(sesion, tmp_path, "CADI")
    sesion.commit()
    assert cargados == 1
    assert omitidos == ["cadi 99vo piso.svg: el piso P99 no existe en el sistema"]

    plano = cliente.get(f"{API}/edificios/CADI/pisos/P12/plano?tramo=T1").json()
    assert (plano["ancho_px"], plano["alto_px"]) == (300, 200)
    assert b"\x01" not in cliente.get(f"/media/{plano['archivo']}").content

    # Una segunda pasada no duplica el plano ya vigente.
    assert cargar(sesion, tmp_path, "CADI")[0] == 0
