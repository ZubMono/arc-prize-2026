"""[arc-agi3-kaggle-agent] BL.20783 -- tests de arc_agent/policy.py (heuristica offline)."""
from __future__ import annotations

from _helpers import make_frame

from arc_agent.policy import (
    ExplorationPolicy,
    compute_signature,
    pick_click_target,
    rank_candidates,
)
from arc_agent.prng import create_seeded_random
from arc_agent.types import GRID_MAX_COORD, GameAction, GameState


def test_policy_resets_when_not_started() -> None:
    policy = ExplorationPolicy(create_seeded_random("s1"))
    frame = make_frame(state=GameState.NOT_STARTED, available_actions=())
    decision = policy.decide(frame)
    assert decision.action == GameAction.RESET


def test_policy_resets_when_no_available_actions() -> None:
    policy = ExplorationPolicy(create_seeded_random("s2"))
    frame = make_frame(state=GameState.NOT_FINISHED, available_actions=())
    decision = policy.decide(frame)
    assert decision.action == GameAction.RESET


def test_policy_avoids_repeating_a_detected_no_op_action() -> None:
    policy = ExplorationPolicy(create_seeded_random("s3"))
    frame = make_frame(available_actions=(1, 2, 3))

    first = policy.decide(frame)
    # El frame NO cambio (mismo grid/available_actions) -- simula que `first.action` fue un no-op.
    second = policy.decide(frame)

    assert second.action != first.action


def test_policy_choose_action_deterministic_for_same_seed() -> None:
    frame = make_frame(available_actions=(1, 2, 3))
    policy_a = ExplorationPolicy(create_seeded_random("determinism"))
    policy_b = ExplorationPolicy(create_seeded_random("determinism"))
    assert policy_a.decide(frame) == policy_b.decide(frame)


def test_rank_candidates_filters_out_no_op_actions_when_alternatives_exist() -> None:
    rng = create_seeded_random("rank-1")
    ranked = rank_candidates(
        available_actions=(1, 2, 3),
        visits={},
        no_op_actions={GameAction.ACTION1},
        rng=rng,
    )
    assert GameAction.ACTION1 not in ranked
    assert set(ranked) == {GameAction.ACTION2, GameAction.ACTION3}


def test_rank_candidates_keeps_all_when_every_action_is_no_op() -> None:
    rng = create_seeded_random("rank-2")
    all_actions = {GameAction.ACTION1, GameAction.ACTION2}
    ranked = rank_candidates(
        available_actions=(1, 2), visits={}, no_op_actions=all_actions, rng=rng
    )
    assert set(ranked) == all_actions


def test_rank_candidates_prefers_least_visited() -> None:
    rng = create_seeded_random("rank-3")
    ranked = rank_candidates(
        available_actions=(1, 2, 3),
        visits={GameAction.ACTION1: 5, GameAction.ACTION2: 0, GameAction.ACTION3: 2},
        no_op_actions=set(),
        rng=rng,
    )
    assert ranked[0] == GameAction.ACTION2


def test_pick_click_target_prefers_color_boundary() -> None:
    grid = tuple(tuple(0 if x < 4 else 1 for x in range(8)) for _ in range(8))
    rng = create_seeded_random("click-1")
    x, y = pick_click_target(grid, rng)
    assert x in (3, 4)
    assert 0 <= y < 8


def test_pick_click_target_falls_back_to_random_on_uniform_grid() -> None:
    grid = tuple(tuple(5 for _ in range(8)) for _ in range(8))
    rng = create_seeded_random("click-2")
    x, y = pick_click_target(grid, rng)
    assert 0 <= x <= GRID_MAX_COORD
    assert 0 <= y <= GRID_MAX_COORD


# ── BL.21518 — el lockout de ACTION6 en la politica Python ────────────────────────────────────
# Hermano del defecto que BL.21500 arreglo en el runner TS, y aca es PEOR: ACTION6 (el click)
# esta parametrizada por COORDENADA (`pick_click_target` la elige con el rng en cada decision),
# asi que el no-op observado pertenece al par (accion, coordenada). Un click sin efecto en (0,0)
# no dice nada sobre (32,17) -- pero antes descartaba TODAS las coordenadas de ese estado.


def test_bl21518_action6_nunca_se_marca_no_op() -> None:
    """ACTION6 sigue disponible aunque el frame no cambie: su efecto depende de la coordenada."""
    policy = ExplorationPolicy(create_seeded_random("bl21518-a6"))
    frame = make_frame(available_actions=(6,))

    # Varias decisiones seguidas sin que el frame cambie -> antes ACTION6 quedaba marcada no-op.
    for _ in range(5):
        policy.decide(frame)

    signature = compute_signature(frame)
    entry = policy._memory[signature]  # noqa: SLF001 -- se inspecciona el estado interno a proposito
    assert GameAction.ACTION6 not in entry.no_op_actions


def test_bl21518_una_sola_observacion_no_alcanza_para_excluir() -> None:
    """Una observacion no-op puede ser ruido del entorno (frame identico por lag)."""
    policy = ExplorationPolicy(create_seeded_random("bl21518-una"))
    frame = make_frame(available_actions=(1, 2, 3))

    first = policy.decide(frame)
    policy.decide(frame)  # el frame no cambio -> 1ra observacion no-op de `first.action`

    entry = policy._memory[compute_signature(frame)]  # noqa: SLF001
    assert first.action not in entry.no_op_actions, "con 1 sola observacion NO debe excluirse"
    assert entry.no_op_streak.get(first.action) == 1


