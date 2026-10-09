"""[arc-agi3-kaggle-agent/tests/test_bl21593_real_games] BL.21593 -- EFECTO del posterior
jerarquico sobre las mismas partidas REALES de ARC-AGI-3 (fixture compartido con BL.21558/61/90),
como DELTA contra la maquina de estados de BL.21590 sola.

QUE SE AFIRMA, con numeros exactos (paridad con bl21593.realGames.effect.test.ts):
  (a) DELTA "acciones hasta mapeo resuelto": con el posterior las cuatro flechas quedan
      resueltas en 5-14 pasos; con SOLO los estados terminales de BL.21590 (confirmada/
      remapeada/observada/sinEvidencia) NINGUNA de las cuatro partidas resuelve jamas el mapeo
      completo -- la grabacion round-robin no fabrica corridas para todas las flechas y el
      libro (que declara sinEvidencia) no corre en esta reproduccion abierta.
  (b) El posterior llega a las respuestas CORRECTAS: mapeo canonico al 0.98 donde las flechas
      mueven (ar25/ka59/dc22) e `inerte` via arquetipo flechasSinMapeo donde no (lf52).
  (c) La pared se VE en dato real: lf52 tiene 44 fallos de flecha con pared presente en la
      direccion canonica -- fallos que quedan explicados y no cuentan contra el mapeo.
  (d) Cero remapeos espurios: el posterior corre bajo el MISMO protocolo round-robin que
      fabrica mapeos invertidos y no cambia una sola direccion en falso.

AISLAMIENTO. El fixture vive en el OTRO proyecto y se resuelve por ruta relativa con skip si no
esta: este proyecto tiene que poder extraerse del monorepo y seguir corriendo sus tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc_agent.direction_beliefs import CreenciaDeDirecciones
from arc_agent.mechanics_posterior import ARQUETIPO_MUEVE, ARQUETIPO_SIN_MAPEO
from arc_agent.wall_perception import (
    PARED_PRESENTE,
    RastreadorDeAvatar,
    contexto_de_pared,
    profundidad_de_sondeo,
)
from arc_agent.world_model import VolatilityTracker, detectar_mecanica

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "arc-agi-runner"
    / "src"
    / "worldModel"
    / "__fixtures__"
    / "volatilityRealGames.json"
)

ESTADOS_TERMINALES_21590 = ("confirmada", "remapeada", "observada", "sinEvidencia")
NOMBRE_DE_DIRECCION = {(-1, 0): "arriba", (1, 0): "abajo", (0, -1): "izquierda", (0, 1): "derecha"}

#: Magnitudes medidas sobre la grabacion vigente -- contrato de paridad con el motor TypeScript.
ESPERADO: dict[str, dict] = {
    "lf52-271a04aa": {
        "pasoResueltoPosterior": 14,
        "dominantes": {a: "inerte" for a in ("ACTION1", "ACTION2", "ACTION3", "ACTION4")},
        "arquetipo": ARQUETIPO_SIN_MAPEO,
        "fallosConParedCanonica": 44,
    },
    "ar25-0c556536": {
        "pasoResueltoPosterior": 7,
        "dominantes": {
            "ACTION1": "arriba", "ACTION2": "abajo", "ACTION3": "izquierda", "ACTION4": "derecha",
        },
        "arquetipo": ARQUETIPO_MUEVE,
        "fallosConParedCanonica": 1,
    },
    "ka59-38d34dbb": {
        "pasoResueltoPosterior": 5,
        "dominantes": {
            "ACTION1": "arriba", "ACTION2": "abajo", "ACTION3": "izquierda", "ACTION4": "derecha",
        },
        "arquetipo": ARQUETIPO_MUEVE,
        "fallosConParedCanonica": 0,
    },
    "dc22-fdcac232": {
        "pasoResueltoPosterior": 5,
        "dominantes": {
            "ACTION1": "arriba", "ACTION2": "abajo", "ACTION3": "izquierda", "ACTION4": "derecha",
        },
        "arquetipo": ARQUETIPO_MUEVE,
        "fallosConParedCanonica": 0,
    },
}


def _cargar_juegos() -> list[dict]:
    if not FIXTURE.exists():
        pytest.skip("fixture volatilityRealGames.json no disponible (proyecto extraido)")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["juegos"]


def _medir(juego: dict) -> dict:
    """Reproduce la partida con el MISMO pipeline que la politica: mascara del episodio,
    detector de BL.21561, contexto de pared del rastreador y creencia con posterior."""
    grillas = [[fila[:] for fila in juego["base"]]]
    for paso in juego["pasos"]:
        siguiente = [fila[:] for fila in grillas[-1]]
        d = paso["diff"]
        for i in range(0, len(d), 3):
            siguiente[d[i]][d[i + 1]] = d[i + 2]
        grillas.append(siguiente)

    tracker_vol = VolatilityTracker()
    for i, paso in enumerate(juego["pasos"]):
        tracker_vol.observe(paso["accion"], grillas[i], grillas[i + 1])
    mask = tracker_vol.mask

    creencia = CreenciaDeDirecciones()
    creencia.sembrar(juego["pasos"][0]["accionesDisponibles"])
    sembradas = creencia.acciones_sembradas()
    avatar = RastreadorDeAvatar()

    paso_resuelto_posterior = None
    paso_resuelto_estados = None
    fallos_con_pared = 0
    for i, paso in enumerate(juego["pasos"]):
        mecanica = detectar_mecanica(grillas[i], grillas[i + 1], mask)
        pared = None
        if paso["accion"] in sembradas and mecanica.traslacion_principal is None:
            pared = contexto_de_pared(
                grillas[i],
                avatar.caja,
                avatar.piso,
                profundidad_de_sondeo(creencia.magnitud_de(paso["accion"])),
            )
            canonica = creencia.direccion_de(paso["accion"])
            nombre = NOMBRE_DE_DIRECCION.get(canonica)
            if nombre is not None and pared[nombre] == PARED_PRESENTE:
                fallos_con_pared += 1
        creencia.observar(paso["accion"], mecanica, pared)
        avatar.observar(mecanica, grillas[i + 1])
        if paso_resuelto_posterior is None and all(creencia.resuelta(a) for a in sembradas):
            paso_resuelto_posterior = i + 1
        if paso_resuelto_estados is None and all(
            creencia.estado_de(a) in ESTADOS_TERMINALES_21590 for a in sembradas
        ):
            paso_resuelto_estados = i + 1

    return {
        "creencia": creencia,
        "sembradas": sembradas,
        "pasoResueltoPosterior": paso_resuelto_posterior,
        "pasoResueltoEstados": paso_resuelto_estados,
        "fallosConPared": fallos_con_pared,
    }


@pytest.fixture(scope="module")
def mediciones() -> dict[str, dict]:
    return {juego["gameId"]: _medir(juego) for juego in _cargar_juegos()}


def test_delta_acciones_hasta_mapeo_resuelto(mediciones: dict[str, dict]) -> None:
    """La metrica del BL: el posterior resuelve el mapeo completo en 5-14 pasos donde la maquina
    de estados de BL.21590 sola JAMAS lo logra sobre la misma grabacion."""
    for game_id, esperado in ESPERADO.items():
        medicion = mediciones[game_id]
        assert medicion["pasoResueltoPosterior"] == esperado["pasoResueltoPosterior"], game_id
        assert medicion["pasoResueltoEstados"] is None, game_id  # la baseline no llega nunca


def test_el_posterior_llega_a_las_respuestas_correctas(mediciones: dict[str, dict]) -> None:
    for game_id, esperado in ESPERADO.items():
        medicion = mediciones[game_id]
        posterior = medicion["creencia"].posterior
        for accion, mecanica in esperado["dominantes"].items():
            dominante = posterior.mecanica_dominante(accion)
            assert dominante is not None and dominante[0] == mecanica, (game_id, accion)
            assert dominante[1] > 0.9, (game_id, accion)
        arquetipo = posterior.posterior_de_arquetipo()
        assert max(arquetipo, key=lambda a: arquetipo[a]) == esperado["arquetipo"], game_id
        assert arquetipo[esperado["arquetipo"]] > 0.9, game_id


def test_la_pared_se_ve_en_dato_real(mediciones: dict[str, dict]) -> None:
    """lf52: 44 fallos de flecha con pared observada en la direccion canonica -- el termino
    P(pared|grilla) de la descomposicion existe en la grabacion, no solo en los sinteticos."""
    for game_id, esperado in ESPERADO.items():
        assert mediciones[game_id]["fallosConPared"] == esperado["fallosConParedCanonica"], game_id


def test_cero_remapeos_espurios_bajo_round_robin(mediciones: dict[str, dict]) -> None:
    """El protocolo que FABRICA mapeos invertidos (medido: 20 lecturas contra 6) no consigue que
    el posterior cambie una sola direccion en falso."""
    canonico = {"ACTION1": (-1, 0), "ACTION2": (1, 0), "ACTION3": (0, -1), "ACTION4": (0, 1)}
    for game_id, medicion in mediciones.items():
        creencia = medicion["creencia"]
        for accion in medicion["sembradas"]:
            assert creencia.estado_de(accion) != "remapeada", (game_id, accion)
            direccion = creencia.posterior.direccion_de(accion)
            if direccion is not None:
                assert direccion == canonico[accion], (game_id, accion)
