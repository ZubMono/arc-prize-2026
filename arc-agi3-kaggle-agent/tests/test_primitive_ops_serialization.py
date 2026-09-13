"""[arc-agi3-kaggle-agent/tests/world_model/primitive_ops -- serializacion] -- constructores del
DSL, serializacion canonica (program_to_json == JSON.stringify byte a byte) y desempate por clave
(compare_program_keys == String.prototype.localeCompare de Node).

Separado de test_primitive_ops.py solo por el limite de 500 lineas: alla vive la EJECUCION de los
primitivos, aca la forma CANONICA con la que viajan al fixture y con la que se rankean.

Los vectores esperados salieron de ejecutar el TS canonico (JSON.stringify / localeCompare en
Node) sobre exactamente estas entradas -- no son valores recalculados desde el Python."""
from __future__ import annotations

import json
from functools import cmp_to_key

import pytest

from arc_agent.world_model.primitive_ops import (
    EMPTY_CONTEXT,
    PARAM_KEY_ORDER,
    PROGRAM_STEP_NAMES,
    PrimitiveContext,
    Program,
    compare_program_keys,
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
    program_key,
    program_to_json,
    step_to_json,
)

# ─── Constructores ───────────────────────────────────────────────────────────


class TestConstructores:
    def test_producen_las_claves_exactas_del_dsl(self) -> None:
        assert make_translate(1, -2) == {"name": "translate", "params": {"dx": 1, "dy": -2}}
        assert make_reflect("vertical") == {"name": "reflect", "params": {"axis": "vertical"}}
        assert make_rotate(3) == {"name": "rotate", "params": {"quarterTurns": 3}}
        assert make_recolor({1: 9}) == {"name": "recolor", "params": {"mapping": {1: 9}}}
        assert make_flood_fill(1, 2, 7) == {
            "name": "floodFill", "params": {"x": 1, "y": 2, "to": 7}
        }
        assert make_crop_to_bbox(0) == {"name": "cropToBBox", "params": {"backgroundColor": 0}}
        assert make_overlay() == {"name": "overlay", "params": {}}
        assert make_replicate(2, 3) == {
            "name": "replicate", "params": {"timesX": 2, "timesY": 3}
        }
        assert make_conditional_recolor(1, 2, "border") == {
            "name": "conditionalRecolor", "params": {"from": 1, "to": 2, "predicate": "border"}
        }

    def test_object_extract_sin_color_omite_la_clave(self) -> None:
        # NUNCA {"color": None}: seria otro JSON y romperia el fixture y el desempate por clave.
        assert make_object_extract() == {"name": "objectExtract", "params": {}}
        assert make_object_extract(None) == {"name": "objectExtract", "params": {}}
        assert make_object_extract(0) == {"name": "objectExtract", "params": {"color": 0}}

    def test_recolor_copia_el_mapping(self) -> None:
        mapping = {1: 9}
        step = make_recolor(mapping)
        mapping[2] = 8
        assert step["params"]["mapping"] == {1: 9}

    def test_hay_un_constructor_por_primitivo_del_dsl(self) -> None:
        # Si el DSL crece y el primitivo nuevo no trae constructor, dos implementadores terminan
        # armando el dict a mano con claves distintas -- que es justo lo que los make_* evitan.
        construidos = [
            make_translate(0, 0), make_reflect("horizontal"), make_rotate(1), make_recolor({}),
            make_flood_fill(0, 0, 0), make_crop_to_bbox(0), make_overlay(), make_replicate(1, 1),
            make_object_extract(), make_conditional_recolor(0, 0, "all"),
        ]
        assert {step["name"] for step in construidos} == set(PROGRAM_STEP_NAMES)
        # Y cada uno produce EXACTAMENTE las claves del orden canonico (salvo `color`, opcional).
        for step in construidos:
            claves = set(step["params"])
            assert claves <= set(PARAM_KEY_ORDER[step["name"]]), step["name"]


