/* [arc-agi-runner/gameRunner.memory.test] BL.20861 -- el runner es el que CIERRA el ciclo de
   aprendizaje: escribe las firmas de estado que el distilador necesita para separar transiciones
   reales de no-ops, y consume la semilla de la corrida anterior. Si cualquiera de las dos mitades
   se rompe, la memoria deja de mejorar nada en silencio -- de ahi estos tests. */

import { describe, expect, it, vi } from 'vitest';

import type { ActivityMemorySeed } from '../activityMemorySeed';
import { createDeadLetterTracker } from '../deadLetterTracker';
import { runGame } from '../gameRunner';
import type { ArcFrameResponse } from '../types';
import type { Grid } from '../worldModel/grid';
import { computeStateSignature } from '../worldModel/stateSignature';

function gridConMarca(valor: number): Grid {
  return [
    [0, 0, 0],
    [0, valor, 0],
    [0, 0, 0],
  ];
}

function frame(overrides: Partial<ArcFrameResponse> = {}): ArcFrameResponse {
  return {
    game_id: 'g1',
    guid: 'guid-x',
    frame: [gridConMarca(1)],
    state: 'NOT_FINISHED',
    levels_completed: 0,
    win_levels: 0,
    available_actions: [1, 2, 3, 4],
    ...overrides,
  };
}

function baseOpts(sendCommand: ReturnType<typeof vi.fn>) {
  return {
    client: { sendCommand },
    cardId: 'card-1',
    gameId: 'g1',
    seed: 'seed-fijo',
    gameTimeoutMs: 60_000,
    deadLetter: createDeadLetterTracker(3),
  };
}

describe('runGame -- firmas de estado persistidas (insumo del distilador)', () => {
  it('el step de RESET trae firma DESPUES y ninguna ANTES (no habia estado previo)', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ frame: [gridConMarca(1)] }))
      .mockResolvedValueOnce(frame({ state: 'WIN', available_actions: [] }));

    const result = await runGame(baseOpts(sendCommand));

    const reset = result.steps[0];
    expect(reset.action).toBe('RESET');
    expect(reset.stateSignatureBefore).toBeUndefined();
    expect(reset.stateSignatureAfter).toBe(
      String(computeStateSignature(gridConMarca(1), [1, 2, 3, 4])),
    );
  });

  it('una transicion REAL queda con firmas distintas antes/despues', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ frame: [gridConMarca(1)] })) // RESET
      .mockResolvedValueOnce(frame({ frame: [gridConMarca(2)] })) // accion que cambia el mundo
      .mockResolvedValueOnce(frame({ state: 'WIN', available_actions: [] }));

    const result = await runGame(baseOpts(sendCommand));

    const paso = result.steps[1];
    expect(paso.stateSignatureBefore).toBeDefined();
    expect(paso.stateSignatureAfter).toBeDefined();
    expect(paso.stateSignatureBefore).not.toBe(paso.stateSignatureAfter);
  });

  it('un NO-OP queda con firmas IGUALES -- es exactamente lo que el distilador filtra', async () => {
    const identico = frame({ frame: [gridConMarca(1)] });
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(identico) // RESET
      .mockResolvedValueOnce(identico) // accion sin efecto: mismo frame
      .mockResolvedValueOnce(frame({ state: 'WIN', available_actions: [] }));

    const result = await runGame(baseOpts(sendCommand));

    const paso = result.steps[1];
    expect(paso.stateSignatureBefore).toBe(paso.stateSignatureAfter);
  });

  it('sin grilla en el frame no se inventa firma -- ausente significa "sin evidencia"', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ frame: [] })) // RESET sin capas
      .mockResolvedValueOnce(frame({ frame: [], state: 'WIN', available_actions: [] }));

    const result = await runGame(baseOpts(sendCommand));

    expect(result.steps[0].stateSignatureAfter).toBeUndefined();
    expect(result.steps[1].stateSignatureBefore).toBeUndefined();
    expect(result.steps[1].stateSignatureAfter).toBeUndefined();
  });

  it('la firma ANTES de un step coincide con la firma DESPUES del anterior (cadena consistente)', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ frame: [gridConMarca(1)] }))
      .mockResolvedValueOnce(frame({ frame: [gridConMarca(2)] }))
      .mockResolvedValueOnce(frame({ frame: [gridConMarca(3)] }))
      .mockResolvedValueOnce(frame({ state: 'WIN', available_actions: [] }));

    const result = await runGame(baseOpts(sendCommand));

    for (let i = 1; i < result.steps.length; i++) {
      expect(result.steps[i].stateSignatureBefore).toBe(result.steps[i - 1].stateSignatureAfter);
    }
  });
});

