/* [arc-agi-runner/levelProgress.test] BL.21557 -- la SENAL DENSA. El caso que da sentido a todo el
   BL es el ultimo: dos derrotas que antes valian 0 y 0 ahora se ordenan. */
import { describe, expect, it } from 'vitest';

import {
  accumulateLevelProgress,
  completionRatio,
  computeRunScore,
  EMPTY_LEVEL_PROGRESS,
  formatBatchLevelSummary,
  rankRunsByLevelProgress,
  readFrameLevels,
} from '../levelProgress';
import type { ArcEvaluationRun, ArcFrameResponse } from '../types';

function frame(overrides: Partial<ArcFrameResponse> = {}): ArcFrameResponse {
  return {
    game_id: 'g',
    guid: 'guid',
    frame: [],
    state: 'NOT_FINISHED',
    levels_completed: 0,
    win_levels: 0,
    available_actions: [1],
    ...overrides,
  };
}

function run(overrides: Partial<ArcEvaluationRun> = {}): ArcEvaluationRun {
  return {
    runId: 'm:g:2026-08-17',
    modelId: 'm',
    environmentId: 'g',
    status: 'completed',
    steps: [],
    result: { success: false, score: 0 },
    replayMetadata: { seed: 's', envVersion: '2.0.0' },
    startedAt: new Date(),
    createdAt: new Date(),
    ...overrides,
  };
}

describe('readFrameLevels', () => {
  it('lee los contadores que la API mandaba desde el dia uno y nadie leia', () => {
    expect(readFrameLevels(frame({ levels_completed: 3, win_levels: 8 }))).toEqual({
      maxLevelsCompleted: 3,
      winLevels: 8,
    });
  });

  it('degrada a 0 ante valores ausentes, negativos o no numericos', () => {
    const roto = { levels_completed: -2, win_levels: 'ocho' } as unknown as ArcFrameResponse;
    expect(readFrameLevels(roto)).toEqual({ maxLevelsCompleted: 0, winLevels: 0 });
  });
});

describe('accumulateLevelProgress', () => {
  it('se queda con el MAXIMO: un frame terminal que resetea el contador no borra el progreso', () => {
    let acc = EMPTY_LEVEL_PROGRESS;
    acc = accumulateLevelProgress(acc, frame({ levels_completed: 1, win_levels: 4 }));
    acc = accumulateLevelProgress(acc, frame({ levels_completed: 3, win_levels: 4 }));
    acc = accumulateLevelProgress(acc, frame({ levels_completed: 0, state: 'GAME_OVER' }));

    expect(acc).toEqual({ maxLevelsCompleted: 3, winLevels: 4 });
  });

  it('un win_levels tardio en 0 no pisa el total ya conocido', () => {
    let acc = accumulateLevelProgress(EMPTY_LEVEL_PROGRESS, frame({ win_levels: 6 }));
    acc = accumulateLevelProgress(acc, frame({ win_levels: 0 }));
    expect(acc.winLevels).toBe(6);
  });
});

describe('computeRunScore', () => {
  it('da credito parcial entero a una derrota con progreso (antes valia 0)', () => {
    expect(computeRunScore({ maxLevelsCompleted: 3, winLevels: 8 }, false)).toBe(3);
  });

  it('una victoria nunca puntua menos que 1 aunque el juego no informe niveles', () => {
    expect(computeRunScore({ maxLevelsCompleted: 0, winLevels: 0 }, true)).toBe(1);
  });

  it('una victoria con niveles informados puntua los niveles, no 1', () => {
    expect(computeRunScore({ maxLevelsCompleted: 8, winLevels: 8 }, true)).toBe(8);
  });

  it('una derrota sin progreso sigue valiendo 0', () => {
    expect(computeRunScore({ maxLevelsCompleted: 0, winLevels: 8 }, false)).toBe(0);
  });
});

describe('completionRatio', () => {
  it('normaliza el progreso contra el total de niveles del juego', () => {
    expect(completionRatio({ maxLevelsCompleted: 2, winLevels: 8 }, false)).toBeCloseTo(0.25);
  });

  it('sin total conocido solo puede afirmar 1 (gano) o 0 (no gano)', () => {
    expect(completionRatio({ maxLevelsCompleted: 5, winLevels: 0 }, true)).toBe(1);
    expect(completionRatio({ maxLevelsCompleted: 5, winLevels: 0 }, false)).toBe(0);
  });
});

describe('rankRunsByLevelProgress (metrica de seleccion offline)', () => {
  it('ordena dos DERROTAS que antes eran indistinguibles -- el punto entero del BL', () => {
    const peor = run({
      runId: 'm:g1:d',
      environmentId: 'g1',
      result: { success: false, score: 1, maxLevelReached: 1, winLevels: 8 },
    });
    const mejor = run({
      runId: 'm:g2:d',
      environmentId: 'g2',
      result: { success: false, score: 4, maxLevelReached: 4, winLevels: 8 },
    });

    expect(rankRunsByLevelProgress([peor, mejor]).map((r) => r.runId)).toEqual([
      'm:g2:d',
      'm:g1:d',
    ]);
  });

  it('desempata por fraccion completada cuando el score entero empata', () => {
    const juegoLargo = run({
      runId: 'm:largo:d',
      result: { success: false, score: 2, maxLevelReached: 2, winLevels: 20 },
    });
    const juegoCorto = run({
      runId: 'm:corto:d',
      result: { success: false, score: 2, maxLevelReached: 2, winLevels: 4 },
    });

    expect(rankRunsByLevelProgress([juegoLargo, juegoCorto])[0].runId).toBe('m:corto:d');
  });

  it('el orden es TOTAL y estable -- dos ejecuciones eligen el mismo ganador', () => {
    const runs = [
      run({ runId: 'b', result: { success: false, score: 0 } }),
      run({ runId: 'a', result: { success: false, score: 0 } }),
      run({ runId: 'c', result: { success: false, score: 0 } }),
    ];
    expect(rankRunsByLevelProgress(runs).map((r) => r.runId)).toEqual(['a', 'b', 'c']);
    expect(rankRunsByLevelProgress([...runs].reverse()).map((r) => r.runId)).toEqual([
      'a',
      'b',
      'c',
    ]);
  });

  it('tolera corridas viejas (pre BL.21557) sin los campos nuevos', () => {
    const vieja = run({ runId: 'vieja', result: { success: false, score: 0 } });
    expect(rankRunsByLevelProgress([vieja])[0]).toMatchObject({
      maxLevelReached: 0,
      winLevels: 0,
      score: 0,
    });
  });
});

describe('formatBatchLevelSummary', () => {
  it('resume el batch en espanol con el score total como numero a mirar', () => {
    const texto = formatBatchLevelSummary([
      run({
        runId: 'a',
        environmentId: 'ls20',
        result: { success: false, score: 3, maxLevelReached: 3, winLevels: 8 },
      }),
      run({ runId: 'b', environmentId: 'ft09', result: { success: false, score: 0 } }),
    ]);
    expect(texto).toContain('score total 3');
    expect(texto).toContain('1/2 corrida(s) con progreso');
    expect(texto).toContain('ls20 con nivel 3/8');
  });

  it('dice explicitamente cuando ninguna corrida supero un nivel', () => {
    expect(formatBatchLevelSummary([run({ result: { success: false, score: 0 } })])).toContain(
      'ninguna corrida supero un solo nivel',
    );
  });

  it('no explota con un batch vacio', () => {
    expect(formatBatchLevelSummary([])).toContain('sin corridas');
  });
});
