/* [arc-agi-runner] BL.20775 -- entrypoint del runner: agente baseline que juega los juegos
   publicos ARC-AGI-3 contra la API oficial y persiste scorecards + steps en la coleccion Mongo
   `prometheusEvaluationRuns` (contrato definido en packages/api/prometheusEvaluationRuns,
   BL.20774 -- ver el mirror de tipos en ./types.ts).

   Flujo: abrir UN scorecard para todo el batch -> por cada juego publico (o el subset de
   ARC_RUNNER_GAME_IDS) chequear idempotencia por runId -> jugar -> persistir resultado -> al
   terminar (o ante crash) cerrar el scorecard. `runBatch` es la funcion orquestadora, exportada e
   inyectable (client/store) para poder testearse sin red ni Mongo reales -- `main()` es el unico
   punto que arma las dependencias reales. */

import type { ActivityMemoryDocLike } from './activityMemorySeed';
import { createActivityMemoryStore, type ActivityMemoryStore } from './activityMemoryStore';
import { createArcApiClient } from './arcApiClient';
import type { ArcApiClient } from './arcApiClient';
import { type ArcRunnerConfig, diaDelBatch, loadConfig, RUNNER_ENV_VERSION } from './config';
import { registerCrashHandlers } from './crashGuard';
import { createDeadLetterTracker } from './deadLetterTracker';
import { createEvaluationRunStore, type EvaluationRunStore } from './evaluationRunStore';
import { runGame } from './gameRunner';
import { computeRunScore, formatBatchLevelSummary } from './levelProgress';
import { closeArcRunnerMongoClient, getArcRunnerMongoClient } from './mongoClient';
import { retencionDeCorrida } from './politicaDeRetencion';
import { generateSeed } from './prng';
import { createReplayFrameStore, type ReplayCapture } from './replayFrameStore';
import type {
  ArcEvaluationRun,
  ArcEvaluationRunStatus,
  ArcGameSummary,
  ArcReplayFrame,
} from './types';

/* Mirror puro de prometheusEvaluationRuns/archivePolicy.ts::computeRunExpiryDate (BL.20774) --
   mismo limite de aislamiento que el mirror de tipos en ./types.ts: este proyecto no importa
   packages/api, asi que reimplementa la formula (trivial: fecha + dias en ms). Si la politica de
   retencion privada cambia, actualizar RETENTION_DAYS aca a mano.

   BL.21749 -- SE CALCULA AL ABRIR LA PARTIDA, no al cerrarla. La politica privada define
   `expiresAt = completedAt + 90 dias`, y aca se usa `startedAt`: la diferencia es la duracion de
   una partida (tope duro 30 min, `ARC_GAME_TIMEOUT_MS`) sobre un horizonte de 90 dias, o sea
   0,02%. A cambio, la fecha viaja en el MISMO insert que crea el documento y por lo tanto puede ir
   en `$setOnInsert` (ver `evaluationRunStore.ts::CAMPOS_SOLO_AL_CREAR`): un solo `updateOne`
   atomico, ningun upsert posterior puede reescribirla, y no existe el estado intermedio "corrida
   cerrada sin fecha y sin marca" que un crash entre dos escrituras dejaba antes. */
const RETENTION_DAYS = 90;

function computeExpiryDate(iniciadaEn: Date, retentionDays: number = RETENTION_DAYS): Date {
  return new Date(iniciadaEn.getTime() + retentionDays * 24 * 60 * 60 * 1000);
}

export interface RunBatchDeps {
  config: ArcRunnerConfig;
  client: Pick<ArcApiClient, 'openScorecard' | 'closeScorecard' | 'sendCommand' | 'listGames'>;
  store: EvaluationRunStore;
  /** BL.20861 -- memoria que persiste entre corridas. Opcional a proposito: el batch debe poder
   *  correr sin ella (arranque frio) igual que antes de que existiera. */
  memory?: ActivityMemoryStore;
  /** Override de la lista de juegos -- default: client.listGames() (los 25 juegos publicos). */
  gameIds?: string[];
  /** Inyectable para tests: funcion de salida del crash guard (default: process.exit real). */
  crashExit?: (code: number) => void;
  /** BL.21557 -- fabrica del sink de captura del corpus de replay, UNA por partida (el runId cambia
   *  con el juego). Ausente = sin captura: el batch corre igual que antes, que es lo que debe pasar
   *  cuando no hay Mongo o la captura esta apagada por env. */
  createCapture?: (ctx: { runId: string; gameId: string; modelId: string }) => ReplayCapture;
}