# ─── Serializacion canonica (paridad byte a byte con JSON.stringify) ─────────

JSON_PARITY: list[tuple[str, Program, str]] = [
    ("vacio", [], "[]"),
    ("translate_negativo", [make_translate(-2, 3)],
     '[{"name":"translate","params":{"dx":-2,"dy":3}}]'),
    ("reflect", [make_reflect("horizontal")],
     '[{"name":"reflect","params":{"axis":"horizontal"}}]'),
    ("rotate", [make_rotate(3)], '[{"name":"rotate","params":{"quarterTurns":3}}]'),
    # JS ordena las claves enteras de un objeto ascendente por valor numerico, no por insercion.
    ("recolor", [make_recolor({2: 3, 0: 5, 10: 1})],
     '[{"name":"recolor","params":{"mapping":{"0":5,"2":3,"10":1}}}]'),
    ("flood_fill", [make_flood_fill(1, 2, 7)],
     '[{"name":"floodFill","params":{"x":1,"y":2,"to":7}}]'),
    ("crop", [make_crop_to_bbox(0)], '[{"name":"cropToBBox","params":{"backgroundColor":0}}]'),
    ("overlay", [make_overlay()], '[{"name":"overlay","params":{}}]'),
    ("replicate", [make_replicate(2, 3)],
     '[{"name":"replicate","params":{"timesX":2,"timesY":3}}]'),
    ("object_extract_sin_color", [make_object_extract()],
     '[{"name":"objectExtract","params":{}}]'),
    ("object_extract_color", [make_object_extract(4)],
     '[{"name":"objectExtract","params":{"color":4}}]'),
    ("cond_recolor", [make_conditional_recolor(1, 2, "border")],
     '[{"name":"conditionalRecolor","params":{"from":1,"to":2,"predicate":"border"}}]'),
    ("compuesto", [make_reflect("vertical"), make_recolor({1: 9})],
     '[{"name":"reflect","params":{"axis":"vertical"}},'
     '{"name":"recolor","params":{"mapping":{"1":9}}}]'),
]


@pytest.mark.parametrize(
    "program,expected",
    [case[1:] for case in JSON_PARITY],
    ids=[case[0] for case in JSON_PARITY],
)
def test_program_to_json_reproduce_json_stringify(program, expected) -> None:
    assert program_to_json(program) == expected


def test_program_key_es_el_mismo_objeto_que_program_to_json() -> None:
    # Dos serializadores distintos podrian divergir sin que nadie se entere.
    assert program_key is program_to_json


def test_step_to_json_de_un_paso_suelto() -> None:
    assert step_to_json(make_translate(0, 0)) == '{"name":"translate","params":{"dx":0,"dy":0}}'


def test_round_trip_json_salvo_claves_de_mapping() -> None:
    program = [make_translate(-1, 2), make_reflect("horizontal"), make_object_extract()]
    assert json.loads(program_to_json(program)) == program
    # Unica excepcion: las claves de mapping vuelven como str (ver CONTRATO 10.9).
    recolor = [make_recolor({1: 9})]
    assert json.loads(program_to_json(recolor)) != recolor
    parsed = json.loads(program_to_json(recolor))
    parsed[0]["params"]["mapping"] = {
        int(k): v for k, v in parsed[0]["params"]["mapping"].items()
    }
    assert parsed == recolor


def test_serializar_un_paso_desconocido_lanza() -> None:
    with pytest.raises(ValueError, match="paso de DSL desconocido"):
        program_to_json([{"name": "teleport", "params": {}}])


def test_serializar_un_paso_sin_nombre_lanza_el_error_del_dsl() -> None:
    # Un step malformado llega de deserializar un fixture roto: el mensaje tiene que hablar del
    # DSL, no ser un KeyError pelado que no dice donde mirar.
    with pytest.raises(ValueError, match="paso de DSL desconocido"):
        program_to_json([{"params": {}}])


