"""Sincroniza el inventario con un sistema externo.

    python -m app.scripts.sincronizar zabbix              # muestra el plan
    python -m app.scripts.sincronizar zabbix --aplicar    # lo ejecuta
    python -m app.scripts.sincronizar zabbix --edificio CADI

Por omisión no modifica nada: compara y muestra qué crearía o actualizaría.
Con ``--aplicar`` ejecuta el plan y guarda en NetDoc el id que el sistema
asignó a cada elemento (``identificador_externo``). Si una acción falla, las
demás siguen y el error se informa al final.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SesionLocal
from app.integraciones import CONECTORES, Conector, ErrorConector
from app.models import Edificio, Elemento, IdentificadorExterno

SIMBOLOS = {"crear": "+", "actualizar": "~", "sin_cambios": "="}


def sincronizar(
    sesion: Session, conector: Conector, *, aplicar: bool = False, edificio: str | None = None
) -> dict:
    consulta = select(Elemento).where(Elemento.activo.is_(True)).order_by(Elemento.codigo)
    if edificio:
        consulta = consulta.join(Edificio, Elemento.edificio_id == Edificio.id).where(
            Edificio.codigo == edificio.upper()
        )
    elementos = conector.seleccionar(list(sesion.scalars(consulta).unique()))
    acciones = conector.planificar(elementos)

    for accion in acciones:
        if accion.tipo != "sin_cambios":
            print(f"  {SIMBOLOS[accion.tipo]} {accion.tipo:10} {accion.codigo}  {accion.detalle or ''}")
    resumen = Counter(a.tipo for a in acciones)
    print(
        f"{conector.sistema}: {resumen['crear']} por crear, {resumen['actualizar']} por "
        f"actualizar, {resumen['sin_cambios']} sin cambios ({len(elementos)} elementos)"
    )
    if not aplicar:
        return {"plan": dict(resumen), "aplicadas": 0, "errores": []}

    por_codigo = {e.codigo: e for e in elementos}
    ahora = dt.datetime.now(dt.UTC)
    aplicadas, errores = 0, []
    for accion in acciones:
        try:
            id_externo = conector.aplicar(accion)
        except ErrorConector as exc:
            errores.append(f"{accion.codigo}: {exc}")
            continue
        elemento = por_codigo[accion.codigo]
        registro = next((x for x in elemento.externos if x.sistema == conector.sistema), None)
        if registro is None:
            registro = IdentificadorExterno(sistema=conector.sistema, id_externo=id_externo)
            elemento.externos.append(registro)
        registro.id_externo = id_externo
        registro.url = conector.url_de(id_externo)
        registro.sincronizado_en = ahora
        aplicadas += accion.tipo != "sin_cambios"
    sesion.commit()

    print(f"Aplicadas: {aplicadas}")
    for error in errores:
        print(f"  ! {error}")
    return {"plan": dict(resumen), "aplicadas": aplicadas, "errores": errores}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza el inventario con otro sistema")
    parser.add_argument("sistema", choices=sorted(CONECTORES))
    parser.add_argument("--aplicar", action="store_true", help="Ejecuta el plan (si no, solo lo muestra)")
    parser.add_argument("--edificio", help="Limita a un edificio, p. ej. CADI")
    args = parser.parse_args()

    try:
        conector = CONECTORES[args.sistema]()
        with SesionLocal() as sesion:
            resultado = sincronizar(sesion, conector, aplicar=args.aplicar, edificio=args.edificio)
    except ErrorConector as exc:
        raise SystemExit(f"Error: {exc}") from exc
    if not args.aplicar and (resultado["plan"].get("crear") or resultado["plan"].get("actualizar")):
        print("Nada se modificó. Para ejecutar el plan: --aplicar")
    if resultado["errores"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
