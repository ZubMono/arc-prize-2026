/* [arc-agi-runner/config.test] BL.20775 -- carga y validacion de config desde env.

   BL.21700 -- ESTE ARCHIVO CONSAGRABA EL BUG. `BASE_ENV` traia `MONGO_URL` y habia un caso
   "lanza si falta MONGO_URL": los tests describian con precision el comportamiento que estaba
   partiendo el corpus de ARC entre dos clusters, asi que arreglar el runner los ponia rojos. Se
   actualizan (no se rodean): la config obligatoria pasa a ser una de las DOS variables del ciclo
   ARC, y `MONGO_URL` deja de servir a proposito. */
import { describe, expect, it } from 'vitest';

import {
  defaultRunBatchId,
  diaDelBatch,
  loadConfig,
  RUNNER_ENV_VERSION,
  RUNNER_ENV_VERSION_HISTORY,
} from '../config';

const URL_PROD = 'mongodb://prod-cluster:27017/invierte';
const URL_DEV = 'mongodb://dev-cluster:27017/invierte';

const BASE_ENV = {
  ARC_API_KEY: 'test-key-123',
  PROMETHEUS_MONGO_URL: URL_PROD,
};

describe('loadConfig', () => {
  it('lanza si falta ARC_API_KEY', () => {
    expect(() => loadConfig({ PROMETHEUS_MONGO_URL: URL_PROD })).toThrow(/ARC_API_KEY/);
  });

  it('lanza -- nombrando las dos variables del ciclo -- si no hay ninguna URL de ARC', () => {
    expect(() => loadConfig({ ARC_API_KEY: 'x' })).toThrow(/ARC_RUNNER_MONGO_URL/);
    expect(() => loadConfig({ ARC_API_KEY: 'x' })).toThrow(/PROMETHEUS_MONGO_URL/);
  });

  it('con MONGO_URL sola NO arranca: no puede caer a dev en silencio (BL.21700)', () => {
    /* El caso exacto del incidente: quien invoca el runner a mano hereda MONGO_URL de
       .env.development. Antes eso alcanzaba para arrancar y escribir el corpus en el cluster
       equivocado; ahora es un fail-closed ruidoso. */
    expect(() => loadConfig({ ARC_API_KEY: 'x', MONGO_URL: URL_DEV })).toThrow(
      /ARC_RUNNER_MONGO_URL/,
    );
  });

  it('con MONGO_URL=dev y PROMETHEUS_MONGO_URL=prod resuelve PROD', () => {
    const cfg = loadConfig({ ...BASE_ENV, MONGO_URL: URL_DEV });
    expect(cfg.mongoUrl).toBe(URL_PROD);
  });

  it('ARC_RUNNER_MONGO_URL gana sobre PROMETHEUS_MONGO_URL y sobre MONGO_URL', () => {
    const cfg = loadConfig({
      ...BASE_ENV,
      MONGO_URL: URL_DEV,
      ARC_RUNNER_MONGO_URL: 'mongodb://descartable:27017/invierte',
    });
    expect(cfg.mongoUrl).toBe('mongodb://descartable:27017/invierte');
  });

  it('aplica defaults cuando no hay overrides', () => {
    const cfg = loadConfig(BASE_ENV);
    expect(cfg.arcApiKey).toBe('test-key-123');
    expect(cfg.mongoUrl).toBe(URL_PROD);
    expect(cfg.arcApiBaseUrl).toBe('https://three.arcprize.org');
    expect(cfg.modelId).toBe('prometheus-arc-baseline-v1');
    expect(cfg.gameTimeoutMs).toBe(30 * 60 * 1000);
    expect(cfg.stepTimeoutMs).toBe(60 * 1000);
    expect(cfg.maxApiFailures).toBe(3);
    // BL.21707: el batch id ya no es la fecha pelada -- arranca con ella y sigue con hora + sufijo.
    expect(cfg.runBatchId).toMatch(/^\d{4}-\d{2}-\d{2}T\d{6}\.\d{3}Z-[0-9a-f]{6}$/);
  });

  it('respeta overrides explicitos', () => {
    const cfg = loadConfig({
      ...BASE_ENV,
      ARC_API_BASE_URL: 'https://custom.example.com',
      ARC_RUNNER_MODEL_ID: 'mi-modelo',
      ARC_RUN_BATCH_ID: 'batch-fijo',
      ARC_GAME_TIMEOUT_MS: '1000',
      ARC_STEP_TIMEOUT_MS: '500',
      ARC_MAX_API_FAILURES: '5',
    });
    expect(cfg.arcApiBaseUrl).toBe('https://custom.example.com');
    expect(cfg.modelId).toBe('mi-modelo');
    expect(cfg.runBatchId).toBe('batch-fijo');
    expect(cfg.gameTimeoutMs).toBe(1000);
    expect(cfg.stepTimeoutMs).toBe(500);
    expect(cfg.maxApiFailures).toBe(5);
  });

  it('ignora overrides invalidos (no numericos o negativos) y cae al default', () => {
    const cfg = loadConfig({ ...BASE_ENV, ARC_GAME_TIMEOUT_MS: 'not-a-number' });
    expect(cfg.gameTimeoutMs).toBe(30 * 60 * 1000);
    const cfg2 = loadConfig({ ...BASE_ENV, ARC_MAX_API_FAILURES: '-1' });
    expect(cfg2.maxApiFailures).toBe(3);
  });

  it('RUNNER_ENV_VERSION es un semver valido (replayMetadata.envVersion)', () => {
    expect(RUNNER_ENV_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
  });
});

/* BL.21707 -- el runBatchId por default ERA la fecha UTC, asi que el runId
   `modelId:gameId:runBatchId` se repetia entre dos partidas del mismo juego en un mismo dia y la
   segunda pisaba a la primera en Mongo. Estos tests fijan las tres propiedades que tiene que
   cumplir el reemplazo: unico, ordenable por fecha, y con el dia recuperable como prefijo (que es
   lo que consultan el cron y el backstop de idempotencia). */
describe('defaultRunBatchId (unicidad por corrida, BL.21707)', () => {
  it('dos corridas del mismo modelo y juego EL MISMO DIA producen runIds distintos', () => {
    const cfgA = loadConfig(BASE_ENV);
    const cfgB = loadConfig(BASE_ENV);
    const runIdA = `${cfgA.modelId}:ar25-0c556536:${cfgA.runBatchId}`;
    const runIdB = `${cfgB.modelId}:ar25-0c556536:${cfgB.runBatchId}`;
    expect(runIdA).not.toBe(runIdB);
  });

  it('el sufijo aleatorio desempata aunque el reloj devuelva el MISMO milisegundo', () => {
    const instante = new Date('2026-08-18T14:22:33.456Z');
    const ids = new Set(Array.from({ length: 200 }, () => defaultRunBatchId(instante)));
    /* Con 6 hex (24 bits) y 200 muestras la probabilidad de colision es ~0,12%: se exige que la
       gran mayoria sean distintos sin volver el test flaky por el cumpleaños. */
    expect(ids.size).toBeGreaterThan(190);
  });

  it('no contiene ":" -- es el separador del runId y romperia cualquier split', () => {
    expect(defaultRunBatchId()).not.toContain(':');
  });

  it('ordena lexicograficamente = cronologicamente', () => {
    const temprano = defaultRunBatchId(new Date('2026-08-18T01:00:00.000Z'));
    const tarde = defaultRunBatchId(new Date('2026-08-18T23:00:00.000Z'));
    const otroDia = defaultRunBatchId(new Date('2026-08-19T00:00:00.000Z'));
    expect([otroDia, tarde, temprano].sort()).toEqual([temprano, tarde, otroDia]);
  });

  it('arranca con la fecha UTC del dia -- sigue siendo legible de un vistazo', () => {
    expect(defaultRunBatchId(new Date('2026-08-18T14:22:33.456Z'))).toMatch(/^2026-08-18T/);
  });
});

describe('diaDelBatch (prefijo estable del backstop de idempotencia)', () => {
  it('extrae el dia UTC del batch id por default', () => {
    expect(diaDelBatch('2026-08-18T142233.456Z-a1b2c3')).toBe('2026-08-18');
  });

  it('matchea tambien el formato VIEJO (fecha pelada), para no perder las corridas historicas', () => {
    expect(diaDelBatch('2026-08-17')).toBe('2026-08-17');
  });

  it('con un ARC_RUN_BATCH_ID explicito devuelve el batch entero: el prefijo es la corrida exacta', () => {
    /* Fijar el batch a mano es la forma de pedir "reintenta ESTA corrida"; achicar el prefijo al
       dia haria que un reintento explicito se saltease por una corrida ajena del mismo dia. */
    expect(diaDelBatch('batch-fijo')).toBe('batch-fijo');
    expect(diaDelBatch('sonda-25-juegos')).toBe('sonda-25-juegos');
  });

  it('el prefijo del default es prefijo REAL del runBatchId (el regex del cron depende de eso)', () => {
    const batch = defaultRunBatchId();
    expect(batch.startsWith(diaDelBatch(batch))).toBe(true);
  });
});

/* BL.21024 -- `RUNNER_ENV_VERSION` quedo en '1.0.0' durante tres cambios de comportamiento del
   agente (BL.20860 reemplazo la politica RANDOM por planificacion; BL.20861 la cambio dos veces
   mas). Las corridas de ambas generaciones quedaron con el MISMO envVersion, asi que un replay no
   permite saber cual las produjo -- exactamente lo que la constante existia para evitar. El drift
   fue silencioso porque nada lo verificaba: el unico test miraba el FORMATO, no si el valor seguia
   describiendo al agente actual. Estos tests atan la version a un historial explicito, para que
   subirla obligue a decir que cambio y agregar una entrada obligue a subirla. */
describe('RUNNER_ENV_VERSION_HISTORY (anti-drift, BL.21024)', () => {
  it('la version vigente esta descrita en el historial', () => {
    expect(Object.keys(RUNNER_ENV_VERSION_HISTORY)).toContain(RUNNER_ENV_VERSION);
  });

  it('la version vigente es la MAS ALTA del historial -- nadie puede documentar un cambio sin subirla', () => {
    const ordenadas = Object.keys(RUNNER_ENV_VERSION_HISTORY).sort((a, b) => {
      const [ma, mia, pa] = a.split('.').map(Number);
      const [mb, mib, pb] = b.split('.').map(Number);
      return ma - mb || mia - mib || pa - pb;
    });
    expect(ordenadas[ordenadas.length - 1]).toBe(RUNNER_ENV_VERSION);
  });

  it('cada entrada del historial explica el comportamiento, no solo el numero', () => {
    for (const [version, descripcion] of Object.entries(RUNNER_ENV_VERSION_HISTORY)) {
      expect(version).toMatch(/^\d+\.\d+\.\d+$/);
      /* Un texto corto no sirve para interpretar un replay viejo: se exige una descripcion real y
         que cite el BL que introdujo el cambio. */
      expect(descripcion.length).toBeGreaterThan(40);
      expect(descripcion).toMatch(/BL\.\d+/);
    }
  });
});
