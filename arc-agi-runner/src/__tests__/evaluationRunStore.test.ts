/* [arc-agi-runner/evaluationRunStore.test] BL.20775 -- persistencia idempotente hacia
   prometheusEvaluationRuns (via Collection<T> inyectada -- sin Mongo real en tests).

   BL.21707 -- el nucleo de este archivo es ahora el guard contra la perdida silenciosa de
   telemetria: el writer hacia `$set` del doc ENTERO, asi que dos corridas que compartieran runId
   se pisaban sin error ni aviso. Los tests de abajo fijan la particion inmutable/mutable, corren
   dos corridas contra una coleccion falsa que aplica la semantica REAL de $setOnInsert, y dejan
   una regresion que se pone roja si alguien vuelve a mandar el doc completo por $set. */
import { describe, expect, it, vi } from 'vitest';

import {
  CAMPOS_INMUTABLES_CORRIDA,
  createEvaluationRunStore,
  escaparRegex,
  particionarActualizacion,
} from '../evaluationRunStore';
import {
  MOTIVO_RETENCION_PARTIDA_REAL,
  esCorridaNoRegenerable,
  retencionDeCorrida,
} from '../politicaDeRetencion';
import type { ArcEvaluationRun } from '../types';

function makeRun(overrides: Partial<ArcEvaluationRun> = {}): ArcEvaluationRun {
  return {
    runId: 'prometheus-arc-baseline-v1:ls20-016295f7601e:2026-08-07',
    modelId: 'prometheus-arc-baseline-v1',
    environmentId: 'ls20-016295f7601e',
    status: 'running',
    steps: [],
    result: { success: false, score: 0 },
    replayMetadata: { seed: 'seed-1', envVersion: '1.0.0' },
    startedAt: new Date('2026-08-07T00:00:00Z'),
    createdAt: new Date('2026-08-07T00:00:00Z'),
    ...overrides,
  };
}

function fakeCollection() {
  return {
    updateOne: vi.fn().mockResolvedValue({ acknowledged: true }),
    findOne: vi.fn(),
  };
}

/** Coleccion falsa que aplica la semantica REAL del upsert de Mongo: `$setOnInsert` solo corre
 *  cuando el doc se CREA, `$set` siempre. Sin esto los tests de "la primera corrida sobrevive" no
 *  probarian nada -- estarian afirmando sobre un mock que no distingue insert de update. */
function coleccionEnMemoria() {
  const docs = new Map<string, Record<string, unknown>>();
  return {
    docs,
    updateOne: vi.fn(
      async (
        filtro: { runId: string },
        update: { $set: Record<string, unknown>; $setOnInsert: Record<string, unknown> },
        opciones: { upsert?: boolean },
      ) => {
        const existente = docs.get(filtro.runId);
        if (!existente) {
          if (!opciones.upsert) return { acknowledged: true, matchedCount: 0 };
          docs.set(filtro.runId, { ...update.$setOnInsert, ...update.$set });
          return { acknowledged: true, upsertedCount: 1 };
        }
        Object.assign(existente, update.$set);
        return { acknowledged: true, matchedCount: 1 };
      },
    ),
    findOne: vi.fn(async (filtro: { runId?: unknown; status?: string }) => {
      const patron =
        typeof filtro.runId === 'object' && filtro.runId !== null
          ? new RegExp((filtro.runId as { $regex: string }).$regex)
          : null;
      for (const doc of docs.values()) {
        if (filtro.status && doc.status !== filtro.status) continue;
        if (patron && !patron.test(String(doc.runId))) continue;
        if (typeof filtro.runId === 'string' && doc.runId !== filtro.runId) continue;
        return doc;
      }
      return null;
    }),
  };
}

