"""[arc-agi3-kaggle-agent/tests/test_program_coverage] BL.21561 -- cobertura puntuada en vez de
verificacion de cero tolerancia. Espejo de la seccion homonima de
arc-agi-runner/src/worldModel/__tests__/synthesis.test.ts.

POR QUE IMPORTA: `verify_program` mataba una regla CORRECTA en la primera observacion que no
encajaba, y en ARC-AGI-3 esa observacion llega siempre -- es el choque contra la pared.
"""
from __future__ import annotations

from arc_agent.world_model import (
    MIN_PROGRAM_COVERAGE,
    Grid,
    Observation,
    make_recolor,
    program_coverage,
    synthesize_program_scored,
    verify_program,
)

PROGRAMA = [make_recolor({1: 9})]


def _obs(pre: Grid, post: Grid) -> Observation:
    return Observation(pre=pre, post=post)


def test_program_coverage_cuenta_aciertos_y_fallos() -> None:
    observaciones = [
        _obs([[1, 2]], [[9, 2]]),
        _obs([[1, 1]], [[9, 9]]),
        _obs([[1, 1]], [[8, 8]]),
    ]
    puntaje = program_coverage(PROGRAMA, observaciones)
    assert (puntaje.aciertos, puntaje.fallos) == (2, 1)
    assert abs(puntaje.cobertura - 2 / 3) < 1e-9
    # el booleano viejo sigue existiendo y sigue siendo implacable
    assert verify_program(PROGRAMA, observaciones) is False


def test_sin_observaciones_la_cobertura_es_1() -> None:
    puntaje = program_coverage(PROGRAMA, [])
    assert (puntaje.aciertos, puntaje.fallos, puntaje.cobertura) == (0, 0, 1.0)


def test_acepta_la_regla_que_explica_2_de_3() -> None:
    observaciones = [
        _obs([[1, 2]], [[9, 2]]),
        _obs([[1, 1]], [[9, 9]]),
        _obs([[1, 1]], [[8, 8]]),
    ]
    puntuado = synthesize_program_scored(observaciones)
    assert puntuado.program == PROGRAMA
    assert (puntuado.aciertos, puntuado.fallos) == (2, 1)
    assert puntuado.cobertura >= MIN_PROGRAM_COVERAGE


def test_la_identidad_nunca_se_acepta_parcialmente() -> None:
    """Aceptarla a medias equivale a declarar no-op una accion que a veces SI hace algo -- el
    lockout que BL.21500/BL.21501 tuvieron que desarmar."""
    observaciones = [
        _obs([[3, 3]], [[3, 3]]),
        _obs([[3, 3]], [[3, 3]]),
        _obs([[1, 1]], [[9, 9]]),
    ]
    assert synthesize_program_scored(observaciones).program != []


def test_por_debajo_del_minimo_de_cobertura_devuelve_none() -> None:
    observaciones = [_obs([[1, 1]], [[9, 9]]), _obs([[1, 1]], [[8, 8]])]
    puntuado = synthesize_program_scored(observaciones)
    assert puntuado.program is None
    assert puntuado.cobertura == 0.0
