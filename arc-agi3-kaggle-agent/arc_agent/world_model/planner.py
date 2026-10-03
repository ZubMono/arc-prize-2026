"""[arc-agi3-kaggle-agent/world_model/planner] -- planificacion con busqueda acotada (variante de
A-estrella) sobre el modelo de mundo aprendido (transition_memory.py), con profundidad ligada al
presupuesto de acciones restante. ANYTIME: si no hay plan completo dentro del presupuesto, cae a
greedy sobre la heuristica de distancia-al-objetivo. Puerto de
arc-agi-runner/src/worldModel/planner.ts (BL.20860).

Heuristica: estimate_distance combina un termino ESPACIAL (distancia Manhattan entre las esquinas
superior-izquierda de los bounding boxes de foreground de `grid` y `goal`) con la distancia de
Hamming cruda (cell_diff_count). El termino de Hamming solo no sirve de guia para navegar un objeto
puntual (queda constante hasta el paso exacto que lo alinea); el termino espacial da gradiente
continuo. La suma NO es necesariamente admisible en sentido estricto de A-estrella (una sola accion
puede cambiar muchas celdas a la vez, ej. recolor global) -- esto es busqueda SATISFICING:
encuentra un plan valido rapido, no garantiza el mas corto posible.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# Imports relativos en UNA sola linea a proposito: submission/build_notebook.py los desmonta con
# `^from \.\w* import .+$` (regex de una linea) y la forma con parentesis dejaria los nombres
# sueltos y un `)` colgando dentro del notebook de Kaggle -- SyntaxError en la submission.
from .grid import Grid, cell_diff_count, detect_background_color, foreground_bounding_box
from .grid import grids_equal, hash_grid


class TransitionPredictor(Protocol):
    """Lo UNICO que el planner necesita de la memoria de transiciones. Se declara como Protocol en
    vez de importar TransitionMemory por dos razones: (1) mantiene el planner testeable con un
    doble trivial, (2) el builder del notebook de Kaggle aplana los modulos en un solo namespace y
    un import relativo de dos puntos no sobrevive al stripping. TransitionMemory lo satisface
    ESTRUCTURALMENTE, sin herencia ni registro."""

    def predict(self, action: str, grid: Grid) -> Grid | None: ...


@dataclass(frozen=True)
class PlanOptions:
    """Las acciones son str ("ACTION1", ...): el caller convierte desde GameAction, el world model
    no conoce el enum del wire format."""

    current_grid: Grid
    available_actions: list[str]
    memory: TransitionPredictor
    goal_grid: Grid
    # Profundidad estructural maxima del plan. Default efectivo 6.
    max_depth: int | None = None
    # Acciones restantes reales del episodio -- acota la profundidad efectiva (nunca planifica mas
    # alla de lo que el presupuesto permite gastar). Default efectivo: max_depth.
    budget: int | None = None
    # Tope duro de nodos expandidos, independiente del branching real. Default efectivo 500.
    max_expansions: int | None = None


@dataclass(frozen=True)
class PlanResult:
    """`plan`: secuencia completa de acciones hasta el goal, si se encontro dentro del presupuesto;
    [] si ya se esta en el goal; None si no se encontro plan completo.
    `fallback_action` (ANYTIME): mejor accion individual (la que mas reduce la heuristica en un
    paso) entre las acciones con efecto conocido -- solo presente cuando `plan` es None. None si
    ninguna accion conocida aporta progreso medible (el llamador debe caer a active learning).
    `current_distance`: heuristica de distancia del estado actual al goal (diagnostico)."""

    plan: list[str] | None
    current_distance: int
    fallback_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        # `fallbackAction` se OMITE cuando es None -- replica el drop de `undefined` que hace
        # JSON.stringify en el TS, para que el JSON del fixture sea byte a byte el mismo.
        salida: dict[str, Any] = {"plan": self.plan, "currentDistance": self.current_distance}
        if self.fallback_action is not None:
            salida["fallbackAction"] = self.fallback_action
        return salida


def estimate_distance(grid: Grid, goal: Grid) -> int:
    """Heuristica espacial + residual (ver docstring de modulo). Publica a proposito (es privada
    en el TS): es una ley afirmable directamente contra fixtures, sin pasar por una busqueda."""
    residual = cell_diff_count(grid, goal)
    ancho_grid = len(grid[0]) if grid else 0
    ancho_goal = len(goal[0]) if goal else 0
    if len(grid) != len(goal) or ancho_grid != ancho_goal:
        return residual
    # El fondo se toma del GOAL, no de grid: el objetivo define que es "figura" y que es "fondo".
    bg = detect_background_color(goal)
    bbox_grid = foreground_bounding_box(grid, bg)
    bbox_goal = foreground_bounding_box(goal, bg)
    if bbox_grid is None or bbox_goal is None:
        return residual
    spatial = abs(bbox_grid.min_x - bbox_goal.min_x) + abs(bbox_grid.min_y - bbox_goal.min_y)
    return spatial + residual


def _pick_greedy_fallback(
    current_grid: Grid,
    known_actions: list[str],
    memory: TransitionPredictor,
    goal_grid: Grid,
) -> str | None:
    best_action: str | None = None
    best_distance = estimate_distance(current_grid, goal_grid)
    for action in known_actions:
        predicted = memory.predict(action, current_grid)
        if predicted is None:
            continue
        distance = estimate_distance(predicted, goal_grid)
        # Estricto: una accion que empata la distancia actual no es progreso medible.
        if distance < best_distance:
            best_distance = distance
            best_action = action
    return best_action


@dataclass
class _SearchNode:
    grid: Grid
    path: list[str]
    g: int


def plan_actions(opts: PlanOptions) -> PlanResult:
    max_depth = opts.max_depth if opts.max_depth is not None else 6
    max_expansions = opts.max_expansions if opts.max_expansions is not None else 500
    budget = opts.budget if opts.budget is not None else max_depth
    effective_depth = max(0, min(max_depth, budget))

    current_grid = opts.current_grid
    goal_grid = opts.goal_grid
    memory = opts.memory

    current_distance = estimate_distance(current_grid, goal_grid)
    if grids_equal(current_grid, goal_grid):
        # El 0 es literal (no current_distance): estar en el goal es distancia cero por definicion.
        return PlanResult(plan=[], current_distance=0)

    known_actions = [
        a for a in opts.available_actions if memory.predict(a, current_grid) is not None
    ]

    if effective_depth == 0 or not known_actions:
        return PlanResult(
            plan=None,
            current_distance=current_distance,
            fallback_action=_pick_greedy_fallback(current_grid, known_actions, memory, goal_grid),
        )

    frontier: list[_SearchNode] = [_SearchNode(grid=current_grid, path=[], g=0)]
    visited: set[int] = {hash_grid(current_grid)}
    expansions = 0

    while frontier and expansions < max_expansions:
        # Reordena la frontera ENTERA en cada vuelta y saca el primero. Es lo que hace el TS
        # (frontier.sort + shift): ineficiente, pero el desempate ante f-scores iguales depende del
        # orden de insercion, y el sort estable de Python coincide con el de V8. Cambiarlo por un
        # heap elegiria otro nodo ante empates y el plan dejaria de ser el mismo.
        frontier.sort(key=lambda n: n.g + estimate_distance(n.grid, goal_grid))
        node = frontier.pop(0)

        if grids_equal(node.grid, goal_grid):
            return PlanResult(plan=node.path, current_distance=current_distance)
        if node.g >= effective_depth:
            continue

        for action in known_actions:
            if expansions >= max_expansions:
                break
            # Se cuenta ANTES de predecir: la prediccion es el trabajo que el tope acota.
            expansions += 1
            predicted = memory.predict(action, node.grid)
            if predicted is None:
                continue
            h = hash_grid(predicted)
            if h in visited:
                continue
            visited.add(h)
            frontier.append(_SearchNode(grid=predicted, path=[*node.path, action], g=node.g + 1))

    return PlanResult(
        plan=None,
        current_distance=current_distance,
        fallback_action=_pick_greedy_fallback(current_grid, known_actions, memory, goal_grid),
    )
