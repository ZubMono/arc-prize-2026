/* [arc-agi-runner/index.test] BL.20775 -- orquestacion del batch completo: abrir scorecard, jugar
   cada juego, idempotencia por runId, mapeo de resultado (WIN/GAME_OVER/timeout/dead-letter) a
   status, y cierre garantizado del scorecard/run activo ante crash. Cliente ARC + store Mongo
   mockeados -- sin red ni Mongo reales. */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { loadConfig } from '../config';
import { runBatch } from '../index';
import type { ArcEvaluationRun, ArcFrameResponse } from '../types';

function makeConfig(overrides: Record<string, string> = {}) {
  return loadConfig({
    ARC_API_KEY: 'k',
    // BL.21700: el runner ya no lee MONGO_URL -- la URL del ciclo ARC viene de estas variables.
    PROMETHEUS_MONGO_URL: 'mongodb://localhost:27017/x',
    ARC_RUN_BATCH_ID: 'batch-1',
    ...overrides,
  });
}

function frame(overrides: Partial<ArcFrameResponse> = {}): ArcFrameResponse {
  return {
    game_id: 'g1',
    guid: 'guid-1',
    frame: [],
    state: 'NOT_FINISHED',
    levels_completed: 0,
    win_levels: 0,
    available_actions: [1, 2],
    ...overrides,
  };
}

function fakeClient(sendCommand = vi.fn()) {
  return {
    openScorecard: vi.fn().mockResolvedValue('card-1'),
    closeScorecard: vi.fn().mockResolvedValue({ card_id: 'card-1', score: 0 }),
    sendCommand,
    listGames: vi.fn().mockResolvedValue([]),
  };
}

function fakeStore(initial: Record<string, ArcEvaluationRun> = {}) {
  const db = new Map(Object.entries(initial));
  return {
    upsertRun: vi.fn(async (run: ArcEvaluationRun) => {
      db.set(run.runId, run);
    }),
    findByRunId: vi.fn(async (runId: string) => db.get(runId) ?? null),
    /* BL.21707: el backstop busca por PREFIJO `modelId:gameId:diaDelBatch`, no por runId exacto --
       desde este BL el runBatchId es unico por corrida y la igualdad nunca volveria a dar true. */
    findCompletedByPrefix: vi.fn(async (prefijo: string) => {
      for (const run of db.values()) {
        if (run.status === 'completed' && run.runId.startsWith(prefijo)) return run;
      }
      return null;
    }),
  };
}

