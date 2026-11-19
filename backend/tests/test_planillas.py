"""Planillas del levantamiento con errores de tipeo, y la columna «Sala del plano»."""

from __future__ import annotations

import pytest

from app.models import EstadoCondicion, EstadoOperativo
from app.scripts import cargar_planos, importar_edificio
from app.servicios.planillas import (
    COLUMNAS_EQUIPO,
    POSICIONES_EQUIPO,
    columnas_de,
    leer_condicion,
    leer_estado,
    leer_tipo,
    numero_de_rack,
    piso_y_tramo,
)
from app.servicios.planos import quitar_caracteres_de_control
from app.servicios.recintos import FilaRecinto, escribir_recintos, huella_lamina

API = "/api/v1"


@pytest.mark.parametrize(
    ("texto", "codigo", "corregido"),
    [
        ("Switches", "SW", None),
        ("SWITCH", "SW", None),
        ("SW", "SW", None),
        ("Swich", "SW", "switch"),
        ("Acces Point", "AP", "access point"),
        ("Punto de acceso", "AP", None),
        ("Patch pannel", "PP", "patch panel"),
        ("Cabecera F.O.", "ODF", None),
        ("Gabinete", "R", None),
        ("Rack", "R", None),
        ("Roseta", "PD", None),
        ("U.P.S", None, None),
        ("Impresora", None, None),
        ("", None, None),
    ],
)
def test_tipo_tolera_errores_de_tipeo(texto, codigo, corregido):
    lectura = leer_tipo(texto)
    assert (lectura.valor, lectura.corregido) == (codigo, corregido)


@pytest.mark.parametrize(
    ("texto", "estado", "corregido"),
    [
        ("Operativo / Activo / En línea (Online)", EstadoOperativo.ACTIVO, None),
        ("", EstadoOperativo.ACTIVO, None),
        ("Operatibo", EstadoOperativo.ACTIVO, "operativo"),
        ("Fuera de servicio", EstadoOperativo.INACTIVO, None),
        ("Fuera de serbicio", EstadoOperativo.INACTIVO, "fuera de servicio"),
        ("No operativo", EstadoOperativo.INACTIVO, None),
        ("Inactivo", EstadoOperativo.INACTIVO, None),
        ("En falla", EstadoOperativo.EN_FALLA, None),
        ("En mantención", EstadoOperativo.EN_MANTENIMIENTO, None),
        ("Mantenimiento", EstadoOperativo.EN_MANTENIMIENTO, None),
    ],
)
def test_estado_operativo_tolera_errores_de_tipeo(texto, estado, corregido):
    lectura = leer_estado(texto)
    assert lectura.reconocido
    assert (lectura.valor, lectura.corregido) == (estado, corregido)


def test_estado_que_no_se_entiende_no_se_inventa():
    assert not leer_estado("xyz").reconocido
    assert not leer_condicion("??").reconocido


@pytest.mark.parametrize(
    ("texto", "condicion"),
    [
        ("Excelente / Bueno (Óptimo)", EstadoCondicion.EXCELENTE),
        ("Bueno", EstadoCondicion.EXCELENTE),
        ("Exelente", EstadoCondicion.EXCELENTE),
        ("Regular / Aceptable", EstadoCondicion.REGULAR),
        ("Regulr", EstadoCondicion.REGULAR),
        ("Malo", EstadoCondicion.MALO),
        ("Obsoleto", EstadoCondicion.OBSOLETO),
        ("", None),
    ],
)
def test_condicion_tolera_errores_de_tipeo(texto, condicion):
    assert leer_condicion(texto).valor == condicion


