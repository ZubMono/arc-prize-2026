"""[arc-agi3-kaggle-agent/tests/test_dsl_parity] BL.20865 -- el contrato EJECUTABLE entre el motor
TypeScript canonico (projects/arc-agi-runner/src/worldModel) y este puerto Python.

POR QUE EXISTE. El puerto es una reimplementacion a mano de ~1500 lineas: no hay compilador que
garantice que las dos den lo mismo, y las divergencias no explotan -- devuelven una grilla
plausible pero distinta, y el agente aprende un modelo de mundo equivocado en silencio. El caso mas
probable es el indexado: TypeScript devuelve `undefined` fuera de rango, Python indexa NEGATIVO sin
error (grid[-1] es la ultima fila), asi que un `translate` con dx negativo portado ingenuamente lee
del otro extremo de la grilla.

COMO FUNCIONA. `projects/arc-agi-runner/scripts/generateDslParityFixture.ts` importa el motor
canonico y emite `dslParity.json` con casos (programa, grilla) -> resultado. Los dos lados lo
consumen: el test TypeScript falla si el fixture quedo stale respecto del motor, y este falla si el
puerto divergio. El fixture es el unico arbitro; ninguno de los dos lados se cree a si mismo.

AISLAMIENTO. El fixture vive en el OTRO proyecto, asi que se resuelve por ruta relativa y se hace
skip si no esta: `arc-agi3-kaggle-agent` tiene que poder extraerse del monorepo y seguir corriendo
sus tests. Es el mismo criterio que `activityMemorySeed.contract.test.ts` del lado TypeScript. Este
archivo es de DESARROLLO: nunca viaja al notebook de Kaggle (no esta en MODULE_ORDER).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc_agent.world_model import PrimitiveContext, apply_program

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "arc-agi-runner"
    / "src"
    / "worldModel"
    / "__fixtures__"
    / "dslParity.json"
)


def _cargar_casos() -> list[dict]:
    if not FIXTURE.exists():
        pytest.skip(
            f"fixture de paridad ausente ({FIXTURE}) -- se corre desde el monorepo; "
            "el agente extraido solo no lo tiene y eso es correcto por diseno."
        )
    datos = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert datos["generatedFrom"] == "typescript", (
        "el fixture tiene que venir del lado canonico: si alguien lo regenera desde Python, "
        "el test se vuelve un espejo de si mismo y deja de probar la paridad."
    )
    return datos["cases"]


CASOS = _cargar_casos() if FIXTURE.exists() else []


def _requerir_casos() -> None:
    """BL.21555 -- los meta-tests sobre CASOS tienen que respetar el MISMO skip que el resto: sin
    fixture (proyecto copiado fuera del monorepo) `CASOS` queda vacio y asertar sobre el era
    fallar por diseno en el primer checkout extraido -- mal debut para un repo publico."""
    if not CASOS:
        pytest.skip(
            f"fixture de paridad ausente ({FIXTURE}) -- se corre desde el monorepo; "
            "el agente extraido solo no lo tiene y eso es correcto por diseno."
        )


def test_el_fixture_cubre_los_diez_primitivos() -> None:
    """Un fixture que perdio cobertura silenciosamente es peor que no tenerlo: sigue en verde
    mientras deja de mirar la mitad del DSL."""
    _requerir_casos()
    esperados = {
        "translate", "reflect", "rotate", "recolor", "floodFill",
        "cropToBBox", "overlay", "replicate", "objectExtract", "conditionalRecolor",
    }
    vistos = {paso["name"] for caso in CASOS for paso in caso["program"]}
    assert esperados <= vistos, f"primitivos sin cubrir en el fixture: {sorted(esperados - vistos)}"


def test_hay_casos_de_composicion() -> None:
    """La paridad paso-a-paso no implica paridad de composicion: los errores de tamano de grilla
    intermedia solo aparecen encadenando."""
    _requerir_casos()
    assert any(len(c["program"]) >= 2 for c in CASOS), "el fixture no tiene programas de 2+ pasos"


@pytest.mark.parametrize(
    "caso",
    CASOS,
    ids=[c["name"] for c in CASOS] or ["sin-fixture"],
)
def test_paridad_con_el_motor_typescript(caso: dict) -> None:
    """El `anchor` del caso es el contexto de `overlay`: sin pasarlo, overlay degrada a identidad
    (comportamiento defensivo) y el test reportaria una divergencia que no existe."""
    ancla = caso.get("anchor")
    ctx = PrimitiveContext(anchor_grid=ancla) if ancla is not None else None
    obtenido = apply_program(caso["program"], caso["pre"], ctx)
    assert obtenido == caso["expected"], (
        f"DIVERGENCIA con el motor canonico en '{caso['name']}'.\n"
        f"  por que existe el caso: {caso.get('why', '(sin nota)')}\n"
        f"  programa:   {caso['program']}\n"
        f"  entrada:    {caso['pre']}\n"
        f"  TypeScript: {caso['expected']}\n"
        f"  Python:     {obtenido}"
    )
