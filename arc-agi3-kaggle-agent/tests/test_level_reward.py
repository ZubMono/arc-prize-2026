"""[arc-agi3-kaggle-agent] BL.21557 -- SENAL DENSA como recompensa extrinseca.

`FrameData` traia `levels_completed`/`win_levels` desde BL.20783 y la politica no los miraba:
exploraba con recompensa puramente intrinseca, o sea que una accion que hizo SUBIR DE NIVEL valia
lo mismo que una que no hizo nada. Estos tests cubren las tres cosas que eso cambia: la accion
premiada pasa al frente, el credito SE AGOTA (no es un lockout) y el progreso maximo sobrevive al
frame terminal de un GAME_OVER."""
from __future__ import annotations

import time

from _helpers import make_frame

from arc_agent.local_harness import LocalGameConfig, LocalGameEnvironment
from arc_agent.policy import (
    LEVEL_REWARD_PRIORITY_USES,
    ExplorationPolicy,
    rank_candidates,
)
from arc_agent.prng import create_seeded_random
from arc_agent.prometheus_agent import PrometheusOfflineAgent
from arc_agent.runner import play_game
from arc_agent.runtime_report import build_runtime_report, run_score
from arc_agent.swarm import GameOutcome, SwarmResult
from arc_agent.types import GameAction, GameState


def test_rank_candidates_pone_al_frente_la_accion_premiada() -> None:
    rng = create_seeded_random("premio-1")
    ranked = rank_candidates(
        available_actions=(1, 2, 3),
        # ACTION1 es la MAS visitada: sin la recompensa quedaria ultima por el sort.
        visits={GameAction.ACTION1: 50, GameAction.ACTION2: 0, GameAction.ACTION3: 0},
        no_op_actions=set(),
        rng=rng,
        rewarded_actions={GameAction.ACTION1},
    )
    assert ranked[0] == GameAction.ACTION1


def test_una_accion_premiada_nunca_se_filtra_como_no_op() -> None:
    rng = create_seeded_random("premio-2")
    ranked = rank_candidates(
        available_actions=(1, 2),
        visits={},
        no_op_actions={GameAction.ACTION1},
        rng=rng,
        rewarded_actions={GameAction.ACTION1},
    )
    assert ranked[0] == GameAction.ACTION1, "progreso real gana sobre 'no cambio el frame'"


def test_la_recompensa_no_altera_la_secuencia_del_rng() -> None:
    """La reproducibilidad de una partida dado su seed no puede depender del contenido de la
    memoria: la prioridad se aplica como particion estable DESPUES del barajado."""
    sin_premio = create_seeded_random("rng-estable")
    con_premio = create_seeded_random("rng-estable")
    for _ in range(20):
        rank_candidates((1, 2, 3), {}, set(), sin_premio)
        rank_candidates((1, 2, 3), {}, set(), con_premio, {GameAction.ACTION2})
    assert sin_premio() == con_premio()


def test_la_politica_premia_la_accion_que_hizo_subir_de_nivel() -> None:
    # BL.21555 -- acciones SIN prior de direccion (ACTION1..4 lo tienen, ver direction_beliefs):
    # desde BL.21590 la sonda de validacion tiene prioridad sobre el credito en los primeros pasos
    # (deliberado), y con (1,2,3) este test media la sonda en vez del credito de recompensa.
    policy = ExplorationPolicy(create_seeded_random("nivel-1"))
    estado = make_frame(available_actions=(5, 7), grid_value=0, win_levels=4)

    primera = policy.decide(estado)
    # Mismo estado (misma firma) pero el juego reporta un nivel mas: la accion anterior sirvio.
    policy.decide(make_frame(available_actions=(5, 7), grid_value=0, levels_completed=1, win_levels=4))
    # Al volver al MISMO estado, la accion premiada debe salir primero.
    siguiente = policy.decide(
        make_frame(available_actions=(5, 7), grid_value=0, levels_completed=1, win_levels=4)
    )

    assert siguiente.action == primera.action


