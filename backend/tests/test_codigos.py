"""Pruebas de la convención de nomenclatura (SOP sección 8)."""

from __future__ import annotations

import pytest

from app.servicios.codigos import (
    CodigoInvalido,
    construir_codigo,
    descomponer_codigo,
    normalizar_piso,
    normalizar_tramo,
)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [(1, "P01"), ("Piso 1", "P01"), ("p03", "P03"), (12, "P12"), ("exterior", "PXX")],
)
def test_normalizar_piso(entrada, esperado):
    assert normalizar_piso(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [(2, "T2"), ("Tramo 2", "T2"), ("t3", "T3"), (None, None), ("", None)],
)
def test_normalizar_tramo(entrada, esperado):
    assert normalizar_tramo(entrada) == esperado


def test_ejemplo_rack_del_sop():
    """CADI-R04-P01-T2 → Rack N°4 del CADI, Piso 1 Tramo 2."""
    assert (
        construir_codigo(edificio="CADI", tipo="R", correlativo=4, piso="P01", tramo="T2")
        == "CADI-R04-P01-T2"
    )


def test_ejemplo_punto_de_datos_del_sop():
    """CADI-PD-P01-T3-R01-T20: tipo terminal, sin correlativo y con detalle."""
    assert (
        construir_codigo(
            edificio="CADI", tipo="PD", piso="P01", tramo="T3", detalle="R01-T20"
        )
        == "CADI-PD-P01-T3-R01-T20"
    )


def test_ida_y_vuelta():
    codigo = construir_codigo(
        edificio="CADI", tipo="SW", correlativo=1, piso="P03", tramo="T2"
    )
    partes = descomponer_codigo(codigo)
    assert partes.edificio == "CADI"
    assert partes.tipo == "SW"
    assert partes.correlativo == 1
    assert partes.piso == "P03"
    assert partes.tramo == "T2"
    assert partes.detalle is None


def test_codigo_malformado():
    with pytest.raises(CodigoInvalido):
        descomponer_codigo("esto no es un codigo")
