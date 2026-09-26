"""[arc-agi3-kaggle-agent/tests] -- tests de la mitad CIEGA de arc_agent/world_model/primitives.py:
enumerate_structural_steps (los 39 pasos que expande la BFS de synthesis.py sin mirar el `post`),
las invariantes sobre corpus aleatorio determinista, y los re-exports del DSL.

Archivo separado de test_primitives.py (que cubre los propose_* data-driven) por responsabilidad:
son las dos mitades de la API publica del modulo, y juntas pasaban el limite de 500 lineas.

Porta el caso de arc-agi-runner/src/worldModel/__tests__/primitives.test.ts sobre
enumerateStructuralSteps ("conjunto acotado y determinista"), reforzado con el conteo y el ORDEN
exactos: aguas arriba ese orden fija el orden de expansion de la BFS y, con el, que programa se
encuentra primero.
"""
from __future__ import annotations

import random

import pytest

from arc_agent.world_model.grid import Grid
from arc_agent.world_model.primitives import (
    EMPTY_CONTEXT,
    PrimitiveContext,
    apply_program,
    apply_step,
    enumerate_structural_steps,
    program_key,
    propose_all_steps,
)


def _names(steps: list[dict]) -> list[str]:
    return [step["name"] for step in steps]


# --- enumerate_structural_steps ---------------------------------------------


def test_enumerate_structural_steps_devuelve_39_pasos_en_orden_fijo() -> None:
    grid: Grid = [[0, 0], [0, 1]]
    steps = enumerate_structural_steps(grid)
    assert len(steps) == 39
    assert _names(steps[:24]) == ["translate"] * 24
    assert steps[0]["params"] == {"dx": -2, "dy": -2}
    assert steps[1]["params"] == {"dx": -2, "dy": -1}
    assert steps[2]["params"] == {"dx": -2, "dy": 0}
    assert steps[23]["params"] == {"dx": 2, "dy": 2}
    assert steps[24] == {"name": "reflect", "params": {"axis": "horizontal"}}
    assert steps[25] == {"name": "reflect", "params": {"axis": "vertical"}}
    assert [s["params"]["quarterTurns"] for s in steps[26:29]] == [1, 2, 3]
    assert _names(steps[29:37]) == ["replicate"] * 8
    assert [(s["params"]["timesX"], s["params"]["timesY"]) for s in steps[29:37]] == [
        (1, 2), (1, 3), (2, 1), (2, 2), (2, 3), (3, 1), (3, 2), (3, 3)
    ]
    assert steps[37] == {"name": "cropToBBox", "params": {"backgroundColor": 0}}
    assert steps[38] == {"name": "objectExtract", "params": {}}


def test_enumerate_structural_steps_excluye_el_no_op_de_cada_familia() -> None:
    steps = enumerate_structural_steps([[0, 0], [0, 1]])
    translates = [s["params"] for s in steps if s["name"] == "translate"]
    assert {"dx": 0, "dy": 0} not in translates
    # dx=0 y dy=0 POR SEPARADO si estan: cubren movimientos puramente verticales/horizontales.
    assert {"dx": 0, "dy": 1} in translates
    assert {"dx": 1, "dy": 0} in translates
    replicates = [s["params"] for s in steps if s["name"] == "replicate"]
    assert {"timesX": 1, "timesY": 1} not in replicates


def test_enumerate_structural_steps_excluye_los_primitivos_semanticos() -> None:
    # recolor/floodFill/overlay/conditionalRecolor solo se prueban como finisher data-driven:
    # sin el `post` a la vista su espacio de params es inabordable.
    nombres = set(_names(enumerate_structural_steps([[0, 1], [1, 0]])))
    assert nombres.isdisjoint({"recolor", "floodFill", "overlay", "conditionalRecolor"})


def test_enumerate_structural_steps_usa_el_fondo_detectado_de_la_grilla() -> None:
    grid: Grid = [[3, 3, 3], [3, 7, 3]]
    crop = [s for s in enumerate_structural_steps(grid) if s["name"] == "cropToBBox"]
    assert crop == [{"name": "cropToBBox", "params": {"backgroundColor": 3}}]


def test_enumerate_structural_steps_es_determinista_y_devuelve_listas_frescas() -> None:
    grid: Grid = [[0, 0], [0, 1]]
    primera = enumerate_structural_steps(grid)
    assert enumerate_structural_steps(grid) == primera
    primera.clear()
    assert len(enumerate_structural_steps(grid)) == 39


