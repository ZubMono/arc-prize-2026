/* [arc-agi-runner/worldModel/planner] BL.20860 -- planificacion con busqueda acotada (variante de
   A-estrella) sobre el modelo de mundo aprendido (transitionMemory.ts), con profundidad ligada al
   presupuesto de acciones restante. ANYTIME (discuss-context BL.20858): si no hay plan completo
   dentro del presupuesto, cae a greedy sobre la heuristica de distancia-al-objetivo.

   Heuristica: `estimateDistance` combina un termino ESPACIAL (distancia Manhattan entre las
   esquinas superior-izquierda de los bounding boxes de foreground de `grid` y `goal`) con la
   distancia de Hamming cruda (cellDiffCount). El termino de Hamming solo no sirve de guia para
   navegar un objeto puntual (queda constante hasta el paso exacto que lo alinea); el termino
   espacial da gradiente continuo. La suma NO es necesariamente admisible en sentido estricto de
   A-estrella (una sola accion puede cambiar muchas celdas a la vez, ej. recolor global) -- esto
   es busqueda SATISFICING: encuentra un plan valido rapido, no garantiza el mas corto posible. */

import {
  cellDiffCount,
  detectBackgroundColor,
  foregroundBoundingBox,
  gridsEqual,
  hashGrid,
  type Grid,
} from './grid';
import type { TransitionMemory } from './transitionMemory';

export interface PlanOptions {
  currentGrid: Grid;
  availableActions: string[];
  memory: TransitionMemory;
  goalGrid: Grid;
  /** Profundidad estructural maxima del plan. Default 6. */
  maxDepth?: number;
  /** Acciones restantes reales del episodio -- acota la profundidad efectiva (nunca planifica
   *  mas alla de lo que el presupuesto permite gastar). */
  budget?: number;
  /** Tope duro de nodos expandidos, independiente del branching real. Default 500. */
  maxExpansions?: number;
}

export interface PlanResult {
  /** Secuencia completa de acciones hasta el goal, si se encontro dentro del presupuesto.
   *  `[]` si ya se esta en el goal. `null` si no se encontro plan completo. */
  plan: string[] | null;
  /** ANYTIME: mejor accion individual (mas reduce la heuristica en un paso) entre las acciones
   *  con efecto conocido -- solo presente cuando `plan` es `null`. `undefined` si ninguna accion
   *  conocida aporta progreso medible (el llamador debe caer a active learning). */
  fallbackAction?: string;
  /** Heuristica de distancia del estado actual al goal (diagnostico/reasoning). */
  currentDistance: number;
}

function estimateDistance(grid: Grid, goal: Grid): number {
  const residual = cellDiffCount(grid, goal);
  if (grid.length !== goal.length || (grid[0]?.length ?? 0) !== (goal[0]?.length ?? 0)) {
    return residual;
  }
  const bg = detectBackgroundColor(goal);
  const bboxGrid = foregroundBoundingBox(grid, bg);
  const bboxGoal = foregroundBoundingBox(goal, bg);
  if (!bboxGrid || !bboxGoal) return residual;
  const spatial = Math.abs(bboxGrid.minX - bboxGoal.minX) + Math.abs(bboxGrid.minY - bboxGoal.minY);
  return spatial + residual;
}

function pickGreedyFallback(
  currentGrid: Grid,
  knownActions: string[],
  memory: TransitionMemory,
  goalGrid: Grid,
): string | undefined {
  let bestAction: string | undefined;
  let bestDistance = estimateDistance(currentGrid, goalGrid);
  for (const action of knownActions) {
    const predicted = memory.predict(action, currentGrid);
    if (predicted === null) continue;
    const distance = estimateDistance(predicted, goalGrid);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestAction = action;
    }
  }
  return bestAction;
}

interface SearchNode {
  grid: Grid;
  path: string[];
  g: number;
}

export function planActions(opts: PlanOptions): PlanResult {
  const { currentGrid, availableActions, memory, goalGrid } = opts;
  const maxDepth = opts.maxDepth ?? 6;
  const maxExpansions = opts.maxExpansions ?? 500;
  const budget = opts.budget ?? maxDepth;
  const effectiveDepth = Math.max(0, Math.min(maxDepth, budget));

  const currentDistance = estimateDistance(currentGrid, goalGrid);
  if (gridsEqual(currentGrid, goalGrid)) {
    return { plan: [], currentDistance: 0 };
  }

  const knownActions = availableActions.filter((a) => memory.predict(a, currentGrid) !== null);

  if (effectiveDepth === 0 || knownActions.length === 0) {
    return {
      plan: null,
      fallbackAction: pickGreedyFallback(currentGrid, knownActions, memory, goalGrid),
      currentDistance,
    };
  }

  const start: SearchNode = { grid: currentGrid, path: [], g: 0 };
  const frontier: SearchNode[] = [start];
  const visited = new Set<number>([hashGrid(currentGrid)]);
  let expansions = 0;

  while (frontier.length > 0 && expansions < maxExpansions) {
    frontier.sort(
      (a, b) =>
        a.g + estimateDistance(a.grid, goalGrid) - (b.g + estimateDistance(b.grid, goalGrid)),
    );
    const node = frontier.shift() as SearchNode;

    if (gridsEqual(node.grid, goalGrid)) {
      return { plan: node.path, currentDistance };
    }
    if (node.g >= effectiveDepth) continue;

    for (const action of knownActions) {
      if (expansions >= maxExpansions) break;
      expansions++;
      const predicted = memory.predict(action, node.grid);
      if (predicted === null) continue;
      const hash = hashGrid(predicted);
      if (visited.has(hash)) continue;
      visited.add(hash);
      frontier.push({ grid: predicted, path: [...node.path, action], g: node.g + 1 });
    }
  }

  return {
    plan: null,
    fallbackAction: pickGreedyFallback(currentGrid, knownActions, memory, goalGrid),
    currentDistance,
  };
}
