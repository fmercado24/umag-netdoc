"""Exporta el esquema de la base en DBML, para diagramarlo en dbdiagram.io.

    python -m app.scripts.exportar_dbml                               # salida estándar
    python -m app.scripts.exportar_dbml -o ../docs/modelo-datos.dbml

Se genera desde los modelos, el mismo metadata que usa Alembic, así que
coincide con el esquema de la última migración sin importar el motor (SQLite o
PostgreSQL). Incluye tablas, tipos, llaves, índices, enumeraciones, relaciones
con su regla de borrado y la descripción de cada tabla.

Para verlo, en https://dbdiagram.io se abre el editor (*Create your diagram*)
y se pega el contenido en el panel izquierdo.
"""

from __future__ import annotations

import argparse
import re
import sys
from enum import Enum
from pathlib import Path

from sqlalchemy import Column, ForeignKeyConstraint, Table, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.schema import DefaultClause
from sqlalchemy.types import Enum as SAEnum

import app.models  # noqa: F401  (registra todas las tablas en el metadata)
from app.db.base import Base

#: Agrupación de las tablas, la misma de docs/modelo-datos.md. Una tabla nueva
#: que no esté aquí cae en «otros» (y la prueba del script lo avisa).
GRUPOS: dict[str, tuple[str, str, list[str]]] = {
    "territorio": (
        "Territorio",
        "#1e6fd9",
        ["edificio", "piso", "tramo", "plano", "recinto", "persona", "levantamiento"],
    ),
    "catalogo": ("Catálogo", "#7c3aed", ["tipo_elemento", "definicion_atributo"]),
    "elementos": ("Elementos", "#0f9d58", ["elemento", "fotografia", "historial_elemento"]),
    "logica": (
        "Lógica y conectividad",
        "#e8710a",
        ["vlan", "elemento_vlan", "enlace", "identificador_externo"],
    ),
}
GRUPO_OTROS = ("Otros", "#6b7280")

ENCABEZADO = (
    "// Generado por app.scripts.exportar_dbml a partir de los modelos: no editar a mano.\n"
    "// Pegar en https://dbdiagram.io (Create your diagram)."
)
NOTA_PROYECTO = (
    "NetDoc UMAG: documentación de la infraestructura de red de la Universidad de Magallanes. "
    "En desarrollo corre sobre SQLite; los enums se guardan como VARCHAR + CHECK."
)

SANGRIA = "  "