export interface RunBatchResult {
  cardId: string;
  results: ArcEvaluationRun[];
}

/** Cierra un run activo como consecuencia de un crash -- GAME_OVER registrado, nunca queda
 *  huerfano en 'running'. */
async function closeRunAsCrashed(
  store: EvaluationRunStore,
  run: ArcEvaluationRun,
  reason: string,
): Promise<void> {
  const completedAt = new Date();
  /* `expiresAt` / las marcas de retencion NO se recalculan aca: viajan en `...run` desde que la
     corrida se abrio y el writer solo las escribe al INSERTAR. Un cierre por crash no puede
     cambiar si una partida caduca o no. */
  await store.upsertRun({
    ...run,
    status: 'failed',
    result: {
      success: false,
      score: 0,
      error: `Proceso interrumpido (${reason}) -- cierre forzado, GAME_OVER registrado.`,
    },
    completedAt,
  });
}

interface PlayOneGameOptions {
  config: ArcRunnerConfig;
  client: RunBatchDeps['client'];
  store: EvaluationRunStore;
  game: ArcGameSummary;
  cardId: string;
  setActive: (run: ArcEvaluationRun | null) => void;
  /** BL.20861 -- ausente cuando no hay Mongo de memoria disponible: el batch corre igual, en frio. */
  memory?: ActivityMemoryStore;
  /** BL.21557 -- ver RunBatchDeps.createCapture. */
  createCapture?: RunBatchDeps['createCapture'];
}