describe('runGame -- consumo de la semilla de memoria', () => {
  const planSeed: ActivityMemorySeed = {
    activityId: 'g1',
    nonOps: [],
    transitions: [],
    plans: [{ actions: ['ACTION3', 'ACTION2'], validatedByRuns: 1 }],
    isCold: false,
  };

  it('reejecuta el plan aprendido contra la API, en orden', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ frame: [gridConMarca(1)] }))
      .mockResolvedValueOnce(frame({ frame: [gridConMarca(2)] }))
      .mockResolvedValueOnce(
        frame({ frame: [gridConMarca(3)], state: 'WIN', available_actions: [] }),
      );

    const result = await runGame({ ...baseOpts(sendCommand), memorySeed: planSeed });

    expect(result.finalState).toBe('WIN');
    expect(result.steps.map((s) => s.action)).toEqual(['RESET', 'ACTION3', 'ACTION2']);
  });

  it('seedSummary viaja en el resultado -- permite auditar si la mejora vino de la memoria', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ frame: [gridConMarca(1)] }))
      .mockResolvedValueOnce(frame({ state: 'WIN', available_actions: [] }));

    const result = await runGame({ ...baseOpts(sendCommand), memorySeed: planSeed });
    expect(result.seedSummary).toEqual({ nonOpStates: 0, transitions: 0, planLength: 2 });
  });

  it('sin semilla, seedSummary reporta arranque frio en vez de quedar indefinido', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ frame: [gridConMarca(1)] }))
      .mockResolvedValueOnce(frame({ state: 'WIN', available_actions: [] }));

    const result = await runGame(baseOpts(sendCommand));
    expect(result.seedSummary).toEqual({ nonOpStates: 0, transitions: 0, planLength: 0 });
  });

  it('seedSummary tambien viaja cuando el RESET inicial falla (camino de error temprano)', async () => {
    const sendCommand = vi.fn().mockRejectedValue(new Error('API caida'));

    const result = await runGame({ ...baseOpts(sendCommand), memorySeed: planSeed });
    expect(result.finalState).toBe('GAME_OVER');
    expect(result.seedSummary.planLength).toBe(2);
  });

  it('MENOS acciones con memoria que sin memoria sobre el mismo mundo (criterio del BL)', async () => {
    /* Mundo determinista de 3 estados: solo ACTION3 avanza de s1, solo ACTION2 desde s2. El resto
       de las acciones son no-ops. Sin memoria el agente tiene que descubrirlo probando; con la
       semilla lo sabe y va derecho. */
    function mundo() {
      let estado = 1;
      return vi.fn().mockImplementation((action: string) => {
        if (action === 'RESET') estado = 1;
        else if (estado === 1 && action === 'ACTION3') estado = 2;
        else if (estado === 2 && action === 'ACTION2') estado = 3;
        return Promise.resolve(
          frame({
            frame: [gridConMarca(estado)],
            state: estado === 3 ? 'WIN' : 'NOT_FINISHED',
            available_actions: estado === 3 ? [] : [1, 2, 3, 4],
          }),
        );
      });
    }

    const frio = await runGame({ ...baseOpts(mundo()), seed: 'semilla-prng-igual' });
    const tibio = await runGame({
      ...baseOpts(mundo()),
      seed: 'semilla-prng-igual',
      memorySeed: planSeed,
    });

    expect(frio.finalState).toBe('WIN');
    expect(tibio.finalState).toBe('WIN');
    // Con el plan: RESET + 2 acciones exactas. Sin el: hay que explorar.
    expect(tibio.steps).toHaveLength(3);
    expect(tibio.steps.length).toBeLessThan(frio.steps.length);
  });
});
