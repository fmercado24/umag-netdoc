"""Preparación de láminas SVG: limpieza y orientación horizontal."""

from __future__ import annotations

import pytest

from app.scripts.preparar_laminas import diagnosticar, main, preparar


def _lamina(transformacion: str, ancho: int = 100, alto: int = 200, textos: int = 5) -> bytes:
    cuerpo = "".join(
        f'<text transform="{transformacion}" id="t{i}\x01">Sala {i}</text>' for i in range(textos)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ancho} {alto}" '
        f'width="{ancho}" height="{alto}">{cuerpo}</svg>'
    ).encode()


@pytest.mark.parametrize(
    ("transformacion", "giro"),
    [
        ("matrix(0,1,-1,0,10,10)", -90),  # se lee hacia abajo: se gira a la izquierda
        ("matrix(0,-1,1,0,10,10)", 90),  # se lee hacia arriba: a la derecha
        ("rotate(90 10 10)", -90),
        ("matrix(1,0,0,1,10,10)", 0),  # ya horizontal
    ],
)
def test_detecta_el_giro_que_endereza_el_texto(transformacion, giro):
    assert diagnosticar(_lamina(transformacion)).giro == giro


def test_prepara_una_hoja_vertical_y_no_la_gira_dos_veces():
    preparada, diagnostico = preparar(_lamina("matrix(0,1,-1,0,10,10)"))
    assert diagnostico.caracteres_invalidos == 5
    assert b"\x01" not in preparada
    # La hoja queda horizontal y el dibujo, dentro de la nueva caja.
    assert b'viewBox="0 -100 200 100"' in preparada
    assert b'width="200" height="100"' in preparada
    assert b'<g transform="rotate(-90)">' in preparada

    otra_vez = diagnosticar(preparada)
    assert (otra_vez.giro, otra_vez.ancho, otra_vez.alto) == (0, 200, 100)
    assert preparar(preparada)[0] == preparada


def test_una_lamina_horizontal_solo_se_limpia():
    preparada, diagnostico = preparar(_lamina("matrix(1,0,0,1,0,0)", ancho=300, alto=200))
    assert diagnostico.giro == 0
    assert b'viewBox="0 0 300 200"' in preparada and b"<g transform" not in preparada


def test_el_texto_mixto_no_se_gira():
    # Menos del 60 % de lado: probablemente rótulos verticales en un plano horizontal.
    mixto = _lamina("matrix(0,1,-1,0,0,0)", textos=2).replace(
        b"</svg>", b'<text>a</text><text>b</text><text>c</text></svg>'
    )
    assert diagnosticar(mixto).giro == 0


def test_renombra_a_la_nomenclatura_lo_que_se_deja_deducir(tmp_path, capsys):
    horizontal = _lamina("matrix(1,0,0,1,10,10)", ancho=200, alto=100)
    (tmp_path / "ing 1er piso tramo 2.svg").write_bytes(horizontal)
    (tmp_path / "planta 3er piso.svg").write_bytes(horizontal)
    (tmp_path / "leyenda.svg").write_bytes(horizontal)
    (tmp_path / "ing-p04.svg").write_bytes(horizontal)  # ya estándar
    (tmp_path / "ing-p01-t1.svg").write_bytes(horizontal)
    (tmp_path / "ING_P01_T01.svg").write_bytes(horizontal)  # chocaría con la anterior

    main(["ING", "--carpeta", str(tmp_path)])
    salida = capsys.readouterr().out
    assert "ing 1er piso tramo 2.svg: 200×100" in salida
    assert "→ limpiar, renombrar a «ing-p01-t2.svg»" in salida
    assert "! «leyenda.svg» no sigue la nomenclatura" in salida
    assert (tmp_path / "ing 1er piso tramo 2.svg").exists()  # sin --aplicar no toca nada

    main(["ING", "--carpeta", str(tmp_path), "--aplicar"])
    salida = capsys.readouterr().out
    assert sorted(r.name for r in tmp_path.glob("*.svg")) == [
        "ING_P01_T01.svg",
        "ing-p01-t1.svg",
        "ing-p01-t2.svg",
        "ing-p03.svg",
        "ing-p04.svg",
        "leyenda.svg",
    ]
    assert "! no se renombra «ING_P01_T01.svg»: ya existe «ing-p01-t1.svg»" in salida
    # El original limpiado queda con su nombre de origen.
    assert (tmp_path / "originales" / "ing 1er piso tramo 2.svg").exists()
