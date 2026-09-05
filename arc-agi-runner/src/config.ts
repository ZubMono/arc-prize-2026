/* [arc-agi-runner/config] BL.20775 -- carga y validacion de configuracion desde variables de
   entorno. Sin dependencias del monorepo privado (aislamiento critico -- ver CLAUDE.md). */

import { randomBytes } from 'node:crypto';

import { mensajeSinUrlArc, resolverArcMongoUrl } from './arcMongoUrl';

export interface ArcRunnerConfig {
  /** Clave de la API oficial ARC-AGI-3 (https://three.arcprize.org/api-keys). */
  arcApiKey: string;
  /** Host base de la API. Override solo para tests/entornos alternativos. */
  arcApiBaseUrl: string;
  /** Identificador del agente que juega -- aparece en prometheusEvaluationRuns.modelId. */
  modelId: string;
  /** Identifica UNIVOCAMENTE a esta corrida (runId = modelId:gameId:runBatchId).
   *  BL.21707: el default incluye hora, milisegundos y un sufijo aleatorio -- ver
   *  `defaultRunBatchId`. Solo un `ARC_RUN_BATCH_ID` explicito lo vuelve compartible entre
   *  procesos, que es la unica forma de pedir "reintenta ESTA corrida" en vez de "corre una nueva". */
  runBatchId: string;
  /** URI de MongoDB donde vive prometheusEvaluationRuns.
   *  BL.21700: resuelta por `arcMongoUrl.ts` (ARC_RUNNER_MONGO_URL -> PROMETHEUS_MONGO_URL),
   *  NUNCA por MONGO_URL. */
  mongoUrl: string;
  /** Tope duro por juego (ms). Diseno: 30 minutos. */
  gameTimeoutMs: number;
  /** Tope duro por step/llamada HTTP (ms). Diseno: 60 segundos. */
  stepTimeoutMs: number;
  /** Fallas de API consecutivas antes de marcar un juego como dead-letter. Diseno: 3. */
  maxApiFailures: number;
}

/** Historial de versiones del CONTRATO de esta integracion. Existe para que la constante de abajo
 *  no pueda subirse (ni quedarse quieta) sin dejar dicho QUE cambio: un `envVersion` sin semantica
 *  no sirve para interpretar un replay viejo, que es su unica razon de ser.
 *
 *  La clave es la version; el valor, el comportamiento del agente que produjo esas corridas. */
export const RUNNER_ENV_VERSION_HISTORY: Readonly<Record<string, string>> = Object.freeze({
  '1.0.0':
    'BL.20775 -- agente baseline: elige al azar (PRNG semillado) entre las acciones disponibles. ' +
    'Sin percepcion de grilla ni planificacion.',
  '2.0.0':
    'BL.20860 + BL.20861 -- planificacion sobre modelo de mundo aprendido reemplaza la politica ' +
    'RANDOM: firmas de estado, memoria de transiciones, sintesis de programas con presupuesto y ' +
    'consumo de la memoria destilada entre corridas.',
});

/** Version pineada de ESTE runner/adaptador -- se persiste en replayMetadata.envVersion.
 *  ARC-AGI-3 no expone un semver propio por juego publico (el game_id ya incluye un hash de
 *  version); este valor versiona el CONTRATO de nuestra integracion (politica del agente baseline,
 *  formato de persistencia), no el juego en si. Subir esta constante en cada cambio de
 *  comportamiento del baseline agent para que los replays viejos sigan siendo interpretables.
 *
 *  BL.21024 (2026-08-10): estuvo en '1.0.0' desde el commit del MVP pese a que BL.20860 reemplazo
 *  la politica RANDOM por planificacion sobre modelo de mundo y BL.20861 la cambio dos veces mas.
 *  Consecuencia: las corridas de ambas generaciones de agente quedaron persistidas con el MISMO
 *  envVersion, y un replay no permite saber cual las produjo -- justo lo que la constante existia
 *  para evitar. Se sube a '2.0.0' (cambio de comportamiento incompatible) y se agrega el historial
 *  de arriba + un test que obliga a que ambos se muevan juntos. */
export const RUNNER_ENV_VERSION = '2.0.0';

const DEFAULT_ARC_API_BASE_URL = 'https://three.arcprize.org';
const DEFAULT_MODEL_ID = 'prometheus-arc-baseline-v1';
const DEFAULT_GAME_TIMEOUT_MS = 30 * 60 * 1000;
const DEFAULT_STEP_TIMEOUT_MS = 60 * 1000;
const DEFAULT_MAX_API_FAILURES = 3;

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/** Sufijo aleatorio corto del batch id. `node:crypto` es la unica dependencia nueva y ya la usa
 *  `prng.ts` (misma frontera de aislamiento). Existe para el caso en que dos procesos arranquen
 *  en el MISMO milisegundo -- el cron y una corrida manual, por ejemplo. */
