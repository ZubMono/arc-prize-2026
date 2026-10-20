"""[arc-agi3-kaggle-agent/tests/test_bl22856_metricas_densas] BL.22856 -- las metricas densas y su
criterio de admision.

Dos mitades, una por cada mitad del BL:
  1. `metricas_de_partida`/`agregar_densas` cuentan LO QUE DICEN contar, sobre FrameData REALES
     (los del repo, hasheables) -- no sobre un stub que podria divergir del contrato.
  2. `analizar` de la calibracion decide ADMISION por rangos disjuntos, mantiene el control
     negativo (nivelesTotales), y falla CERRADO (exit 2) cuando no hay datos suficientes o las
     corridas no son comparables -- nunca un veredicto fabricado.

El test de SENSIBILIDAD existe por RFM-61: una metrica que devuelve constantes pasaria cualquier
conteo puntual; aca dos partidas distintas TIENEN que producir numeros distintos, que es el control
positivo de que el instrumento ve algo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ))

from arc_agent.types import FrameData, GameState  # noqa: E402
from metricas_densas import agregar_densas, metricas_de_partida  # noqa: E402
from calibracion_de_metricas import analizar  # noqa: E402


def _grilla(valor: int):
    return ((tuple([valor] * 4),) * 4,)


def _frame(grilla, niveles: int = 0) -> FrameData:
    return FrameData(
        game_id="test", guid="g", frame=grilla, state=GameState.NOT_FINISHED,
        available_actions=(1,), levels_completed=niveles,
    )


class SinGrilla:
    """Un frame que no expone `.frame` ni `.levels_completed` -- el agente inlineado minimo."""


# ─── mitad 1: el instrumento cuenta lo que dice contar ───────────────────────────────────────────

def test_cuenta_cambios_estados_y_primer_avance():
    a, b = _grilla(1), _grilla(2)
    frames = [_frame(a), _frame(a), _frame(b, niveles=1), _frame(b, niveles=1)]
    m = metricas_de_partida(frames)
    assert m["framesConCambio"] == 1, "solo la transicion a->b cambio la grilla"
    assert m["estadosDistintos"] == 2
    assert m["pasoPrimerAvance"] == 2
    assert m["avanceTemprano"] == 1, "despues del frame 2 quedo 1 frame"
    assert m["framesSinGrilla"] == 0


def test_sin_avance_es_none_y_no_cero():
    frames = [_frame(_grilla(1)), _frame(_grilla(2))]
    m = metricas_de_partida(frames)
    assert m["pasoPrimerAvance"] is None, "'no avanzo' y 'avanzo en el paso 0' son dos estados"
    assert m["avanceTemprano"] == 0


def test_frames_sin_grilla_se_declaran_no_se_disimulan():
    frames = [_frame(_grilla(1)), SinGrilla(), _frame(_grilla(2))]
    m = metricas_de_partida(frames)
    assert m["framesSinGrilla"] == 1
    assert m["framesConCambio"] == 1, "los cambios se cuentan sobre las grillas que SI se vieron"


def test_grillas_del_framework_real_son_listas_y_cuentan_igual():
    # El FrameData que el gate ve corriendo el agente inlineado trae LISTAS (formato wire), no
    # las tuplas del mirror del repo: el primer smoke murio con `unhashable type: 'list'`. Las
    # dos formas de la MISMA grilla tienen que dar las MISMAS metricas.
    class FrameWire:
        def __init__(self, grilla, niveles=0):
            self.frame = grilla
            self.levels_completed = niveles

    en_listas = [FrameWire([[[1, 1], [1, 1]]]), FrameWire([[[2, 2], [2, 2]]], niveles=1)]
    en_tuplas = [_frame(((tuple([1, 1]),) * 2,)), _frame(((tuple([2, 2]),) * 2,), niveles=1)]
    assert metricas_de_partida(en_listas) == metricas_de_partida(en_tuplas)
    assert metricas_de_partida(en_listas)["framesConCambio"] == 1


def test_grilla_inconvertible_cuenta_como_no_mirada():
    class FrameRoto:
        frame = 42  # ni lista ni tupla: no es una grilla
        levels_completed = 0

    m = metricas_de_partida([_frame(_grilla(1)), FrameRoto()])
    assert m["framesSinGrilla"] == 1, "inconvertible NO es 'sin cambio': es 'no pude mirar'"
    assert m["estadosDistintos"] == 1


def test_partida_vacia_no_revienta():
    m = metricas_de_partida([])
    assert m["framesConCambio"] == 0 and m["estadosDistintos"] == 0
    assert m["pasoPrimerAvance"] is None


def test_sensibilidad_dos_partidas_distintas_dan_numeros_distintos():
    quieta = [_frame(_grilla(1))] * 5
    movida = [_frame(_grilla(k)) for k in range(5)]
    assert metricas_de_partida(quieta) != metricas_de_partida(movida), (
        "si dos partidas opuestas dan lo mismo, el instrumento no ve nada y su veredicto "
        "no significa nada"
    )


def test_agregar_densas_totaliza_y_cuenta_partidas():
    con = {"densas": metricas_de_partida([_frame(_grilla(1)), _frame(_grilla(2))])}
    sin = {"niveles": 0}
    totales = agregar_densas({"s1": {"j1": con, "j2": con}, "s2": {"j1": con, "j2": sin}})
    assert totales["partidasMedidas"] == 3, "la fila sin densas NO se cuenta como medida"
    assert totales["framesConCambio"] == 3
    assert totales["estadosDistintos"] == 6


# ─── mitad 2: la admision decide por rangos y falla cerrado ──────────────────────────────────────

def _gate_json(niveles: int, cambios: int, partidas: int = 75) -> dict:
    return {
        "config": {"pasos": 200},
        "totales": {
            "nivelesTotales": niveles,
            "densasTotales": {
                "framesConCambio": cambios, "estadosDistintos": cambios * 2,
                "avanceTemprano": 0, "partidasMedidas": partidas, "framesSinGrilla": 0,
            },
        },
    }


def _escribir(directorio: Path, docs: list[dict]) -> Path:
    directorio.mkdir(parents=True, exist_ok=True)
    for i, doc in enumerate(docs):
        (directorio / f"corrida-{i}.json").write_text(json.dumps(doc), encoding="utf-8")
    return directorio


def test_admision_por_rangos_disjuntos(tmp_path):
    # base: cambios 100-110; candidato: 150-160 -> separa. niveles solapados -> control en pie.
    base = _escribir(tmp_path / "base", [_gate_json(9, 100), _gate_json(11, 110)])
    cand = _escribir(tmp_path / "cand", [_gate_json(10, 150), _gate_json(8, 160)])
    informe, codigo = analizar(base, cand)
    assert codigo == 0 and informe["pudoAnalizar"]
    assert "framesConCambio" in informe["admitidas"]
    assert informe["controlNegativo"]["premisaReproducida"], "niveles solapa: la premisa se sostiene"
    assert informe["descartadasSinMedir"], "las no medidas van DICHAS en el informe, no borradas"


def test_ninguna_separa_se_dice_con_esas_palabras(tmp_path):
    base = _escribir(tmp_path / "base", [_gate_json(9, 100), _gate_json(11, 120)])
    cand = _escribir(tmp_path / "cand", [_gate_json(10, 110), _gate_json(8, 115)])
    informe, codigo = analizar(base, cand)
    assert codigo == 0 and informe["ningunaSepara"] and informe["admitidas"] == []


def test_con_una_sola_corrida_no_hay_veredicto(tmp_path):
    base = _escribir(tmp_path / "base", [_gate_json(9, 100)])
    cand = _escribir(tmp_path / "cand", [_gate_json(10, 150), _gate_json(8, 160)])
    informe, codigo = analizar(base, cand)
    assert codigo == 2 and not informe["pudoAnalizar"]


def test_partidas_desiguales_no_son_comparables(tmp_path):
    base = _escribir(tmp_path / "base", [_gate_json(9, 100), _gate_json(11, 110)])
    cand = _escribir(tmp_path / "cand", [_gate_json(10, 150), _gate_json(8, 160, partidas=74)])
    informe, codigo = analizar(base, cand)
    assert codigo == 2, "un total sumado sobre menos partidas se leeria como caida del agente"
