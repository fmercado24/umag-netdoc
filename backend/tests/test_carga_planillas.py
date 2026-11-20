"""Importar el levantamiento subiendo sus planillas CSV desde el visor."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import configuracion
from app.db.session import SesionLocal
from app.models import Piso, Plano
from app.servicios.carga_planillas import revisar
from tests.test_planillas import _edificio_con_planos

API = "/api/v1"

EQUIPOS = (
    "Elemento,Etiqueta,Tipo,Sala del plano,Ubicación,Estado Operativo,Estado Condición,Rack,Notas\n"
    "Rack mural 12U,RACK-01,Rack,Aula tecnológica,,Operativo,Excelente,Rack-01,\n"
    "Grandstream GWN7803P,SW-1,Swich,15,,Operativo,Excelente,R01,\n"
    "Ubiquiti UniFi 6,AP-JUR,Access Point,Colección jurídica,,Operativo,Excelente,,\n"
    "Ubiquiti UniFi,AP-X,Access Point,32,,Operativo,Excelente,,\n"
)
VLANS = "numero,nombre,gateway,prefijo,servicio\n3,DATOS,10.50.0.1,16,datos\n"


# --- Nombres ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("archivo", "nombre", "contenido"),
    [
        ("leve-p01-t1.csv", "leve-p01-t1.csv", "Equipamiento: Piso 1, tramo 1"),
        ("LEVE-P02.CSV", "leve-p02.csv", "Equipamiento: Piso 2 completo"),
        ("leve-p00.csv", "leve-p00.csv", "Equipamiento: Subterráneo"),
        ("leve-puntos-de-datos.csv", "leve-puntos-de-datos.csv", "Puntos de datos del edificio"),
        ("leve-vlans.csv", "leve-vlans.csv", "Leyenda de VLANs"),
        ("leve-laminas.csv", "leve-laminas.csv", "Excepciones de lámina"),
        ("leve-levantamiento.csv", "leve-levantamiento.csv", "Fechas de las visitas a terreno"),
        ("leve-recintos.csv", "leve-recintos.csv", "Salas de los planos, revisadas"),
    ],
)
def test_nombres_que_siguen_la_nomenclatura(archivo, nombre, contenido):
    revision = revisar("LEVE", archivo)
    assert (revision.nombre, revision.contenido, revision.error) == (nombre, contenido, None)


@pytest.mark.parametrize(
    ("archivo", "sugerencia"),
    [
        ("leve-p1-t1.csv", "leve-p01-t1.csv"),
        ("leve-p01-t01.csv", "leve-p01-t1.csv"),
        ("LEVE P1 T2.csv", "leve-p01-t2.csv"),
        ("leve 1er piso tramo 2.csv", "leve-p01-t2.csv"),
        ("leve-p01-t1 (1).csv", "leve-p01-t1.csv"),
        ("Puntos de datos.csv", "leve-puntos-de-datos.csv"),
        ("leve-puntos-datos.csv", "leve-puntos-de-datos.csv"),
        ("leve_vlan.csv", "leve-vlans.csv"),
        ("leve-láminas.csv", "leve-laminas.csv"),
        ("Levantamientos.csv", "leve-levantamiento.csv"),
    ],
)
def test_un_nombre_mal_escrito_se_rechaza_con_el_que_corresponde(archivo, sugerencia):
    revision = revisar("LEVE", archivo)
    assert revision.nombre is None
    assert revision.error == "No sigue la nomenclatura."
    assert revision.sugerencia == sugerencia


@pytest.mark.parametrize(
    ("archivo", "error"),
    [
        ("otro-p01.csv", "Es del edificio OTRO, no de LEVE."),
        ("otro-vlans.csv", "Es del edificio OTRO, no de LEVE."),
        ("leve-p01.xlsx", "Es un libro de cálculo"),
        ("leve-p01.svg", "Solo se aceptan planillas CSV."),
        ("inventario.csv", "No sigue la nomenclatura: leve-p01-t1.csv"),
    ],
)
def test_lo_que_no_se_puede_deducir_se_rechaza_sin_sugerencia(archivo, error):
    revision = revisar("LEVE", archivo)
    assert revision.nombre is None and revision.sugerencia is None
    assert revision.error.startswith(error)


# --- Con planos: revisar e importar ------------------------------------------------------


def _subir(cliente, edificio, *archivos, ensayo=True, usuario=None):
    return cliente.post(
        f"{API}/edificios/{edificio}/carga-de-planillas",
        params={"ensayo": str(ensayo).lower()},
        files=[("archivos", (nombre, contenido, "text/csv")) for nombre, contenido in archivos],
        data={"usuario": usuario} if usuario else None,
    )


def _inventario(cliente, edificio):
    return {
        e["codigo"]: e
        for e in cliente.get(f"{API}/integraciones/inventario?edificio={edificio}").json()["elementos"]
    }


@pytest.fixture
def leve(cliente, tmp_path_factory):
    """Un edificio con su plano y sus salas leídas. Lo comparten las pruebas que
    siguen, en orden: primero sin elementos y después con los importados."""
    if cliente.get(f"{API}/edificios/LEVE").status_code == 404:
        _edificio_con_planos(cliente, tmp_path_factory.mktemp("leve"), "LEVE")
    return "LEVE"


def test_antes_de_elegir_dice_como_deben_llamarse(cliente, leve):
    estado = cliente.get(f"{API}/edificios/{leve}/carga-de-planillas").json()
    assert (estado["permitida"], estado["modo"]) == (True, "nuevo")
    assert {"nombre": "leve-p01-t1.csv", "contenido": "Equipamiento: Piso 1, tramo 1"} in estado["ejemplos"]
    assert {"nombre": "leve-puntos-de-datos.csv", "contenido": "Puntos de datos del edificio"} in estado["ejemplos"]


def test_el_ensayo_informa_sin_cambiar_nada(cliente, leve):
    respuesta = _subir(cliente, leve, ("leve-p01.csv", EQUIPOS.encode()), ("leve-p1.csv", b"x"))
    assert respuesta.status_code == 200, respuesta.text
    informe = respuesta.json()
    assert informe["ensayo"] and informe["modo"] == "nuevo" and informe["motivo"] is None
    assert [a["nombre"] for a in informe["aceptados"]] == ["leve-p01.csv"]
    assert [(r["archivo"], r["sugerencia"]) for r in informe["rechazados"]] == [("leve-p1.csv", "leve-p01.csv")]
    assert informe["importado"]["equipos"] == 4
    assert "leve-p01.csv: «Swich» en la columna Tipo se leyó como «switch»; corríjalo en la planilla de origen" in informe["advertencias"]
    assert informe["ubicados"] >= 2 and informe["sin_ubicar"] == 1
    assert not any("netdoc-planillas" in linea for linea in informe["advertencias"] + informe["ubicacion"])
    # Nada quedó: ni elementos ni planillas guardadas.
    assert _inventario(cliente, leve) == {}
    assert not (configuracion.dir_planillas / leve).exists()


def test_con_un_archivo_rechazado_no_se_importa_nada(cliente, leve):
    respuesta = _subir(cliente, leve, ("leve-p01.csv", EQUIPOS.encode()), ("leve-p1.csv", b"x"), ensayo=False)
    assert respuesta.status_code == 422
    assert "«leve-p1.csv»: No sigue la nomenclatura." in respuesta.json()["detail"]
    assert _inventario(cliente, leve) == {}


@pytest.mark.parametrize(
    ("contenido", "error"),
    [
        (b"  \n", "Está vacío."),
        (b"PK\x03\x04resto", "Es un libro de Excel con extensión .csv"),
        ("Elemento,Etiqueta\n".encode("utf-16"), "No es texto CSV"),
    ],
)
def test_un_archivo_que_no_es_una_planilla_se_rechaza(cliente, leve, contenido, error):
    informe = _subir(cliente, leve, ("leve-p02.csv", contenido)).json()
    assert informe["rechazados"][0]["error"].startswith(error)
    assert informe["importado"] is None


def test_el_mismo_nombre_dos_veces_se_rechaza(cliente, leve):
    informe = _subir(cliente, leve, ("leve-p01.csv", EQUIPOS.encode()), ("LEVE-P01.csv", EQUIPOS.encode())).json()
    assert [a["archivo"] for a in informe["aceptados"]] == ["leve-p01.csv"]
    assert informe["rechazados"][0]["error"] == "Ya viene otro archivo llamado «leve-p01.csv»."


def test_importar_crea_ubica_y_guarda_las_planillas(cliente, leve):
    respuesta = _subir(cliente, leve, ("LEVE-P01.csv", EQUIPOS.encode()), ensayo=False, usuario="Ana Pérez")
    assert respuesta.status_code == 200, respuesta.text
    informe = respuesta.json()
    assert not informe["ensayo"] and informe["importado"]["equipos"] == 4

    elementos = _inventario(cliente, leve)
    assert set(elementos) == {"LEVE-R01-P01", "LEVE-SW01-P01", "LEVE-AP01-P01", "LEVE-AP02-P01"}
    mapa = cliente.get(f"{API}/elementos/mapa", params={"edificio": leve, "piso": "P01"}).json()
    ubicados = {e["codigo"]: e["ubicado"] for e in mapa["elementos"] if not e["montado"]}
    assert ubicados == {"LEVE-R01-P01": True, "LEVE-AP01-P01": True, "LEVE-AP02-P01": False}
    historial = cliente.get(f"{API}/elementos/LEVE-AP01-P01/historial").json()
    # El alta, de quien importó; la posición en su sala, del sistema.
    assert {h["usuario"] for h in historial} == {"Ana Pérez", "ubicacion-automatica"}

    guardada = configuracion.dir_planillas / leve / "leve-p01.csv"
    assert guardada.read_bytes() == EQUIPOS.encode()
    # Traen IP, MAC e inventario: no se sirven.
    assert cliente.get(f"/media/planillas/{leve}/leve-p01.csv").status_code == 404


def test_con_elementos_se_suma_lo_nuevo_con_lo_ya_guardado(cliente, leve):
    estado = cliente.get(f"{API}/edificios/{leve}/carga-de-planillas").json()
    assert estado["modo"] == "agregar"
    assert estado["guardadas"] == [{"nombre": "leve-p01.csv", "contenido": "Equipamiento: Piso 1 completo"}]

    informe = _subir(cliente, leve, ("leve-vlans.csv", VLANS.encode()), ensayo=False).json()
    assert informe["modo"] == "agregar" and informe["guardadas"] == ["leve-p01.csv"]
    assert informe["omitidas"] == ["leve-p01.csv (ya importada)"]
    assert informe["importado"]["equipos"] == 0 and informe["importado"]["vlans"] == 1
    assert len(_inventario(cliente, leve)) == 4

    # Otra versión de una planilla ya guardada: la anterior no se pierde.
    _subir(cliente, leve, ("leve-vlans.csv", (VLANS + "2,TELEFONIA,10.51.0.1,16,telefonia\n").encode()), ensayo=False)
    anteriores = list((configuracion.dir_planillas / leve / "anteriores").glob("*-leve-vlans.csv"))
    assert [a.read_bytes() for a in anteriores] == [VLANS.encode()]


def test_sin_planos_se_revisa_pero_no_se_importa(cliente):
    assert cliente.post(f"{API}/edificios", json={"codigo": "LEVF", "nombre": "Prueba"}).status_code == 201
    estado = cliente.get(f"{API}/edificios/LEVF/carga-de-planillas").json()
    assert not estado["permitida"] and estado["motivo"].startswith("Primero cargue los planos de LEVF")

    informe = _subir(cliente, "LEVF", ("levf-p01.csv", EQUIPOS.encode())).json()
    assert informe["motivo"] == estado["motivo"] and informe["importado"]["equipos"] == 4
    assert informe["ubicacion"] == []

    respuesta = _subir(cliente, "LEVF", ("levf-p01.csv", EQUIPOS.encode()), ensayo=False)
    assert respuesta.status_code == 409
    assert _inventario(cliente, "LEVF") == {}


def test_mientras_se_leen_las_salas_no_se_importa(cliente, tmp_path):
    _edificio_con_planos(cliente, tmp_path, "LEVG")
    with SesionLocal() as bd:
        plano = bd.scalar(select(Plano).join(Piso).where(Piso.edificio.has(codigo="LEVG")))
        plano.lectura_recintos = "leyendo"
        bd.commit()
    respuesta = _subir(cliente, "LEVG", ("levg-p01.csv", EQUIPOS.encode()), ensayo=False)
    assert respuesta.status_code == 409
    assert "Todavía se están leyendo las salas de 1 plano(s)" in respuesta.json()["detail"]