@pytest.mark.parametrize(
    ("texto", "numero"),
    [
        ("Rack-04", 4), ("RACK 4", 4), ("Rack N° 4", 4), ("R04", 4), ("r-4", 4),
        ("Rak 4", 4), ("Gabinete 2", 2), ("RACK 1 PRINCIPAL", 1), ("", None), ("Sala", None),
    ],
)
def test_numero_de_rack(texto, numero):
    assert numero_de_rack(texto) == numero


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Piso 1 - Tramo 2", ("P01", "T2")),
        ("P01-T2", ("P01", "T2")),
        ("p1 t2", ("P01", "T2")),
        ("Pizo 3", ("P03", None)),
        ("Piso Subterráneo", ("P00", None)),
        ("Subterráneo - Tramo 1", ("P00", "T1")),
        ("Pasillo", None),
    ],
)
def test_piso_y_tramo(texto, esperado):
    assert piso_y_tramo(texto) == esperado


def test_columnas_en_otro_orden_y_mal_escritas():
    columnas = columnas_de(
        ["Tipo", "Etiquta", "Sala del plano", "Marca y modelo", "Estado", "Color"],
        COLUMNAS_EQUIPO,
        POSICIONES_EQUIPO,
    )
    assert columnas.indices == {"tipo": 0, "etiqueta": 1, "sala": 2, "modelo": 3, "estado_operativo": 4}
    assert columnas.corregidas == [("Etiquta", "etiqueta")]
    assert columnas.desconocidas == ["Color"]


def test_sin_encabezado_reconocible_vale_el_orden_del_cadi():
    assert columnas_de(["a", "b"], COLUMNAS_EQUIPO, POSICIONES_EQUIPO).indices == POSICIONES_EQUIPO


# De punta a punta: primero los planos, después la planilla
# --------------------------------------------------------------------------
ANCHO, ALTO = 1000, 800


def _edificio_con_planos(cliente, tmp_path, codigo):
    """Un edificio con la nomenclatura de la Biblioteca y su lámina ya cargada,
    con sus salas leídas, como cuando se carga desde el visor."""
    assert cliente.post(f"{API}/edificios", json={"codigo": codigo, "nombre": "Prueba"}).status_code == 201
    cliente.post(f"{API}/edificios/{codigo}/pisos", json={"codigo": "P01", "orden": 1})
    prefijo = codigo.lower()
    planos = tmp_path / "planos"
    planos.mkdir()
    contenido = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ANCHO} {ALTO}"><text>plano</text></svg>'
    ).encode()
    (planos / f"{prefijo}-p01.svg").write_bytes(contenido)
    huella = huella_lamina(quitar_caracteres_de_control(contenido))
    lamina = f"{prefijo}-p01.svg"
    escribir_recintos(
        tmp_path / f"{prefijo}-recintos.csv",
        [
            FilaRecinto(lamina, "07", "OFICINA ADMINISTRATIVA", 100, 100, huella),
            FilaRecinto(lamina, "09", "OFICINA ADMINISTRATIVA", 200, 100, huella),
            FilaRecinto(lamina, "12", "COLECCIÓN JURÍDICA", 300, 300, huella),
            FilaRecinto(lamina, "15", "AULA TECNOLÓGICA", 500, 500, huella),
            FilaRecinto(lamina, "R01", "RACK 01", 520, 520, huella),
        ],
    )
    cargar_planos.main([codigo, "--planos", str(planos)])