describe('runBatch', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('abre scorecard, juega cada juego dado en gameIds y lo cierra al final', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ game_id: 'g1', state: 'WIN', available_actions: [] }))
      .mockResolvedValueOnce(frame({ game_id: 'g2', state: 'WIN', available_actions: [] }));
    const client = fakeClient(sendCommand);
    const store = fakeStore();

    const { cardId, results } = await runBatch({
      config: makeConfig(),
      client,
      store,
      gameIds: ['g1', 'g2'],
    });

    expect(cardId).toBe('card-1');
    expect(client.openScorecard).toHaveBeenCalledTimes(1);
    expect(client.closeScorecard).toHaveBeenCalledWith('card-1');
    expect(results).toHaveLength(2);
    expect(results.every((r) => r.status === 'completed' && r.result.success)).toBe(true);
  });

  it('hace skip de un juego ya completado en este batch (idempotencia)', async () => {
    const config = makeConfig();
    const runId = `${config.modelId}:g1:batch-1`;
    const existingRun: ArcEvaluationRun = {
      runId,
      modelId: config.modelId,
      environmentId: 'g1',
      status: 'completed',
      steps: [],
      result: { success: true, score: 1 },
      replayMetadata: { seed: 's', envVersion: '1.0.0' },
      startedAt: new Date('2026-08-01'),
      completedAt: new Date('2026-08-01'),
      createdAt: new Date('2026-08-01'),
    };
    const store = fakeStore({ [runId]: existingRun });
    const sendCommand = vi.fn();
    const client = fakeClient(sendCommand);

    const { results } = await runBatch({ config, client, store, gameIds: ['g1'] });

    expect(sendCommand).not.toHaveBeenCalled();
    expect(results[0]).toEqual(existingRun);
  });

  it('GAME_OVER normal (el agente pierde) es una evaluacion COMPLETADA, no una falla de infra', async () => {
    const sendCommand = vi
      .fn()
      .mockResolvedValueOnce(frame({ state: 'GAME_OVER', available_actions: [] }));
    const client = fakeClient(sendCommand);
    const store = fakeStore();

    const { results } = await runBatch({ config: makeConfig(), client, store, gameIds: ['g1'] });

    expect(results[0].status).toBe('completed');
    expect(results[0].result.success).toBe(false);
    expect(results[0].result.score).toBe(0);
  });

  it('un timeout duro mapea a status failed con error descriptivo', async () => {
    const config = { ...makeConfig(), gameTimeoutMs: 0 };
    const sendCommand = vi.fn().mockResolvedValueOnce(frame({ state: 'NOT_FINISHED' }));
    const client = fakeClient(sendCommand);
    const store = fakeStore();

    const { results } = await runBatch({ config, client, store, gameIds: ['g1'] });

    expect(results[0].status).toBe('failed');
    expect(results[0].result.error).toMatch(/[Tt]imeout/);
  });

  it('no deja listeners de proceso colgados aunque el batch lance (finally desregistra el crash guard)', async () => {
    const before = process.listenerCount('SIGINT');
    const client = fakeClient(vi.fn());
    const store = {
      upsertRun: vi.fn().mockRejectedValue(new Error('mongo caido')),
      findByRunId: vi.fn(),
      findCompletedByPrefix: vi.fn().mockResolvedValue(null),
    };

    await expect(
      runBatch({ config: makeConfig(), client, store, gameIds: ['g1'] }),
    ).rejects.toThrow('mongo caido');

    expect(process.listenerCount('SIGINT')).toBe(before);
  });

  it('ante SIGINT con un juego en curso, cierra el run activo como failed y el scorecard antes de salir', async () => {
    let resolveReset!: (f: ArcFrameResponse) => void;
    const pending = new Promise<ArcFrameResponse>((resolve) => {
      resolveReset = resolve;
    });
    const sendCommand = vi.fn().mockReturnValueOnce(pending);
    const client = fakeClient(sendCommand);
    const store = fakeStore();
    const exit = vi.fn();

    void runBatch({ config: makeConfig(), client, store, gameIds: ['g1'], crashExit: exit });

    await vi.waitFor(() => expect(sendCommand).toHaveBeenCalledTimes(1));
    process.emit('SIGINT');
    await vi.waitFor(() => expect(exit).toHaveBeenCalledWith(130));

    expect(client.closeScorecard).toHaveBeenCalledWith('card-1');
    const failedUpsert = store.upsertRun.mock.calls.find(([run]) => run.status === 'failed');
    expect(failedUpsert).toBeTruthy();
    expect(failedUpsert?.[0].result.error).toMatch(/SIGINT/);

    resolveReset(frame({ state: 'WIN' })); // libera la promesa colgada -- no deja el runner en el limbo
  });

  /* BL.21707 -- el runId ya no repite el del dia, asi que el skip del backstop no puede depender
     de una igualdad exacta. Estos dos tests fijan las dos mitades: sigue habiendo skip cuando el
     juego YA se completo hoy (aunque con otro runBatchId), y NO hay colision entre dos corridas
     legitimas del mismo dia. */
  it('el backstop hace skip aunque la corrida de hoy tenga OTRO runBatchId (o el formato viejo)', async () => {
    const config = makeConfig({ ARC_RUN_BATCH_ID: '' });
    const dia = config.runBatchId.slice(0, 10);
    const previa: ArcEvaluationRun = {
      runId: `${config.modelId}:g1:${dia}`, // formato viejo: fecha pelada
      modelId: config.modelId,
      environmentId: 'g1',
      status: 'completed',
      steps: [],
      result: { success: true, score: 1 },
      replayMetadata: { seed: 's', envVersion: '1.0.0' },
      startedAt: new Date(),
      completedAt: new Date(),
      createdAt: new Date(),
    };
    const store = fakeStore({ [previa.runId]: previa });
    const sendCommand = vi.fn();

    const { results } = await runBatch({
      config,
      client: fakeClient(sendCommand),
      store,
      gameIds: ['g1'],
    });

    expect(sendCommand).not.toHaveBeenCalled();
    expect(results[0]).toEqual(previa);
  });

  it('dos corridas del mismo modelo+juego el mismo dia se persisten con runIds DISTINTOS', async () => {
    const juego = 'ar25-0c556536';
    const runIds: string[] = [];

    for (const _ of [1, 2]) {
      void _;
      // Config nueva por corrida = proceso nuevo: es el escenario real (dos invocaciones).
      const config = makeConfig({ ARC_RUN_BATCH_ID: '' });
      const store = fakeStore(); // vacio: nada completado -> el backstop no interfiere
      const sendCommand = vi
        .fn()
        .mockResolvedValueOnce(frame({ game_id: juego, state: 'WIN', available_actions: [] }));
      const { results } = await runBatch({
        config,
        client: fakeClient(sendCommand),
        store,
        gameIds: [juego],
      });
      runIds.push(results[0].runId);
    }

    expect(runIds[0]).not.toBe(runIds[1]);
    // Ambos siguen siendo legibles y ordenables: mismo modelo, mismo juego, mismo dia.
    expect(runIds[0].startsWith(`prometheus-arc-baseline-v1:${juego}:`)).toBe(true);
    expect(runIds[1].startsWith(`prometheus-arc-baseline-v1:${juego}:`)).toBe(true);
  });
});

