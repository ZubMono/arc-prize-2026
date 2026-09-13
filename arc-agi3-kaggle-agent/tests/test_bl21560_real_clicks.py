"""[arc-agi3-kaggle-agent/tests/test_bl21560_real_clicks] BL.21560 -- el efecto del ranker de
coordenadas y de la memoria de clicks, medido sobre la partida REAL grabada en clickRealFrames.json
(corrida ft09-0d8bbf25 contra la API oficial de ARC-AGI-3).

POR QUE DATO REAL Y NO GRILLAS SINTETICAS. Ya paso dos veces (BL.21500 y el primer intento de
BL.21558) que un cambio "verde en los tests" tuviera efecto CERO contra frames reales. Aca la trampa
concreta es que el MISMO dibujo (una ficha 6x6 de color 9) aparece dos veces en pantalla: como panel
decorativo, donde el click no hace nada, y como ficha del tablero, donde siempre funciona. Ninguna
grilla sintetica razonable reproduce eso -- el dato si.

LOS NUMEROS SON UN CONTRATO entre los dos puertos, igual que en BL.21558: el archivo homonimo del
lado TypeScript (arc-agi-runner/src/worldModel/__tests__/bl21560.realClicks.effect.test.ts) afirma
exactamente los mismos valores sobre exactamente la misma grabacion. Si un puerto cambia el criterio
y el otro no, uno de los dos se pone en rojo.

AISLAMIENTO. El fixture vive en el OTRO proyecto y se resuelve por ruta relativa con skip si no
esta: `arc-agi3-kaggle-agent` tiene que poder extraerse del monorepo y seguir corriendo sus tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc_agent.banderas import Banderas
from arc_agent.click_targeting import (
    ClickFeatureBoard,
    ClickMemory,
    puntuar_celda,
    region_que_cambio,
    sigmoide,
)

#: BL.21702 -- este archivo mide el contrato de BL.21560 y sus numeros son un CONTRATO ENTRE LOS DOS
#: PUERTOS (el archivo homonimo del lado TypeScript afirma los mismos valores sobre la misma
#: grabacion). La memoria de coordenadas transversal al estado es una palanca POSTERIOR y solo
#: existe de este lado, asi que aca se mide con la palanca APAGADA: los dos puertos siguen
#: comparables. El efecto de encenderla se mide en tests/test_bl21702_palancas.py, sobre este mismo
#: corpus (232 -> 293 clicks productivos).
SIN_PALANCAS = Banderas(())
from arc_agent.priors import CLICK_PRIORS
from arc_agent.world_model import compute_state_signature

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "arc-agi-runner"
    / "src"
    / "worldModel"
    / "__fixtures__"
    / "clickRealFrames.json"
)

#: ft09 es CLICK-ONLY: la unica accion disponible es ACTION6, que es lo que reduce el juego al
#: problema de donde clickear.
ACCIONES_DISPONIBLES = (6,)

pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(),
    reason="corpus de clicks ausente (proyecto extraido del monorepo) -- ver exportClickCorpus.ts",
)


def _aplicar_diff(grid: list[list[int]], diff: list[int]) -> list[list[int]]:
    nueva = [fila[:] for fila in grid]
    for i in range(0, len(diff), 3):
        nueva[diff[i]][diff[i + 1]] = diff[i + 2]
    return nueva


def _clicks_reales() -> list[dict]:
    """Secuencia real de (grilla que el agente tenia delante, click, resultado)."""
    datos = json.loads(FIXTURE.read_text(encoding="utf-8"))
    salida: list[dict] = []
    for partida in datos["partidas"]:
        grid = [list(fila) for fila in partida["base"]]
        previa: list[list[int]] | None = None
        for paso in partida["pasos"]:
            siguiente = _aplicar_diff(grid, paso["diff"])
            if paso.get("x") is not None:
                salida.append(
                    {
                        "grid": grid,
                        "previa": previa,
                        "x": paso["x"],
                        "y": paso["y"],
                        "productivo": bool(paso["diff"]),
                    }
                )
            previa = grid
            grid = siguiente
    return salida


CLICKS = _clicks_reales() if FIXTURE.exists() else []


def test_el_corpus_trae_la_patologia_medida() -> None:
    assert len(CLICKS) == 346
    productivos = sum(1 for c in CLICKS if c["productivo"])
    assert productivos == 32

    vistas: set[tuple[int, int]] = set()
    fallidas: set[tuple[int, int]] = set()
    repetidas = 0
    sobre_fallida = 0
    for c in CLICKS:
        clave = (c["x"], c["y"])
        if clave in vistas:
            repetidas += 1
        if clave in fallidas:
            sobre_fallida += 1
        vistas.add(clave)
        if not c["productivo"]:
            fallidas.add(clave)
    assert repetidas == 117
    assert sobre_fallida == 106
    # 9,2%: no es mala suerte. La heuristica previa sorteaba uniformemente entre ~410 celdas de
    # "borde de color" de las cuales ~36 son esquinas de ficha -- 36/410 = 8,8%.
    assert round(productivos / len(CLICKS), 4) == 0.0925


def test_la_etiqueta_es_consistente_por_coordenada() -> None:
    productivas = {(c["x"], c["y"]) for c in CLICKS if c["productivo"]}
    muertas = {(c["x"], c["y"]) for c in CLICKS if not c["productivo"]}
    assert productivas & muertas == set()
    assert len(productivas) == 21


def test_el_ranker_separa_productivos_de_muertos_sobre_los_clicks_reales() -> None:
    """Metrica sin contrafactuales: se puntua cada click que el agente REALMENTE hizo y se mide
    cuantos de los que el ranker habria aprobado eran productivos."""
    umbral = CLICK_PRIORS["umbralesDetectores"]["probabilidadMinimaDeClick"]
    aprobados = 0
    aprobados_productivos = 0
    for c in CLICKS:
        tablero = ClickFeatureBoard(c["grid"], region_que_cambio(c["previa"], c["grid"]))
        prob = sigmoide(
            puntuar_celda(tablero.features(c["x"], c["y"]), CLICK_PRIORS["pesosClick"])
        )
        if prob < umbral:
            continue
        aprobados += 1
        if c["productivo"]:
            aprobados_productivos += 1
    # Los 32 productivos entran y ningun muerto se cuela: precision 1,00 contra la tasa base 0,092.
    assert aprobados == 32
    assert aprobados_productivos == 32


def test_la_politica_nueva_elige_coordenadas_productivas() -> None:
    """Evaluacion off-policy CONSERVADORA: se recorre la MISMA trayectoria real (la politica no
    puede cambiar el tablero, asi que no se inventa ninguna transicion) y en cada paso se le pide a
    la memoria de clicks su coordenada. Una coordenada sin observar cuenta como DESCONOCIDA y se le
    realimenta "no hubo cambio" -- el lado pesimista, que castiga a la politica nueva quitandole
    plantillas que quizas merecia."""
    oraculo: dict[tuple[int, int], bool] = {}
    for c in CLICKS:
        clave = (c["x"], c["y"])
        oraculo[clave] = oraculo.get(clave, False) or c["productivo"]

    memoria = ClickMemory(banderas=SIN_PALANCAS)
    productivos = muertos = desconocidos = repetidas = 0
    emitidas: set[tuple[int, int, int]] = set()

    for c in CLICKS:
        firma = compute_state_signature(c["grid"], ACCIONES_DISPONIBLES, None)
        x, y = memoria.elegir_objetivo(
            c["grid"], firma, lambda: 0.5, region_que_cambio(c["previa"], c["grid"])
        )
        if (firma, x, y) in emitidas:
            repetidas += 1
        emitidas.add((firma, x, y))

        etiqueta = oraculo.get((x, y))
        if etiqueta is None:
            desconocidos += 1
        elif etiqueta:
            productivos += 1
        else:
            muertos += 1
        memoria.registrar_resultado(firma, x, y, etiqueta is True, c["grid"])

    # Nunca repite un (firma, x, y): garantia estructural de la capa de memoria. Por si sola borra
    # los 106 clicks que el agente gasto sobre coordenadas ya fallidas.
    assert repetidas == 0
    # Clicks sobre una coordenada que el corpus vio fallar: 106 -> 1. El unico que queda es un
    # artefacto de la realimentacion pesimista de esta simulacion (a las coordenadas desconocidas se
    # les responde "no hubo cambio", lo que crea anti-plantillas que el juego real no crearia).
    assert muertos == 1
    # 232 aciertos comprobados sobre los mismos 346 pasos, contra los 32 que la partida grabo:
    # 67,1% contra 9,2%. Los 113 restantes caen en coordenadas que el corpus nunca probo, asi que
    # 67,1% es un PISO, no el techo.
    assert productivos == 232
    assert desconocidos == 113
    assert memoria.plantillas_aprendidas == 7
