"""[arc-agi3-kaggle-agent/scripts/medir_lazo_cerrado] Banco de LAZO CERRADO reusable: corre
`tests/support/lazo_cerrado.py` sobre los 25 MUNDOS SIMULADOS y escupe su tabla. Uso:

    python3 scripts/medir_lazo_cerrado.py [--pasos 200] [--seed lazo] [--json salida.json]

Es una herramienta de MEDICION del repo, no parte del entregable (no esta en MODULE_ORDER).

ESTO NO ES EL GATE DE MERGE (BL.21744). El gate de merge es `scripts/gate_de_merge.py`, que corre
contra el HARNESS REAL (`arc_agi` + `environment_files`). Este script mide un SIMULADOR del mapeo
de acciones, no los puzzles: sirve para ver si una politica identifica el mundo mas rapido y gasta
menos acciones en botones muertos, y NO para decidir si un cambio entra.

El motivo es concreto y esta medido: hasta BL.21744 este banco tenia el objetivo clavado fuera de
la reticula de 19 de los 25 mundos, asi que su columna `niveles` era CERO por construccion en esos
19 hiciera lo que hiciera la politica. Todo gate escrito como "se mergea solo si suben los niveles
totales aca" era, por lo tanto, un falso negativo sistematico. La geometria ya esta corregida y hay
un guard con BFS que impide que vuelva a pasar (`tests/test_bl21744_alcanzabilidad_de_niveles.py`),
pero la regla de fondo no cambia: para decidir un merge se mide contra el harness real."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arc_agent.policy import ExplorationPolicy  # noqa: E402
from tests.support.lazo_cerrado import medir_todos, totales  # noqa: E402


#: La advertencia que hasta BL.21744 vivia SOLO en docstrings. Un agente (o una persona) que CORRE
#: la herramienta no abre el archivo, asi que la advertencia no llegaba a quien decidia con el
#: numero. Ahora sale por `--help`, por stderr al arrancar y otra vez debajo de la tabla.
ADVERTENCIA = (
    "ESTO NO ES EL GATE DE MERGE. Es un SIMULADOR del mapeo de acciones (que boton mueve, cual "
    "esta muerto, cual abre un menu), no de los puzzles: 'subir de nivel' aca no es subir de nivel "
    "en el juego, y `niveles` es la columna que este banco mide PEOR (hasta BL.21744 era cero por "
    "construccion en 19 de los 25 mundos). Su columna valida es `accionesEnBotonesMuertos`. Para "
    "decidir un merge: scripts/gate_de_merge.py, contra el harness REAL."
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Medicion A/B en lazo cerrado sobre los 25 juegos publicos. " + ADVERTENCIA,
        epilog=ADVERTENCIA,
    )
    parser.add_argument("--pasos", type=int, default=200)
    parser.add_argument("--seed", default="lazo")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    print(f"[banco parametrico] {ADVERTENCIA}", file=sys.stderr)
    medicion = medir_todos(ExplorationPolicy, args.pasos, args.seed)
    resumen = totales(medicion)
    ancho = max(len(n) for n in medicion)
    print(f"{'juego':<{ancho}}  muertos  resuelto  niveles  produc  clicks  dist")
    for nombre, fila in medicion.items():
        print(
            f"{nombre:<{ancho}}  {fila['accionesEnBotonesMuertos']:>7}  "
            f"{str(fila['pasoDeMapeoResuelto']):>8}  {fila['niveles']:>7}  "
            f"{fila['pasosProductivos']:>6}  {fila['clicksProductivos']:>6}  {fila['distancia']:>4}"
        )
    print("TOTALES:", json.dumps(resumen, sort_keys=True))
    print(f"\n[banco parametrico] {ADVERTENCIA}")
    if args.json:
        Path(args.json).write_text(
            json.dumps({"detalle": medicion, "totales": resumen}, indent=1), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
