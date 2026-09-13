"""[arc-agi3-kaggle-agent/tests/planner] -- planificacion con busqueda acotada (variante de
A-estrella) sobre el modelo de mundo aprendido, profundidad ligada al presupuesto de acciones
restante. ANYTIME: si no hay plan completo, cae a greedy sobre la heuristica de
distancia-al-objetivo del DSL. Puerto de arc-agi-runner/src/worldModel/__tests__/planner.test.ts +
casos borde propios de Python (grillas vacias, coordenadas negativas en el doble de memoria,
serializacion camelCase)."""
from __future__ import annotations

from arc_agent.world_model.grid import Grid
from arc_agent.world_model.planner import (
    PlanOptions,
    PlanResult,
    estimate_distance,
    plan_actions,
)
from arc_agent.world_model.primitive_ops import apply_program
from arc_agent.world_model.transition_memory import TransitionMemory


def marker_grid(x: int, y: int) -> Grid:
    g: Grid = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    g[y][x] = 5
    return g


def memory_with_moves() -> TransitionMemory:
    memory = TransitionMemory()
    memory.record_observation("RIGHT", marker_grid(0, 0), marker_grid(1, 0))
    memory.record_observation("DOWN", marker_grid(0, 0), marker_grid(0, 1))
    return memory


class _MemoriaFalsa:
    """Doble trivial del Protocol TransitionPredictor -- lo unico que el planner necesita. Que este
    doble alcance ES la propiedad: el planner no depende de TransitionMemory ni por import ni por
    herencia."""

    def __init__(self, tabla: dict[str, Grid | None]) -> None:
        self._tabla = tabla

    def predict(self, action: str, grid: Grid) -> Grid | None:
        return self._tabla.get(action)


# --- estimate_distance ---------------------------------------------------------------------------


def test_estimate_distance_cero_si_las_grillas_son_iguales() -> None:
    assert estimate_distance(marker_grid(1, 1), marker_grid(1, 1)) == 0


def test_estimate_distance_suma_termino_espacial_y_residual() -> None:
    """Manhattan entre las esquinas superior-izquierda de los bboxes (1) mas la Hamming (2 celdas
    distintas: la vieja y la nueva posicion del marcador)."""
    assert estimate_distance(marker_grid(0, 0), marker_grid(1, 0)) == 3


def test_estimate_distance_da_gradiente_continuo_al_acercarse() -> None:
    """Es la razon de ser del termino espacial: la Hamming sola vale 2 en las dos posiciones y no
    guiaria la navegacion."""
    goal = marker_grid(2, 2)
    assert estimate_distance(marker_grid(1, 1), goal) < estimate_distance(marker_grid(0, 0), goal)


def test_estimate_distance_solo_residual_si_las_dimensiones_diferen() -> None:
    """Sin misma forma el termino espacial no significa nada: se devuelve la Hamming cruda, que ya
    penaliza el cambio de tamano no explicado."""
    chica: Grid = [[1, 2]]
    grande: Grid = [[1, 2], [3, 4]]
    assert estimate_distance(chica, grande) == 2


def test_estimate_distance_solo_residual_si_el_goal_es_uniforme() -> None:
    """Un goal de un solo color no tiene foreground: no hay bbox del que medir distancia."""
    uniforme: Grid = [[0, 0], [0, 0]]
    assert estimate_distance([[0, 1], [0, 0]], uniforme) == 1


def test_estimate_distance_con_grillas_vacias() -> None:
    """Caso borde propio de Python: [] no puede explotar al derivar el ancho de la fila 0."""
    assert estimate_distance([], []) == 0


# --- plan_actions (puerto de planner.test.ts) ----------------------------------------------------


def test_plan_vacio_si_ya_se_esta_en_el_goal() -> None:
    result = plan_actions(
        PlanOptions(
            current_grid=marker_grid(1, 1),
            available_actions=["RIGHT", "DOWN"],
            memory=memory_with_moves(),
            goal_grid=marker_grid(1, 1),
        )
    )
    assert result.plan == []
    assert result.current_distance == 0


def test_encuentra_un_plan_de_dos_pasos_combinando_acciones_conocidas() -> None:
    result = plan_actions(
        PlanOptions(
            current_grid=marker_grid(0, 0),
            available_actions=["RIGHT", "DOWN"],
            memory=memory_with_moves(),
            goal_grid=marker_grid(1, 1),
            budget=4,
        )
    )
    assert result.plan is not None
    assert len(result.plan) <= 2

    # Ejecutar el plan predicho debe efectivamente llegar al goal.
    grid = marker_grid(0, 0)
    for action in result.plan:
        program = (
            [{"name": "translate", "params": {"dx": 1, "dy": 0}}]
            if action == "RIGHT"
            else [{"name": "translate", "params": {"dx": 0, "dy": 1}}]
        )
        grid = apply_program(program, grid)
    assert grid == marker_grid(1, 1)


