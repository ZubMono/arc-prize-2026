/* [arc-agi-runner/worldModel/planner.test] BL.20860 -- planificacion con busqueda acotada
   (A-estrella / beam) sobre el modelo de mundo aprendido, profundidad ligada al presupuesto de
   acciones restante. ANYTIME: si no hay plan completo, cae a greedy sobre la heuristica de
   distancia-al-objetivo del DSL. */
import { describe, expect, it } from 'vitest';

import type { Grid } from '../grid';
import { planActions } from '../planner';
import { applyProgram } from '../primitiveOps';
import { TransitionMemory } from '../transitionMemory';

function markerGrid(x: number, y: number): Grid {
  const g: Grid = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  g[y][x] = 5;
  return g;
}

function memoryWithMoves(): TransitionMemory {
  const memory = new TransitionMemory();
  memory.recordObservation('RIGHT', markerGrid(0, 0), markerGrid(1, 0));
  memory.recordObservation('DOWN', markerGrid(0, 0), markerGrid(0, 1));
  return memory;
}

describe('planActions', () => {
  it('plan vacio si ya se esta en el goal', () => {
    const memory = memoryWithMoves();
    const result = planActions({
      currentGrid: markerGrid(1, 1),
      availableActions: ['RIGHT', 'DOWN'],
      memory,
      goalGrid: markerGrid(1, 1),
    });
    expect(result.plan).toEqual([]);
    expect(result.currentDistance).toBe(0);
  });

  it('encuentra un plan de 2 pasos combinando acciones conocidas', () => {
    const memory = memoryWithMoves();
    const result = planActions({
      currentGrid: markerGrid(0, 0),
      availableActions: ['RIGHT', 'DOWN'],
      memory,
      goalGrid: markerGrid(1, 1),
      budget: 4,
    });
    expect(result.plan).not.toBeNull();
    expect((result.plan as string[]).length).toBeLessThanOrEqual(2);

    // ejecutar el plan predicho debe efectivamente llegar al goal
    let grid = markerGrid(0, 0);
    for (const action of result.plan as string[]) {
      const program =
        action === 'RIGHT'
          ? [{ name: 'translate' as const, params: { dx: 1, dy: 0 } }]
          : [{ name: 'translate' as const, params: { dx: 0, dy: 1 } }];
      grid = applyProgram(program, grid, {});
    }
    expect(grid).toEqual(markerGrid(1, 1));
  });

  it('sin acciones con efecto conocido: sin plan y sin fallback', () => {
    const memory = new TransitionMemory(); // nada aprendido todavia
    const result = planActions({
      currentGrid: markerGrid(0, 0),
      availableActions: ['RIGHT', 'DOWN'],
      memory,
      goalGrid: markerGrid(1, 1),
    });
    expect(result.plan).toBeNull();
    expect(result.fallbackAction).toBeUndefined();
  });

  it('presupuesto insuficiente: sin plan completo pero con fallback greedy que reduce la distancia', () => {
    const memory = memoryWithMoves();
    const result = planActions({
      currentGrid: markerGrid(0, 0),
      availableActions: ['RIGHT', 'DOWN'],
      memory,
      goalGrid: markerGrid(1, 1),
      budget: 1,
    });
    expect(result.plan).toBeNull();
    expect(['RIGHT', 'DOWN']).toContain(result.fallbackAction);
  });

  it('budget 0: sin plan, fallback greedy sigue disponible (no requiere profundidad)', () => {
    const memory = memoryWithMoves();
    const result = planActions({
      currentGrid: markerGrid(0, 0),
      availableActions: ['RIGHT', 'DOWN'],
      memory,
      goalGrid: markerGrid(1, 1),
      budget: 0,
    });
    expect(result.plan).toBeNull();
    expect(result.fallbackAction).toBeDefined();
  });

  it('ignora acciones disponibles sin efecto conocido en la busqueda', () => {
    const memory = memoryWithMoves();
    const result = planActions({
      currentGrid: markerGrid(0, 0),
      availableActions: ['RIGHT', 'DOWN', 'ACTION7'], // ACTION7 nunca observada
      memory,
      goalGrid: markerGrid(1, 1),
      budget: 4,
    });
    expect(result.plan).not.toBeNull();
    expect((result.plan as string[]).every((a) => a === 'RIGHT' || a === 'DOWN')).toBe(true);
  });
});
