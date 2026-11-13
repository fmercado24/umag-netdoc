"""Varias personas usando NetDoc a la vez."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.config import UsuarioAdicional, configuracion
from app.db.session import SesionLocal, tomar_turno_de_escritura
from app.main import app
from app.models import Elemento, SesionAcceso
from app.servicios.autenticacion import abrir_sesion, cifrar_clave
from app.servicios.proteccion import COOKIE_HTTP
from tests.conftest import EQUIPO_LOCAL

API = "/api/v1"
VERSION = "X-NetDoc-Version"
PERSONAS = 8


def _persona(usuario: str | None = None) -> TestClient:
    with SesionLocal() as bd:
        token = abrir_sesion(bd, "pruebas", usuario=usuario)
        bd.commit()
    return TestClient(app, client=EQUIPO_LOCAL, cookies={COOKIE_HTTP: token})


def _a_la_vez(acciones: list) -> list:
    """Corre cada acción en su hilo, partiendo todas juntas."""
    barrera = threading.Barrier(len(acciones))
    salida: list = [None] * len(acciones)

    def correr(i: int) -> None:
        barrera.wait()
        salida[i] = acciones[i]()

    hilos = [threading.Thread(target=correr, args=(i,)) for i in range(len(acciones))]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    return salida


@pytest.fixture(scope="module")
def personas() -> list[TestClient]:
    return [_persona() for _ in range(PERSONAS)]


@pytest.fixture(scope="module")
def edificio(personas) -> str:
    admin = personas[0]
    admin.post(f"{API}/edificios", json={"codigo": "VAR", "nombre": "Varias personas"})
    for piso in ("P01", "P02", "P03"):
        admin.post(f"{API}/edificios/VAR/pisos", json={"codigo": piso, "orden": 1})
    return "VAR"


def _alta(persona: TestClient, **datos) -> dict:
    respuesta = persona.post(f"{API}/elementos", json={"edificio": "VAR", "piso": "P01", **datos})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# --- Altas y códigos ---------------------------------------------------------------


def test_altas_simultaneas_reciben_codigos_distintos(personas, edificio):
    def varias(persona):
        return [
            persona.post(f"{API}/elementos", json={"tipo": "SW", "edificio": "VAR", "piso": "P02"})
            for _ in range(4)
        ]

    respuestas = [r for grupo in _a_la_vez([lambda p=p: varias(p) for p in personas]) for r in grupo]
    assert [r.status_code for r in respuestas] == [201] * (PERSONAS * 4)
    codigos = sorted(r.json()["codigo"] for r in respuestas)
    assert codigos == [f"VAR-SW{n:02d}-P02" for n in range(1, PERSONAS * 4 + 1)]


def test_el_mismo_puerto_documentado_a_la_vez_queda_una_sola_vez(personas, edificio):
    rack = _alta(personas[0], tipo="R")["codigo"]
    punto = {"tipo": "PD", "edificio": "VAR", "piso": "P01", "rack_origen": rack, "puerto": "D01"}
    respuestas = _a_la_vez([lambda p=p: p.post(f"{API}/elementos", json=punto) for p in personas])
    assert sorted(r.status_code for r in respuestas) == [201] + [409] * (PERSONAS - 1)


def test_el_mismo_piso_creado_a_la_vez_no_es_un_error_interno(personas, edificio):
    piso = {"codigo": "P09", "orden": 9}
    respuestas = _a_la_vez(
        [lambda p=p: p.post(f"{API}/edificios/VAR/pisos", json=piso) for p in personas]
    )
    assert sorted(r.status_code for r in respuestas) == [201] + [409] * (PERSONAS - 1)


def test_dos_traslados_a_la_vez_dejan_un_historial_coherente(personas, edificio):
    codigo = _alta(personas[0], tipo="AP")["codigo"]
    destinos = ["P02", "P03"]
    respuestas = _a_la_vez(
        [
            lambda i=i: personas[i].post(f"{API}/elementos/{codigo}/trasladar", json={"piso": destinos[i]})
            for i in range(2)
        ]
    )
    assert [r.status_code for r in respuestas] == [200, 200]
    final = personas[0].get(f"{API}/elementos/{codigo}").json()
    historial = personas[0].get(f"{API}/elementos/{final['codigo']}/historial").json()
    cambios = [
        (h["valor_anterior"], h["valor_nuevo"])
        for h in sorted(historial, key=lambda h: h["id"])
        if h["campo"] == "codigo"
    ]
    # El segundo partió de donde lo dejó el primero, no de donde ambos lo vieron.
    assert cambios[0][0] == codigo
    assert cambios[1][0] == cambios[0][1]
    assert cambios[1][1] == final["codigo"]


def test_leer_mientras_otros_escriben(personas, edificio):
    objetivos = [_alta(personas[0], tipo="AP")["codigo"] for _ in range(PERSONAS)]

    def trabajo(i):
        if i % 2:
            return [
                personas[i].patch(f"{API}/elementos/{objetivos[i]}", json={"marca": f"m{n}"}).status_code
                for n in range(5)
            ]
        return [
            personas[i].get(f"{API}/elementos/mapa?edificio=VAR&piso=P01").status_code for _ in range(5)
        ]

    codigos = [c for grupo in _a_la_vez([lambda i=i: trabajo(i) for i in range(PERSONAS)]) for c in grupo]
    assert codigos == [200] * (PERSONAS * 5)


# --- El cambio de otra persona no se pisa sin aviso ------------------------------------


def test_cada_cambio_sube_la_version(personas, edificio):
    elemento = _alta(personas[0], tipo="AP")
    assert elemento["version"] == 1
    editado = personas[0].patch(f"{API}/elementos/{elemento['id']}", json={"marca": "A"}).json()
    assert editado["version"] == 2
    # Guardar lo mismo no es un cambio.
    assert personas[0].patch(f"{API}/elementos/{elemento['id']}", json={"marca": "A"}).json()["version"] == 2
    en_lista = personas[0].get(f"{API}/elementos?edificio=VAR&q={elemento['codigo']}").json()["items"][0]
    assert en_lista["version"] == 2


def test_no_se_pisa_lo_que_otra_persona_cambio_entretanto(personas, edificio):
    ana, beto = personas[0], _persona()
    abierto = _alta(ana, tipo="AP")
    ruta = f"{API}/elementos/{abierto['id']}"
    vista = {VERSION: str(abierto["version"])}

    # Las dos lo tienen abierto. Guarda Ana…
    assert ana.patch(ruta, json={"marca": "la de Ana"}, headers=vista).status_code == 200
    # …y Beto, que sigue viendo lo anterior, no la pisa.
    rechazo = beto.patch(ruta, json={"marca": "la de Beto"}, headers=vista)
    assert rechazo.status_code == 412
    assert abierto["codigo"] in rechazo.json()["detail"]
    assert "admin-netdoc" in rechazo.json()["detail"]  # quién lo modificó
    assert ana.get(ruta).json()["marca"] == "la de Ana"

    # Con la versión actual a la vista, sí.
    actual = {VERSION: str(beto.get(ruta).json()["version"])}
    assert beto.patch(ruta, json={"modelo": "el de Beto"}, headers=actual).status_code == 200
    final = ana.get(ruta).json()
    assert (final["marca"], final["modelo"]) == ("la de Ana", "el de Beto")


@pytest.mark.parametrize(
    "metodo, sufijo, cuerpo",
    [
        ("PATCH", "", {"marca": "x"}),
        ("PATCH", "/posicion", {"plano_id": 1, "pos_x": 1, "pos_y": 1}),
        ("POST", "/trasladar", {"piso": "P02"}),
        ("POST", "/ubicar-en-recinto", None),
        ("DELETE", "", None),
    ],
)
def test_todo_lo_que_cambia_un_elemento_respeta_la_version(personas, edificio, metodo, sufijo, cuerpo):
    elemento = _alta(personas[0], tipo="AP")
    ruta = f"{API}/elementos/{elemento['id']}"
    personas[1].patch(ruta, json={"modelo": "cambio ajeno"})
    respuesta = personas[0].request(metodo, ruta + sufijo, json=cuerpo, headers={VERSION: "1"})
    assert respuesta.status_code == 412, respuesta.text
    despues = personas[0].get(ruta).json()
    assert (despues["activo"], despues["piso_codigo"], despues["modelo"]) == (True, "P01", "cambio ajeno")


def test_no_se_restaura_sobre_el_cambio_de_otra_persona(personas, edificio):
    elemento = _alta(personas[0], tipo="AP")
    ruta = f"{API}/elementos/{elemento['id']}"
    baja = personas[0].delete(ruta).json()
    assert personas[1].post(f"{ruta}/restaurar").status_code == 200
    tarde = personas[0].post(f"{ruta}/restaurar", headers={VERSION: str(baja["version"])})
    assert tarde.status_code == 412


def test_sin_decir_la_version_no_se_comprueba(personas, edificio):
    # Lo que necesitan los programas que cambian un elemento sin haberlo mostrado.
    elemento = _alta(personas[0], tipo="AP")
    ruta = f"{API}/elementos/{elemento['id']}"
    personas[1].patch(ruta, json={"modelo": "uno"})
    assert personas[0].patch(ruta, json={"modelo": "dos"}).status_code == 200
    assert personas[0].patch(ruta, json={"modelo": "tres"}, headers={VERSION: "no-es-numero"}).status_code == 200


# --- Quién hizo cada cambio --------------------------------------------------------------


def test_el_historial_anota_la_cuenta_si_no_se_escribe_un_nombre(personas, edificio, monkeypatch):
    monkeypatch.setattr(
        configuracion, "usuarios", {"otra-cuenta": UsuarioAdicional(clave_hash=cifrar_clave("clave-inventada"))}
    )
    otra = _persona("otra-cuenta")
    elemento = _alta(otra, tipo="AP")
    ruta = f"{API}/elementos/{elemento['id']}"
    otra.patch(ruta, json={"marca": "sin nombre"})
    otra.patch(ruta, json={"modelo": "con nombre", "usuario": "Técnico en terreno"})
    personas[0].patch(ruta, json={"numero_serie": "del administrador"})

    quien = {h["campo"]: h["usuario"] for h in otra.get(f"{ruta}/historial").json()}
    assert quien["alta"] == "otra-cuenta"
    assert quien["marca"] == "otra-cuenta"
    assert quien["modelo"] == "Técnico en terreno"
    assert quien["numero_serie"] == "admin-netdoc"


# --- Ver lo que hacen los demás ----------------------------------------------------------


def test_la_marca_del_edificio_cambia_con_cada_cambio_y_solo_entonces(personas, edificio):
    def marca() -> str:
        return personas[1].get(f"{API}/edificios/VAR/novedades").json()["marca"]

    inicial = marca()
    assert marca() == inicial
    assert personas[1].get(f"{API}/elementos/mapa?edificio=VAR&piso=P01").json()["marca"] == inicial

    elemento = _alta(personas[0], tipo="AP")
    tras_alta = marca()
    assert tras_alta != inicial
    ruta = f"{API}/elementos/{elemento['id']}"
    personas[0].patch(ruta, json={"marca": "x"})
    tras_edicion = marca()
    personas[0].delete(ruta)
    tras_baja = marca()
    assert len({inicial, tras_alta, tras_edicion, tras_baja}) == 4
    # Lo de otro edificio no la mueve.
    personas[0].post(f"{API}/elementos", json={"tipo": "AP", "edificio": "CADI", "piso": "P01", "tramo": "T1"})
    assert marca() == tras_baja


def test_preguntar_por_novedades_no_mantiene_viva_la_sesion(edificio):
    persona = _persona()
    token = persona.cookies[COOKIE_HTTP]
    hace_un_rato = time.time() - 10 * 60

    def ultimo_uso() -> float:
        with SesionLocal() as bd:
            return bd.scalar(select(SesionAcceso.ultimo_uso).order_by(SesionAcceso.id.desc()))

    with SesionLocal() as bd:
        del token
        fila = bd.scalar(select(SesionAcceso.id).order_by(SesionAcceso.id.desc()))
        bd.execute(update(SesionAcceso).where(SesionAcceso.id == fila).values(ultimo_uso=hace_un_rato))
        bd.commit()

    assert persona.get(f"{API}/edificios/VAR/novedades").status_code == 200
    assert ultimo_uso() == hace_un_rato
    assert persona.get(f"{API}/edificios/VAR").status_code == 200
    assert ultimo_uso() > hace_un_rato


def test_la_sesion_vencida_tampoco_revive_preguntando(edificio):
    persona = _persona()
    with SesionLocal() as bd:
        fila = bd.scalar(select(SesionAcceso.id).order_by(SesionAcceso.id.desc()))
        vencida = time.time() - (configuracion.sesion_inactividad_minutos + 1) * 60
        bd.execute(update(SesionAcceso).where(SesionAcceso.id == fila).values(ultimo_uso=vencida))
        bd.commit()
    assert persona.get(f"{API}/edificios/VAR/novedades").status_code == 401


# --- El turno de escritura ---------------------------------------------------------------


def test_lo_guardado_ya_esta_confirmado_cuando_llega_la_respuesta(personas, edificio):
    # Con la confirmación después de responder, otra persona podía no verlo todavía.
    vistos = []

    def al_responder(respuesta):
        codigo = respuesta.json().get("codigo")
        with SesionLocal() as bd:
            vistos.append(bd.scalar(select(Elemento.id).where(Elemento.codigo == codigo)) is not None)

    persona = _persona()
    persona.event_hooks["response"] = [lambda r: (r.read(), al_responder(r))]
    assert persona.post(f"{API}/elementos", json={"tipo": "AP", "edificio": "VAR", "piso": "P01"}).status_code == 201
    assert vistos == [True]


def test_las_escrituras_esperan_su_turno_y_las_lecturas_no(personas, edificio):
    elemento = _alta(personas[0], tipo="AP")
    ruta = f"{API}/elementos/{elemento['id']}"
    momentos = {}

    def escribir():
        momentos["escritura"] = personas[1].patch(ruta, json={"marca": "en espera"}).status_code
        momentos["fin"] = time.monotonic()

    # Algo de fuera de la API tiene el turno, como una importación en curso…
    with SesionLocal() as importacion:
        tomar_turno_de_escritura(importacion)
        hilo = threading.Thread(target=escribir)
        hilo.start()
        time.sleep(0.3)
        # …y mientras tanto no se puede escribir, pero sí consultar.
        assert "escritura" not in momentos
        inicio = time.monotonic()
        assert personas[2].get(ruta).status_code == 200
        assert personas[2].get(f"{API}/elementos/mapa?edificio=VAR&piso=P01").status_code == 200
        assert time.monotonic() - inicio < 2
        assert "escritura" not in momentos
        importacion.rollback()
        soltado = time.monotonic()
    hilo.join(timeout=20)
    assert momentos["escritura"] == 200
    assert momentos["fin"] >= soltado