def test_serializar_un_booleano_lanza() -> None:
    # bool es subclase de int en Python: sin el guard se emitiria `True`, JSON invalido.
    with pytest.raises(ValueError, match="booleano"):
        program_to_json([{"name": "rotate", "params": {"quarterTurns": True}}])


def test_los_nombres_del_dsl_y_el_orden_de_claves_son_una_sola_fuente() -> None:
    # PROGRAM_STEP_NAMES y PARAM_KEY_ORDER se leen desde modulos distintos (synthesis, primitives,
    # el serializador): si se desincronizaran, un primitivo quedaria sin orden canonico de claves
    # y su program_key dejaria de ser comparable.
    assert PROGRAM_STEP_NAMES == tuple(PARAM_KEY_ORDER)


# ─── Desempate: localeCompare, no orden de codepoint ─────────────────────────

COMPARE_PARITY: list[tuple[str, str, int]] = [
    # ICU pone la puntuacion ANTES de los digitos; con orden de codepoint ('}' = 125 > '5' = 53)
    # este par saldria invertido respecto del TS.
    ('{"color":1}', '{"color":15}', -1),
    ("[]", '[{"name":"overlay","params":{}}]', -1),
    ('{"name":"recolor"}', '{"name":"reflect"}', -1),
    ('{"name":"reflect"}', '{"name":"replicate"}', -1),
    ('{"dx":-2}', '{"dx":2}', -1),
    ('{"dx":-2}', '{"dx":-10}', 1),
    ('{"a":1}', '{"a":1}', 0),
    ('[{"name":"rotate","params":{"quarterTurns":1}}]',
     '[{"name":"translate","params":{"dx":1,"dy":0}}]', -1),
    ('[{"name":"objectExtract","params":{}}]',
     '[{"name":"objectExtract","params":{"color":0}}]', 1),
]


@pytest.mark.parametrize("a,b,expected", COMPARE_PARITY)
def test_compare_program_keys_reproduce_locale_compare(a: str, b: str, expected: int) -> None:
    assert compare_program_keys(a, b) == expected
    assert compare_program_keys(b, a) == -expected


def test_compare_program_keys_ordena_prefijos_por_longitud() -> None:
    assert compare_program_keys('{"a":1', '{"a":1}') == -1


def test_compare_program_keys_lanza_ante_un_caracter_fuera_de_la_tabla() -> None:
    # Falla ruidosa: significa que el DSL crecio y la tabla de colacion quedo desactualizada.
    with pytest.raises(ValueError, match="tabla de colacion"):
        compare_program_keys('{"a":1}', '{"a":ñ}')


def test_orden_total_de_claves_canonicas_coincide_con_el_typescript() -> None:
    # Orden exacto que devuelve Array.prototype.sort con localeCompare en Node sobre estas mismas
    # claves: "15" antes que "2" (comparacion lexicografica, no numerica) y el objeto vacio AL
    # FINAL, porque en ICU '}' pesa mas que el '"' que abre la clave `color`.
    keys = [program_key([make_object_extract(c)]) for c in (None, 0, 1, 15, 2)]
    assert sorted(keys, key=cmp_to_key(compare_program_keys)) == [
        '[{"name":"objectExtract","params":{"color":0}}]',
        '[{"name":"objectExtract","params":{"color":1}}]',
        '[{"name":"objectExtract","params":{"color":15}}]',
        '[{"name":"objectExtract","params":{"color":2}}]',
        '[{"name":"objectExtract","params":{}}]',
    ]


def test_contexto_serializa_en_camel_case_y_omite_el_ancla_ausente() -> None:
    assert EMPTY_CONTEXT.to_dict() == {}
    assert PrimitiveContext(anchor_grid=[[1]]).to_dict() == {"anchorGrid": [[1]]}
    assert PrimitiveContext.from_dict({"anchorGrid": [[1]]}).anchor_grid == [[1]]
    assert PrimitiveContext.from_dict({}).anchor_grid is None
