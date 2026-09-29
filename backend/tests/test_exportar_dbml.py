"""El DBML para dbdiagram.io debe cubrir todo el esquema y estar al día en docs/."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import ForeignKeyConstraint

from app.db.base import Base
from app.scripts.exportar_dbml import generar, grupo_de

DBML_DOCS = Path(__file__).resolve().parents[2] / "docs" / "modelo-datos.dbml"


def test_toda_tabla_tiene_grupo():
    # Si falla: agregar la tabla nueva a GRUPOS en app/scripts/exportar_dbml.py.
    assert [t for t in Base.metadata.tables if grupo_de(t) == "otros"] == []


def test_incluye_tablas_relaciones_y_enums():
    dbml = generar()
    tablas = set(re.findall(r"^Table (\w+) ", dbml, re.MULTILINE))
    assert tablas == set(Base.metadata.tables)
    llaves = [
        r for t in Base.metadata.tables.values() for r in t.constraints
        if isinstance(r, ForeignKeyConstraint)
    ]
    assert len(re.findall(r"^Ref ", dbml, re.MULTILINE)) == len(llaves)
    assert "Ref fk_elemento_padre_id_elemento: elemento.padre_id > elemento.id [delete: set null]" in dbml
    assert "estado_operativo estado_operativo [not null, default: 'activo']" in dbml
    assert "(edificio_id, numero) [unique, name: 'uq_vlan_edificio_numero']" in dbml


def test_el_dbml_de_docs_esta_al_dia():
    # Si falla: python -m app.scripts.exportar_dbml -o ../docs/modelo-datos.dbml
    assert DBML_DOCS.read_text(encoding="utf-8") == generar()