def test_planilla_con_errores_se_importa_y_se_ubica_por_su_sala(cliente, tmp_path, capsys):
    _edificio_con_planos(cliente, tmp_path, "LEVA")
    planillas = tmp_path / "planillas"
    planillas.mkdir()
    # Columnas en otro orden, una sin tilde y otra mal escrita, y valores con errores de tipeo.
    (planillas / "leva-p01.csv").write_text(
        "Tipo,Elemento,Etiquta,Sala del plano,Ubicacion,Estado Operativo,Estado Condicion,Rack,Notas\n"
        "Rak,Rack mural 12U,RACK-01,Aula tecnologica,,Operatibo,Bueno,Rack-01,\n"
        "Swich,Grandstream GWN7803P,BIBLIO-01,15,,Operativo,Exelente,R01,\n"
        "Acces Point,Ubiquiti UniFi 6,AP-JUR,Coleccion Juridca,Sobre la puerta,En falla,Regular,,\n"
        "Access Point,Ubiquiti UniFi,AP-ADM,Oficina administrativa,,Operativo,Excelente,,\n"
        "Access Point,Ubiquiti UniFi,AP-X,32,,Operativo,Excelente,,\n"
        "Impresora,HP,IMP-1,15,,Operativo,Excelente,,\n",
        encoding="utf-8",
    )

    importar_edificio.main(["LEVA", "--datos", str(planillas)])
    salida = capsys.readouterr().out

    elementos = {
        e["codigo"]: e
        for e in cliente.get(f"{API}/integraciones/inventario?edificio=LEVA").json()["elementos"]
    }
    assert set(elementos) == {"LEVA-R01-P01", "LEVA-SW01-P01", "LEVA-AP01-P01", "LEVA-AP02-P01", "LEVA-AP03-P01"}
    switch = cliente.get(f"{API}/elementos/LEVA-SW01-P01").json()
    assert switch["montado"] and switch["padre_codigo"] == "LEVA-R01-P01"
    assert switch["estado_condicion"] == "excelente"
    juridica = cliente.get(f"{API}/elementos/LEVA-AP01-P01").json()
    assert (juridica["numero_recinto"], juridica["estado_operativo"]) == ("12", "en_falla")
    assert juridica["ubicacion_descriptiva"] == "Coleccion Juridca, Sobre la puerta"

    mapa = cliente.get(f"{API}/elementos/mapa", params={"edificio": "LEVA", "piso": "P01"}).json()
    ubicados = {e["codigo"]: e["ubicado"] for e in mapa["elementos"] if not e["montado"]}
    # El rack, sobre su rótulo; el AP de la colección jurídica, en su sala.
    assert ubicados["LEVA-R01-P01"] and ubicados["LEVA-AP01-P01"]
    # Un nombre de varias salas y una sala que el plano no tiene: sin ubicar, para el visor.
    assert not ubicados["LEVA-AP02-P01"] and not ubicados["LEVA-AP03-P01"]

    assert "la columna «Etiquta» se leyó como «etiqueta»" in salida
    assert "«Swich» en la columna Tipo se leyó como «switch»" in salida
    assert "«Operatibo» en la columna Estado Operativo se leyó como «operativo»" in salida
    assert "«Oficina administrativa» es el nombre de 2 salas del piso P01 (07, 09)" in salida
    assert "la sala «32» no está entre las leídas de las láminas del piso P01" in salida
    assert "tipo no reconocido «Impresora»" in salida


def test_sin_planos_se_guarda_el_codigo_y_se_avisa(cliente, tmp_path, capsys):
    assert cliente.post(f"{API}/edificios", json={"codigo": "LEVB", "nombre": "Prueba"}).status_code == 201
    (tmp_path / "levb-p01.csv").write_text(
        "Elemento,Etiqueta,Tipo,Sala del plano,Ubicación,Estado Operativo,Estado Condición\n"
        "UniFi,AP-1,Access Point,Oficina administrativa 09,Sobre la puerta,Operativo,Excelente\n"
        "UniFi,AP-2,Access Point,Idiomas,,Operativo,Excelente\n",
        encoding="utf-8",
    )
    importar_edificio.main(["LEVB", "--datos", str(tmp_path)])
    assert "El piso P01 aún no tiene láminas con sus salas leídas" in capsys.readouterr().out
    uno = cliente.get(f"{API}/elementos/LEVB-AP01-P01").json()
    assert (uno["numero_recinto"], uno["ubicacion_descriptiva"]) == ("09", "Oficina administrativa 09, Sobre la puerta")
    dos = cliente.get(f"{API}/elementos/LEVB-AP02-P01").json()
    assert (dos["numero_recinto"], dos["ubicacion_descriptiva"]) == (None, "Idiomas")