def test_sin_acciones_con_efecto_conocido_no_hay_plan_ni_fallback() -> None:
    result = plan_actions(
        PlanOptions(
            current_grid=marker_grid(0, 0),
            available_actions=["RIGHT", "DOWN"],
            memory=TransitionMemory(),  # nada aprendido todavia
            goal_grid=marker_grid(1, 1),
        )
    )
    assert result.plan is None
    assert result.fallback_action is None


def test_presupuesto_insuficiente_cae_a_fallback_greedy() -> None:
    result = plan_actions(
        PlanOptions(
            current_grid=marker_grid(0, 0),
            available_actions=["RIGHT", "DOWN"],
            memory=memory_with_moves(),
            goal_grid=marker_grid(1, 1),
            budget=1,
        )
    )
    assert result.plan is None
    assert result.fallback_action in ("RIGHT", "DOWN")


def test_budget_cero_no_planifica_pero_conserva_el_fallback() -> None:
    result = plan_actions(
        PlanOptions(
            current_grid=marker_grid(0, 0),
            available_actions=["RIGHT", "DOWN"],
            memory=memory_with_moves(),
            goal_grid=marker_grid(1, 1),
            budget=0,
        )
    )
    assert result.plan is None
    assert result.fallback_action is not None


def test_ignora_acciones_disponibles_sin_efecto_conocido() -> None:
    result = plan_actions(
        PlanOptions(
            current_grid=marker_grid(0, 0),
            available_actions=["RIGHT", "DOWN", "ACTION7"],  # ACTION7 nunca observada
            memory=memory_with_moves(),
            goal_grid=marker_grid(1, 1),
            budget=4,
        )
    )
    assert result.plan is not None
    assert all(a in ("RIGHT", "DOWN") for a in result.plan)


# --- casos borde propios ------------------------------------------------------------------------


def test_el_planner_solo_necesita_el_protocol_no_la_memoria_real() -> None:
    memoria = _MemoriaFalsa({"SALTO": marker_grid(1, 1), "NADA": None})
    result = plan_actions(
        PlanOptions(
            current_grid=marker_grid(0, 0),
            available_actions=["NADA", "SALTO"],
            memory=memoria,
            goal_grid=marker_grid(1, 1),
        )
    )
    assert result.plan == ["SALTO"]


def test_max_expansions_corta_la_busqueda_y_deja_fallback() -> None:
    """Con una sola expansion permitida la busqueda no puede llegar a un goal de 2 pasos, pero el
    modo ANYTIME sigue devolviendo la mejor accion individual."""
    result = plan_actions(
        PlanOptions(
            current_grid=marker_grid(0, 0),
            available_actions=["RIGHT", "DOWN"],
            memory=memory_with_moves(),
            goal_grid=marker_grid(2, 2),
            budget=6,
            max_expansions=1,
        )
    )
    assert result.plan is None
    assert result.fallback_action in ("RIGHT", "DOWN")


def test_fallback_none_si_ninguna_accion_conocida_progresa() -> None:
    """El desempate es ESTRICTO: una accion que empata la distancia actual no es progreso, y el
    llamador tiene que poder distinguir "no se que hacer" de "hago esto"."""
    quieto = _MemoriaFalsa({"NOOP": marker_grid(0, 0)})
    result = plan_actions(
        PlanOptions(
            current_grid=marker_grid(0, 0),
            available_actions=["NOOP"],
            memory=quieto,
            goal_grid=marker_grid(2, 2),
        )
    )
    assert result.plan is None
    assert result.fallback_action is None


def test_no_revisita_estados_ya_vistos() -> None:
    """La memoria de visitados esta indexada por hash_grid: una accion que devuelve al estado
    inicial no puede reinyectarlo en la frontera (la busqueda no terminaria)."""
    ciclo = _MemoriaFalsa({"VUELTA": marker_grid(0, 0)})
    result = plan_actions(
        PlanOptions(
            current_grid=marker_grid(0, 0),
            available_actions=["VUELTA"],
            memory=ciclo,
            goal_grid=marker_grid(2, 2),
            budget=6,
        )
    )
    assert result.plan is None


def test_plan_result_serializa_en_camel_case_y_omite_el_fallback_ausente() -> None:
    """`fallbackAction` ausente (no null) replica el drop de undefined de JSON.stringify: el
    fixture del TS no trae la clave."""
    assert PlanResult(plan=[], current_distance=0).to_dict() == {"plan": [], "currentDistance": 0}
    assert PlanResult(plan=None, current_distance=3, fallback_action="RIGHT").to_dict() == {
        "plan": None,
        "currentDistance": 3,
        "fallbackAction": "RIGHT",
    }
