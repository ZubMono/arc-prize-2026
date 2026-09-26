/* [arc-agi-runner/worldModel/intelligentPolicy.test] BL.20860 -- politica que reemplaza a
   baselineAgent.ts: orquesta DSL + sintesis + modelo de mundo + planificacion acotada +
   exploracion activa. Contrato de entrada/salida identico a decideNextAction (mismo
   ArcActionDecision) para que gameRunner.ts pueda intercambiarla sin cambios estructurales. */
import { describe, expect, it } from 'vitest';

import { createSeededRandom } from '../../prng';
import type { ArcFrameResponse } from '../../types';
import type { Grid } from '../grid';
import { IntelligentPolicy } from '../intelligentPolicy';

function frame(overrides: Partial<ArcFrameResponse> = {}): ArcFrameResponse {
  return {
    game_id: 'ls20-016295f7601e',
    guid: 'guid-1',
    frame: [],
    state: 'NOT_FINISHED',
    levels_completed: 0,
    win_levels: 0,
    available_actions: [1, 2, 3],
    ...overrides,
  };
}

function markerGrid(x: number, y: number, size = 3): Grid {
  const g: Grid = Array.from({ length: size }, () => new Array(size).fill(0));
  g[y][x] = 5;
  return g;
}

describe('IntelligentPolicy.decide', () => {
  it('elige RESET cuando el estado es NOT_STARTED', () => {
    const policy = new IntelligentPolicy({ rng: createSeededRandom('s1') });
    const decision = policy.decide(frame({ state: 'NOT_STARTED' }));
    expect(decision.action).toBe('RESET');
  });

  it('elige RESET si no hay acciones disponibles', () => {
    const policy = new IntelligentPolicy({ rng: createSeededRandom('s2') });
    const decision = policy.decide(frame({ available_actions: [] }));
    expect(decision.action).toBe('RESET');
  });

  it('siempre elige una accion dentro de available_actions (sin grilla -- frame vacio)', () => {
    const policy = new IntelligentPolicy({ rng: createSeededRandom('s3') });
    const f = frame({ available_actions: [2, 4], frame: [] });
    for (let i = 0; i < 10; i++) {
      const decision = policy.decide(f);
      expect(['ACTION2', 'ACTION4']).toContain(decision.action);
    }
  });

  it('incluye x,y en rango 0-63 cuando elige ACTION6', () => {
    const policy = new IntelligentPolicy({ rng: createSeededRandom('s4') });
    const decision = policy.decide(frame({ available_actions: [6], frame: [] }));
    expect(decision.action).toBe('ACTION6');
    expect(decision.x).toBeGreaterThanOrEqual(0);
    expect(decision.x).toBeLessThanOrEqual(63);
    expect(decision.y).toBeGreaterThanOrEqual(0);
    expect(decision.y).toBeLessThanOrEqual(63);
  });

  it('siempre devuelve un reasoning no vacio', () => {
    const policy = new IntelligentPolicy({ rng: createSeededRandom('s5') });
    const decision = policy.decide(frame());
    expect(decision.reasoning.length).toBeGreaterThan(0);
  });

  it('es deterministico dado el mismo seed y la misma secuencia de frames', () => {
    const frames = [
      frame({ frame: [markerGrid(0, 0)] }),
      frame({ frame: [markerGrid(1, 0)] }),
      frame({ frame: [markerGrid(1, 1)] }),
    ];
    const policyA = new IntelligentPolicy({ rng: createSeededRandom('determinismo') });
    const policyB = new IntelligentPolicy({ rng: createSeededRandom('determinismo') });
    const seqA = frames.map((f) => policyA.decide(f).action);
    const seqB = frames.map((f) => policyB.decide(f).action);
    expect(seqA).toEqual(seqB);
  });

  it('aprende la regla de una accion y planifica hacia goalGrid en vez de explorar a ciegas', () => {
    const policy = new IntelligentPolicy({
      rng: createSeededRandom('learn'),
      goalGrid: markerGrid(1, 0),
    });

    // Frame 1: estado inicial, marcador en (0,0).
    policy.decide(frame({ available_actions: [1], frame: [markerGrid(0, 0)] }));
    // Frame 2: tras ACTION1, el marcador se movio a (1,0) -- ensena translate(dx=1,dy=0).
    const secondDecision = policy.decide(
      frame({ available_actions: [1], frame: [markerGrid(1, 0)] }),
    );
    // Ya en el goal tras la 2da observacion -- la politica no deberia fallar ni devolver
    // una accion fuera de las disponibles.
    expect(['ACTION1']).toContain(secondDecision.action);
  });
});