async function playOneGame(opts: PlayOneGameOptions): Promise<ArcEvaluationRun> {
  const { config, client, store, game, cardId, setActive, memory } = opts;
  const runId = `${config.modelId}:${game.game_id}:${config.runBatchId}`;

  /* BL.21707 -- el backstop de idempotencia NO puede mirar el runId exacto: desde este BL el
     runBatchId es unico por corrida, asi que un proceso nuevo nunca coincidiria consigo mismo y el
     skip quedaria muerto en silencio. Se busca por el prefijo estable
     `modelId:gameId:diaDelBatch`, que es la pregunta que el skip siempre quiso hacer ("¿este
     modelo ya completo este juego en este batch?") y la que protege del solapamiento de dos ticks
     del cron. Con un ARC_RUN_BATCH_ID explicito el prefijo es la corrida exacta: reintentar sigue
     siendo idempotente. */
  const prefijoIdempotencia = `${config.modelId}:${game.game_id}:${diaDelBatch(config.runBatchId)}`;
  const yaCompletada = await store.findCompletedByPrefix(prefijoIdempotencia);
  if (yaCompletada) {
    console.warn(
      `[arc-agi-runner] ${prefijoIdempotencia} ya completado en ${yaCompletada.runId} -- skip (idempotencia).`,
    );
    return yaCompletada;
  }

  const seed = generateSeed();
  const startedAt = new Date();
  const initialRun: ArcEvaluationRun = {
    runId,
    modelId: config.modelId,
    environmentId: game.game_id,
    status: 'running',
    steps: [],
    result: { success: false, score: 0 },
    replayMetadata: { seed, envVersion: RUNNER_ENV_VERSION },
    startedAt,
    createdAt: startedAt,
    /* BL.21749 -- LA RETENCION SE DECIDE AL NACER. Una partida contra la API oficial
       (`prometheus-arc-baseline-v1`) nace RETENIDA: sin `expiresAt` y con `retenidoPor`. Las demas
       nacen con su fecha de purga. Antes toda corrida nacia con fecha de muerte y sin marca, y el
       cron horario re-armaba la bomba que este BL habia desactivado a mano. */
    ...retencionDeCorrida(config.modelId, startedAt, computeExpiryDate(startedAt)),
  };
  await store.upsertRun(initialRun);
  setActive(initialRun);

  /* La memoria se lee por ACTIVIDAD (game_id), no por runId: lo aprendido en la corrida de ayer
     sobre este juego es exactamente lo que debe informar la de hoy. */
  const memorySeed = await memory?.loadSeed(game.game_id);

  const deadLetter = createDeadLetterTracker(config.maxApiFailures);
  /* BL.21557 -- el sink se crea (y se cierra) por PARTIDA: su presupuesto de 1MB y su buffer son
     por runId, y una fabrica compartida entre juegos mezclaria ambos. */
  const capture = opts.createCapture?.({
    runId,
    gameId: game.game_id,
    modelId: config.modelId,
  });
  let gameResult;
  try {
    gameResult = await runGame({
      client,
      cardId,
      gameId: game.game_id,
      seed,
      gameTimeoutMs: config.gameTimeoutMs,
      deadLetter,
      memorySeed,
      ...(capture ? { capture } : {}),
    });
  } finally {
    /* Se vacia SIEMPRE, incluso si la partida murio por excepcion: lo capturado hasta ese punto es
       justamente el corpus del fallo, que es el mas caro de reproducir. `flush` no lanza. */
    await capture?.flush();
  }
  if (capture) {
    const { framesEscritos, bytesEstimados, presupuestoAgotado, errores } = capture.stats();
    console.warn(
      `[arc-agi-runner] corpus de replay ${game.game_id}: ${framesEscritos} frame(s) escrito(s), ` +
        `~${bytesEstimados} byte(s)${presupuestoAgotado ? ' (presupuesto agotado, captura detenida)' : ''}` +
        `${errores > 0 ? `, ${errores} error(es) de escritura` : ''}.`,
    );
  }

  const { nonOpStates, transitions, planLength } = gameResult.seedSummary;
  // BL.21499: cuando la semilla viene vacia hay que decir POR QUE. Antes los tres casos se
  // reportaban como "en frio" y eran indistinguibles desde el log, que es lo que oculto durante
  // una semana que el destilador nunca proceso una corrida de ARC: cada partida parecia ser la
  // primera. Si no hay Mongo de memoria (`memory` ausente) tampoco es "primera vez" -- es que
  // el runner corrio sin memoria conectada.
  let arranque: string;
  if (planLength > 0 || nonOpStates > 0 || transitions > 0) {
    arranque =
      `plan de ${planLength} paso(s), ${nonOpStates} estado(s) con no-ops conocidos, ` +
      `${transitions} transicion(es) sembradas.`;
  } else if (!memorySeed) {
    arranque = 'en frio -- SIN memoria conectada (no hay Mongo de memoria disponible).';
  } else if (memorySeed.sinDocumento) {
    arranque = 'en frio -- primera corrida de esta actividad (normal, no es un error).';
  } else {
    arranque =
      'en frio pese a EXISTIR memoria de esta actividad: el documento no aporto nada ' +
      'utilizable. Sintoma tipico de que el ciclo de destilacion no esta corriendo sobre ' +
      'estas corridas -- revisar antes de asumir que el agente empieza de cero.';
  }
  const { maxLevelsCompleted, winLevels } = gameResult.levelProgress;
  console.warn(
    `[arc-agi-runner] ${game.game_id}: ${gameResult.steps.length} accion(es), ` +
      `estado final ${gameResult.finalState}, nivel maximo alcanzado ${maxLevelsCompleted}` +
      `${winLevels > 0 ? ` de ${winLevels}` : ' (el juego no informo el total de niveles)'}. ` +
      `Arranque: ${arranque}`,
  );

  let status: ArcEvaluationRunStatus;
  let success = false;
  let error: string | undefined;

  if (gameResult.finalState === 'WIN') {
    status = 'completed';
    success = true;
  } else if (gameResult.timedOut) {
    status = 'failed';
    error = `Timeout duro de ${config.gameTimeoutMs}ms alcanzado sin que el juego terminara.`;
  } else if (gameResult.deadLettered) {
    status = 'failed';
    error = gameResult.error ?? 'Dead-letter: fallas de API consecutivas superaron el tope.';
  } else if (gameResult.error) {
    status = 'failed';
    error = gameResult.error;
  } else {
    // GAME_OVER "normal": el agente perdio, pero la evaluacion SI corrio hasta el final -- es un
    // resultado valido, no una falla de infraestructura.
    status = 'completed';
  }

  /* BL.21557 -- score ENTERO con credito parcial (niveles superados), no el 0/1 de BL.20775. Antes
     de este BL las 11 corridas acumuladas valian todas 0 y era imposible saber si una version del
     agente era mejor que otra; el leaderboard oficial puntua exactamente asi (submission.parquet
     tiene `score` entero). Una derrota que llego al nivel 3 ahora vale 3 y ordena el ranking. */
  const score = computeRunScore(gameResult.levelProgress, success);

  const completedAt = new Date();
  const finalRun: ArcEvaluationRun = {
    ...initialRun,
    status,
    steps: gameResult.steps,
    result: {
      success,
      score,
      maxLevelReached: gameResult.levelProgress.maxLevelsCompleted,
      winLevels: gameResult.levelProgress.winLevels,
      ...(error ? { error } : {}),
    },
    completedAt,
    // `expiresAt` y las marcas vienen de `initialRun` (`...initialRun` arriba): se fijaron al abrir.
  };
  await store.upsertRun(finalRun);
  setActive(null);
  return finalRun;
}