describe('particionarActualizacion (BL.21707)', () => {
  it('los campos de IDENTIDAD van a $setOnInsert y nunca a $set', () => {
    const { $set, $setOnInsert } = particionarActualizacion(makeRun());
    for (const campo of CAMPOS_INMUTABLES_CORRIDA) {
      expect($setOnInsert).toHaveProperty(campo);
      expect($set).not.toHaveProperty(campo);
    }
  });

  it('lo que cambia durante la partida va a $set; expiresAt va a $setOnInsert (BL.21749)', () => {
    const { $set, $setOnInsert } = particionarActualizacion(
      makeRun({
        status: 'completed',
        steps: [{ stepNum: 1, action: 'ACTION1', state: 'WIN', ts: new Date() }] as never,
        result: { success: true, score: 3 },
        completedAt: new Date('2026-08-07T01:00:00Z'),
        expiresAt: new Date('2026-11-05T01:00:00Z'),
      }),
    );
    expect(Object.keys($set).sort()).toEqual(['completedAt', 'result', 'status', 'steps'].sort());
    /* La fecha de purga se escribe SOLO al crear el documento: un reintento del mismo runId sobre
       una corrida retenida a mano (las partidas reales contra la API oficial) no puede devolverle
       fecha de muerte. Y al viajar en el mismo update que el resto, el upsert vuelve a ser UNA
       escritura atomica -- partirlo en dos dejaba, ante un crash entre ambas, una corrida sin fecha
       y sin marca, que es justo el estado que este BL existe para eliminar. */
    expect($setOnInsert.expiresAt).toEqual(new Date('2026-11-05T01:00:00Z'));
    expect($set).not.toHaveProperty('expiresAt');
  });

  it('las marcas de retencion solo pueden escribirse al CREAR, nunca pisarse', () => {
    const { $set, $setOnInsert } = particionarActualizacion(
      makeRun({
        retenidoPor: 'BL.21749 — ...',
        retenidoEn: new Date('2026-08-19T00:00:00Z'),
      } as Partial<ArcEvaluationRun>),
    );
    // En $set jamas: un upsert de cierre pisaria el motivo que dejo la operacion de retencion.
    expect($set).not.toHaveProperty('retenidoPor');
    expect($set).not.toHaveProperty('retenidoEn');
    // En $setOnInsert si: asi nace retenida una partida real contra la API oficial (BL.21749).
    expect($setOnInsert.retenidoPor).toBe('BL.21749 — ...');
    expect($setOnInsert.retenidoEn).toEqual(new Date('2026-08-19T00:00:00Z'));
  });

  it('nunca manda _id (Mongo lo asigna y es inmutable: en $set romperia el update)', () => {
    const { $set, $setOnInsert } = particionarActualizacion(
      makeRun({ _id: 'abc123' } as Partial<ArcEvaluationRun>),
    );
    expect($set).not.toHaveProperty('_id');
    expect($setOnInsert).not.toHaveProperty('_id');
  });

  it('descarta claves peligrosas de un doc que vuelve de Mongo (prototype pollution)', () => {
    const envenenado = JSON.parse(
      '{"runId":"r1","status":"running","__proto__":{"hackeado":true}}',
    );
    const { $set } = particionarActualizacion({ ...makeRun(), ...envenenado });
    expect(({} as Record<string, unknown>).hackeado).toBeUndefined();
    expect(Object.keys($set)).not.toContain('__proto__');
  });

  /* REGRESION EXPLICITA. El bug era literalmente `{ $set: run }`. Si alguien vuelve a mandar el
     doc completo por $set, esta afirmacion se pone roja antes que ninguna otra. */
  it('REGRESION: $set NUNCA contiene el doc completo', () => {
    const run = makeRun();
    const { $set } = particionarActualizacion(run);
    expect(Object.keys($set).length).toBeLessThan(Object.keys(run).length);
    expect($set).not.toEqual(run);
  });
});

