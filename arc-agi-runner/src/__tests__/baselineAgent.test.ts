/* [arc-agi-runner/baselineAgent.test] BL.20775 -- politica de decision del agente baseline MVP. */
import { describe, expect, it } from 'vitest';

import { decideNextAction } from '../baselineAgent';
import { createSeededRandom } from '../prng';
import type { ArcFrameResponse } from '../types';

function makeFrame(overrides: Partial<ArcFrameResponse> = {}): ArcFrameResponse {
  return {
    game_id: 'ls20-016295f7601e',
    guid: 'guid-1',
    frame: [],
    state: 'NOT_FINISHED',
    levels_completed: 0,
    win_levels: 0,
    available_actions: [1, 2, 3, 4, 5, 6],
    ...overrides,
  };
}

describe('decideNextAction', () => {
  it('elige RESET cuando el estado es NOT_STARTED', () => {
    const rng = createSeededRandom('s1');
    const decision = decideNextAction(makeFrame({ state: 'NOT_STARTED' }), rng);
    expect(decision.action).toBe('RESET');
  });

  it('elige RESET si no hay acciones disponibles', () => {
    const rng = createSeededRandom('s2');
    const decision = decideNextAction(makeFrame({ available_actions: [] }), rng);
    expect(decision.action).toBe('RESET');
  });

  it('siempre elige una accion dentro de available_actions', () => {
    const rng = createSeededRandom('s3');
    const frame = makeFrame({ available_actions: [2, 4] });
    for (let i = 0; i < 30; i++) {
      const decision = decideNextAction(frame, rng);
      expect(['ACTION2', 'ACTION4']).toContain(decision.action);
    }
  });

  it('incluye x,y en rango 0-63 cuando elige ACTION6', () => {
    const rng = createSeededRandom('s4');
    const frame = makeFrame({ available_actions: [6] });
    const decision = decideNextAction(frame, rng);
    expect(decision.action).toBe('ACTION6');
    expect(decision.x).toBeGreaterThanOrEqual(0);
    expect(decision.x).toBeLessThanOrEqual(63);
    expect(decision.y).toBeGreaterThanOrEqual(0);
    expect(decision.y).toBeLessThanOrEqual(63);
  });

  it('siempre devuelve un reasoning no vacio en espanol', () => {
    const rng = createSeededRandom('s5');
    const decision = decideNextAction(makeFrame(), rng);
    expect(decision.reasoning.length).toBeGreaterThan(0);
  });

  it('es deterministico dado el mismo seed', () => {
    const frame = makeFrame({ available_actions: [1, 2, 3, 4, 5, 6] });
    const rngA = createSeededRandom('determinismo');
    const rngB = createSeededRandom('determinismo');
    const seqA = Array.from({ length: 15 }, () => decideNextAction(frame, rngA).action);
    const seqB = Array.from({ length: 15 }, () => decideNextAction(frame, rngB).action);
    expect(seqA).toEqual(seqB);
  });
});
