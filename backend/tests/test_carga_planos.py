"""Cargar y quitar los planos de un edificio sin elementos, desde el visor."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import UsuarioAdicional, configuracion
from app.db.session import SesionLocal
from app.main import app
from app.models import Piso, Plano, Tramo
from app.servicios.autenticacion import abrir_sesion, cifrar_clave
from app.servicios.planos import NOMENCLATURA
from app.servicios.proteccion import COOKIE_HTTP
from tests.conftest import EQUIPO_LOCAL

API = "/api/v1"


def svg(ancho: int = 1000, alto: int = 700) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ancho} {alto}">'
        '<rect width="10" height="10"/></svg>'
    ).encode()


_contador = iter(range(1, 1000))


@pytest.fixture
def edificio(cliente) -> str:
    """Un edificio recién creado, sin nada."""
    codigo = "VAC" + "".join(chr(65 + int(c)) for c in f"{next(_contador):03d}")
    respuesta = cliente.post(f"{API}/edificios", json={"codigo": codigo, "nombre": f"Vacío {codigo}"})
    assert respuesta.status_code == 201, respuesta.text
    return codigo


def _estado(cliente, edificio, *archivos):
    return cliente.get(f"{API}/edificios/{edificio}/carga-de-planos", params={"archivo": list(archivos)}).json()


def _subir(cliente, edificio, nombre, contenido=None, tipo="image/svg+xml"):
    return cliente.post(
        f"{API}/edificios/{edificio}/carga-de-planos",
        files={"archivo": (nombre, svg() if contenido is None else contenido, tipo)},
    )


def _confirmar(cliente, edificio):
    return cliente.post(f"{API}/edificios/{edificio}/carga-de-planos/confirmar")


# --- Cuándo se puede -------------------------------------------------------------------


def test_un_edificio_vacio_puede_cargar_planos_y_sabe_como_llamarlos(cliente, edificio):
    estado = _estado(cliente, edificio)
    p = edificio.lower()
    assert estado["permitida"] is True and estado["motivo"] is None
    assert estado["nomenclatura"] == NOMENCLATURA.replace("cadi", p)
    assert [e["nombre"] for e in estado["ejemplos"]] == [f"{p}-p01-t1.svg", f"{p}-p01-t2.svg", f"{p}-p02.svg", f"{p}-p00.svg"]
    assert estado["ejemplos"][0]["destino"] == "Piso 1, tramo 1"
    # El nombre de un edificio con un solo plano.
    assert estado["unico"] == f"{p}-p01.svg"
    assert estado["pendientes"] == []


def test_un_edificio_con_elementos_no_puede(cliente, edificio):
    cliente.post(f"{API}/edificios/{edificio}/pisos", json={"codigo": "P01", "orden": 1})
    cliente.post(f"{API}/elementos", json={"tipo": "SW", "edificio": edificio, "piso": "P01"})
    estado = _estado(cliente, edificio)
    assert estado["permitida"] is False
    assert f"{edificio} ya tiene" in estado["motivo"] and "cargar_planos" in estado["motivo"]
    assert _confirmar(cliente, edificio).status_code == 409
    assert cliente.delete(f"{API}/edificios/{edificio}/planos", params={"confirmar": edificio}).status_code == 409
    assert _subir(cliente, edificio, f"{edificio.lower()}-p02.svg").status_code == 409


def test_un_edificio_con_elementos_tampoco(cliente, edificio):
    cliente.post(f"{API}/edificios/{edificio}/pisos", json={"codigo": "P01", "orden": 1})
    cliente.post(f"{API}/elementos", json={"tipo": "SW", "edificio": edificio, "piso": "P01"})
    estado = _estado(cliente, edificio)
    assert estado["permitida"] is False and "1 elemento(s)" in estado["motivo"]
    assert _subir(cliente, edificio, f"{edificio.lower()}-p01.svg").status_code == 409


def test_un_elemento_eliminado_tambien_cuenta(cliente, edificio):
    cliente.post(f"{API}/edificios/{edificio}/pisos", json={"codigo": "P01", "orden": 1})
    codigo = cliente.post(f"{API}/elementos", json={"tipo": "SW", "edificio": edificio, "piso": "P01"}).json()["codigo"]
    cliente.delete(f"{API}/elementos/{codigo}")
    assert _estado(cliente, edificio)["permitida"] is False


def test_pisos_creados_sin_nada_no_impiden_la_carga(cliente, edificio):
    cliente.post(f"{API}/edificios/{edificio}/pisos", json={"codigo": "P01", "nombre": "Planta baja", "orden": 1})
    assert _estado(cliente, edificio)["permitida"] is True


def test_exige_sesion(anonimo, edificio):
    assert anonimo.get(f"{API}/edificios/{edificio}/carga-de-planos").status_code == 401
    assert _subir(anonimo, edificio, f"{edificio.lower()}-p01.svg").status_code == 401


# --- El nombre -------------------------------------------------------------------------


def test_revisa_los_nombres_antes_de_subir(cliente, edificio):
    p = edificio.lower()
    revisados = _estado(
        cliente, edificio, f"{p}-p01-t2.svg", f"{edificio}-P00.SVG", "planta 3.svg", f"{p} 2do piso.svg", "cadi-p01.svg", f"{p}-p01.png"
    )["revisados"]
    bien_tramo, bien_sub, mal, deducible, ajeno, png = revisados
    assert (bien_tramo["nombre"], bien_tramo["piso"], bien_tramo["tramo"], bien_tramo["destino"], bien_tramo["error"]) == (
        f"{p}-p01-t2.svg", "P01", "T2", "Piso 1, tramo 2", None,
    )
    assert (bien_sub["nombre"], bien_sub["destino"]) == (f"{p}-p00.svg", "Subterráneo")
    assert mal["nombre"] is None and "no sigue la nomenclatura" in mal["error"]
    assert deducible["sugerencia"] == f"{p}-p02.svg"
    # El nombre sugerido va aparte, no repetido en el mensaje.
    assert deducible["error"] == f"«{p} 2do piso.svg» no sigue la nomenclatura."
    # Los ejemplos son los del edificio, no los del CADI.
    assert f"{p}-p01-t1.svg" in mal["error"] and "cadi" not in mal["error"]
    assert f"del edificio CADI, no de {edificio}" in ajeno["error"]
    assert "SVG" in png["error"]


@pytest.mark.parametrize(
    "nombre, codigo",
    [
        ("plano-sin-nomenclatura.svg", 422),
        ("cadi-p01.svg", 422),
        ("{p}-p1.svg", 422),
        ("{p}-p01-t01.svg", 422),
        ("{p}-p01.png", 415),
    ],
)
def test_un_archivo_mal_nombrado_se_rechaza(cliente, edificio, nombre, codigo):
    respuesta = _subir(cliente, edificio, nombre.format(p=edificio.lower()))
    assert respuesta.status_code == codigo, respuesta.text
    if nombre.startswith("plano-sin"):
        assert edificio.lower() + "-p01-t1.svg" in respuesta.json()["detail"]
    assert _estado(cliente, edificio)["pendientes"] == []


@pytest.mark.parametrize(
    "contenido, mensaje",
    [
        (b"esto no es xml", "no es XML"),
        (b"<html><body/></html>", "no un SVG"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "viewBox"),
    ],
)
def test_un_archivo_que_no_es_un_svg_util_se_rechaza(cliente, edificio, contenido, mensaje):
    respuesta = _subir(cliente, edificio, f"{edificio.lower()}-p01.svg", contenido)
    assert respuesta.status_code == 422
    assert mensaje in respuesta.json()["detail"]


# --- En espera -------------------------------------------------------------------------


def test_subir_deja_el_plano_en_espera_sin_crear_nada(cliente, edificio):
    p = edificio.lower()
    respuesta = _subir(cliente, edificio, f"{edificio}-P01-T1.SVG", svg(4768, 6740))
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json() == {
        "nombre": f"{p}-p01-t1.svg", "piso": "P01", "tramo": "T1", "destino": "Piso 1, tramo 1",
        "ancho_px": 4768, "alto_px": 6740, "bytes": len(svg(4768, 6740)),
    }
    assert [x["nombre"] for x in _estado(cliente, edificio)["pendientes"]] == [f"{p}-p01-t1.svg"]
    # Todavía no hay pisos ni planos: el edificio sigue vacío.
    assert cliente.get(f"{API}/edificios/{edificio}/pisos").json() == []
    assert _estado(cliente, edificio)["permitida"] is True


def test_subir_otra_vez_el_mismo_nombre_lo_reemplaza(cliente, edificio):
    p = edificio.lower()
    _subir(cliente, edificio, f"{p}-p02.svg", svg(100, 100))
    _subir(cliente, edificio, f"{p}-p02.svg", svg(200, 150))
    pendientes = _estado(cliente, edificio)["pendientes"]
    assert [(x["nombre"], x["ancho_px"]) for x in pendientes] == [(f"{p}-p02.svg", 200)]


def test_los_planos_en_espera_no_se_sirven(cliente, edificio):
    p = edificio.lower()
    _subir(cliente, edificio, f"{p}-p01.svg")
    assert (configuracion.dir_planos_pendientes / edificio / f"{p}-p01.svg").exists()
    for ruta in (
        f"/media/pendientes/{edificio}/{p}-p01.svg",
        f"/media/planos/../pendientes/{edificio}/{p}-p01.svg",
        f"/media/planos/%2e%2e/pendientes/{edificio}/{p}-p01.svg",
        f"/media/pendientes/{edificio}/{p}-p01.json",
    ):
        assert cliente.get(ruta).status_code == 404, ruta


def test_quitar_uno_de_la_espera(cliente, edificio):
    p = edificio.lower()
    _subir(cliente, edificio, f"{p}-p01.svg")
    _subir(cliente, edificio, f"{p}-p02.svg")
    assert cliente.delete(f"{API}/edificios/{edificio}/carga-de-planos/{p}-p01.svg").status_code == 204
    assert [x["nombre"] for x in _estado(cliente, edificio)["pendientes"]] == [f"{p}-p02.svg"]
    assert cliente.delete(f"{API}/edificios/{edificio}/carga-de-planos/{p}-p01.svg").status_code == 404


@pytest.mark.parametrize("nombre", ["..%2F..%2Fumag.db", "%2e%2e", "cualquiera.svg", "cadi-p01.svg"])
def test_quitar_no_toca_nada_fuera_de_la_espera(cliente, edificio, nombre):
    p = edificio.lower()
    _subir(cliente, edificio, f"{p}-p01.svg")
    assert cliente.delete(f"{API}/edificios/{edificio}/carga-de-planos/{nombre}").status_code == 404
    assert len(_estado(cliente, edificio)["pendientes"]) == 1


# --- Confirmar -------------------------------------------------------------------------


def test_confirmar_crea_pisos_tramos_y_planos(cliente, edificio):
    p = edificio.lower()
    for nombre, tamano in ((f"{p}-p00.svg", (900, 600)), (f"{p}-p01-t1.svg", (1000, 700)), (f"{p}-p01-t2.svg", (1200, 800)), (f"{p}-p02.svg", (800, 500))):
        assert _subir(cliente, edificio, nombre, svg(*tamano)).status_code == 201

    respuesta = _confirmar(cliente, edificio)
    assert respuesta.status_code == 200, respuesta.text
    resultado = respuesta.json()
    assert resultado["pisos"] == ["P00", "P01", "P02"]
    assert resultado["tramos"] == ["P01-T1", "P01-T2"]
    assert [x["nombre"] for x in resultado["planos"]] == [
        f"{edificio} P00 · Piso completo", f"{edificio} P01 · Tramo 1", f"{edificio} P01 · Tramo 2", f"{edificio} P02 · Piso completo",
    ]

    pisos = cliente.get(f"{API}/edificios/{edificio}/pisos").json()
    assert [(x["codigo"], x["nombre"], x["orden"]) for x in pisos] == [
        ("P00", "Subterráneo", 0), ("P01", "Primer piso", 1), ("P02", "Segundo piso", 2),
    ]
    p01 = pisos[1]
    assert [t["codigo"] for t in p01["tramos"]] == ["T1", "T2"]
    assert sorted((x["tramo_codigo"], x["ancho_px"], x["alto_px"]) for x in p01["planos_vigentes"]) == [
        ("T1", 1000, 700), ("T2", 1200, 800),
    ]
    # Los archivos quedan con el nombre de siempre, y la espera se vacía.
    archivos = [x["archivo"] for x in resultado["planos"]]
    assert f"planos/{edificio}-P01-T1-v1.svg" in archivos
    assert all((configuracion.dir_media / a).exists() for a in archivos)
    assert not (configuracion.dir_planos_pendientes / edificio).exists()
    # Sin elementos, sigue pudiendo cargar o quitar; el visor ya puede abrirlo.
    estado = _estado(cliente, edificio)
    assert estado["permitida"] is True
    assert [c["destino"] for c in estado["cargados"]] == ["Subterráneo", "Piso 1, tramo 1", "Piso 1, tramo 2", "Piso 2 completo"]
    mapa = cliente.get(f"{API}/elementos/mapa", params={"edificio": edificio, "piso": "P01", "tramo": "T1"}).json()
    assert mapa["plano"]["ancho_px"] == 1000
    assert cliente.get("/media/" + archivos[1]).content == svg(1000, 700)


def test_confirmar_aprovecha_los_pisos_que_ya_existian(cliente, edificio):
    p = edificio.lower()
    cliente.post(f"{API}/edificios/{edificio}/pisos", json={"codigo": "P01", "nombre": "Planta baja", "orden": 1})
    cliente.post(f"{API}/edificios/{edificio}/pisos/P01/tramos", json={"codigo": "T1", "nombre": "Ala norte"})
    _subir(cliente, edificio, f"{p}-p01-t1.svg")
    resultado = _confirmar(cliente, edificio).json()
    assert (resultado["pisos"], resultado["tramos"]) == ([], [])
    with SesionLocal() as bd:
        pisos = bd.scalars(select(Piso).join(Piso.edificio).where(Piso.codigo == "P01").where(Piso.edificio.has(codigo=edificio))).all()
        assert [(x.nombre, [t.nombre for t in x.tramos]) for x in pisos] == [("Planta baja", ["Ala norte"])]


def test_sin_planos_en_espera_no_hay_nada_que_confirmar(cliente, edificio):
    respuesta = _confirmar(cliente, edificio)
    assert respuesta.status_code == 409
    assert "No hay planos en espera" in respuesta.json()["detail"]


def test_si_otra_persona_agrego_un_elemento_entretanto_no_se_confirma(cliente, edificio):
    p = edificio.lower()
    _subir(cliente, edificio, f"{p}-p01.svg")
    cliente.post(f"{API}/edificios/{edificio}/pisos", json={"codigo": "P01", "orden": 1})
    cliente.post(f"{API}/elementos", json={"tipo": "SW", "edificio": edificio, "piso": "P01"})
    assert _confirmar(cliente, edificio).status_code == 409
    with SesionLocal() as bd:
        assert bd.scalar(select(Plano).join(Piso).where(Piso.edificio.has(codigo=edificio))) is None


def test_dos_confirmaciones_a_la_vez_cargan_una_sola_vez(cliente, edificio):
    p = edificio.lower()
    _subir(cliente, edificio, f"{p}-p01-t1.svg")
    _subir(cliente, edificio, f"{p}-p02.svg")
    barrera = threading.Barrier(2)
    codigos = []

    def confirmar():
        barrera.wait()
        codigos.append(_confirmar(cliente, edificio).status_code)

    hilos = [threading.Thread(target=confirmar) for _ in range(2)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert sorted(codigos) == [200, 409]
    with SesionLocal() as bd:
        planos = bd.scalars(select(Plano).join(Piso).where(Piso.edificio.has(codigo=edificio))).all()
        tramos = bd.scalars(select(Tramo).join(Piso).where(Piso.edificio.has(codigo=edificio))).all()
    assert (len(planos), len(tramos)) == (2, 1)


def test_un_usuario_limitado_carga_los_planos_de_su_edificio_si_esta_vacio(cliente, edificio, monkeypatch):
    monkeypatch.setattr(configuracion, "usuarios", {"del-vac": UsuarioAdicional(clave_hash=cifrar_clave("x" * 12), edificio=edificio)})
    with SesionLocal() as bd:
        token = abrir_sesion(bd, "pruebas", usuario="del-vac")
        bd.commit()
    propio = TestClient(app, client=EQUIPO_LOCAL, cookies={COOKIE_HTTP: token})
    assert _subir(propio, edificio, f"{edificio.lower()}-p01.svg").status_code == 201
    assert _confirmar(propio, edificio).status_code == 200
    assert propio.get(f"{API}/edificios/CADI/carga-de-planos").status_code == 403


# --- Mientras no tenga elementos: agregar los que faltan y quitar todo ---------------------


def _cargar(cliente, edificio, *nombres):
    for nombre in nombres:
        assert _subir(cliente, edificio, nombre).status_code == 201
    assert _confirmar(cliente, edificio).status_code == 200


def test_se_agregan_los_que_faltan(cliente, edificio):
    p = edificio.lower()
    _cargar(cliente, edificio, f"{p}-p01.svg")
    # Me faltaban dos.
    _cargar(cliente, edificio, f"{p}-p02.svg", f"{p}-p03-t1.svg")
    pisos = cliente.get(f"{API}/edificios/{edificio}/pisos").json()
    assert [(x["codigo"], len(x["planos_vigentes"])) for x in pisos] == [("P01", 1), ("P02", 1), ("P03", 1)]


def test_un_piso_que_ya_tiene_plano_no_se_reemplaza_desde_el_visor(cliente, edificio):
    p = edificio.lower()
    _cargar(cliente, edificio, f"{p}-p01.svg")
    revision = _estado(cliente, edificio, f"{p}-p01.svg")["revisados"][0]
    assert "ya tiene plano" in revision["error"] and "quite los planos" in revision["error"]
    respuesta = _subir(cliente, edificio, f"{p}-p01.svg")
    assert respuesta.status_code == 409
    assert "ya tiene plano" in respuesta.json()["detail"]


def test_si_otra_persona_cargo_el_mismo_piso_entretanto_no_se_confirma(cliente, edificio):
    p = edificio.lower()
    _subir(cliente, edificio, f"{p}-p01.svg")
    # Otra persona sube y confirma el mismo piso por su cuenta…
    with SesionLocal() as bd:
        from app.models import Edificio
        from app.servicios import carga_planos

        ed = bd.scalar(select(Edificio).where(Edificio.codigo == edificio))
        carga_planos.confirmar(bd, ed)
        bd.commit()
    # …y lo que dejó en espera la primera ya no se puede confirmar encima.
    _subir_directo = configuracion.dir_planos_pendientes / edificio
    _subir_directo.mkdir(parents=True, exist_ok=True)
    (_subir_directo / f"{p}-p01.svg").write_bytes(svg())
    ficha = {"nombre": f"{p}-p01.svg", "piso": "P01", "tramo": None, "destino": "Piso 1 completo",
             "ancho_px": 1000, "alto_px": 700, "bytes": 10}
    (_subir_directo / f"{p}-p01.json").write_text(json.dumps(ficha), encoding="utf-8")
    respuesta = _confirmar(cliente, edificio)
    assert respuesta.status_code == 409
    assert "ya tiene plano" in respuesta.json()["detail"]


def test_quitar_los_planos_deja_el_edificio_vacio(cliente, edificio):
    p = edificio.lower()
    _cargar(cliente, edificio, f"{p}-p00.svg", f"{p}-p01-t1.svg", f"{p}-p01-t2.svg")
    archivos = [c["archivo"] for c in _estado(cliente, edificio)["cargados"]]
    teselas = configuracion.dir_media / "teselas" / Path(archivos[0]).stem
    teselas.mkdir(parents=True, exist_ok=True)
    (teselas / "teselas.json").write_text("{}", encoding="utf-8")
    _subir(cliente, edificio, f"{p}-p02.svg")  # algo en espera, que también se descarta

    respuesta = cliente.delete(f"{API}/edificios/{edificio}/planos", params={"confirmar": edificio.lower()})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"planos": 3, "tramos": 2, "pisos": ["P00", "P01"]}

    assert cliente.get(f"{API}/edificios/{edificio}/pisos").json() == []
    estado = _estado(cliente, edificio)
    assert (estado["permitida"], estado["cargados"], estado["pendientes"]) == (True, [], [])
    assert not any((configuracion.dir_media / a).exists() for a in archivos)
    assert not teselas.exists()
    with SesionLocal() as bd:
        from app.models import Edificio

        assert bd.scalar(select(Edificio).where(Edificio.codigo == edificio)) is not None
        assert bd.scalar(select(Plano).join(Piso).where(Piso.edificio.has(codigo=edificio))) is None
    # Y se puede volver a cargar desde cero.
    _cargar(cliente, edificio, f"{p}-p01.svg")


def test_quitar_exige_escribir_el_codigo_del_edificio(cliente, edificio):
    p = edificio.lower()
    _cargar(cliente, edificio, f"{p}-p01.svg")
    for confirmar in ("", "SI", "CADI", edificio + "X"):
        respuesta = cliente.delete(f"{API}/edificios/{edificio}/planos", params={"confirmar": confirmar})
        assert respuesta.status_code == 422, confirmar
        assert edificio in respuesta.json()["detail"]
    assert cliente.delete(f"{API}/edificios/{edificio}/planos").status_code == 422
    assert len(_estado(cliente, edificio)["cargados"]) == 1


def test_quitar_sin_planos_no_hace_nada(cliente, edificio):
    respuesta = cliente.delete(f"{API}/edificios/{edificio}/planos", params={"confirmar": edificio})
    assert respuesta.status_code == 409


def test_con_un_elemento_ya_no_se_quitan_ni_se_agregan(cliente, edificio):
    p = edificio.lower()
    _cargar(cliente, edificio, f"{p}-p01.svg")
    cliente.post(f"{API}/elementos", json={"tipo": "SW", "edificio": edificio, "piso": "P01"})
    assert _estado(cliente, edificio)["permitida"] is False
    assert cliente.delete(f"{API}/edificios/{edificio}/planos", params={"confirmar": edificio}).status_code == 409
    assert _subir(cliente, edificio, f"{p}-p02.svg").status_code == 409
    assert len(cliente.get(f"{API}/edificios/{edificio}/pisos").json()) == 1


def test_quitar_no_toca_los_planos_de_otro_edificio(cliente, edificio):
    otro = edificio[:-1] + ("Z" if edificio[-1] != "Z" else "Y")
    assert cliente.post(f"{API}/edificios", json={"codigo": otro, "nombre": "Otro vacío"}).status_code == 201
    _cargar(cliente, edificio, f"{edificio.lower()}-p01.svg")
    _cargar(cliente, otro, f"{otro.lower()}-p01.svg")
    del_otro = _estado(cliente, otro)["cargados"][0]["archivo"]

    assert cliente.delete(f"{API}/edificios/{edificio}/planos", params={"confirmar": edificio}).status_code == 200
    assert _estado(cliente, otro)["cargados"][0]["archivo"] == del_otro
    assert (configuracion.dir_media / del_otro).exists()
    assert [x["codigo"] for x in cliente.get(f"{API}/edificios/{otro}/pisos").json()] == ["P01"]


def test_borrar_archivos_no_sale_de_la_carpeta_de_planos(tmp_path):
    from app.servicios.carga_planos import borrar_archivos

    afuera = configuracion.dir_media / "no-es-un-plano.txt"
    afuera.write_text("x", encoding="utf-8")
    borrar_archivos(["../no-es-un-plano.txt", "planos/../no-es-un-plano.txt", "fotografias/x.jpg"])
    assert afuera.exists()
    afuera.unlink()


def test_un_plano_vuelto_a_cargar_no_hereda_teselas_viejas(cliente, edificio):
    p = edificio.lower()
    _cargar(cliente, edificio, f"{p}-p01.svg")
    archivo = _estado(cliente, edificio)["cargados"][0]["archivo"]
    # Las teselas del primero quedaron (p. ej. se terminaron de generar después de quitarlo).
    viejas = configuracion.dir_media / "teselas" / Path(archivo).stem
    viejas.mkdir(parents=True, exist_ok=True)
    cliente.delete(f"{API}/edificios/{edificio}/planos", params={"confirmar": edificio})
    viejas.mkdir(parents=True, exist_ok=True)

    _cargar(cliente, edificio, f"{p}-p01.svg")
    nuevo = _estado(cliente, edificio)["cargados"][0]["archivo"]
    assert Path(nuevo).stem != Path(archivo).stem


def test_las_teselas_de_un_plano_ya_quitado_no_se_generan(monkeypatch):
    from app.servicios import teselas

    monkeypatch.setattr(configuracion, "teselas", True)
    llamadas = []
    monkeypatch.setattr(teselas, "ProcessPoolExecutor", lambda **k: llamadas.append(k))
    assert teselas.asegurar_teselas("planos/NOEXISTE-P01-v1.svg", 1000) is None
    assert llamadas == []
