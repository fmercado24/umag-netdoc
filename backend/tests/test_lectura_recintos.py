"""Salas con la nomenclatura de cada plano: leerlas con OCR y ubicar en ellas.

El CADI numera sus salas por piso (1083 en el primero); la Biblioteca pone la
categoría, un número de dos cifras que empieza de nuevo en cada piso y el
nombre debajo (``E.`` / ``09`` / ``Oficina administrativa``).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import configuracion
from app.db.session import SesionLocal
from app.models import Edificio, Elemento, Piso, Plano, Recinto
from app.servicios import lectura_recintos
from app.servicios.novedades import marca_del_edificio
from app.servicios.ocr_recintos import (
    Interpretacion,
    Lectura,
    LecturaDeLamina,
    RecintoLeido,
    Relector,
    como_codigo,
    interpretar,
    reconocer_rotulado,
    releer_sin_numero,
)
from app.servicios.recintos import (
    buscar_codigo,
    clave_de_codigo,
    normalizar_codigo,
    numero_de_recinto,
)

API = "/api/v1"


# --------------------------------------------------------------------------
# Códigos
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("09", "09"),
        ("25A", "25A"),
        ("25a", "25A"),
        ("O9", "09"),
        ("OO17", "0017"),
        ("1083,2", "1083.2"),
        ("B-101", "B-101"),
        # Nombres, categorías y superficies no son códigos.
        ("SALA 1", None),
        ("Il", None),
        ("E.", None),
        ("12,68 m²", None),
        ("Sala estudio", None),
    ],
)
def test_como_codigo_acepta_cualquier_nomenclatura(texto, esperado):
    assert como_codigo(texto) == esperado


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("09", "09"), (" 25a ", "25A"), ("1083,2", "1083.2"), ("B-101", "B-101"), ("sala", None), ("#$", None)],
)
def test_normalizar_codigo(valor, esperado):
    assert normalizar_codigo(valor) == esperado


def test_un_codigo_se_reconoce_aunque_se_escriba_distinto():
    conocidos = ["01", "09", "25A"]
    assert clave_de_codigo("09") == clave_de_codigo("9") == "9"
    assert buscar_codigo("9", conocidos) == "09"
    assert buscar_codigo("25a", conocidos) == "25A"
    assert buscar_codigo("10", conocidos) is None


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Oficina administrativa 09", "09"),
        ("Sala de reunión 25A", "25A"),
        # La nomenclatura completa de la nota de las láminas de la Biblioteca.
        ("BC-01-09-E", "09"),
        ("oficina 25a", "25A"),
        # En un texto libre, el código va como en la lámina: «Piso 1» no es la 01.
        ("Sala 9", None),
        ("Piso 1, oficina", None),
        ("Oficina 1083", None),
        ("Sala Eléctrica", None),
    ],
)
def test_numero_de_recinto_con_los_codigos_del_piso(texto, esperado):
    assert numero_de_recinto(texto, "P01", ["01", "09", "25A"]) == esperado


def test_numero_de_recinto_con_la_numeracion_del_cadi():
    # Con salas numeradas por piso, vale lo de siempre.
    assert numero_de_recinto("Oficina 1083", "P01", ["1083", "1090"]) == "1083"
    assert numero_de_recinto("Box 2022", "P01", ["1083"]) is None


# --------------------------------------------------------------------------
# Leer la lámina
# --------------------------------------------------------------------------
def _l(texto, x, y, ancho=12, alto=9):
    return Lectura(texto, x, y, x + ancho, y + alto)


def _rotulo_biblioteca(categoria, codigo, nombre, x, y, *, con_codigo=True):
    """Como en la Biblioteca: categoría, código y nombre debajo, centrados en x."""
    ancho_nombre = len(nombre) * 4.5
    lecturas = [
        _l(categoria, x - 4, y, ancho=8),
        _l(nombre, x - ancho_nombre / 2, y + 26, ancho=ancho_nombre),
    ]
    if con_codigo:
        lecturas.append(_l(codigo, x - len(codigo) * 3, y + 13, ancho=len(codigo) * 6))
    return lecturas


def _lamina_biblioteca():
    return [
        *_rotulo_biblioteca("E.", "09", "Oficina administrativa", 200, 100),
        *_rotulo_biblioteca("K.", "02", "Circulacion", 400, 100),
        *_rotulo_biblioteca("G.", "25A", "Sala reunion", 600, 100),
        *_rotulo_biblioteca("J.", "06", "Bodega", 800, 100),
        _l("12,68 m²", 790, 139, ancho=20),
        # La palabra del nombre que el OCR leyó aparte.
        *_rotulo_biblioteca("A.", "45", "estudio", 1000, 100),
        _l("Sala", 975, 126, ancho=16),
        # La viñeta y el título, que no son salas.
        _l("FECHA", 1500, 600, ancho=25),
        _l("2025", 1502, 612, ancho=20),
        _l("A4", 1450, 612),
        _l("PLANTA 1 NIVEL (CÓDIGO 01)", 300, 650, ancho=300, alto=22),
        _l("01", 520, 650, alto=22),
    ]


def test_la_lamina_de_la_biblioteca_se_lee_con_su_nomenclatura():
    interpretacion = interpretar(_lamina_biblioteca(), "P01")

    rotulado = interpretacion.rotulado
    assert (rotulado.por_piso, rotulado.nombre_debajo, rotulado.forma) == (False, True, (False, 2))
    por_codigo = {r.numero: r for r in interpretacion.recintos}
    assert set(por_codigo) == {"09", "02", "25A", "06", "45"}
    assert por_codigo["09"].nombre == "Oficina administrativa"
    assert por_codigo["25A"].nombre == "Sala reunion"
    # La superficie no es parte del nombre, y las palabras sueltas se juntan.
    assert por_codigo["06"].nombre == "Bodega"
    assert por_codigo["45"].nombre == "Sala estudio"
    # El punto queda bajo todo el rótulo: con el nombre debajo, bajo el nombre.
    assert (por_codigo["09"].x, por_codigo["09"].y) == (200.0, 144.0)
    assert interpretacion.avisos == []


def test_la_simbologia_repetida_no_cambia_la_numeracion_por_piso():
    lecturas = [
        _l("SECRETARÍA", 92, 100, ancho=40),
        _l("1082", 104, 109),
        _l("SALA", 300, 300, ancho=20),
        _l("1060", 302, 309),
    ]
    # «F.0» con «CCTV IP» debajo, en cada cámara.
    for x in range(500, 1000, 100):
        lecturas += [_l("F.0", x, 500), _l("CCTV IP", x - 5, 510, ancho=30)]
    rotulado = reconocer_rotulado(lecturas, "P01")
    assert rotulado.por_piso is True
    assert {r.numero for r in interpretar(lecturas, "P01").recintos} == {"1082", "1060"}


class RelectorFalso(Relector):
    """Responde con lo que «se ve» en cada región."""

    def __init__(self, visibles):
        self.visibles = visibles
        self.regiones = []

    def leer_varios(self, regiones, factor):
        self.regiones += regiones
        return [
            [l for l in self.visibles if r[0] <= l.centro[0] <= r[2] and r[1] <= l.centro[1] <= r[3]]
            for r in regiones
        ]


def test_la_segunda_lectura_busca_el_codigo_que_falta_sobre_su_nombre():
    lecturas = [
        *_lamina_biblioteca(),
        # El 39, tapado por una silla en la primera pasada.
        *_rotulo_biblioteca("A.", "39", "Sala estudio", 1200, 100, con_codigo=False),
        # Un nombre sin código y otro cuyo «código» es de otra forma o ya está.
        *_rotulo_biblioteca("D.", "", "Deposito", 1400, 100, con_codigo=False),
        *_rotulo_biblioteca("E.", "", "Lectura", 1600, 100, con_codigo=False),
    ]
    interpretacion = interpretar(lecturas, "P01")
    assert "39" not in {r.numero for r in interpretacion.recintos}
    relector = RelectorFalso([_l("39", 1194, 113), _l("2024", 1390, 113, ancho=20), _l("09", 1594, 113)])

    hallados = releer_sin_numero(
        relector, lecturas, interpretacion, "P01", {r.numero for r in interpretacion.recintos}
    )
    assert [(r.numero, r.nombre) for r in hallados] == [("39", "Sala estudio")]
    assert relector.regiones  # se leyó de nuevo, en un solo pedido


def test_leer_varios_devuelve_cada_lectura_a_su_trozo():
    np = pytest.importorskip("numpy")
    # Una lámina de 400 × 200 unidades dibujada a 800 × 400 px.
    matriz = np.full((400, 800, 3), 255, dtype=np.uint8)
    matriz[100:120, 100:140] = 0
    matriz[300:320, 600:640] = 0
    llamadas = []

    def ocr(imagen):
        """Una caja por cada mancha oscura, de izquierda a derecha."""
        llamadas.append(imagen.shape)
        oscuras = (imagen.min(axis=2) < 128).any(axis=0)
        cajas, x = [], 0
        while x < len(oscuras):
            if oscuras[x]:
                fin = x
                while fin < len(oscuras) and oscuras[fin]:
                    fin += 1
                filas = np.where((imagen[:, x:fin].min(axis=2) < 128).any(axis=1))[0]
                y0, y1 = int(filas[0]), int(filas[-1]) + 1
                cajas.append([[[x, y0], [fin, y0], [fin, y1], [x, y1]], f"T{len(cajas)}", 0.9])
                x = fin
            x += 1
        return cajas, None

    relector = Relector(matriz, 400, ocr)
    leidas = relector.leer_varios(
        [
            (40, 40, 80, 70),  # la primera mancha
            (200, 10, 250, 30),  # en blanco: no se lee
            (290, 140, 330, 170),  # la segunda
            (60, 40, 100, 70),  # corta la primera: lo cortado no vale
        ],
        factor=3,
    )
    assert len(llamadas) == 1  # todo en una pasada
    assert [(round(l.x0), round(l.y0), round(l.x1), round(l.y1)) for l in leidas[0]] == [(50, 50, 70, 60)]
    assert leidas[1] == []
    assert [(round(l.x0), round(l.y0)) for l in leidas[2]] == [(300, 150)]
    assert leidas[3] == []


# --------------------------------------------------------------------------
# N° de recinto de los elementos
# --------------------------------------------------------------------------
_contador = iter(range(1, 1000))


@pytest.fixture
def edificio(cliente) -> str:
    codigo = "LEC" + "".join(chr(65 + int(c)) for c in f"{next(_contador):03d}")
    respuesta = cliente.post(f"{API}/edificios", json={"codigo": codigo, "nombre": f"Lectura {codigo}"})
    assert respuesta.status_code == 201, respuesta.text
    cliente.post(f"{API}/edificios/{codigo}/pisos", json={"codigo": "P01", "orden": 1})
    return codigo


def _lamina(sesion, edificio, piso="P01", salas=(), **campos):
    piso_id = sesion.scalar(
        select(Piso.id).join(Piso.edificio).where(Piso.codigo == piso, Piso.edificio.has(codigo=edificio))
    )
    plano = Plano(
        piso_id=piso_id,
        nombre=f"{edificio} {piso}",
        archivo=f"planos/{edificio}-{piso}.svg",
        ancho_px=1000,
        alto_px=700,
        **campos,
    )
    plano.recintos = [
        Recinto(numero=numero, nombre=nombre, pos_x=100 + 50 * i, pos_y=100)
        for i, (numero, nombre) in enumerate(salas)
    ]
    sesion.add(plano)
    sesion.commit()
    return plano.id


SALAS_BIBLIOTECA = [("01", "Mampara"), ("09", "Oficina administrativa"), ("25A", "Sala reunion")]


def _alta(cliente, edificio, **datos):
    return cliente.post(f"{API}/elementos", json={"tipo": "AP", "edificio": edificio, "piso": "P01", **datos})


@pytest.mark.parametrize(
    ("escrito", "guardado", "ubicado"),
    [
        ("9", "09", True),
        ("25a", "25A", True),
        ("BC-01-09-E", "09", True),
        # En el campo sí se escribe un código a propósito.
        ("Sala 9", "09", True),
        # No está en la lámina (el OCR no lo leyó): se acepta y se ubica con un clic.
        ("77", "77", False),
        ("Sala 77", "77", False),
    ],
)
def test_el_numero_de_recinto_se_guarda_como_lo_escribe_el_plano(
    cliente, sesion, edificio, escrito, guardado, ubicado
):
    plano_id = _lamina(sesion, edificio, salas=SALAS_BIBLIOTECA)
    respuesta = _alta(cliente, edificio, numero_recinto=escrito)
    assert respuesta.status_code == 201, respuesta.text
    creado = respuesta.json()
    assert creado["numero_recinto"] == guardado
    assert (creado["plano_id"] == plano_id) is ubicado


def test_un_codigo_imposible_se_rechaza_con_ejemplos_del_plano(cliente, sesion, edificio):
    _lamina(sesion, edificio, salas=SALAS_BIBLIOTECA)
    respuesta = _alta(cliente, edificio, numero_recinto="#$%")
    assert respuesta.status_code == 422
    assert "como aparece en el plano, como 01 o 09" in respuesta.json()["detail"][0]["msg"]


def test_sin_salas_leidas_se_acepta_el_codigo_del_plano(cliente, edificio):
    respuesta = _alta(cliente, edificio, numero_recinto="09")
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["numero_recinto"] == "09"


def test_la_ubicacion_trae_el_codigo_de_la_sala(cliente, sesion, edificio):
    plano_id = _lamina(sesion, edificio, salas=SALAS_BIBLIOTECA)
    creado = _alta(cliente, edificio, ubicacion_descriptiva="Oficina administrativa 09").json()
    assert (creado["numero_recinto"], creado["plano_id"]) == ("09", plano_id)


def test_en_un_piso_nuevo_del_cadi_rige_su_numeracion(cliente, sesion, edificio):
    # Las salas del primer piso siguen la numeración por piso: también el segundo.
    _lamina(sesion, edificio, salas=[("1083", "OFICINA"), ("1090", "BODEGA")])
    cliente.post(f"{API}/edificios/{edificio}/pisos", json={"codigo": "P02", "orden": 2})
    malo = _alta(cliente, edificio, piso="P02", numero_recinto="1045")
    assert malo.status_code == 422
    assert "empiezan con 2" in malo.json()["detail"][0]["msg"]
    assert _alta(cliente, edificio, piso="P02", numero_recinto="2045").status_code == 201


# --------------------------------------------------------------------------
# Leer las salas de los planos cargados desde el visor
# --------------------------------------------------------------------------
def _svg() -> bytes:
    return b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 700"><rect width="9"/></svg>'


def _cargar(cliente, edificio, nombre=None):
    nombre = nombre or f"{edificio.lower()}-p01.svg"
    respuesta = cliente.post(
        f"{API}/edificios/{edificio}/carga-de-planos", files={"archivo": (nombre, _svg(), "image/svg+xml")}
    )
    assert respuesta.status_code == 201, respuesta.text
    return cliente.post(f"{API}/edificios/{edificio}/carga-de-planos/confirmar")


@pytest.fixture
def vacio(cliente) -> str:
    """Un edificio sin pisos, para cargar sus planos desde el visor."""
    codigo = "OCR" + "".join(chr(65 + int(c)) for c in f"{next(_contador):03d}")
    assert cliente.post(f"{API}/edificios", json={"codigo": codigo, "nombre": codigo}).status_code == 201
    return codigo


LEIDO = LecturaDeLamina(
    recintos=[
        RecintoLeido("09", "Oficina administrativa", 120.0, 140.0),
        RecintoLeido("25A", "Sala reunion", 300.0, 140.0),
    ],
    releidos=0,
    racks=[RecintoLeido("R01", "RACK 01", 500.0, 300.0)],
    avisos=[],
    rotulado=None,
)


@pytest.fixture
def ocr_falso(monkeypatch):
    """Un OCR que «lee» LEIDO, y lo que se le pidió leer."""
    monkeypatch.setattr(configuracion, "leer_recintos", True)
    monkeypatch.setattr(lectura_recintos, "hay_ocr", lambda: True)
    pedidos = []

    def leer(encargo):
        pedidos.append(encargo)
        if isinstance(ocr_falso_respuesta[0], Exception):
            raise ocr_falso_respuesta[0]
        return ocr_falso_respuesta[0]

    ocr_falso_respuesta = [LEIDO]
    monkeypatch.setattr(lectura_recintos, "leer", leer)
    return pedidos, ocr_falso_respuesta


def _plano(cliente, edificio):
    return cliente.get(f"{API}/edificios/{edificio}/pisos/P01/plano").json()


def test_al_confirmar_la_carga_se_leen_las_salas(cliente, vacio, ocr_falso, monkeypatch):
    pedidos, _ = ocr_falso
    # La marca de novedades mientras se lee: el plano ya está, sin salas.
    marcas = []
    leer = lectura_recintos.leer

    def leer_y_anotar(encargo):
        with SesionLocal() as bd:
            edificio = bd.scalar(select(Edificio).where(Edificio.codigo == vacio))
            marcas.append(marca_del_edificio(bd, edificio))
        return leer(encargo)

    monkeypatch.setattr(lectura_recintos, "leer", leer_y_anotar)
    assert _cargar(cliente, vacio).status_code == 200

    # Las tareas de fondo de TestClient corren antes de volver.
    assert [(p.piso, p.ancho, p.alto) for p in pedidos] == [("P01", 1000, 700)]
    plano = _plano(cliente, vacio)
    assert (plano["lectura_recintos"], plano["cantidad_recintos"]) == ("lista", 3)
    assert plano["lectura_aviso"] == "2 salas y 1 rack leídos del plano"
    recintos = cliente.get(f"{API}/edificios/{vacio}/pisos/P01/recintos").json()
    assert [(r["numero"], r["nombre"]) for r in recintos] == [
        ("09", "Oficina administrativa"),
        ("25A", "Sala reunion"),
        ("R01", "RACK 01"),
    ]
    # Al terminar cambia: el visor vuelve a pedir el plano y ve las salas.
    assert cliente.get(f"{API}/edificios/{vacio}/novedades").json()["marca"] != marcas[0]

    # Con las salas leídas, el N° de recinto ubica al elemento.
    creado = cliente.post(
        f"{API}/elementos", json={"tipo": "AP", "edificio": vacio, "piso": "P01", "numero_recinto": "9"}
    ).json()
    assert (creado["numero_recinto"], creado["plano_id"]) == ("09", plano["id"])


def test_lo_escrito_antes_de_leer_las_salas_queda_en_su_sala_al_leerlas(cliente, sesion, vacio, ocr_falso):
    _, respuesta = ocr_falso
    respuesta[0] = RuntimeError("todavía no")
    _cargar(cliente, vacio)
    plano = _plano(cliente, vacio)
    assert plano["lectura_recintos"] == "fallida" and "todavía no" in plano["lectura_aviso"]

    completo = cliente.post(
        f"{API}/elementos",
        json={"tipo": "AP", "edificio": vacio, "piso": "P01", "numero_recinto": "BC-01-09-E"},
    ).json()
    por_ubicacion = cliente.post(
        f"{API}/elementos",
        json={"tipo": "SW", "edificio": vacio, "piso": "P01", "ubicacion_descriptiva": "Sala de reunión 25A"},
    ).json()
    assert (completo["numero_recinto"], completo["plano_id"]) == ("BC-01-09-E", None)
    assert (por_ubicacion["numero_recinto"], por_ubicacion["plano_id"]) == (None, None)

    respuesta[0] = LEIDO
    pedido = cliente.post(f"{API}/edificios/{vacio}/planos/{plano['id']}/leer-recintos")
    assert pedido.status_code == 200, pedido.text
    assert _plano(cliente, vacio)["lectura_recintos"] == "lista"
    sesion.expire_all()
    for codigo, numero in ((completo["codigo"], "09"), (por_ubicacion["codigo"], "25A")):
        elemento = sesion.scalar(select(Elemento).where(Elemento.codigo == codigo))
        assert (elemento.numero_recinto, elemento.plano_id) == (numero, plano["id"])


def test_sin_ocr_lo_dice_y_no_deja_pedirlo(cliente, vacio, ocr_falso, monkeypatch):
    pedidos, _ = ocr_falso
    monkeypatch.setattr(lectura_recintos, "hay_ocr", lambda: False)
    _cargar(cliente, vacio)
    plano = _plano(cliente, vacio)
    assert plano["lectura_recintos"] == "sin_ocr"
    assert "no tiene instalado el OCR" in plano["lectura_aviso"]
    assert pedidos == []

    pedido = cliente.post(f"{API}/edificios/{vacio}/planos/{plano['id']}/leer-recintos")
    assert pedido.status_code == 409
    assert "instalar-servidor.sh" in pedido.json()["detail"]


def test_lo_que_viene_del_csv_no_se_relee_desde_el_visor(cliente, sesion, edificio, ocr_falso):
    plano_id = _lamina(sesion, edificio, salas=[("1083", "OFICINA")])
    pedido = cliente.post(f"{API}/edificios/{edificio}/planos/{plano_id}/leer-recintos")
    assert pedido.status_code == 409
    assert f"{edificio.lower()}-recintos.csv" in pedido.json()["detail"]
    # Ni el de otro edificio.
    otro = cliente.post(f"{API}/edificios/CADI/planos/{plano_id}/leer-recintos")
    assert otro.status_code == 404


def test_al_arrancar_se_leen_las_que_quedaron_pendientes(sesion, edificio, ocr_falso):
    pedidos, _ = ocr_falso
    # Un plano a medio leer cuando se reinició la API (el archivo debe existir).
    archivo = configuracion.dir_media / "planos" / f"{edificio}-P01.svg"
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_bytes(_svg())
    plano_id = _lamina(sesion, edificio, lectura_recintos="leyendo")

    lectura_recintos.retomar_pendientes()
    # La base de pruebas es compartida: puede haber otros planos pendientes.
    assert [p.piso for p in pedidos if p.ruta == str(archivo)] == ["P01"]
    sesion.expire_all()
    plano = sesion.get(Plano, plano_id)
    assert (plano.lectura_recintos, len(plano.recintos)) == ("lista", 3)


def test_lo_leido_de_un_archivo_que_cambio_se_descarta(cliente, vacio, ocr_falso):
    original = lectura_recintos.leer

    def leer_y_cambiar(encargo):
        from pathlib import Path

        Path(encargo.ruta).write_bytes(_svg() + b"<!-- otra -->")
        return original(encargo)

    lectura_recintos.leer = leer_y_cambiar
    try:
        _cargar(cliente, vacio)
    finally:
        lectura_recintos.leer = original
    plano = _plano(cliente, vacio)
    assert (plano["lectura_recintos"], plano["cantidad_recintos"]) == ("pendiente", 0)


def test_interpretacion_vacia_sin_rotulos():
    assert interpretar([_l("PLANTA", 10, 10, ancho=40)], "P01") == Interpretacion()


def test_lo_que_carga_la_terminal_sin_su_archivo_de_recintos_se_lee_al_arrancar(
    cliente, edificio, tmp_path, monkeypatch, capsys
):
    from app.scripts import cargar_planos
    from app.servicios.planos import quitar_caracteres_de_control
    from app.servicios.recintos import FilaRecinto, escribir_recintos, huella_lamina

    monkeypatch.setattr(configuracion, "leer_recintos", True)
    nombre = f"{edificio.lower()}-p01.svg"
    (tmp_path / "planos").mkdir()
    (tmp_path / "planos" / nombre).write_bytes(_svg())
    cargar_planos.main([edificio, "--planos", str(tmp_path / "planos")])
    assert "NetDoc las leerá con OCR al arrancar" in capsys.readouterr().out
    plano = _plano(cliente, edificio)
    assert (plano["lectura_recintos"], plano["cantidad_recintos"]) == ("pendiente", 0)

    # Cuando llega su archivo de recintos, valen esos: ya no es una lectura del sistema.
    huella = huella_lamina(quitar_caracteres_de_control(_svg()))
    escribir_recintos(
        tmp_path / f"{edificio.lower()}-recintos.csv",
        [FilaRecinto(nombre, "09", "OFICINA", 100, 100, huella)],
    )
    cargar_planos.main([edificio, "--planos", str(tmp_path / "planos")])
    plano = _plano(cliente, edificio)
    assert (plano["lectura_recintos"], plano["cantidad_recintos"]) == (None, 1)