describe('createEvaluationRunStore', () => {
  it('upsertRun usa $setOnInsert para la identidad y $set solo para lo mutable', async () => {
    const col = fakeCollection();
    const store = createEvaluationRunStore(col as never);
    const run = makeRun();
    await store.upsertRun(run);

    const [filtro, update, opciones] = col.updateOne.mock.calls[0];
    expect(filtro).toEqual({ runId: run.runId });
    expect(opciones).toEqual({ upsert: true });
    expect(update.$setOnInsert.runId).toBe(run.runId);
    expect(update.$setOnInsert.startedAt).toBe(run.startedAt);
    expect(update.$set.status).toBe('running');
    expect(update.$set).not.toHaveProperty('startedAt');
  });

  it('el cierre de la corrida actualiza status/result/steps sobre el MISMO doc', async () => {
    const col = coleccionEnMemoria();
    const store = createEvaluationRunStore(col as never);
    const inicial = makeRun();
    await store.upsertRun(inicial);
    await store.upsertRun({
      ...inicial,
      status: 'completed',
      result: { success: true, score: 4 },
      completedAt: new Date('2026-08-07T01:00:00Z'),
    });

    expect(col.docs.size).toBe(1);
    const doc = col.docs.get(inicial.runId) as Record<string, unknown>;
    expect(doc.status).toBe('completed');
    expect((doc.result as { score: number }).score).toBe(4);
  });

  it('un segundo upsert NO puede reescribir la identidad de una corrida ya persistida', async () => {
    const col = coleccionEnMemoria();
    const store = createEvaluationRunStore(col as never);
    const original = makeRun();
    await store.upsertRun(original);

    /* Colision: mismo runId, otra partida. Antes de BL.21707 esto reescribia gameId, seed y
       startedAt y la primera corrida desaparecia. */
    await store.upsertRun(
      makeRun({
        environmentId: 'ar25-0c556536',
        replayMetadata: { seed: 'seed-IMPOSTORA', envVersion: '2.0.0' },
        startedAt: new Date('2026-08-08T00:00:00Z'),
        createdAt: new Date('2026-08-08T00:00:00Z'),
        status: 'completed',
      }),
    );

    const doc = col.docs.get(original.runId) as Record<string, unknown>;
    expect(doc.environmentId).toBe('ls20-016295f7601e');
    expect(doc.replayMetadata).toEqual({ seed: 'seed-1', envVersion: '1.0.0' });
    expect(doc.startedAt).toEqual(original.startedAt);
    expect(doc.createdAt).toEqual(original.createdAt);
    // Lo que SI cambia legitimamente durante la partida.
    expect(doc.status).toBe('completed');
  });

  it('dos corridas con runIds distintos conviven -- la primera queda intacta', async () => {
    const col = coleccionEnMemoria();
    const store = createEvaluationRunStore(col as never);
    const base = 'prometheus-arc-baseline-v1:ar25-0c556536:2026-08-17';
    const primera = makeRun({
      runId: `${base}T090000.000Z-aaa111`,
      environmentId: 'ar25-0c556536',
      status: 'completed',
      result: { success: false, score: 2 },
    });
    const segunda = makeRun({
      runId: `${base}T153000.000Z-bbb222`,
      environmentId: 'ar25-0c556536',
      status: 'completed',
      result: { success: true, score: 5 },
    });
    await store.upsertRun(primera);
    await store.upsertRun(segunda);

    expect(col.docs.size).toBe(2);
    const doc1 = col.docs.get(primera.runId) as Record<string, unknown>;
    expect((doc1.result as { score: number }).score).toBe(2);
  });

  it('findCompletedByPrefix encuentra la corrida completada del dia (backstop de idempotencia)', async () => {
    const col = coleccionEnMemoria();
    const store = createEvaluationRunStore(col as never);
    await store.upsertRun(
      makeRun({
        runId: 'prometheus-arc-baseline-v1:ar25-0c556536:2026-08-17T090000.000Z-aaa111',
        environmentId: 'ar25-0c556536',
        status: 'completed',
      }),
    );

    const hallada = await store.findCompletedByPrefix(
      'prometheus-arc-baseline-v1:ar25-0c556536:2026-08-17',
    );
    expect(hallada?.runId).toContain('aaa111');
  });

  it('findCompletedByPrefix tambien encuentra los runIds del formato VIEJO (fecha pelada)', async () => {
    const col = coleccionEnMemoria();
    const store = createEvaluationRunStore(col as never);
    await store.upsertRun(
      makeRun({
        runId: 'prometheus-arc-baseline-v1:ar25-0c556536:2026-08-17',
        environmentId: 'ar25-0c556536',
        status: 'completed',
      }),
    );

    const hallada = await store.findCompletedByPrefix(
      'prometheus-arc-baseline-v1:ar25-0c556536:2026-08-17',
    );
    expect(hallada).not.toBeNull();
  });

  it('findCompletedByPrefix ignora corridas running/failed -- se debe poder reintentar', async () => {
    const col = coleccionEnMemoria();
    const store = createEvaluationRunStore(col as never);
    await store.upsertRun(
      makeRun({
        runId: 'prometheus-arc-baseline-v1:g1:2026-08-17T090000.000Z-aaa111',
        environmentId: 'g1',
        status: 'running',
      }),
    );
    expect(
      await store.findCompletedByPrefix('prometheus-arc-baseline-v1:g1:2026-08-17'),
    ).toBeNull();
  });

  it('findCompletedByPrefix ancla el regex al comienzo y escapa el prefijo', async () => {
    const col = fakeCollection();
    col.findOne.mockResolvedValueOnce(null);
    const store = createEvaluationRunStore(col as never);
    await store.findCompletedByPrefix('modelo.v1:g1:2026-08-17');
    expect(col.findOne).toHaveBeenCalledWith({
      runId: { $regex: '^modelo\\.v1:g1:2026-08-17' },
      status: 'completed',
    });
  });

  it('escaparRegex neutraliza los metacaracteres del modelId/gameId', () => {
    expect(escaparRegex('a.b*c+d')).toBe('a\\.b\\*c\\+d');
    expect(new RegExp(`^${escaparRegex('a.b')}`).test('axb')).toBe(false);
  });

  it('findByRunId delega en collection.findOne por runId', async () => {
    const col = fakeCollection();
    const run = makeRun();
    col.findOne.mockResolvedValueOnce(run);
    const store = createEvaluationRunStore(col as never);
    const found = await store.findByRunId(run.runId);
    expect(found).toEqual(run);
    expect(col.findOne).toHaveBeenCalledWith({ runId: run.runId });
  });
});

