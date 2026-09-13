"""[arc-agi3-kaggle-agent/tests/test_bl21558_real_games] BL.21558 -- el efecto de la mascara de
volatilidad medido sobre partidas REALES de ARC-AGI-3, y la PARIDAD exacta con el motor TypeScript
canonico sobre esos mismos datos.

POR QUE HACE FALTA DATO REAL. La primera version de este fix pasaba todos sus tests sinteticos y
enmascaraba CERO celdas contra frames reales: el ruido de ARC-AGI-3 no es un digito que parpadea
(lo que simulaba el entorno de juguete) sino una BARRA de progreso que avanza UNA celda por paso,
con cada celda cambiando una sola vez en todo el episodio. Es la misma leccion de BL.21500 -- un
fix verde con efecto cero -- llevada al unico lugar donde no puede repetirse: la evidencia.

POR QUE LOS NUMEROS SON EXACTOS. Son un contrato ejecutable entre los dos puertos, igual que
dslParity.json: el archivo homonimo del lado TypeScript
(arc-agi-runner/src/worldModel/__tests__/bl21558.realGames.effect.test.ts) afirma exactamente los
mismos valores sobre exactamente la misma grabacion. Si un puerto cambia el criterio y el otro no,
uno de los dos se pone en rojo.

AISLAMIENTO. El fixture vive en el OTRO proyecto y se resuelve por ruta relativa con skip si no
esta: `arc-agi3-kaggle-agent` tiene que poder extraerse del monorepo y seguir corriendo sus tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc_agent.world_model import (
    SWEEP_MIN_CELLS,
    VolatilityTracker,
    compute_state_signature,
    is_no_op_transition,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "arc-agi-runner"
    / "src"
    / "worldModel"
    / "__fixtures__"
    / "volatilityRealGames.json"
)

#: Magnitudes medidas sobre la grabacion vigente. Por juego:
#: (celdas enmascaradas, no-ops sin mascara, no-ops con mascara, firmas sin mascara, firmas con
#: mascara). Regenerar el fixture (scripts/generateVolatilityRealFixture.ts) obliga a re-medir estos
#: numeros a mano en los DOS puertos -- que es exactamente lo que se quiere que cueste.
ESPERADO: dict[str, tuple[int, int, int, int, int]] = {
    "lf52-271a04aa": (64, 0, 90, 92, 3),
    "ar25-0c556536": (64, 4, 7, 78, 19),
    "ka59-38d34dbb": (64, 5, 6, 95, 9),
    "dc22-fdcac232": (64, 5, 9, 123, 9),
}


def _cargar_juegos() -> list[dict]:
    if not FIXTURE.exists():
        pytest.skip(
            f"fixture de partidas reales ausente ({FIXTURE}) -- se corre desde el monorepo; "
            "el agente extraido solo no lo tiene y eso es correcto por diseno."
        )
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["juegos"]


def _reconstruir(juego: dict) -> list[list[list[int]]]:
    """Reconstruye la secuencia de grillas aplicando los diffs sobre la grilla base."""
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

    no_ops_sin = 0
    no_ops_con = 0
    for i in range(len(juego["pasos"])):
        if is_no_op_transition(grillas[i], grillas[i + 1], None) is True:
            no_ops_sin += 1
        if is_no_op_transition(grillas[i], grillas[i + 1], mask) is True:
            no_ops_con += 1

    firmas_sin = set()
    firmas_con = set()
    for i, paso in enumerate(juego["pasos"]):
        disponibles = paso["accionesDisponibles"]
        firmas_sin.add(compute_state_signature(grillas[i + 1], disponibles, None))
        firmas_con.add(compute_state_signature(grillas[i + 1], disponibles, mask))

    filas = {
        y
        for y in range(juego["alto"])
        for x in range(juego["ancho"])
        if mask is not None and mask[y][x]
    }
    columnas = {
        x
        for y in range(juego["alto"])
        for x in range(juego["ancho"])
        if mask is not None and mask[y][x]
    }
    return {
        "celdas": tracker.volatile_cell_count(),
        "no_ops_sin": no_ops_sin,
        "no_ops_con": no_ops_con,
        "firmas_sin": len(firmas_sin),
        "firmas_con": len(firmas_con),
        "filas": filas,
        "columnas": columnas,
    }


def test_el_fixture_trae_las_cuatro_partidas_del_bl() -> None:
    juegos = _cargar_juegos()
    assert sorted(j["gameId"] for j in juegos) == sorted(ESPERADO)
    for juego in juegos:
        assert len(juego["pasos"]) > 60


def test_la_mascara_ve_la_barra_en_las_cuatro_partidas_reales() -> None:
    juegos = _cargar_juegos()
    for juego in juegos:
        medicion = _medir(juego)
        celdas, sin_mascara, con_mascara, firmas_sin, firmas_con = ESPERADO[juego["gameId"]]
        # Paridad exacta con el motor TypeScript sobre la misma grabacion.
        assert medicion["celdas"] == celdas, juego["gameId"]
        assert medicion["no_ops_sin"] == sin_mascara, juego["gameId"]
        assert medicion["no_ops_con"] == con_mascara, juego["gameId"]
        assert medicion["firmas_sin"] == firmas_sin, juego["gameId"]
        assert medicion["firmas_con"] == firmas_con, juego["gameId"]


def test_lo_enmascarado_es_una_linea_y_una_fraccion_minuscula_del_frame() -> None:
    # El error caro no es dejar el HUD adentro: es enmascarar tablero, que deja al agente ciego
    # justo donde esta la señal. Una barra ocupa una fila o una columna y nada mas.
    juegos = _cargar_juegos()
    for juego in juegos:
        medicion = _medir(juego)
        assert len(medicion["filas"]) == 1 or len(medicion["columnas"]) == 1, juego["gameId"]
        assert medicion["celdas"] >= SWEEP_MIN_CELLS
        assert medicion["celdas"] < juego["alto"] * juego["ancho"] * 0.05


def test_en_el_agregado_la_deteccion_de_no_ops_se_multiplica() -> None:
    # Por-juego el numero depende de la propia politica (en cuanto aprende que una accion no hace
    # nada, deja de gastarla); lo que no depende de la politica es que sobre la MISMA trayectoria la
    # mascara descubra los no-ops que la barra tapaba.
    juegos = _cargar_juegos()
    sin_mascara = sum(_medir(j)["no_ops_sin"] for j in juegos)
    con_mascara = sum(_medir(j)["no_ops_con"] for j in juegos)
    assert con_mascara > sin_mascara * 3
