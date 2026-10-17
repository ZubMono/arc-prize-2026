"""[arc-agi3-kaggle-agent/tests/test_kaggle_adapter] BL.21555 -- el contrato del wrapper `MyAgent`
contra el framework REAL (`arcengine` + `agents` del dataset de la competencia).

QUE PROTEGE. Las tres clausulas del contrato oficial que, mal cableadas, matan la submission sin
sintoma local: (1) `is_done` que corta en GAME_OVER pierde todos los reintentos (el starter lo
dice literal: "Don't stop on GAME_OVER, we want to RESET and retry"); (2) un ACTION6 sin
`set_data` o fuera de 0..63 lo rechaza el gateway; (3) la traduccion de frames tiene que producir
la representacion interna EXACTA (tuplas hasheables, NOT_PLAYED->NOT_STARTED, sin el id 0 en las
acciones disponibles) o la memoria de exploracion trabaja sobre basura.

AISLAMIENTO. `arcengine` viene de la wheel del dataset y `agents` del framework vendorizado:
sin `make setup` estos tests se skipean limpio con razon accionable (CI no baja el dataset)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

arcengine = pytest.importorskip(
    "arcengine", reason="arcengine no instalado: correr `make setup` y ejecutar con `make test`"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from starter_config import VENDOR_DIR, faltantes_para_jugar  # noqa: E402

if faltantes_para_jugar():
    pytest.skip("dataset no descargado: correr `make setup`", allow_module_level=True)
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))
pytest.importorskip(
    "agents.agent", reason="framework vendorizado no importable: correr `make setup`"
)

from arc_agent.kaggle_adapter import (  # noqa: E402  (necesita arcengine + vendor de arriba)
    MyAgent,
    decision_a_accion_oficial,
    frame_oficial_a_interno,
)
from arc_agent.reloj_presupuesto import (  # noqa: E402
    COTA_DE_SEGURIDAD_DE_ACCIONES,
    RelojDePresupuesto,
)
from arc_agent.types import ActionDecision, FrameData, GameAction, GameState  # noqa: E402


def frame_oficial(**kwargs) -> "arcengine.FrameData":
    base = dict(
        game_id="ls20-test",
        frame=[[[1, 2], [3, 4]]],
        state=arcengine.GameState.NOT_FINISHED,
        levels_completed=1,
        win_levels=3,
        available_actions=[1, 2, 3, 6],
    )
    base.update(kwargs)
    return arcengine.FrameData(**base)


def agente_de_prueba(semilla: str = "semilla-test", reloj: RelojDePresupuesto | None = None) -> MyAgent:
    """MyAgent con los MISMOS kwargs que usa play_local.py -- el contrato `__init__(*args,
    **kwargs)` delegando en super() es parte de lo que se prueba.

    `reloj` inyecta un reloj de presupuesto propio (BL.21701) para no tocar el global del proceso:
    un test que agotara `RELOJ_GLOBAL` dejaria a los siguientes cortando de entrada."""
    MyAgent.SEMILLA = semilla
    reloj_previo = MyAgent.RELOJ
    if reloj is not None:
        MyAgent.RELOJ = reloj
    try:
        return MyAgent(
            card_id="test",
            game_id="ls20",
            agent_name="MyAgent.test",
            ROOT_URL="http://localhost",
            record=False,
            arc_env=None,
        )
    finally:
        MyAgent.SEMILLA = None
        MyAgent.RELOJ = reloj_previo


class TestConversionDeFrames:
    def test_estados_se_mapean_al_vocabulario_interno(self) -> None:
        esperados = {
            arcengine.GameState.NOT_PLAYED: GameState.NOT_STARTED,
            arcengine.GameState.NOT_FINISHED: GameState.NOT_FINISHED,
            arcengine.GameState.WIN: GameState.WIN,
            arcengine.GameState.GAME_OVER: GameState.GAME_OVER,
        }
        for oficial, interno in esperados.items():
            assert frame_oficial_a_interno(frame_oficial(state=oficial)).state is interno

    def test_la_grilla_queda_hasheable_para_la_firma_de_estado(self) -> None:
        interno = frame_oficial_a_interno(frame_oficial())
        assert isinstance(interno, FrameData)
        assert interno.frame == (((1, 2), (3, 4)),)
        hash((interno.frame, interno.available_actions))  # lo que hace compute_signature

    def test_el_id_de_reset_no_entra_al_ranking_de_exploracion(self) -> None:
        """El nucleo mapea cada id a `ACTION{n}`: el 0 (RESET) no es una accion de exploracion y
        `GameAction("ACTION0")` seria un ValueError en pleno ranking."""
        interno = frame_oficial_a_interno(frame_oficial(available_actions=[0, 3, 1]))
        assert interno.available_actions == (1, 3)

    def test_frame_vacio_no_rompe(self) -> None:
        interno = frame_oficial_a_interno(
            frame_oficial(frame=[], state=arcengine.GameState.NOT_PLAYED, available_actions=[], levels_completed=0)
        )
        assert interno.frame == ()
        assert interno.state is GameState.NOT_STARTED

    def test_preserva_todas_las_capas_de_animacion_no_solo_la_ultima(self) -> None:
        """BL.22236 -- `frame.frame` oficial trae UNA capa por `step()` interno mientras la accion
        anima antes de asentarse. Esta frontera NUNCA debe recortarlas a la ultima: eso descartaria
        justo la evidencia que `extraer_grid_multicapa`/`_feed_capas_intermedias` necesitan para
        ver mecanicas que solo existen en una capa intermedia."""
        interno = frame_oficial_a_interno(
            frame_oficial(frame=[[[1, 1], [1, 1]], [[2, 2], [2, 2]], [[3, 3], [3, 3]]])
        )
        assert interno.frame == (
            ((1, 1), (1, 1)),
            ((2, 2), (2, 2)),
            ((3, 3), (3, 3)),
        )


class TestConversionDeDecisiones:
    def test_action6_viaja_con_set_data_y_razonamiento(self) -> None:
        decision = ActionDecision(action=GameAction.ACTION6, x=5, y=9, reasoning="click de prueba")
        accion = decision_a_accion_oficial(decision)
        assert accion is arcengine.GameAction.ACTION6
        assert accion.action_data.x == 5 and accion.action_data.y == 9
        assert accion.reasoning["razonamiento"] == "click de prueba"

    def test_coordenadas_se_clampan_a_la_grilla_oficial(self) -> None:
        decision = ActionDecision(action=GameAction.ACTION6, x=99, y=-4, reasoning="fuera de rango")
        accion = decision_a_accion_oficial(decision)
        assert accion.action_data.x == 63 and accion.action_data.y == 0

    def test_accion_simple_conserva_el_razonamiento(self) -> None:
        decision = ActionDecision(action=GameAction.ACTION3, reasoning="exploracion")
        accion = decision_a_accion_oficial(decision)
        assert accion is arcengine.GameAction.ACTION3
        assert accion.reasoning == "exploracion"


class TestContratoMyAgent:
    def test_is_done_solo_corta_al_ganar(self) -> None:
        agente = agente_de_prueba()
        ganado = frame_oficial(state=arcengine.GameState.WIN)
        assert agente.is_done([ganado], ganado) is True
        for estado in (
            arcengine.GameState.NOT_PLAYED,
            arcengine.GameState.NOT_FINISHED,
            arcengine.GameState.GAME_OVER,  # el starter: "Don't stop on GAME_OVER"
        ):
            frame = frame_oficial(state=estado)
            assert agente.is_done([frame], frame) is False, estado

    def test_game_over_resetea_y_sigue_jugando(self) -> None:
        agente = agente_de_prueba()
        frame = frame_oficial(state=arcengine.GameState.GAME_OVER)
        assert agente.choose_action([frame], frame) is arcengine.GameAction.RESET

    def test_partida_sin_arrancar_resetea(self) -> None:
        agente = agente_de_prueba()
        frame = frame_oficial(state=arcengine.GameState.NOT_PLAYED, frame=[], available_actions=[])
        assert agente.choose_action([frame], frame) is arcengine.GameAction.RESET

    def test_en_estado_jugable_emite_una_accion_disponible(self) -> None:
        agente = agente_de_prueba()
        frame = frame_oficial()
        accion = agente.choose_action([frame], frame)
        assert accion.value in {1, 2, 3, 6}, "la accion tiene que salir de available_actions"
        assert accion.reasoning, "el razonamiento declarado es parte del contrato de replay"

    def test_misma_semilla_misma_trayectoria(self) -> None:
        """Reproducibilidad para depurar: dos agentes con la misma SEMILLA deciden lo mismo."""
        decisiones = []
        for _ in range(2):
            agente = agente_de_prueba(semilla="determinista")
            frame = frame_oficial()
            decisiones.append([agente.choose_action([frame], frame).value for _ in range(5)])
        assert decisiones[0] == decisiones[1]

    def test_max_actions_es_la_cota_de_seguridad_y_no_el_limite_operativo(self) -> None:
        """BL.21701: el limite operativo lo pone el reloj (8 h repartidas entre las partidas del
        batch). `MAX_ACTIONS` quedo como la cota que el framework pide "to avoid looping forever",
        y su valor tiene UNA sola fuente: `reloj_presupuesto.COTA_DE_SEGURIDAD_DE_ACCIONES`."""
        assert MyAgent.MAX_ACTIONS == COTA_DE_SEGURIDAD_DE_ACCIONES
        assert MyAgent.MAX_ACTIONS > 1600, "la curva de score todavia subia en 1600 acciones"


def reloj_agotado() -> RelojDePresupuesto:
    """Reloj cuyo presupuesto ya vencio, con tiempo INYECTADO en vez de esperado: la marca de
    inicio sale en 0 y toda consulta posterior devuelve un instante muy pasado el deadline. Un
    test que dependiera de dormir seria lento y flakeante."""
    marca = {"t": 0.0}

    def ahora() -> float:
        valor = marca["t"]
        marca["t"] = 10_000.0
        return valor

    return RelojDePresupuesto(presupuesto_segundos=100.0, margen_de_cierre=10.0, ahora=ahora)


class TestRelojDePresupuestoEnElContratoReal:
    """El cableado del guard de las 9 h (BL.21701) contra los tipos REALES de `arcengine`."""

    def test_is_done_corta_cuando_el_reloj_se_agota(self) -> None:
        """El corte tiene que salir por la MISMA puerta que la victoria: `is_done` True. El
        framework termina su `while`, corre `cleanup()` y el Swarm cierra la scorecard."""
        agente = agente_de_prueba(reloj=reloj_agotado())
        jugable = frame_oficial()
        assert agente.is_done([jugable], jugable) is True
        assert agente.cortada_por_reloj is True

    def test_con_reloj_holgado_sigue_jugando(self) -> None:
        agente = agente_de_prueba(reloj=RelojDePresupuesto(presupuesto_segundos=3600.0))
        jugable = frame_oficial()
        assert agente.is_done([jugable], jugable) is False
        assert agente.cortada_por_reloj is False

    def test_ganar_gana_aunque_el_reloj_este_agotado(self) -> None:
        """La victoria no puede quedar tapada por el corte por tiempo: se reporta como victoria."""
        agente = agente_de_prueba(reloj=reloj_agotado())
        ganado = frame_oficial(state=arcengine.GameState.WIN)
        assert agente.is_done([ganado], ganado) is True
        assert agente.cortada_por_reloj is False

    def test_game_over_no_corta_ni_con_el_reloj_holgado(self) -> None:
        """El reloj no puede haber cambiado la clausula que el starter marca literal: ante
        GAME_OVER se resetea y se sigue jugando."""
        agente = agente_de_prueba(reloj=RelojDePresupuesto(presupuesto_segundos=3600.0))
        frame = frame_oficial(state=arcengine.GameState.GAME_OVER)
        assert agente.is_done([frame], frame) is False

    def test_cada_partida_se_registra_y_cleanup_le_devuelve_el_tiempo_al_pool(self) -> None:
        """`Agent.main()` tambien sale por `action_counter > MAX_ACTIONS`, sin pasar por `is_done`:
        por eso la baja va en `cleanup()`. Sin eso la partida quedaria viva para siempre en el
        reloj y estrangularia la cuota de las demas."""
        reloj = RelojDePresupuesto(presupuesto_segundos=3600.0)
        agente = agente_de_prueba(reloj=reloj)
        assert reloj.partidas_vivas() == 1
        agente.cleanup()
        assert reloj.partidas_vivas() == 0
        agente.cleanup()  # el Swarm limpia de nuevo: idempotente
        assert reloj.partidas_vivas() == 0