describe('retencion de la partida (BL.21749, revision adversarial)', () => {
  /* El cron `arc-live-game-run.cjs` corre CADA HORA y juega partidas REALES contra la API oficial
     con el modelId default `prometheus-arc-baseline-v1`. Antes de este arreglo, cada una nacia con
     `expiresAt = +90 dias` y SIN marca sobre un TTL que ya esta vivo en produccion: la bomba que
     BL.21749 desactivo a mano se re-armaba sola, una vez por hora. */
  it('una partida REAL nace retenida: sin expiresAt y con retenidoPor, desde el primer upsert', async () => {
    const client = fakeClient(
      vi.fn().mockResolvedValue(frame({ state: 'WIN', available_actions: [] })),
    );
    const store = fakeStore();

    await runBatch({ config: makeConfig(), client, store, gameIds: ['g1'] });

    const [abierta] = store.upsertRun.mock.calls[0] as unknown as [
      ArcEvaluationRun & { retenidoPor?: string; retenidoEn?: Date },
    ];
    expect(abierta.modelId).toBe('prometheus-arc-baseline-v1');
    expect(abierta.expiresAt).toBeUndefined();
    expect(abierta.retenidoPor).toContain('BL.21749');
    expect(abierta.retenidoEn).toEqual(abierta.startedAt);

    // Y el cierre no la cambia: no hay upsert que le devuelva fecha de muerte.
    for (const [run] of store.upsertRun.mock.calls as unknown as [ArcEvaluationRun][]) {
      expect(run.expiresAt).toBeUndefined();
    }
  });

  it('una corrida SINTETICA (regenerable) nace con su expiresAt, fijado al ABRIR la partida', async () => {
    const client = fakeClient(
      vi.fn().mockResolvedValue(frame({ state: 'WIN', available_actions: [] })),
    );
    const store = fakeStore();

    await runBatch({
      config: makeConfig({ ARC_RUNNER_MODEL_ID: 'prometheus-baseline' }),
      client,
      store,
      gameIds: ['g1'],
    });

    const [abierta] = store.upsertRun.mock.calls[0] as unknown as [ArcEvaluationRun];
    expect(abierta.expiresAt).toBeInstanceOf(Date);
    expect((abierta.expiresAt as Date).getTime() - abierta.startedAt.getTime()).toBe(
      90 * 24 * 60 * 60 * 1000,
    );
    expect(abierta).not.toHaveProperty('retenidoPor');
    // El cierre conserva la MISMA fecha: `expiresAt` es un campo de creacion, no se recalcula.
    const [cerrada] = store.upsertRun.mock.calls.at(-1) as unknown as [ArcEvaluationRun];
    expect(cerrada.expiresAt).toEqual(abierta.expiresAt);
  });
});
