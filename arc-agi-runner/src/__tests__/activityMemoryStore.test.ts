/* [arc-agi-runner/__tests__/activityMemoryStore] BL.20861 -- la memoria es una MEJORA, nunca un
   requisito: si Mongo no responde, la corrida debe jugarse igual en frio. Un runner que no puede
   jugar porque no pudo leer lo que aprendio ayer es peor que uno sin memoria. */

import type { Collection } from 'mongodb';
import { describe, expect, it, vi } from 'vitest';

import type { ActivityMemoryDocLike } from '../activityMemorySeed';
import { createActivityMemoryStore } from '../activityMemoryStore';

function fakeCollection(
  findOne: () => Promise<ActivityMemoryDocLike | null>,
): Collection<ActivityMemoryDocLike> {
  return { findOne } as unknown as Collection<ActivityMemoryDocLike>;
}

describe('createActivityMemoryStore', () => {
  it('construye la semilla desde el doc encontrado', async () => {
    const store = createActivityMemoryStore(
      fakeCollection(async () => ({
        activityId: 'g1',
        nonOpActions: [{ fromStateSignature: 's1', action: 'ACTION1', confirmedCount: 3 }],
      })),
    );

    const seed = await store.loadSeed('g1');
    expect(seed.isCold).toBe(false);
    expect(seed.nonOps).toEqual([{ fromStateSignature: 's1', action: 'ACTION1' }]);
  });

  it('actividad nunca jugada -> semilla fria, sin warning (no es un error)', async () => {
    const onWarn = vi.fn();
    const store = createActivityMemoryStore(
      fakeCollection(async () => null),
      onWarn,
    );

    const seed = await store.loadSeed('g-nuevo');
    expect(seed).toEqual({
      activityId: 'g-nuevo',
      nonOps: [],
      plans: [],
      transitions: [],
      isCold: true,
      // BL.21499: no habia doc -> esta si es genuinamente la primera corrida.
      sinDocumento: true,
    });
    expect(onWarn).not.toHaveBeenCalled();
  });

  it('fallo de Mongo -> semilla fria + warning, NUNCA propaga (la corrida debe poder jugarse)', async () => {
    const onWarn = vi.fn();
    const store = createActivityMemoryStore(
      fakeCollection(async () => {
        throw new Error('connection refused');
      }),
      onWarn,
    );

    const seed = await store.loadSeed('g1');
    expect(seed.isCold).toBe(true);
    expect(seed.activityId).toBe('g1');
    expect(onWarn).toHaveBeenCalledOnce();
    expect(onWarn.mock.calls[0][0]).toContain('connection refused');
  });

  it('sin callback de warning tampoco lanza -- el default es no-op, no undefined', async () => {
    const store = createActivityMemoryStore(
      fakeCollection(async () => {
        throw new Error('boom');
      }),
    );
    await expect(store.loadSeed('g1')).resolves.toMatchObject({ isCold: true });
  });
});
