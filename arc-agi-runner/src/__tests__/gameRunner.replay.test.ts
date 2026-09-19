/* [arc-agi-runner/gameRunner.replay.test] BL.21557 -- las dos cosas que gameRunner dejaba de hacer:
   (A) leer levels_completed/win_levels de cada frame, (B) conservar las coordenadas del click y lo
   que cambio en pantalla. Cliente y reloj inyectados: sin red, sin Mongo. */
import { describe, expect, it, vi } from 'vitest';

import { createDeadLetterTracker } from '../deadLetterTracker';
import { runGame } from '../gameRunner';
import type { ReplayCapture, ReplayCaptureStep } from '../replayFrameStore';
import type { ArcFrameResponse } from '../types';

function grid(valor: number, size = 8): number[][] {
  return Array.from({ length: size }, () => new Array<number>(size).fill(valor));
}

function frame(overrides: Partial<ArcFrameResponse> = {}): ArcFrameResponse {
  return {
    game_id: 'ft09-abc',
    guid: 'guid-x',
    frame: [grid(0)],
    state: 'NOT_FINISHED',
    levels_completed: 0,
    win_levels: 0,
    available_actions: [1, 2, 6],
    ...overrides,
  };
}

function capturaEnMemoria(): ReplayCapture & { pasos: ReplayCaptureStep[] } {
  const pasos: ReplayCaptureStep[] = [];
  return {
    pasos,
    recordStep: (step) => pasos.push(step),
    flush: async () => {},
    stats: () => ({
      framesCapturados: pasos.length,
      framesEscritos: pasos.length,
      bytesEstimados: 0,
      presupuestoAgotado: false,
      errores: 0,
    }),
  };
}

const base = {
  cardId: 'card-1',
  gameId: 'ft09-abc',
  seed: 'seed-fijo',
  gameTimeoutMs: 60_000,
};

describe('runGame -- senal densa (BL.21557 A)', () => {
  it('acumula el nivel maximo alcanzado aunque el juego termine en GAME_OVER', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ levels_completed: 0, win_levels: 6 }))
      .mockResolvedValueOnce(frame({ levels_completed: 1, win_levels: 6 }))
      .mockResolvedValueOnce(frame({ levels_completed: 3, win_levels: 6 }))
      // El frame terminal viene con el contador en cero -- no debe borrar el pico.
      .mockResolvedValueOnce(
        frame({ state: 'GAME_OVER', levels_completed: 0, win_levels: 6, available_actions: [] }),
      );

    const result = await runGame({
      ...base,
      client: { sendCommand },
      deadLetter: createDeadLetterTracker(3),
    });

    expect(result.finalState).toBe('GAME_OVER');
    expect(result.levelProgress).toEqual({ maxLevelsCompleted: 3, winLevels: 6 });
  });

  it('persiste los contadores POR STEP -- ubica el paso exacto en que se subio de nivel', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ levels_completed: 0, win_levels: 4 }))
      .mockResolvedValueOnce(frame({ levels_completed: 0, win_levels: 4 }))
      .mockResolvedValueOnce(frame({ levels_completed: 1, win_levels: 4 }))
      .mockResolvedValueOnce(
        frame({ state: 'WIN', levels_completed: 4, win_levels: 4, available_actions: [] }),
      );

    const result = await runGame({
      ...base,
      client: { sendCommand },
      deadLetter: createDeadLetterTracker(3),
    });

    expect(result.steps.map((s) => s.levelsCompleted)).toEqual([0, 0, 1, 4]);
    expect(result.steps.every((s) => s.winLevels === 4)).toBe(true);
  });

  it('devuelve progreso vacio cuando el RESET falla -- nunca queda undefined', async () => {
    const sendCommand = vi.fn().mockRejectedValue(new Error('API caida'));
    const result = await runGame({
      ...base,
      client: { sendCommand },
      deadLetter: createDeadLetterTracker(1),
    });

    expect(result.levelProgress).toEqual({ maxLevelsCompleted: 0, winLevels: 0 });
  });
});

describe('runGame -- corpus de replay (BL.21557 B)', () => {
  it('captura el RESET sin grilla previa: es la base del replay', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame())
      .mockResolvedValueOnce(frame({ state: 'WIN', available_actions: [] }));
    const capture = capturaEnMemoria();

    await runGame({
      ...base,
      client: { sendCommand },
      deadLetter: createDeadLetterTracker(3),
      capture,
    });

    expect(capture.pasos[0]).toMatchObject({ stepNum: 0, action: 'RESET', gridBefore: null });
    expect(capture.pasos[0].gridAfter).not.toBeNull();
  });

  it('conserva las coordenadas x,y del click que antes se descartaban al persistir', async () => {
    // La politica elige ACTION6 en algun momento de una partida larga; se fuerza el escenario
    // dejando ACTION6 como unica accion disponible.
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ available_actions: [6] }))
      .mockResolvedValueOnce(frame({ available_actions: [6], frame: [grid(1)] }))
      .mockResolvedValueOnce(frame({ state: 'WIN', available_actions: [] }));
    const capture = capturaEnMemoria();

    await runGame({
      ...base,
      client: { sendCommand },
      deadLetter: createDeadLetterTracker(3),
      capture,
    });

    const click = capture.pasos.find((p) => p.action === 'ACTION6');
    expect(click).toBeDefined();
    expect(typeof click!.x).toBe('number');
    expect(typeof click!.y).toBe('number');
    // Y la MISMA coordenada que se le mando a la API, no una recalculada.
    const enviado = sendCommand.mock.calls.find((c) => c[0] === 'ACTION6')![1];
    expect(click!.x).toBe(enviado.x);
    expect(click!.y).toBe(enviado.y);
  });

  it('captura las acciones disponibles del estado sobre el que se DECIDIO, no del posterior', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ available_actions: [1, 2] }))
      .mockResolvedValueOnce(frame({ state: 'WIN', available_actions: [] }));
    const capture = capturaEnMemoria();

    await runGame({
      ...base,
      client: { sendCommand },
      deadLetter: createDeadLetterTracker(3),
      capture,
    });

    const accion = capture.pasos[1];
    expect(accion.availableActions).toEqual([1, 2]);
    expect(accion.gridBefore).not.toBeNull();
  });

  it('sin capture inyectado el runner se comporta exactamente como antes', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame())
      .mockResolvedValueOnce(frame({ state: 'WIN', available_actions: [] }));

    const result = await runGame({
      ...base,
      client: { sendCommand },
      deadLetter: createDeadLetterTracker(3),
    });

    expect(result.finalState).toBe('WIN');
    expect(result.steps).toHaveLength(2);
  });
});