def test_enumerate_structural_steps_tolera_grillas_degeneradas() -> None:
    for grid in ([], [[]], [[], []]):
        steps = enumerate_structural_steps(grid)
        assert len(steps) == 39
        assert steps[37]["params"] == {"backgroundColor": 0}


# --- invariantes sobre un corpus aleatorio DETERMINISTA ---------------------
# random.Random con semilla fija: mismo corpus en cada corrida y en cada maquina (stdlib pura, sin
# hypothesis ni ninguna otra dependencia de terceros). Estos dos tests generalizan lo que los casos
# puntuales de test_primitives.py afirman de a uno: son la red que atrapa una regresion en un
# proposer que nadie penso en cubrir con un caso a mano.


def _grilla_aleatoria(rng: random.Random, alto: int, ancho: int, paleta: list[int]) -> Grid:
    return [[rng.choice(paleta) for _ in range(ancho)] for _ in range(alto)]


def test_toda_propuesta_de_un_corpus_aleatorio_reproduce_post_exactamente() -> None:
    """LA invariante del modulo: propose_all_steps solo devuelve pasos AUTO-VERIFICADOS. Si un
    proposer dejara pasar una hipotesis sin verificar, la sintesis aguas arriba la rankearia y
    podria elegirla como modelo de mundo -- y el agente actuaria sobre una prediccion falsa."""
    rng = random.Random(20860)
    paletas = [[0, 5], [0, 1, 2], [0, 5, 9], [3, 7], [0, 1, 2, 3, 4, 5]]
    con_propuestas = 0
    for _ in range(400):
        paleta = rng.choice(paletas)
        pre = _grilla_aleatoria(rng, rng.randint(0, 5), rng.randint(0, 5), paleta)
        post = _grilla_aleatoria(rng, rng.randint(0, 5), rng.randint(0, 5), paleta)
        anchor = _grilla_aleatoria(rng, rng.randint(0, 4), rng.randint(0, 4), paleta)
        ctx = PrimitiveContext(anchor_grid=anchor) if rng.random() < 0.5 else EMPTY_CONTEXT
        proposals = propose_all_steps(pre, post, ctx)
        if proposals:
            con_propuestas += 1
        for step in proposals:
            assert apply_step(step, pre, ctx) == post, f"{step} no explica {pre} -> {post}"
    # El corpus tiene que ejercitar el camino positivo, no solo los rechazos.
    assert con_propuestas > 50, f"corpus poco representativo: {con_propuestas} casos con propuesta"


def test_los_39_pasos_estructurales_son_aplicables_sobre_cualquier_grilla() -> None:
    """La BFS de synthesis.py aplica esta enumeracion a CIEGAS sobre grillas intermedias que
    ningun caso a mano anticipa (rotadas, tileadas, recortadas a nada). Un solo paso que lance
    sobre una de ellas mataria la busqueda entera en pleno episodio."""
    rng = random.Random(21029)
    grillas: list[Grid] = [[], [[]], [[], []], [[0]]]
    for _ in range(60):
        grillas.append(_grilla_aleatoria(rng, rng.randint(0, 5), rng.randint(0, 5), [0, 1, 5, 9]))
    for grid in grillas:
        steps = enumerate_structural_steps(grid)
        assert len(steps) == 39
        for step in steps:
            resultado = apply_step(step, grid, EMPTY_CONTEXT)
            # Toda salida sigue siendo una grilla rectangular: la invariante 0.2 del contrato, de
            # la que dependen todos los helpers que derivan el ancho de la fila 0.
            assert len({len(row) for row in resultado}) <= 1


# --- re-exports (paridad con el `export {...}` de primitives.ts) ------------


def test_apply_program_vacio_es_identidad_via_el_re_export() -> None:
    grid: Grid = [[1, 2]]
    assert apply_program([], grid) == grid


def test_apply_program_compone_pasos_en_orden_via_el_re_export() -> None:
    grid: Grid = [[0, 0], [0, 5]]
    program = [
        {"name": "reflect", "params": {"axis": "horizontal"}},
        {"name": "recolor", "params": {"mapping": {5: 9}}},
    ]
    assert apply_program(program, grid) == [[0, 0], [9, 0]]


def test_program_key_del_programa_vacio_es_la_lista_json_vacia() -> None:
    assert program_key([]) == "[]"


def test_apply_step_re_exportado_rechaza_un_paso_desconocido() -> None:
    with pytest.raises(ValueError):
        apply_step({"name": "noExiste", "params": {}}, [[0]], EMPTY_CONTEXT)
