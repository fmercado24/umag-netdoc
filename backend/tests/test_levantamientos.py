"""Fechas de las visitas a terreno (``<código>-levantamiento.csv``)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app.models import EstadoLevantamiento, Levantamiento
from app.scripts import importar_edificio
from app.scripts.importar_edificio import main, registrar_levantamientos
from app.servicios.levantamientos import (
    ArchivoLevantamientoInvalido,
    leer_levantamientos,
)

API = "/api/v1"
ENCABEZADO = "Elemento,Etiqueta,Tipo,Ubicación,Estado Operativo,Estado Condición,Notas,Rack,Foto\n"


def test_lee_fechas_pisos_y_punto_y_coma(tmp_path):
    ruta = tmp_path / "pat-levantamiento.csv"
    ruta.write_text(
        "fecha_inicio;fecha_cierre;pisos;observaciones\n"
        "2026-10-02;;Piso 3;Segunda visita\n"
        "2026-09-15;2026-09-16;p1, 2 P00;Recorrido\n",
        encoding="utf-8",
    )
    primera, segunda = leer_levantamientos(ruta)
    assert (primera.fecha, primera.pisos, primera.observaciones) == (
        dt.date(2026, 9, 16),
        ("P01", "P02", "P00"),
        "Recorrido",
    )
    # Sin cierre, la visita sigue abierta y vale su fecha de inicio.
    assert (segunda.fecha, segunda.pisos) == (dt.date(2026, 10, 2), ("P03",))
    assert leer_levantamientos(tmp_path / "no-existe.csv") == []


@pytest.mark.parametrize(
    ("fila", "mensaje"),
    [
        ("15-09-2026,,,", "no es una fecha"),
        (",2026-09-16,,", "falta la fecha_inicio"),
        ("2026-09-16,2026-09-15,,", "anterior a la fecha_inicio"),
        ("2026-09-15,,Mezzanine,", "no es un piso"),
    ],
)
def test_filas_invalidas(tmp_path, fila, mensaje):
    ruta = tmp_path / "x-levantamiento.csv"
    ruta.write_text(
        "fecha_inicio,fecha_cierre,pisos,observaciones\n" + fila + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ArchivoLevantamientoInvalido, match=mensaje):
        leer_levantamientos(ruta)


def _edificio_de_dos_pisos(tmp_path, codigo: str) -> None:
    prefijo = codigo.lower()
    for piso in (1, 2):
        (tmp_path / f"{prefijo}-p0{piso}.csv").write_text(
            ENCABEZADO
            + f"Cisco CBS250,SW-{piso},Switches,Sala 1{piso}0,Operativo,Excelente,,,\n",
            encoding="utf-8",
        )


def _fechas(cliente, codigo: str) -> dict[str, str | None]:
    elementos = cliente.get(f"{API}/elementos?edificio={codigo}").json()["items"]
    return {
        e["codigo"]: cliente.get(f"{API}/elementos/{e['codigo']}").json()[
            "fecha_ultimo_levantamiento"
        ]
        for e in elementos
    }


def test_la_importacion_fecha_los_pisos_de_cada_visita(
    cliente, sesion, tmp_path, capsys
):
    cliente.post(
        f"{API}/edificios", json={"codigo": "LEV", "nombre": "Edificio de prueba"}
    )
    _edificio_de_dos_pisos(tmp_path, "LEV")
    (tmp_path / "lev-levantamiento.csv").write_text(
        "fecha_inicio,fecha_cierre,pisos,observaciones\n2026-09-15,2026-09-16,P01,Recorrido\n",
        encoding="utf-8",
    )
    main(["LEV", "--datos", str(tmp_path)])

    assert "fecha del último levantamiento en 1 elementos" in capsys.readouterr().out
    assert _fechas(cliente, "LEV") == {
        "LEV-SW01-P01": "2026-09-16",
        "LEV-SW01-P02": None,
    }
    bitacora = sesion.scalars(
        select(Levantamiento).where(Levantamiento.observaciones == "Recorrido")
    ).all()
    assert [(b.fecha_inicio, b.fecha_cierre, b.estado) for b in bitacora] == [
        (dt.date(2026, 9, 15), dt.date(2026, 9, 16), EstadoLevantamiento.CERRADO)
    ]
    historial = cliente.get(f"{API}/elementos/LEV-SW01-P01/historial").json()
    cambio = next(h for h in historial if h["campo"] == "fecha_ultimo_levantamiento")
    assert (cambio["origen"], cambio["comentario"]) == (
        "sistema",
        "Visita a terreno del 15-09-2026 al 16-09-2026",
    )


def test_se_aplica_a_un_edificio_ya_importado_sin_retroceder_fechas(
    cliente, tmp_path, monkeypatch, capsys
):
    carpeta = tmp_path / "dec"
    carpeta.mkdir()
    _edificio_de_dos_pisos(carpeta, "DEC")
    monkeypatch.setattr(importar_edificio, "DIR_DATA", tmp_path)
    importar_edificio.importar_pendientes()
    assert set(_fechas(cliente, "DEC").values()) == {None}

    # Una verificación posterior registrada desde el visor no se pisa.
    respuesta = cliente.patch(
        f"{API}/elementos/DEC-SW01-P02",
        json={"fecha_ultimo_levantamiento": "2026-10-10", "usuario": "visor"},
    )
    assert respuesta.status_code == 200, respuesta.text
    (carpeta / "dec-levantamiento.csv").write_text(
        "fecha_inicio,fecha_cierre,pisos,observaciones\n2026-09-15,2026-09-16,,Recorrido completo\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    importar_edificio.importar_pendientes()
    salida = capsys.readouterr().out
    assert "DEC: ya tiene 2 elementos; no se reimporta." in salida
    assert "fecha del último levantamiento en 1 elementos" in salida
    assert _fechas(cliente, "DEC") == {
        "DEC-SW01-P01": "2026-09-16",
        "DEC-SW01-P02": "2026-10-10",
    }

    # Volver a aplicarlo no cambia nada ni lo informa.
    registrar_levantamientos("DEC", carpeta)
    assert "Levantamiento" not in capsys.readouterr().out


def test_un_archivo_invalido_se_informa_sin_detener_la_carga(tmp_path, capsys):
    (tmp_path / "zzz-levantamiento.csv").write_text(
        "fecha_inicio,fecha_cierre,pisos,observaciones\nayer,,,\n", encoding="utf-8"
    )
    registrar_levantamientos("ZZZ", tmp_path)
    assert "zzz-levantamiento.csv: no se aplicó. fila 2" in capsys.readouterr().out
