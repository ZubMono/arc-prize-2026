"""[arc-agi3-kaggle-agent/tests/test_bl21561_real_games] BL.21561 -- el analizador objeto-centrico
medido sobre partidas REALES de ARC-AGI-3, y la PARIDAD exacta con el motor TypeScript canonico
sobre esos mismos datos.

POR QUE ESTE TEST Y NO UNO SINTETICO. Dos veces (BL.21500 y el primer intento de BL.21558) un
cambio paso todos sus tests y tuvo efecto CERO sobre dato real. La regla ahora es que el efecto se
mide sobre las partidas grabadas o no se mide. Aca se contrastan las DOS implementaciones sobre
exactamente los mismos pares (pre, post): `propose_all_steps` (el DSL grilla-a-grilla) devuelve el
conjunto vacio en el 100% de la muestra, y `detectar_mecanica` recupera 290 traslaciones y el mapeo
canonico de direcciones en 3 de los 4 juegos.

POR QUE LOS NUMEROS SON EXACTOS. Son un contrato ejecutable entre los dos puertos, igual que
dslParity.json: el archivo homonimo del lado TypeScript
(arc-agi-runner/src/worldModel/__tests__/bl21561.realGames.effect.test.ts) afirma exactamente los
mismos valores sobre exactamente la misma grabacion.

AISLAMIENTO. El fixture vive en el OTRO proyecto y se resuelve por ruta relativa con skip si no
esta: `arc-agi3-kaggle-agent` tiene que poder extraerse del monorepo y seguir corriendo sus tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc_agent.world_model import (
    MechanicsMemory,
    VolatilityTracker,
    detectar_mecanica,
    propose_all_steps,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "arc-agi-runner"
    / "src"
    / "worldModel"
    / "__fixtures__"
    / "volatilityRealGames.json"
)

# Magnitudes medidas sobre la grabacion vigente -- contrato de paridad con el motor TypeScript.
ESPERADO: dict[str, dict] = {
    "lf52-271a04aa": {
        # La partida grabada no movio NADA en 90 de 92 pasos (corrobora el round-robin del agente
        # viejo): hay una sola traslacion y por eso ninguna direccion llega a confirmarse.
        "traslaciones": 1,
        "sin_cambio": 90,
        "direcciones": {},
    },
    "ar25-0c556536": {
        "traslaciones": 76,
        "sin_cambio": 7,
        "direcciones": {
            "ACTION1": (-3, 0),
            "ACTION2": (3, 0),
            "ACTION3": (0, -3),
            "ACTION4": (0, 3),
        },
    },
    "ka59-38d34dbb": {
        "traslaciones": 94,
        "sin_cambio": 6,
        "direcciones": {
            "ACTION1": (-3, 0),
            "ACTION2": (3, 0),
            "ACTION3": (0, -3),
            "ACTION4": (0, 3),
        },
    },
    "dc22-fdcac232": {
        "traslaciones": 119,
        "sin_cambio": 9,
        "direcciones": {
            "ACTION1": (-2, 0),
            "ACTION2": (2, 0),
            "ACTION3": (0, -2),
            "ACTION4": (0, 2),
        },
    },
}

# Pasos por juego en los que se le pide una propuesta al DSL viejo. Es una MUESTRA: si en 30 pasos
# consecutivos no propone nada, el punto esta hecho y no hace falta pagar 400.
MUESTRA_DSL = 30


def _cargar() -> list[dict]:
    if not FIXTURE.exists():
        pytest.skip(f"fixture de partidas reales no disponible: {FIXTURE}")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["juegos"]


def _reconstruir(juego: dict) -> list[list[list[int]]]:
    grillas = [[list(fila) for fila in juego["base"]]]
    for paso in juego["pasos"]:
        siguiente = [list(fila) for fila in grillas[-1]]
        diff = paso["diff"]
        for i in range(0, len(diff), 3):
            siguiente[diff[i]][diff[i + 1]] = diff[i + 2]
        grillas.append(siguiente)
    return grillas


def _medir(juego: dict) -> dict:
    grillas = _reconstruir(juego)
    tracker = VolatilityTracker()
    for i, paso in enumerate(juego["pasos"]):
        tracker.observe(paso["accion"], grillas[i], grillas[i + 1])
    mask = tracker.mask

    memoria = MechanicsMemory()
    traslaciones = 0
    sin_cambio = 0
    for i, paso in enumerate(juego["pasos"]):
        mecanica = detectar_mecanica(grillas[i], grillas[i + 1], mask)
        if mecanica.tipo == "traslacion":
            traslaciones += 1
        if mecanica.tipo == "sinCambio":
            sin_cambio += 1
        memoria.observe(paso["accion"], grillas[i], grillas[i + 1], mask)

    direcciones = {a: memoria.get_direction(a) for a in memoria.get_movement_actions()}

    pasos_con_propuesta = 0
    for i in range(min(len(juego["pasos"]), MUESTRA_DSL)):
        if propose_all_steps(grillas[i], grillas[i + 1]):
            pasos_con_propuesta += 1

    return {
        "traslaciones": traslaciones,
        "sin_cambio": sin_cambio,
        "direcciones": direcciones,
        "pasos_con_propuesta_dsl": pasos_con_propuesta,
        "memoria": memoria,
    }


_MEDICIONES: dict[str, dict] = {}


def _mediciones() -> dict[str, dict]:
    if not _MEDICIONES:
        for juego in _cargar():
            _MEDICIONES[juego["gameId"]] = _medir(juego)
    return _MEDICIONES


def test_el_fixture_trae_las_cuatro_partidas() -> None:
    assert sorted(j["gameId"] for j in _cargar()) == [
        "ar25-0c556536",
        "dc22-fdcac232",
        "ka59-38d34dbb",
        "lf52-271a04aa",
    ]


def test_criterio_de_aceptacion_cursor_en_al_menos_3_juegos() -> None:
    con_cursor = [g for g, m in _mediciones().items() if m["direcciones"]]
    assert len(con_cursor) >= 3, f"solo {con_cursor}"


def test_el_dsl_grilla_a_grilla_no_propone_nada_en_ninguna_partida() -> None:
    """Es la evidencia de que esto es un REEMPLAZO y no una mejora incremental: sobre los mismos
    pares, el analizador viejo devuelve el conjunto vacio en el 100% de la muestra."""
    for game_id, medicion in _mediciones().items():
        assert medicion["pasos_con_propuesta_dsl"] == 0, game_id


def test_magnitudes_exactas_paridad_con_typescript() -> None:
    for game_id, medicion in _mediciones().items():
        esperado = ESPERADO[game_id]
        assert medicion["traslaciones"] == esperado["traslaciones"], game_id
        assert medicion["sin_cambio"] == esperado["sin_cambio"], game_id
        assert medicion["direcciones"] == esperado["direcciones"], game_id


def test_agregado_cientos_de_traslaciones_donde_el_dsl_veia_cero() -> None:
    total = sum(m["traslaciones"] for m in _mediciones().values())
    assert total > 250, total


def test_detector_4_la_arena_es_una_fraccion_chica_del_frame() -> None:
    for juego in _cargar():
        medicion = _mediciones()[juego["gameId"]]
        memoria: MechanicsMemory = medicion["memoria"]
        assert memoria.get_active_bounding_box() is not None
        celdas = juego["alto"] * juego["ancho"]
        # En los 4 juegos medidos, mas del 80% del frame no cambia NUNCA: es decorado.
        assert memoria.get_static_cell_count() > celdas * 0.8, juego["gameId"]


def test_detector_5_no_inventa_contadores() -> None:
    """Ninguna de las 4 partidas tiene un color cuya cuenta se mueva siempre en el mismo sentido
    (la barra de progreso, que si lo haria, ya la come la mascara de BL.21558). Que el detector
    devuelva vacio ACA es la prueba de que no dispara por cualquier cosa."""
    for game_id, medicion in _mediciones().items():
        assert medicion["memoria"].get_counters() == [], game_id


def test_las_direcciones_son_el_mapeo_canonico_de_arc_agi3() -> None:
    """No esta cableado en ningun lado: el analizador es parametrico sobre objetos y deltas y NO
    mira el game_id. Que los tres juegos coincidan es el resultado, no la premisa."""
    def signo(d: tuple[int, int]) -> tuple[int, int]:
        return ((d[0] > 0) - (d[0] < 0), (d[1] > 0) - (d[1] < 0))

    for game_id in ("ar25-0c556536", "ka59-38d34dbb", "dc22-fdcac232"):
        direcciones = _mediciones()[game_id]["direcciones"]
        assert signo(direcciones["ACTION1"]) == (-1, 0), game_id
        assert signo(direcciones["ACTION2"]) == (1, 0), game_id
        assert signo(direcciones["ACTION3"]) == (0, -1), game_id
        assert signo(direcciones["ACTION4"]) == (0, 1), game_id