/** Orquesta un batch completo: abre UN scorecard, juega cada juego (secuencial) y lo cierra al
 *  terminar -- o ante crash, via crashGuard. Inyectable/testeable sin red ni Mongo reales. */
export async function runBatch(deps: RunBatchDeps): Promise<RunBatchResult> {
  const { config, client, store, memory } = deps;

  const cardId = await client.openScorecard({
    tags: ['prometheus-benchmark-vivo', 'arc-agi-3', config.modelId],
    opaque: { runBatchId: config.runBatchId, envVersion: RUNNER_ENV_VERSION },
  });

  let active: ArcEvaluationRun | null = null;
  const setActive = (run: ArcEvaluationRun | null): void => {
    active = run;
  };

  const unregisterCrashGuard = registerCrashHandlers(
    async (reason: string) => {
      if (active) {
        await closeRunAsCrashed(store, active, reason);
      }
      await client.closeScorecard(cardId).catch((err) => {
        console.error('[arc-agi-runner] no se pudo cerrar el scorecard tras crash:', err);
      });
    },
    deps.crashExit ? { exit: deps.crashExit } : undefined,
  );

  try {
    const games: ArcGameSummary[] = deps.gameIds
      ? deps.gameIds.map((gameId) => ({ game_id: gameId, title: gameId }))
      : await client.listGames();

    const results: ArcEvaluationRun[] = [];
    for (const game of games) {
      results.push(
        await playOneGame({
          config,
          client,
          store,
          game,
          cardId,
          setActive,
          memory,
          ...(deps.createCapture ? { createCapture: deps.createCapture } : {}),
        }),
      );
    }
    /* BL.21557 -- el batch se cierra diciendo cuanto progreso hubo, no solo cuantos juegos se
       ganaron: con score binario todos los batches se veian identicos (0 victorias) y no habia
       forma de detectar una mejora del agente sin ganar una partida entera. */
    console.warn(`[arc-agi-runner] ${formatBatchLevelSummary(results)}`);
    return { cardId, results };
  } finally {
    unregisterCrashGuard();
    await client.closeScorecard(cardId).catch((err) => {
      console.error('[arc-agi-runner] error cerrando scorecard al final del batch:', err);
    });
  }
}

async function main(): Promise<void> {
  const config = loadConfig();
  const client = createArcApiClient({
    apiKey: config.arcApiKey,
    baseUrl: config.arcApiBaseUrl,
    stepTimeoutMs: config.stepTimeoutMs,
  });

  const mongoClient = await getArcRunnerMongoClient(config.mongoUrl);
  const collection = mongoClient.db().collection<ArcEvaluationRun>('prometheusEvaluationRuns');
  const store = createEvaluationRunStore(collection);
  const memory = createActivityMemoryStore(
    mongoClient.db().collection<ActivityMemoryDocLike>('prometheusActivityMemory'),
    (msg) => console.warn(`[arc-agi-runner] ${msg}`),
  );

  const gameIdsOverride = process.env.ARC_RUNNER_GAME_IDS?.split(',')
    .map((s) => s.trim())
    .filter(Boolean);

  /* BL.21557 -- MODO CAPTURA encendido por default. Va al reves de lo habitual a proposito: el BL
     nace de que durante 11 corridas no se guardo nada y nadie se entero, y una captura apagada por
     default es exactamente esa misma ceguera con otro nombre. Apagarla es explicito
     (`ARC_REPLAY_CAPTURE=0`) y el presupuesto de 1MB por partida acota el costo. */
  const capturaActiva = (process.env.ARC_REPLAY_CAPTURE ?? '1').trim() !== '0';
  const replayFrames = mongoClient.db().collection<ArcReplayFrame>('arcReplayFrames');

  const { cardId, results } = await runBatch({
    config,
    client,
    store,
    memory,
    gameIds: gameIdsOverride && gameIdsOverride.length > 0 ? gameIdsOverride : undefined,
    ...(capturaActiva
      ? {
          createCapture: (ctx: { runId: string; gameId: string; modelId: string }) =>
            createReplayFrameStore(replayFrames, ctx),
        }
      : {}),
  });

  const wins = results.filter((r) => r.result.success).length;

  console.warn(
    `[arc-agi-runner] scorecard ${cardId} cerrado -- ${results.length} juegos, ${wins} ganados.`,
  );

  await closeArcRunnerMongoClient(config.mongoUrl);
}

if (require.main === module) {
  main().catch((err) => {
    console.error('[arc-agi-runner] error fatal:', err);
    process.exitCode = 1;
  });
}