describe('retencion explicita de corridas (BL.21749)', () => {
  it('UNA sola escritura, atomica: expiresAt viaja en $setOnInsert', async () => {
    /* Regresion de la revision adversarial: la primera version de este BL partio el upsert en dos
       (`{$set,$setOnInsert}` y despues `{$set:{expiresAt}}` con filtro que excluia retenidas). Un
       crash, una desconexion o un error entre ambas dejaba la corrida persistida SIN expiresAt y
       SIN retenidoPor -- indistinguible de una retenida a mano, fuera del TTL para siempre y sin
       nadie que la reintente. */
    const col = fakeCollection();
    const store = createEvaluationRunStore(col as never);
    const expira = new Date('2026-11-14T06:30:55.291Z');
    const run = makeRun({ status: 'completed', completedAt: new Date(), expiresAt: expira });

    await store.upsertRun(run);

    expect(col.updateOne).toHaveBeenCalledTimes(1);
    const [filtro, update, opciones] = col.updateOne.mock.calls[0];
    expect(filtro).toEqual({ runId: run.runId });
    expect(opciones).toEqual({ upsert: true });
    expect(
      update.$set,
      'con expiresAt en el $set general, un reintento del mismo runId le devuelve fecha de muerte a una corrida retenida',
    ).not.toHaveProperty('expiresAt');
    expect(update.$setOnInsert.expiresAt).toEqual(expira);
  });

  it('una corrida recien abierta escribe igual una sola vez', async () => {
    const col = fakeCollection();
    const store = createEvaluationRunStore(col as never);

    await store.upsertRun(makeRun());

    expect(col.updateOne).toHaveBeenCalledTimes(1);
  });

  it('una partida REAL nace retenida: sin expiresAt y con la marca, en el mismo insert', async () => {
    const col = fakeCollection();
    const store = createEvaluationRunStore(col as never);
    const ahora = new Date('2026-08-19T02:26:00Z');
    const run = makeRun({
      modelId: 'prometheus-arc-baseline-v1',
      ...retencionDeCorrida('prometheus-arc-baseline-v1', ahora, new Date('2026-11-17T02:26:00Z')),
    } as Partial<ArcEvaluationRun>);

    await store.upsertRun(run);

    const [, update] = col.updateOne.mock.calls[0];
    expect(update.$setOnInsert).not.toHaveProperty('expiresAt');
    expect(update.$setOnInsert.retenidoPor).toBe(MOTIVO_RETENCION_PARTIDA_REAL);
    expect(update.$setOnInsert.retenidoEn).toEqual(ahora);
  });

  it('la politica distingue lo no-regenerable de lo sintetico', () => {
    expect(esCorridaNoRegenerable('prometheus-arc-baseline-v1')).toBe(true);
    expect(esCorridaNoRegenerable('agente-novato-referencia')).toBe(false);
    expect(esCorridaNoRegenerable('prometheus-baseline')).toBe(false);

    const expira = new Date('2026-11-17T02:26:00Z');
    const ahora = new Date('2026-08-19T02:26:00Z');
    // O fecha, o marca: nunca las dos (serian contradictorias).
    expect(retencionDeCorrida('prometheus-baseline', ahora, expira)).toEqual({ expiresAt: expira });
    const real = retencionDeCorrida('prometheus-arc-baseline-v1', ahora, expira) as Record<
      string,
      unknown
    >;
    expect(real).not.toHaveProperty('expiresAt');
    expect(real.retenidoPor).toBe(MOTIVO_RETENCION_PARTIDA_REAL);
  });
});
