/* [arc-agi-runner/gameRunner.test] BL.20775 -- orquesta UN juego: RESET -> loop ACTIONS hasta
   WIN/GAME_OVER, timeout duro de 30 min, dead-letter tras 3 fallas de API. Reloj y cliente HTTP
   inyectados -- nada de tiempo real ni red en tests. */
import { describe, expect, it, vi } from 'vitest';

import { createDeadLetterTracker } from '../deadLetterTracker';
import { runGame } from '../gameRunner';
import type { ArcFrameResponse } from '../types';

function frame(overrides: Partial<ArcFrameResponse> = {}): ArcFrameResponse {
  return {
    game_id: 'ls20-016295f7601e',
    guid: 'guid-x',
    frame: [],
    state: 'NOT_FINISHED',
    levels_completed: 0,
    win_levels: 0,
    available_actions: [1, 2],
    ...overrides,
  };
}

describe('runGame', () => {
  it('juega hasta WIN y registra los steps (incluye el RESET inicial)', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ state: 'NOT_FINISHED' })) // RESET
      .mockResolvedValueOnce(frame({ state: 'NOT_FINISHED' })) // step 1
      .mockResolvedValueOnce(frame({ state: 'WIN', available_actions: [] })); // step 2

    const result = await runGame({
      client: { sendCommand },
      cardId: 'card-1',
      gameId: 'ls20-016295f7601e',
      seed: 'seed-fijo',
      gameTimeoutMs: 60_000,
      deadLetter: createDeadLetterTracker(3),
    });

    expect(result.finalState).toBe('WIN');
    expect(result.timedOut).toBe(false);
    expect(result.deadLettered).toBe(false);
    expect(result.steps.map((s) => s.action)[0]).toBe('RESET');
    expect(result.steps).toHaveLength(3);
    expect(result.steps.every((s) => s.reasoning.length > 0)).toBe(true);
  });

  it('corta por timeout duro cuando se supera el deadline del juego', async () => {
    let now = 0;
    const sendCommand = vi.fn().mockImplementation(() => {
      now += 40_000; // cada llamada "tarda" mas que el timeout total
      return Promise.resolve(frame({ state: 'NOT_FINISHED' }));
    });

    const result = await runGame({
      client: { sendCommand },
      cardId: 'card-1',
      gameId: 'g1',
      seed: 's',
      gameTimeoutMs: 30_000,
      deadLetter: createDeadLetterTracker(3),
      now: () => now,
    });

    expect(result.timedOut).toBe(true);
    expect(result.finalState).not.toBe('WIN');
  });

  it('marca dead-letter tras 3 fallas de API consecutivas y no cuelga el loop', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ state: 'NOT_FINISHED' })) // RESET ok
      .mockRejectedValueOnce(new Error('network fail 1'))
      .mockRejectedValueOnce(new Error('network fail 2'))
      .mockRejectedValueOnce(new Error('network fail 3'));

    const result = await runGame({
      client: { sendCommand },
      cardId: 'card-1',
      gameId: 'g1',
      seed: 's',
      gameTimeoutMs: 60_000,
      deadLetter: createDeadLetterTracker(3),
    });

    expect(result.deadLettered).toBe(true);
    expect(result.finalState).toBe('GAME_OVER');
    expect(result.error).toMatch(/network fail 3/);
  });

  it('si RESET falla, dead-letter tracker cuenta la falla y devuelve GAME_OVER de inmediato', async () => {
    const sendCommand = vi.fn().mockRejectedValueOnce(new Error('reset roto'));
    const dl = createDeadLetterTracker(1);
    const result = await runGame({
      client: { sendCommand },
      cardId: 'card-1',
      gameId: 'g1',
      seed: 's',
      gameTimeoutMs: 60_000,
      deadLetter: dl,
    });
    expect(result.deadLettered).toBe(true);
    expect(result.steps).toHaveLength(0);
  });

  it('respeta el tope de maxSteps de seguridad si el juego nunca termina', async () => {
    const sendCommand = vi.fn().mockResolvedValue(frame({ state: 'NOT_FINISHED' }));
    const result = await runGame({
      client: { sendCommand },
      cardId: 'card-1',
      gameId: 'g1',
      seed: 's',
      gameTimeoutMs: 60_000,
      deadLetter: createDeadLetterTracker(3),
      maxSteps: 5,
    });
    expect(result.steps.length).toBeLessThanOrEqual(5);
    expect(result.error).toMatch(/maxSteps/);
  });

  /* BL.21558 -- las firmas persistidas son lo unico que la corrida siguiente puede reusar
     (packages/api/prometheusActivityMemory destila `nonOps`/`transitions`/`plans` a partir de
     ellas). Si incluyen el contador del HUD no matchean nunca: medido en ar25-0c556536, 150 firmas
     de origen distintas en 153 transiciones destiladas, y el memorySeed solo podia disparar en el
     estado post-RESET. */
  it('BL.21558: re-firma los steps con la mascara FINAL del episodio', async () => {
    /* El tablero no cambia nunca; lo unico que se mueve es el "HUD" de la ultima fila. O sea:
       todos los pasos son el MISMO estado, y las firmas persistidas tienen que decirlo. */
    let contador = 0;
    const frameConHud = (state: ArcFrameResponse['state']): ArcFrameResponse => {
      const grid = [
        [0, 0, 0],
        [0, 5, 0],
        [contador % 11, contador % 13, 0],
      ];
      contador += 1;
      return frame({ state, frame: [grid], available_actions: state === 'WIN' ? [] : [1, 2] });
    };

    const sendCommand = vi.fn().mockImplementation(() => {
      // 20 frames de juego y despues WIN, para que la mascara tenga tiempo de formarse.
      return Promise.resolve(frameConHud(contador < 20 ? 'NOT_FINISHED' : 'WIN'));
    });

    const result = await runGame({
      client: { sendCommand },
      cardId: 'card-1',
      gameId: 'g-hud',
      seed: 'seed-hud',
      gameTimeoutMs: 60_000,
      deadLetter: createDeadLetterTracker(3),
    });

    const firmas = result.steps
      .map((s) => s.stateSignatureAfter)
      .filter((f): f is string => f !== undefined);
    expect(firmas.length).toBeGreaterThan(15);
    // Sin la re-firma habria una firma distinta por paso (el contador entra al hash). Con ella
    // queda UNA sola para todo el tramo jugable: el tablero no cambio en toda la partida, y eso es
    // lo que hay que persistir. El ultimo frame (WIN) firma distinto con razon -- ya no tiene
    // acciones disponibles, y la firma incluye ese dato: es otro estado de verdad.
    expect(new Set(firmas.slice(0, -1)).size).toBe(1);
    expect(new Set(firmas).size).toBe(2);
  });
});