def test_el_credito_de_recompensa_se_agota_y_no_es_un_lockout() -> None:
    # BL.21555 -- (5, 7) por el mismo motivo que arriba: aislar el credito de la sonda de BL.21590.
    policy = ExplorationPolicy(create_seeded_random("nivel-2"))
    base = dict(available_actions=(5, 7), grid_value=0, win_levels=9)

    premiada = policy.decide(make_frame(**base)).action
    policy.decide(make_frame(**base, levels_completed=1))

    elegidas = [
        policy.decide(make_frame(**base, levels_completed=1)).action
        for _ in range(LEVEL_REWARD_PRIORITY_USES + 4)
    ]
    assert elegidas[0] == premiada
    assert any(a != premiada for a in elegidas), "el credito debe agotarse, no fijar la accion"


def test_el_maximo_de_niveles_sobrevive_al_frame_terminal_en_cero() -> None:
    policy = ExplorationPolicy(create_seeded_random("nivel-3"))
    policy.decide(make_frame(levels_completed=1, win_levels=5))
    policy.decide(make_frame(levels_completed=3, win_levels=5, grid_value=2))
    policy.decide(make_frame(levels_completed=0, state=GameState.GAME_OVER, available_actions=()))

    assert policy.max_levels_completed == 3
    assert policy.win_levels == 5


def test_contadores_basura_del_wire_no_corrompen_la_metrica() -> None:
    policy = ExplorationPolicy(create_seeded_random("nivel-4"))
    policy.decide(make_frame(levels_completed=-7, win_levels=-2))
    assert policy.max_levels_completed == 0
    assert policy.win_levels == 0


def test_play_game_reporta_el_progreso_de_niveles_en_el_outcome() -> None:
    def environment_factory(game_id: str) -> LocalGameEnvironment:
        return LocalGameEnvironment(
            LocalGameConfig(game_id=game_id, win_after_steps=8, steps_por_nivel=2)
        )

    outcome = play_game(
        game_id="g1",
        seed="seed-niveles",
        deadline_ts=time.monotonic() + 30,
        agent_factory=lambda gid, s: PrometheusOfflineAgent(game_id=gid, seed=s, max_actions=50),
        environment_factory=environment_factory,
    )

    assert outcome.levels_completed == 4
    assert outcome.win_levels == 4


def test_run_score_da_credito_parcial_a_una_derrota_con_progreso() -> None:
    perdida = GameOutcome("g", "GAME_OVER", 40, success=False, levels_completed=3, win_levels=8)
    assert run_score(perdida) == 3


def test_run_score_nunca_puntua_menos_que_1_una_victoria() -> None:
    ganada = GameOutcome("g", "WIN", 12, success=True, levels_completed=0, win_levels=0)
    assert run_score(ganada) == 1


def test_el_reporte_distingue_dos_batches_que_antes_eran_identicos() -> None:
    """Ambos batches tienen 0 victorias. Antes de BL.21557 producian el MISMO reporte."""
    flojo = SwarmResult(
        outcomes=[GameOutcome("a", "GAME_OVER", 10, success=False, levels_completed=0)],
        elapsed_seconds=1.0,
        deadline_hit=False,
    )
    bueno = SwarmResult(
        outcomes=[GameOutcome("a", "GAME_OVER", 10, success=False, levels_completed=4, win_levels=8)],
        elapsed_seconds=1.0,
        deadline_hit=False,
    )

    r_flojo = build_runtime_report(flojo)
    r_bueno = build_runtime_report(bueno)

    assert r_flojo["gamesWon"] == r_bueno["gamesWon"] == 0
    assert r_bueno["totalScore"] > r_flojo["totalScore"]
    assert r_bueno["maxLevelReached"] == 4
    assert r_bueno["gamesWithProgress"] == 1
    assert r_flojo["gamesWithProgress"] == 0
