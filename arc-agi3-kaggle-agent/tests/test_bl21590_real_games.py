"""[arc-agi3-kaggle-agent/tests/test_bl21590_real_games] BL.21590 -- EFECTO del prior de
direcciones sobre las mismas partidas REALES de ARC-AGI-3 que usan BL.21558/21561, como DELTA
con-prior vs sin-prior.

QUE SE AFIRMA. (a) CON prior el mapeo correcto existe desde el PASO CERO (la siembra), y el
sin-prior (MechanicsMemory de BL.21561) tarda 10-12 pasos en recuperarlo -- ese es el ahorro que
el score de ARC penaliza cuadraticamente. (b) Bajo la grabacion round-robin del agente viejo
(rachas de a lo sumo DOS pasos iguales: el protocolo que FABRICA mapeos invertidos) la creencia
no comete UN solo remapeo espurio. (c) Las confirmaciones por corrida monotona llegan solo donde
la grabacion repite la accion, con el paso exacto anotado. (d) ACTION5/ACTION7 quedan
clasificadas por firma de mecanica con conteos exactos.

POR QUE LOS NUMEROS SON EXACTOS. Contrato ejecutable con el puerto TypeScript:
`arc-agi-runner/src/worldModel/__tests__/bl21590.realGames.effect.test.ts` afirma los MISMOS
valores sobre la MISMA grabacion.

AISLAMIENTO. El fixture vive en el OTRO proyecto y se resuelve por ruta relativa con skip si no
esta: `arc-agi3-kaggle-agent` tiene que poder extraerse del monorepo y seguir corriendo sus tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc_agent.direction_beliefs import (
    ESTADO_CONFIRMADA,
    ESTADO_REMAPEADA,
    CreenciaDeDirecciones,
    IncognitasDeMecanica,
)
from arc_agent.world_model import MechanicsMemory, VolatilityTracker, detectar_mecanica

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "arc-agi-runner"
    / "src"
    / "worldModel"
    / "__fixtures__"
    / "volatilityRealGames.json"
)

FLECHAS = ("ACTION1", "ACTION2", "ACTION3", "ACTION4")
MAPEO_CANONICO = {
    "ACTION1": (-1, 0),
    "ACTION2": (1, 0),
    "ACTION3": (0, -1),
    "ACTION4": (0, 1),
}

# Magnitudes medidas sobre la grabacion vigente -- contrato de paridad con el motor TypeScript.
# `paso_sin_prior` = primer paso en que MechanicsMemory conoce la direccion de las CUATRO flechas
# (None = jamas); `confirmadas_en` = paso de la primera corrida monotona que confirmo cada flecha
# (las que faltan nunca tuvieron dos pulsaciones consecutivas con traslacion: la grabacion es
# round-robin y ese protocolo no fabrica corridas).
ESPERADO: dict[str, dict] = {
    "lf52-271a04aa": {
        # 92 pasos y el detector solo no conoce NINGUNA direccion; el prior al menos deja la
        # hipotesis canonica en pie, sin un solo remapeo en falso.
        "paso_sin_prior": None,
        "confirmadas_en": {},
        "incognitas": {"ACTION7": ("inerte", 14)},
    },
    "ar25-0c556536": {
        "paso_sin_prior": 12,
        "confirmadas_en": {"ACTION3": 27},
        "incognitas": {"ACTION5": ("inerte", 3), "ACTION7": ("cambioDeEscena", 15)},
    },
    "ka59-38d34dbb": {
        "paso_sin_prior": 10,
        "confirmadas_en": {"ACTION1": 6, "ACTION2": 55, "ACTION4": 91},
        "incognitas": {},
    },
    "dc22-fdcac232": {
        "paso_sin_prior": 10,
        "confirmadas_en": {"ACTION2": 6, "ACTION3": 76, "ACTION4": 47},
        "incognitas": {},
    },
}


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

    creencia = CreenciaDeDirecciones()
    incognitas = IncognitasDeMecanica()
    memoria = MechanicsMemory()
    creencia.sembrar(juego["pasos"][0]["accionesDisponibles"])
    sembradas = creencia.acciones_sembradas()

    confirmadas_en: dict[str, int] = {}
    paso_sin_prior: int | None = None
    for i, paso in enumerate(juego["pasos"], start=1):
        mecanica = detectar_mecanica(grillas[i - 1], grillas[i], mask)
        creencia.observar(paso["accion"], mecanica)
        incognitas.observar(paso["accion"], mecanica)
        memoria.observe(paso["accion"], grillas[i - 1], grillas[i], mask)
        for a in sembradas:
            if a not in confirmadas_en and creencia.estado_de(a) == ESTADO_CONFIRMADA:
                confirmadas_en[a] = i
        if paso_sin_prior is None and all(memoria.get_direction(a) is not None for a in sembradas):
            paso_sin_prior = i

    return {
        "creencia": creencia,
        "incognitas": incognitas,
        "confirmadas_en": confirmadas_en,
        "paso_sin_prior": paso_sin_prior,
    }


_MEDICIONES: dict[str, dict] = {}


def _mediciones() -> dict[str, dict]:
    if not _MEDICIONES:
        for juego in _cargar():
            _MEDICIONES[juego["gameId"]] = _medir(juego)
    return _MEDICIONES


def test_delta_con_prior_el_mapeo_existe_en_el_paso_cero_sin_prior_tarda_10_a_12_pasos() -> None:
    """LA MAGNITUD DEL BL: el redescubrimiento que el prior ahorra, medido sobre dato real."""
    for game_id, m in _mediciones().items():
        creencia: CreenciaDeDirecciones = m["creencia"]
        assert creencia.acciones_sembradas() == list(FLECHAS), game_id
        assert creencia.mapeo() == MAPEO_CANONICO, game_id  # sembrado ANTES de la primera accion
        assert m["paso_sin_prior"] == ESPERADO[game_id]["paso_sin_prior"], game_id
        if m["paso_sin_prior"] is not None:
            assert m["paso_sin_prior"] >= 10, game_id


def test_cero_remapeos_espurios_bajo_el_round_robin_que_fabrica_mapeos_invertidos() -> None:
    """La grabacion vieja es EXACTAMENTE el protocolo que la medicion identifico como fabricante
    de inversiones (rachas <= 2). Que la creencia salga con cero refutaciones y cero remapeos es
    la prueba de que exigir corridas monotonas filtra ese artefacto."""
    for game_id, m in _mediciones().items():
        creencia: CreenciaDeDirecciones = m["creencia"]
        for a in FLECHAS:
            assert creencia._creencias[a].refutaciones == 0, f"{game_id} {a}"  # noqa: SLF001
            assert creencia.estado_de(a) != ESTADO_REMAPEADA, f"{game_id} {a}"


def test_las_confirmaciones_por_corrida_monotona_llegan_en_el_paso_exacto_medido() -> None:
    for game_id, m in _mediciones().items():
        assert m["confirmadas_en"] == ESPERADO[game_id]["confirmadas_en"], game_id


def test_action5_y_action7_quedan_clasificadas_por_firma_de_mecanica() -> None:
    for game_id, m in _mediciones().items():
        incognitas: IncognitasDeMecanica = m["incognitas"]
        for accion, (firma, conteo) in ESPERADO[game_id]["incognitas"].items():
            assert incognitas.dominante_de(accion) == firma, f"{game_id} {accion}"
            assert incognitas.conteos_de(accion)[firma] == conteo, f"{game_id} {accion}"