def test_bl21518_dos_observaciones_consecutivas_si_excluyen() -> None:
    """El filtro sigue existiendo: con evidencia sostenida la accion si se excluye."""
    policy = ExplorationPolicy(create_seeded_random("bl21518-dos"))
    frame = make_frame(available_actions=(1,))  # una sola accion -> se repite si o si

    for _ in range(4):
        policy.decide(frame)

    entry = policy._memory[compute_signature(frame)]  # noqa: SLF001
    assert GameAction.ACTION1 in entry.no_op_actions


def test_bl21518_una_accion_que_cambia_el_frame_resetea_su_racha() -> None:
    """Lo que importa es evidencia SOSTENIDA, no acumulada a lo largo de la partida."""
    policy = ExplorationPolicy(create_seeded_random("bl21518-reset"))
    frame_a = make_frame(available_actions=(1,), grid_value=0)
    frame_b = make_frame(available_actions=(1,), grid_value=7)

    policy.decide(frame_a)
    policy.decide(frame_a)  # racha 1 para ACTION1 desde frame_a
    entry = policy._memory[compute_signature(frame_a)]  # noqa: SLF001
    assert entry.no_op_streak.get(GameAction.ACTION1) == 1

    policy.decide(frame_b)  # el frame CAMBIO -> la racha desde frame_a se resetea
    assert entry.no_op_streak.get(GameAction.ACTION1) is None
    assert GameAction.ACTION1 not in entry.no_op_actions


def test_bl21518_el_descarte_no_es_absorbente() -> None:
    """Un no-op confirmado debe poder volver a probarse: el estado del juego cambia.

    Sin el epsilon, una accion excluida no se elige -> no se observa -> el discard que la
    rehabilitaria jamas corre. El sort por menos-visitado ademas la deja siempre ultima, asi que
    meterla al pozo comun no alcanza: hay que darle el turno completo.
    """
    rng = create_seeded_random("bl21518-absorbente")
    elegidas = [
        rank_candidates(
            available_actions=(1, 2),
            visits={GameAction.ACTION1: 50, GameAction.ACTION2: 1},
            no_op_actions={GameAction.ACTION1},
            rng=rng,
        )[0]
        for _ in range(400)
    ]

    veces_action1 = elegidas.count(GameAction.ACTION1)
    assert veces_action1 > 0, "sin epsilon seria exactamente 0 -- descarte absorbente"
    assert veces_action1 < 400 * 0.2, "pero sigue siendo la excepcion, no la regla"


# ── BL.21501 — el motor de sintesis DSL deja de ser codigo muerto en inferencia ────────────────
# world_model/ (2.052 lineas, ~79% del notebook de submission) viajaba a Kaggle sin que NINGUN
# modulo de inferencia lo importara: la politica que jugaba era la heuristica sola, mientras el
# runner TS si usaba IntelligentPolicy sobre el mismo motor.


def test_bl21501_la_politica_alimenta_el_modelo_de_mundo() -> None:
    """Cada transicion observada llega al motor de sintesis -- el DSL se USA, no viaja de adorno."""
    policy = ExplorationPolicy(create_seeded_random("bl21501-feed"))
    frame_a = make_frame(available_actions=(1, 2), grid_value=0)
    frame_b = make_frame(available_actions=(1, 2), grid_value=7)

    first = policy.decide(frame_a)
    policy.decide(frame_b)  # transicion real: grid 0 -> 7 tras `first.action`

    transiciones = policy._world_model.get_known_transitions()  # noqa: SLF001
    assert transiciones, "el modelo de mundo deberia haber registrado la transicion observada"
    assert any(t.action == first.action.value for t in transiciones)


def test_bl21501_el_modelo_aporta_no_ops_que_la_firma_no_ve() -> None:
    """El motor generaliza sobre el EFECTO de la accion; la firma solo memoriza por estado."""
    policy = ExplorationPolicy(create_seeded_random("bl21501-noop"))
    frame = make_frame(available_actions=(1,))

    # Repetidas transiciones sin cambio -> el motor sintetiza identidad para ACTION1.
    for _ in range(5):
        policy.decide(frame)

    detectados = policy._world_model_no_ops((1,))  # noqa: SLF001
    assert GameAction.ACTION1 in detectados


def test_bl21501_action6_exenta_tambien_en_el_modelo_de_mundo() -> None:
    """El motor solo ve (accion, grilla): no distingue un click en (0,0) de uno en (32,17), asi
    que su veredicto de 'identidad' NO es concluyente para una accion parametrizada por coordenada."""
    policy = ExplorationPolicy(create_seeded_random("bl21501-a6"))
    frame = make_frame(available_actions=(6,))

    for _ in range(6):
        policy.decide(frame)

    assert GameAction.ACTION6 not in policy._world_model_no_ops((6,))  # noqa: SLF001


def test_bl21501_un_modelo_que_falla_no_rompe_la_partida() -> None:
    """Fail-open: el modelo de mundo asiste la decision, nunca es requisito para jugar."""

    class _ModeloRoto:
        def record_observation(self, *_args: object) -> None:
            raise RuntimeError("sintesis rota")

        def is_known_no_op(self, *_args: object) -> bool:
            raise RuntimeError("sintesis rota")

    policy = ExplorationPolicy(create_seeded_random("bl21501-failopen"))
    policy._world_model = _ModeloRoto()  # type: ignore[assignment]  # noqa: SLF001
    frame = make_frame(available_actions=(1, 2))

    decision_a = policy.decide(frame)
    decision_b = policy.decide(frame)
    assert decision_a.action in (GameAction.ACTION1, GameAction.ACTION2)
    assert decision_b.action in (GameAction.ACTION1, GameAction.ACTION2)
