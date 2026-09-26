"""[arc-agi3-kaggle-agent/tests/world_model/primitive_ops] -- DSL de transformaciones
grilla-a-grilla: EJECUCION de los 10 primitivos (la forma canonica con la que se serializan y
rankean vive en test_primitive_ops_serialization.py, separado por el limite de 500 lineas).

Tres capas de verificacion:
1. FIXTURE DORADO (94 casos) generado desde el motor TypeScript canonico
   (arc-agi-runner/src/worldModel/__fixtures__/dslParity.json): `expected` lo calculo el TS, no
   esta escrito a mano. Es el contrato ejecutable del port.
2. Casos portados de arc-agi-runner/src/worldModel/__tests__/primitives.test.ts.
3. Bordes propios de PYTHON que el TS no puede tener: indices NEGATIVOS (en TS leer fuera de
   rango da undefined; en Python envuelve por el otro extremo en silencio) y division por cero en
   el modulo de replicate.

Los vectores inline de las capas 2 y 3 salieron de ejecutar el TS con tsx sobre el modulo
canonico -- son la salida de la implementacion de referencia, no un valor recalculado del Python.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc_agent.world_model.primitive_ops import (
    PARAM_KEY_ORDER,
    PROGRAM_STEP_NAMES,
    PrimitiveContext,
    Program,
    ProgramStep,
    _apply_replicate,
    _bbox_of_cells,
    _find_components,
    _flood_region,
    apply_program,
    apply_step,
    make_conditional_recolor,
    make_crop_to_bbox,
    make_flood_fill,
    make_object_extract,
    make_overlay,
    make_recolor,
    make_reflect,
    make_replicate,
    make_rotate,
    make_translate,
)

# ─── Fixture dorado generado desde el TypeScript ─────────────────────────────

_RUNNER_PROJECT = Path(__file__).resolve().parents[2] / "arc-agi-runner"
_FIXTURE_PATH = _RUNNER_PROJECT / "src" / "worldModel" / "__fixtures__" / "dslParity.json"


def _step_from_fixture(raw: dict) -> ProgramStep:
    """Unico punto donde el round-trip JSON no es idempotente: las claves de `mapping` vuelven
    como str y el DSL las usa como int (ver CONTRATO 10.9)."""
    params = dict(raw["params"])
    if "mapping" in params:
        params["mapping"] = {int(k): v for k, v in params["mapping"].items()}
    return {"name": raw["name"], "params": params}


def _load_parity_cases() -> list[dict]:
    if not _RUNNER_PROJECT.exists():
        # Este proyecto se puede extraer solo (se abre bajo dominio publico si se compite,
        # ver BL.21045): sin el motor TS al
        # lado no hay fixture dorado, y el resto de la suite sigue siendo valida.
        return []
    assert _FIXTURE_PATH.exists(), (
        f"falta el fixture dorado {_FIXTURE_PATH} -- regenerar con "
        "`cd projects/arc-agi-runner && npx tsx scripts/generateDslParityFixture.ts`"
    )
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]


_PARITY_CASES = _load_parity_cases()


@pytest.mark.parametrize("case", _PARITY_CASES, ids=lambda case: case["name"])
def test_paridad_con_el_fixture_dorado_del_typescript(case: dict) -> None:
    program: Program = [_step_from_fixture(step) for step in case["program"]]
    ctx = PrimitiveContext(anchor_grid=case["anchor"]) if "anchor" in case else None
    assert apply_program(program, case["pre"], ctx) == case["expected"], case["why"]


def test_el_fixture_dorado_no_quedo_vacio_si_el_motor_ts_esta_al_lado() -> None:
    if not _RUNNER_PROJECT.exists():
        pytest.skip("proyecto arc-agi-runner ausente (extraccion standalone del agente Python)")
    assert len(_PARITY_CASES) >= 90


def test_el_dsl_python_cubre_exactamente_los_primitivos_del_typescript() -> None:
    """Coherencia CRUZADA de lenguajes: el fixture lo genera el TS y su propio test exige >=3
    casos por primitivo del registro TS, asi que los nombres presentes en el fixture SON el DSL
    canonico. Si el TS suma un primitivo, este test se pone rojo del lado Python hasta que se
    porte -- que es exactamente donde queremos enterarnos."""
    if not _RUNNER_PROJECT.exists():
        pytest.skip("proyecto arc-agi-runner ausente (extraccion standalone del agente Python)")
    nombres_fixture = {step["name"] for case in _PARITY_CASES for step in case["program"]}
    assert nombres_fixture == set(PROGRAM_STEP_NAMES)


# ─── apply_step -- casos portados de primitives.test.ts + bordes de Python ────

APPLY_STEP_PARITY: list[tuple[str, ProgramStep, list[list[int]], dict, list[list[int]]]] = [
    # (id, step, grid, kwargs de contexto, salida EXACTA del TS)
    ("translate_dx1", make_translate(1, 0), [[0, 0, 0], [0, 5, 0], [0, 0, 0]], {},
     [[0, 0, 0], [0, 0, 5], [0, 0, 0]]),
    # Sin guarda de limites, grid[0][-1] devolveria el 9 de la ultima columna y el resultado
    # seria [[9, 0, 0]] -- el bug de port mas probable de todo el DSL.
    ("translate_no_envuelve_por_columna", make_translate(1, 0), [[0, 0, 9]], {}, [[0, 0, 0]]),
    ("translate_no_envuelve_por_fila", make_translate(0, 1), [[0, 0], [0, 0], [5, 5]], {},
     [[0, 0], [0, 0], [0, 0]]),
    ("translate_negativo", make_translate(-2, 0), [[0, 0, 9], [0, 0, 0]], {},
     [[9, 0, 0], [0, 0, 0]]),
    ("translate_cero_es_identidad", make_translate(0, 0), [[3, 0], [0, 0]], {}, [[3, 0], [0, 0]]),
    ("reflect_horizontal", make_reflect("horizontal"), [[1, 2, 3]], {}, [[3, 2, 1]]),
    ("reflect_vertical", make_reflect("vertical"), [[1], [2], [3]], {}, [[3], [2], [1]]),
    ("rotate_1", make_rotate(1), [[1, 2], [3, 4]], {}, [[3, 1], [4, 2]]),
    ("rotate_2", make_rotate(2), [[1, 2], [3, 4]], {}, [[4, 3], [2, 1]]),
    ("rotate_3", make_rotate(3), [[1, 2], [3, 4]], {}, [[2, 4], [1, 3]]),
    ("rotate_no_cuadrada", make_rotate(1), [[1, 2, 3], [4, 5, 6]], {}, [[4, 1], [5, 2], [6, 3]]),
    ("recolor", make_recolor({1: 9}), [[1, 2, 3]], {}, [[9, 2, 3]]),
    ("recolor_a_cero", make_recolor({5: 0}), [[5, 5], [0, 5]], {}, [[0, 0], [0, 0]]),
    ("flood_fill", make_flood_fill(0, 0, 7), [[1, 1, 0], [1, 0, 2], [0, 0, 2]], {},
     [[7, 7, 0], [7, 0, 2], [0, 0, 2]]),
    # x = -1 en Python indexaria la ULTIMA columna y pintaria la region equivocada.
    ("flood_fill_x_negativo", make_flood_fill(-1, 0, 7), [[1, 1, 0], [1, 0, 2]], {},
     [[1, 1, 0], [1, 0, 2]]),
    ("flood_fill_y_negativo", make_flood_fill(0, -1, 7), [[1, 1, 0], [1, 0, 2]], {},
     [[1, 1, 0], [1, 0, 2]]),
    ("flood_fill_fuera_por_arriba", make_flood_fill(5, 0, 7), [[1, 1, 0], [1, 0, 2]], {},
     [[1, 1, 0], [1, 0, 2]]),
    ("crop_to_bbox", make_crop_to_bbox(0), [[0, 0, 0], [0, 5, 5], [0, 0, 0]], {}, [[5, 5]]),
    ("crop_to_bbox_uniforme", make_crop_to_bbox(0), [[0, 0], [0, 0]], {}, [[0, 0], [0, 0]]),
    ("overlay", make_overlay(), [[0, 3], [0, 0]], {"anchor_grid": [[1, 1], [1, 1]]},
     [[1, 3], [1, 1]]),
    ("overlay_sin_ancla", make_overlay(), [[0, 3], [0, 0]], {}, [[0, 3], [0, 0]]),
    # El ancla puede ser mas chica: fuera de rango se queda la celda original, nunca envuelve.
    ("overlay_ancla_chica", make_overlay(), [[0, 3], [0, 0]], {"anchor_grid": [[1]]},
     [[1, 3], [0, 0]]),
    ("replicate", make_replicate(2, 2), [[1, 2]], {}, [[1, 2, 1, 2], [1, 2, 1, 2]]),
    ("replicate_1x3", make_replicate(1, 3), [[1, 2]], {}, [[1, 2], [1, 2], [1, 2]]),
    ("object_extract", make_object_extract(), [[0, 5, 0, 3], [0, 5, 0, 0], [0, 0, 0, 0]], {},
     [[5], [5]]),
    ("object_extract_color", make_object_extract(3),
     [[0, 5, 0, 3], [0, 5, 0, 0], [0, 0, 0, 0]], {}, [[3]]),
    # Empate de tamano: gana menor min_y y, a igual fila, menor min_x.
    ("object_extract_empate", make_object_extract(), [[0, 4, 0, 6], [0, 0, 0, 0]], {}, [[4]]),
    # Mismo empate pero decidido por min_y: el 6 esta en la fila 0 y el 4 en la 1, aunque el 4
    # tenga min_x menor. El orden de los criterios es load-bearing (tamano, min_y, min_x).
    ("object_extract_empate_por_min_y", make_object_extract(), [[0, 0, 6], [4, 0, 0]], {}, [[6]]),
    ("object_extract_sin_objetos", make_object_extract(), [[0, 0], [0, 0]], {}, [[0, 0], [0, 0]]),
    ("cond_recolor_border", make_conditional_recolor(5, 9, "border"),
     [[5, 5, 5], [5, 5, 5], [5, 5, 5]], {}, [[9, 9, 9], [9, 5, 9], [9, 9, 9]]),
    ("cond_recolor_interior", make_conditional_recolor(5, 9, "interior"),
     [[5, 5, 5], [5, 5, 5], [5, 5, 5]], {}, [[5, 5, 5], [5, 9, 5], [5, 5, 5]]),
    ("cond_recolor_all", make_conditional_recolor(5, 9, "all"),
     [[5, 0, 5], [5, 5, 5], [5, 5, 5]], {}, [[9, 0, 9], [9, 9, 9], [9, 9, 9]]),
    ("cond_recolor_vecino_distinto", make_conditional_recolor(5, 9, "interior"),
     [[5, 5, 5, 5], [5, 5, 0, 5], [5, 5, 5, 5], [5, 5, 5, 5]], {},
     [[5, 5, 5, 5], [5, 5, 0, 5], [5, 9, 5, 5], [5, 5, 5, 5]]),
]


@pytest.mark.parametrize(
    "step,grid,ctx_kwargs,expected",
    [case[1:] for case in APPLY_STEP_PARITY],
    ids=[case[0] for case in APPLY_STEP_PARITY],
)
def test_apply_step_paridad_con_el_typescript(step, grid, ctx_kwargs, expected) -> None:
    ctx = PrimitiveContext(**ctx_kwargs) if ctx_kwargs else None
    assert apply_step(step, grid, ctx) == expected


@pytest.mark.parametrize(
    "step,grid,ctx_kwargs,_expected",
    [case[1:] for case in APPLY_STEP_PARITY],
    ids=[case[0] for case in APPLY_STEP_PARITY],
)
def test_apply_step_nunca_muta_la_grilla_de_entrada(step, grid, ctx_kwargs, _expected) -> None:
    # Los nodos de la BFS de synthesis.py comparten grillas: una mutacion in-place corromperia
    # ramas ya expandidas sin dejar rastro.
    original = [row[:] for row in grid]
    apply_step(step, grid, PrimitiveContext(**ctx_kwargs) if ctx_kwargs else None)
    assert grid == original


def test_rotate_cuatro_veces_es_identidad() -> None:
    grid = [[1, 2], [3, 4]]
    result = grid
    for _ in range(4):
        result = apply_step(make_rotate(1), result)
    assert result == grid


class TestApplyProgram:
    def test_programa_vacio_es_identidad(self) -> None:
        assert apply_program([], [[1, 2]]) == [[1, 2]]

    def test_programa_vacio_devuelve_un_clon_no_la_entrada(self) -> None:
        grid = [[1, 2]]
        assert apply_program([], grid) is not grid

    def test_compone_pasos_en_orden(self) -> None:
        program = [make_reflect("horizontal"), make_recolor({5: 9})]
        assert apply_program(program, [[0, 0], [0, 5]]) == [[0, 0], [9, 0]]

    def test_compone_pasos_que_cambian_la_forma(self) -> None:
        program = [make_replicate(2, 1), make_crop_to_bbox(0)]
        assert apply_program(program, [[0, 7], [0, 0]]) == [[7, 0, 7]]

    def test_contexto_por_defecto_es_el_vacio(self) -> None:
        assert apply_program([make_overlay()], [[0, 3]]) == [[0, 3]]


# ─── Degradacion defensiva y falla ruidosa ───────────────────────────────────


class TestParamsInvalidos:
    """Un primitivo CONOCIDO con params invalidos degrada a no-op (nunca lanza), igual que el TS
    donde toda comparacion contra undefined es false."""

    def test_rotate_sin_quarter_turns(self) -> None:
        assert apply_step({"name": "rotate", "params": {}}, [[1, 2]]) == [[1, 2]]

    def test_rotate_negativo(self) -> None:
        assert apply_step(make_rotate(-3), [[1, 2]]) == [[1, 2]]

    def test_flood_fill_sin_semilla(self) -> None:
        assert apply_step({"name": "floodFill", "params": {}}, [[1, 1]]) == [[1, 1]]

    def test_crop_sin_background_color(self) -> None:
        assert apply_step({"name": "cropToBBox", "params": {}}, [[0, 5]]) == [[0, 5]]

    def test_recolor_sin_mapping(self) -> None:
        assert apply_step({"name": "recolor", "params": {}}, [[1, 2]]) == [[1, 2]]

    def test_conditional_recolor_sin_predicado(self) -> None:
        step = {"name": "conditionalRecolor", "params": {"from": 5, "to": 9}}
        assert apply_step(step, [[5, 5], [5, 5]]) == [[5, 5], [5, 5]]

    def test_translate_sin_desplazamiento(self) -> None:
        assert apply_step({"name": "translate", "params": {}}, [[3, 0]]) == [[3, 0]]

    def test_reflect_sin_axis_cae_en_vertical(self) -> None:
        # El TS trata cualquier axis distinto de 'horizontal' como vertical: no valida.
        assert apply_step({"name": "reflect", "params": {}}, [[1], [2]]) == [[2], [1]]


class TestFormasDegeneradas:
    def test_grilla_vacia_en_todos_los_primitivos(self) -> None:
        # Ningun primitivo lanza sobre una grilla sin celdas: ancho 0, area 0, loops que no
        # iteran. Recorre PROGRAM_STEP_NAMES para que un primitivo nuevo entre solo al test.
        valores: dict = {"axis": "horizontal", "quarterTurns": 1, "mapping": {1: 2}, "x": 0,
                         "y": 0, "to": 1, "backgroundColor": 0, "timesX": 2, "timesY": 2,
                         "dx": 1, "dy": 1, "from": 1, "predicate": "all", "color": 1}
        for name in PROGRAM_STEP_NAMES:
            step = {"name": name, "params": {k: valores[k] for k in PARAM_KEY_ORDER[name]}}
            assert apply_step(step, []) == [], name

    def test_replicate_con_times_en_cero_devuelve_filas_vacias(self) -> None:
        # El TS produce h filas VACIAS (no una grilla vacia) y jamas divide por cero: los loops
        # simplemente no iteran. Un port que precalcule el modulo fuera del loop explotaria.
        assert _apply_replicate({"timesX": 0, "timesY": 1}, [[1, 2], [3, 4]]) == [[], []]

    def test_replicate_sobre_filas_vacias(self) -> None:
        assert _apply_replicate({"timesX": 2, "timesY": 2}, [[], []]) == [[], [], [], []]

    def test_flood_fill_sobre_filas_vacias(self) -> None:
        assert apply_step(make_flood_fill(0, 0, 7), [[], []]) == [[], []]


def test_nombre_de_paso_desconocido_lanza() -> None:
    with pytest.raises(ValueError, match="paso de DSL desconocido"):
        apply_step({"name": "teleport", "params": {}}, [[1]])


def test_paso_sin_nombre_lanza_el_error_del_dsl_y_no_un_key_error() -> None:
    # Un step malformado llega de deserializar un fixture roto: el mensaje tiene que hablar del
    # DSL, no ser un KeyError pelado que no dice donde mirar.
    with pytest.raises(ValueError, match="paso de DSL desconocido"):
        apply_step({"params": {}}, [[1]])


# ─── Helpers internos: orden y guardas de limites ────────────────────────────


class TestFloodRegion:
    def test_orden_de_recorrido_es_determinista(self) -> None:
        # Push derecha/izquierda/abajo/arriba + pop() LIFO: el orden es load-bearing para el
        # determinismo que afirman los fixtures aguas arriba.
        assert _flood_region([[1, 1], [1, 1]], 0, 0, 1) == [(0, 0), (0, 1), (1, 1), (1, 0)]
        assert _flood_region([[1, 1], [1, 1]], 0, 0, 1) == _flood_region(
            [[1, 1], [1, 1]], 0, 0, 1
        )

    def test_semilla_negativa_no_envuelve(self) -> None:
        assert _flood_region([[1, 1], [1, 1]], -1, 0, 1) == []
        assert _flood_region([[1, 1], [1, 1]], 0, -1, 1) == []

    def test_semilla_fuera_por_arriba(self) -> None:
        assert _flood_region([[1, 1], [1, 1]], 2, 0, 1) == []

    def test_solo_conectividad_4(self) -> None:
        # La diagonal NO conecta: dos celdas en diagonal son dos regiones distintas.
        assert _flood_region([[1, 0], [0, 1]], 0, 0, 1) == [(0, 0)]


class TestFindComponents:
    def test_orden_de_descubrimiento_row_major(self) -> None:
        grid = [[0, 5, 0], [0, 0, 0], [3, 0, 0]]
        assert _find_components(grid, 0) == [[(1, 0)], [(0, 2)]]

    def test_filtra_por_color(self) -> None:
        grid = [[0, 5, 0], [0, 0, 0], [3, 0, 0]]
        assert _find_components(grid, 0, 3) == [[(0, 2)]]

    def test_componentes_son_mono_color(self) -> None:
        grid = [[5, 3], [0, 0]]
        assert _find_components(grid, 0) == [[(0, 0)], [(1, 0)]]


def test_bbox_de_lista_vacia_es_degenerado() -> None:
    # Equivale a los centinelas Infinity del TS: ningun recorrido posterior itera.
    bbox = _bbox_of_cells([])
    assert (bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y) == (0, 0, -1, -1)
