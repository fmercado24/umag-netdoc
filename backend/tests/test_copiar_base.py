"""Pasar los datos de una base a otra, como de SQLite a PostgreSQL."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import (
    Edificio,
    Elemento,
    IntentoIngreso,
    OrigenCambio,
    Piso,
    SesionAcceso,
    TipoElemento,
)
from app.models.elemento import HistorialElemento
from app.scripts import copiar_base as modulo
from app.scripts.copiar_base import DestinoConDatos, _sin_clave, copiar
from app.scripts.migrar import migrar


@pytest.fixture
def bases(tmp_path):
    origen = f"sqlite:///{tmp_path / 'origen.db'}"
    destino = f"sqlite:///{tmp_path / 'destino.db'}"
    migrar(origen)
    migrar(destino)
    motor = create_engine(origen)
    with Session(motor) as s:
        edificio = Edificio(codigo="ING", nombre="Ingeniería")
        tipo_rack = TipoElemento(codigo="R", nombre="Rack", categoria="soporte", es_contenedor=True)
        tipo_sw = TipoElemento(codigo="SW", nombre="Switch", categoria="activo")
        s.add_all([edificio, tipo_rack, tipo_sw])
        s.flush()
        piso = Piso(edificio_id=edificio.id, codigo="P01", orden=1)
        s.add(piso)
        s.flush()
        comunes = {"edificio_id": edificio.id, "piso_id": piso.id}
        # El hijo se crea primero: su padre aún no existe al copiar en orden de id.
        switch = Elemento(codigo="ING-SW01-P01", tipo_elemento_id=tipo_sw.id, atributos={"puertos": 48}, **comunes)
        s.add(switch)
        s.flush()
        rack = Elemento(codigo="ING-R01-P01", tipo_elemento_id=tipo_rack.id, **comunes)
        s.add(rack)
        s.flush()
        switch.padre_id = rack.id
        s.add(
            HistorialElemento(
                elemento_id=switch.id,
                campo="alta",
                valor_nuevo=switch.codigo,
                origen=OrigenCambio.MANUAL,
                registrado_en=dt.datetime(2026, 1, 2, 3, 4, 5),
            )
        )
        # Son de cada instalación: no se copian.
        s.add(SesionAcceso(token_hash="x" * 64, usuario="admin-netdoc", cliente="10.0.0.1", creada_en=1, ultimo_uso=1, vence_en=2))
        s.add(IntentoIngreso(cliente="10.0.0.1", ocurrido_en=1))
        s.commit()
    motor.dispose()
    return origen, destino


def test_copia_todo_incluida_la_referencia_a_la_misma_tabla(bases):
    origen, destino = bases
    copiadas = copiar(origen, destino)
    assert copiadas["elemento"] == 2

    motor = create_engine(destino)
    with Session(motor) as s:
        switch = s.scalar(select(Elemento).where(Elemento.codigo == "ING-SW01-P01"))
        assert switch.padre.codigo == "ING-R01-P01"
        assert switch.atributos == {"puertos": 48}
        assert switch.tipo.codigo == "SW"
        historial = s.scalar(select(HistorialElemento))
        assert historial.origen is OrigenCambio.MANUAL
        assert historial.registrado_en == dt.datetime(2026, 1, 2, 3, 4, 5)
    motor.dispose()


def test_las_sesiones_y_los_bloqueos_no_viajan(bases):
    origen, destino = bases
    copiar(origen, destino)
    motor = create_engine(destino)
    with Session(motor) as s:
        assert s.scalar(select(func.count()).select_from(SesionAcceso)) == 0
        assert s.scalar(select(func.count()).select_from(IntentoIngreso)) == 0
    motor.dispose()


def test_no_pisa_una_base_con_datos_salvo_que_se_pida(bases):
    origen, destino = bases
    copiar(origen, destino)
    with pytest.raises(DestinoConDatos, match="--reemplazar"):
        copiar(origen, destino)
    assert copiar(origen, destino, reemplazar=True)["elemento"] == 2


def test_si_algo_falla_el_destino_queda_como_estaba(bases, monkeypatch):
    origen, destino = bases
    copiar(origen, destino)

    def fallar(tabla):
        raise RuntimeError("falla a mitad de la copia")

    monkeypatch.setattr(modulo, "_columnas_hacia_si_misma", fallar)
    with pytest.raises(RuntimeError, match="a mitad"):
        copiar(origen, destino, reemplazar=True)

    motor = create_engine(destino)
    with Session(motor) as s:
        assert s.scalar(select(func.count()).select_from(Elemento)) == 2
    motor.dispose()


def test_la_contrasena_de_la_url_no_se_muestra():
    url = "postgresql+psycopg://netdoc:secreto@127.0.0.1:5432/umag_netdoc"
    assert "secreto" not in _sin_clave(url)
    assert _sin_clave(url).endswith("127.0.0.1:5432/umag_netdoc")