def _texto(valor: str) -> str:
    """Cadena DBML entre comillas simples."""
    return "'" + valor.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _nombre_enum(clase: type[Enum]) -> str:
    """CategoriaElemento → categoria_elemento."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", clase.__name__).lower()


def _descripcion(tabla: Table) -> str | None:
    """Primer párrafo del docstring del modelo, en una línea."""
    for mapper in Base.registry.mappers:
        if mapper.local_table is tabla:
            doc = (mapper.class_.__doc__ or "").strip()
            return " ".join(doc.split("\n\n")[0].split()) or None
    return None


def _tipo(columna: Column, enums: dict[str, list[str]]) -> str:
    if isinstance(columna.type, SAEnum) and columna.type.enum_class is not None:
        nombre = _nombre_enum(columna.type.enum_class)
        enums[nombre] = list(columna.type.enums)
        return nombre
    tipo = columna.type.compile(dialect=postgresql.dialect()).lower()
    tipo = tipo.replace("timestamp with time zone", "timestamptz")
    return f'"{tipo}"' if " " in tipo else tipo


def _por_omision(columna: Column) -> str | None:
    if isinstance(columna.server_default, DefaultClause):
        expresion = columna.server_default.arg
        texto = expresion if isinstance(expresion, str) else str(
            expresion.compile(dialect=postgresql.dialect())
        )
        return f"`{texto}`"
    defecto = columna.default
    if defecto is None or not getattr(defecto, "is_scalar", False):
        return None
    valor = defecto.arg
    if isinstance(valor, Enum):
        valor = valor.value
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, int | float):
        return str(valor)
    return _texto(str(valor))


def _unicas_simples(tabla: Table) -> set[str]:
    """Columnas con unicidad propia (restricción o índice de una sola columna)."""
    unicas = {
        next(iter(r.columns)).name
        for r in tabla.constraints
        if isinstance(r, UniqueConstraint) and len(r.columns) == 1
    }
    unicas |= {next(iter(i.columns)).name for i in tabla.indexes if i.unique and len(i.columns) == 1}
    return unicas


def _columna(columna: Column, unicas: set[str], enums: dict[str, list[str]]) -> str:
    ajustes: list[str] = []
    pk_simple = columna.primary_key and len(columna.table.primary_key.columns) == 1
    if pk_simple:
        ajustes.append("pk")
        if columna.autoincrement in (True, "auto") and columna.type.python_type is int:
            ajustes.append("increment")
    if not columna.nullable and not pk_simple:
        ajustes.append("not null")
    if columna.name in unicas and not pk_simple:
        ajustes.append("unique")
    if (defecto := _por_omision(columna)) is not None:
        ajustes.append(f"default: {defecto}")
    if columna.comment:
        ajustes.append(f"note: {_texto(columna.comment)}")
    sufijo = f" [{', '.join(ajustes)}]" if ajustes else ""
    return f"{SANGRIA}{columna.name} {_tipo(columna, enums)}{sufijo}"


def _indices(tabla: Table) -> list[str]:
    """Bloque ``indexes``: índices y restricciones que no caben en la columna."""
    lineas: list[str] = []

    def columnas(cols) -> str:
        nombres = [c.name for c in cols]
        return nombres[0] if len(nombres) == 1 else f"({', '.join(nombres)})"

    if len(tabla.primary_key.columns) > 1:
        lineas.append(f"{columnas(tabla.primary_key.columns)} [pk]")
    for restriccion in sorted(tabla.constraints, key=lambda r: str(r.name)):
        if isinstance(restriccion, UniqueConstraint) and len(restriccion.columns) > 1:
            lineas.append(
                f"{columnas(restriccion.columns)} [unique, name: {_texto(str(restriccion.name))}]"
            )
    for indice in sorted(tabla.indexes, key=lambda i: str(i.name)):
        if indice.unique and len(indice.columns) == 1:
            continue  # ya quedó como «unique» en la columna
        ajustes = (["unique"] if indice.unique else []) + [f"name: {_texto(str(indice.name))}"]
        lineas.append(f"{columnas(indice.columns)} [{', '.join(ajustes)}]")
    if not lineas:
        return []
    return [f"{SANGRIA}indexes {{", *(SANGRIA * 2 + l for l in lineas), f"{SANGRIA}}}"]


def _relacion(restriccion: ForeignKeyConstraint) -> str:
    origen = [c.name for c in restriccion.columns]
    destino = [e.column for e in restriccion.elements]
    tabla_destino = destino[0].table.name

    def lado(tabla: str, nombres: list[str]) -> str:
        return f"{tabla}.{nombres[0]}" if len(nombres) == 1 else f"{tabla}.({', '.join(nombres)})"

    # Una FK que además es única es 1 a 1; si no, muchos a uno.
    unica = len(origen) == 1 and origen[0] in _unicas_simples(restriccion.table)
    ajustes = f" [delete: {restriccion.ondelete.lower()}]" if restriccion.ondelete else ""
    return (
        f"Ref {restriccion.name}: {lado(restriccion.table.name, origen)} "
        f"{'-' if unica else '>'} {lado(tabla_destino, [c.name for c in destino])}{ajustes}"
    )


def grupo_de(nombre_tabla: str) -> str:
    for clave, (_, _, tablas) in GRUPOS.items():
        if nombre_tabla in tablas:
            return clave
    return "otros"


def generar() -> str:
    tablas = Base.metadata.sorted_tables
    orden = [t for _, _, nombres in GRUPOS.values() for t in nombres]
    tablas = sorted(tablas, key=lambda t: orden.index(t.name) if t.name in orden else len(orden))

    enums: dict[str, list[str]] = {}
    proyecto = (
        "Project netdoc_umag {\n"
        f"{SANGRIA}database_type: 'PostgreSQL'\n"
        f"{SANGRIA}Note: {_texto(NOTA_PROYECTO)}\n"
        "}"
    )
    bloques: list[str] = [ENCABEZADO, proyecto]

    for tabla in tablas:
        grupo = grupo_de(tabla.name)
        color = GRUPOS[grupo][1] if grupo in GRUPOS else GRUPO_OTROS[1]
        unicas = _unicas_simples(tabla)
        lineas = [f"Table {tabla.name} [headercolor: {color}] {{"]
        lineas += [_columna(c, unicas, enums) for c in tabla.columns]
        indices = _indices(tabla)
        if indices:
            lineas += ["", *indices]
        if descripcion := _descripcion(tabla):
            lineas += ["", f"{SANGRIA}Note: {_texto(descripcion)}"]
        lineas.append("}")
        bloques.append("\n".join(lineas))

    for nombre, valores in sorted(enums.items()):
        bloques.append(
            "\n".join([f"Enum {nombre} {{", *(f'{SANGRIA}"{v}"' for v in valores), "}"])
        )

    relaciones = sorted(
        (
            _relacion(r)
            for t in tablas
            for r in t.constraints
            if isinstance(r, ForeignKeyConstraint)
        ),
    )
    bloques.append("\n".join(relaciones))

    presentes = {t.name for t in tablas}
    grupos = [(clave, *datos) for clave, datos in GRUPOS.items()]
    otros = [t.name for t in tablas if grupo_de(t.name) == "otros"]
    if otros:
        grupos.append(("otros", *GRUPO_OTROS, otros))
    for clave, titulo, color, nombres in grupos:
        miembros = [n for n in nombres if n in presentes]
        if miembros:
            bloques.append(
                "\n".join(
                    [
                        f"TableGroup {clave} [color: {color}] {{",
                        *(SANGRIA + n for n in miembros),
                        f"{SANGRIA}Note: {_texto(titulo)}",
                        "}",
                    ]
                )
            )

    return "\n\n".join(bloques) + "\n"


def main(argumentos: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Exporta el esquema en DBML (dbdiagram.io)")
    parser.add_argument("-o", "--salida", type=Path, help="Archivo de salida (por omisión, pantalla)")
    args = parser.parse_args(argumentos)
    dbml = generar()
    if args.salida:
        args.salida.write_text(dbml, encoding="utf-8")
        print(f"Esquema exportado a {args.salida}", file=sys.stderr)
    else:
        sys.stdout.write(dbml)


if __name__ == "__main__":
    main()
