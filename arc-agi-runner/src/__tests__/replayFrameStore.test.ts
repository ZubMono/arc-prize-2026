/* [arc-agi-runner/replayFrameStore.test] BL.21557 -- sink del corpus. Se testea sin Mongo real
   (bulkWrite inyectado): idempotencia por {runId, stepNum}, presupuesto duro de 1MB por partida y,
   sobre todo, que NINGUN fallo de captura pueda propagarse a la partida. */
import { describe, expect, it, vi } from 'vitest';

import {
  createReplayFrameStore,
  DEFAULT_REPLAY_BYTE_BUDGET,
  type ReplayCaptureStep,
} from '../replayFrameStore';
import type { Grid } from '../worldModel/grid';

function gridUniforme(valor: number, size = 64): Grid {
  return Array.from({ length: size }, () => new Array<number>(size).fill(valor));
}

function paso(overrides: Partial<ReplayCaptureStep> = {}): ReplayCaptureStep {
  const before = gridUniforme(0);
  const after = gridUniforme(0);
  after[1][1] = 7;
  return {
    stepNum: 1,
    action: 'ACTION6',
    x: 32,
    y: 17,
    availableActions: [1, 2, 6],
    gridBefore: before,
    gridAfter: after,
    levelsCompleted: 2,
    winLevels: 5,
    ts: new Date('2026-08-17T00:00:00.000Z'),
    ...overrides,
  };
}

function fakeCollection() {
  const bulkWrite = vi.fn().mockResolvedValue({ ok: 1 });
  return { collection: { bulkWrite }, bulkWrite };
}

const ctx = { runId: 'm:g:2026-08-17', gameId: 'g', modelId: 'm' };

describe('createReplayFrameStore', () => {
  it('persiste las coordenadas del click -- el dato que se descartaba antes de BL.21557', async () => {
    const { collection, bulkWrite } = fakeCollection();
    const store = createReplayFrameStore(collection, ctx);

    store.recordStep(paso());
    await store.flush();

    const doc = bulkWrite.mock.calls[0][0][0].updateOne.update.$set;
    expect(doc.x).toBe(32);
    expect(doc.y).toBe(17);
    expect(doc.availableActions).toEqual([1, 2, 6]);
    expect(doc.levelsCompleted).toBe(2);
    expect(doc.winLevels).toBe(5);
    expect(doc.changedCells).toBe(1);
    expect(doc.diffRle.length).toBeGreaterThan(0);
  });

  it('escribe con upsert por {runId, stepNum} -- re-jugar el mismo runId no duplica el corpus', async () => {
    const { collection, bulkWrite } = fakeCollection();
    const store = createReplayFrameStore(collection, ctx);

    store.recordStep(paso({ stepNum: 4 }));
    await store.flush();

    const op = bulkWrite.mock.calls[0][0][0].updateOne;
    expect(op.filter).toEqual({ runId: ctx.runId, stepNum: 4 });
    expect(op.upsert).toBe(true);
    expect(bulkWrite.mock.calls[0][1]).toEqual({ ordered: false });
  });

  it('omite el paso sin grilla utilizable en vez de escribir un frame vacio', async () => {
    const { collection, bulkWrite } = fakeCollection();
    const store = createReplayFrameStore(collection, ctx);

    store.recordStep(paso({ gridAfter: null }));
    await store.flush();

    expect(bulkWrite).not.toHaveBeenCalled();
    expect(store.stats().framesCapturados).toBe(0);
  });

  it('agrupa en lotes en vez de una escritura por paso', async () => {
    const { collection, bulkWrite } = fakeCollection();
    const store = createReplayFrameStore(collection, { ...ctx, batchSize: 5 });

    for (let i = 0; i < 12; i++) store.recordStep(paso({ stepNum: i }));
    await store.flush();

    expect(bulkWrite).toHaveBeenCalledTimes(3); // 5 + 5 + 2
    expect(store.stats().framesEscritos).toBe(12);
  });

  it('corta la captura al agotar el presupuesto de bytes -- techo duro por partida', async () => {
    const { collection } = fakeCollection();
    const log = vi.fn();
    // Presupuesto minusculo: entra un frame y nada mas.
    const store = createReplayFrameStore(collection, { ...ctx, byteBudget: 300, log });

    for (let i = 0; i < 50; i++) store.recordStep(paso({ stepNum: i }));
    await store.flush();

    const stats = store.stats();
    expect(stats.presupuestoAgotado).toBe(true);
    expect(stats.framesCapturados).toBeLessThan(50);
    expect(stats.bytesEstimados).toBeLessThanOrEqual(300);
    expect(log).toHaveBeenCalledTimes(1); // lo dice UNA vez, no 49
  });

  it('un fallo de Mongo se registra y NUNCA se propaga a la partida', async () => {
    const bulkWrite = vi.fn().mockRejectedValue(new Error('replica set caido'));
    const log = vi.fn();
    const store = createReplayFrameStore({ bulkWrite }, { ...ctx, log });

    store.recordStep(paso());
    await expect(store.flush()).resolves.toBeUndefined();

    expect(store.stats().errores).toBe(1);
    expect(log.mock.calls[0][0]).toContain('La partida continua');
  });

  it('el presupuesto default es 1MB, el techo que exige el corpus', () => {
    expect(DEFAULT_REPLAY_BYTE_BUDGET).toBe(1_000_000);
  });

  it('una partida de 500 pasos con movimiento realista entra en el presupuesto de 1MB', async () => {
    const { collection } = fakeCollection();
    const store = createReplayFrameStore(collection, ctx);

    let actual = gridUniforme(0);
    for (let i = 0; i < 500; i++) {
      const siguiente = actual.map((row) => row.slice());
      // Sprite de 3x3 que se desplaza -- ~18 celdas cambiadas por paso, el orden de magnitud real
      // de un juego ARC-AGI-3.
      for (let dy = 0; dy < 3; dy++) {
        for (let dx = 0; dx < 3; dx++) {
          siguiente[(i + dy) % 64][(i + dx) % 64] = 0;
          siguiente[(i + 1 + dy) % 64][(i + 1 + dx) % 64] = 4;
        }
      }
      store.recordStep(paso({ stepNum: i, gridBefore: actual, gridAfter: siguiente }));
      actual = siguiente;
    }
    await store.flush();

    const stats = store.stats();
    expect(stats.presupuestoAgotado).toBe(false);
    expect(stats.framesCapturados).toBe(500);
    expect(stats.bytesEstimados).toBeLessThan(1_000_000);
  });
});