function sufijoAleatorio(): string {
  return randomBytes(3).toString('hex');
}

/** Batch id default: UNICO POR CORRIDA, legible y ordenable por fecha (BL.21707).
 *
 *  ANTES era la fecha UTC pelada (`2026-08-18`), asi que el runId `modelId:gameId:fecha` NO era
 *  unico: la segunda partida del mismo modelo sobre el mismo juego en un mismo dia reusaba el
 *  runId de la primera y el writer -- que hacia `$set` del doc entero -- la PISABA sin error ni
 *  aviso. Se detecto con la colision real
 *  `prometheus-arc-baseline-v1:ar25-0c556536:2026-08-17`, dos partidas distintas contra la API
 *  oficial compartiendo identidad. Cada partida cuesta presupuesto y no se puede recuperar.
 *
 *  FORMA `2026-08-18T142233.456Z-a1b2c3`, elegida asi y no de otra manera:
 *   - arranca con el `YYYY-MM-DD` de siempre, que es lo que hace legible el runId de un vistazo y
 *     lo que consultan por prefijo el cron (juegos completados hoy) y el backstop de idempotencia;
 *   - el resto es ISO-8601 sin los `:` -- los dos puntos son EL separador del runId, meterlos
 *     adentro de un segmento romperia cualquier `split(':')`;
 *   - ordena lexicograficamente = cronologicamente, igual que antes;
 *   - el sufijo aleatorio cubre el empate al milisegundo entre dos procesos. */
export function defaultRunBatchId(ahora: Date = new Date()): string {
  const iso = ahora.toISOString().replace(/:/g, '');
  return `${iso}-${sufijoAleatorio()}`;
}

/** Dia UTC del batch -- la parte ESTABLE del `runBatchId`, usada como prefijo del backstop de
 *  idempotencia del runner (`index.ts`: "este modelo ya completo este juego hoy").
 *
 *  Con un `ARC_RUN_BATCH_ID` explicito no hay dia que extraer y se devuelve el batch id entero: el
 *  prefijo pasa a ser la corrida exacta, que es justo lo que pide quien fija el batch a mano
 *  (reintentar ESA corrida). Con el default, devuelve `YYYY-MM-DD` y el backstop conserva la
 *  semantica historica -- ademas de seguir matcheando los runIds viejos, cuyo tercer segmento ERA
 *  exactamente esa fecha. */
export function diaDelBatch(runBatchId: string): string {
  return /^\d{4}-\d{2}-\d{2}/.exec(runBatchId)?.[0] ?? runBatchId;
}

/** Carga y valida la config del runner desde `env` (default: process.env). Falla ruidoso ante
 *  variables obligatorias faltantes -- nunca arranca a jugar con config incompleta. */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): ArcRunnerConfig {
  const arcApiKey = env.ARC_API_KEY?.trim();
  if (!arcApiKey) {
    throw new Error(
      '[arc-agi-runner/config] ARC_API_KEY es obligatoria -- generar una en ' +
        'https://three.arcprize.org/api-keys y configurarla en .env/.env.<entorno> (accion humana, ' +
        'no generable en sesion).',
    );
  }

  /* BL.21700 -- fail-closed y NUNCA fallback a MONGO_URL. Que el runner cayera a MONGO_URL es lo
     que partio el corpus entre los dos clusters: quien lo invoca a mano hereda la de
     .env.development y escribia en DEV mientras todos los lectores miraban PROD. Sin una de las
     dos variables del ciclo no arranca -- escribir "en algun lado" es peor que no escribir. */
  const mongoUrl = resolverArcMongoUrl(env);
  if (!mongoUrl) {
    throw new Error(
      mensajeSinUrlArc('el runner persiste las corridas en prometheusEvaluationRuns'),
    );
  }

  return {
    arcApiKey,
    mongoUrl,
    arcApiBaseUrl: env.ARC_API_BASE_URL?.trim() || DEFAULT_ARC_API_BASE_URL,
    modelId: env.ARC_RUNNER_MODEL_ID?.trim() || DEFAULT_MODEL_ID,
    runBatchId: env.ARC_RUN_BATCH_ID?.trim() || defaultRunBatchId(),
    gameTimeoutMs: parsePositiveInt(env.ARC_GAME_TIMEOUT_MS, DEFAULT_GAME_TIMEOUT_MS),
    stepTimeoutMs: parsePositiveInt(env.ARC_STEP_TIMEOUT_MS, DEFAULT_STEP_TIMEOUT_MS),
    maxApiFailures: parsePositiveInt(env.ARC_MAX_API_FAILURES, DEFAULT_MAX_API_FAILURES),
  };
}
