/* [arc-agi-runner/gameRunner] BL.20775 -- orquesta UN juego publico ARC-AGI-3: RESET -> loop de
   ACTIONs hasta WIN/GAME_OVER, tope duro de 30 min (diseno) via deadline inyectable (`now`), y
   dead-letter tras N fallas de API consecutivas (deadLetter inyectado -- diseno: 3). El tope de
   60s por step vive en arcApiClient (AbortSignal.timeout por llamada); este modulo solo vigila
   el presupuesto TOTAL del juego.

   Politica de decision (BL.20860, wave 2 de BL.20858): IntelligentPolicy reemplaza la eleccion
   uniforme al azar de baselineAgent.ts (BL.20775, ahora solo referencia/baseline de comparacion,
   ver worldModel/__tests__/intelligentPolicy.syntheticEnv.test.ts) por planificacion sobre un
   modelo de mundo aprendido durante la partida -- el scoring de ARC-AGI-3 penaliza
   CUADRATICAMENTE cada accion de mas, asi que reducir intentos importa. */

import type { ActivityMemorySeed } from './activityMemorySeed';
import type { DeadLetterTracker } from './deadLetterTracker';
import {
  accumulateLevelProgress,
  EMPTY_LEVEL_PROGRESS,
  readFrameLevels,
  type LevelProgress,
} from './levelProgress';
import { createSeededRandom } from './prng';
import type { ReplayCapture } from './replayFrameStore';
import type { ArcAction, ArcActionState, ArcEvaluationStep, ArcFrameResponse } from './types';
import type { VolatilityMask } from './worldModel/grid';
import { IntelligentPolicy } from './worldModel/intelligentPolicy';
import { computeFrameSignature, extractGrid } from './worldModel/stateSignature';

/** Tope de seguridad de steps -- red adicional independiente del deadline de tiempo: un juego que
 *  reporta NOT_FINISHED indefinidamente pero responde rapido no debe loopear para siempre. */
const DEFAULT_MAX_STEPS = 500;

export interface GameRunnerClient {
  sendCommand(
    action: ArcAction,
    body: {
      game_id: string;
      card_id?: string;
      guid?: string | null;
      x?: number;
      y?: number;
      reasoning?: Record<string, unknown>;
    },
  ): Promise<ArcFrameResponse>;
}

export interface RunGameOptions {
  client: GameRunnerClient;
  cardId: string;
  gameId: string;
  seed: string;
  gameTimeoutMs: number;
  deadLetter: DeadLetterTracker;
  maxSteps?: number;
  /** Reloj inyectable -- tests controlan el paso del tiempo sin esperas reales. */
  now?: () => number;
  /** BL.20861 -- conocimiento destilado de corridas anteriores sobre este mismo juego. Ausente =
   *  arranque en frio (primera corrida de la actividad: el caso NORMAL, no un error). */
  memorySeed?: ActivityMemorySeed;
  /** BL.21557 -- MODO CAPTURA del corpus de replay. Ausente = no se captura nada y el runner se
   *  comporta exactamente como antes; presente = cada paso se persiste en `arcReplayFrames` con
   *  coordenadas, diff RLE y acciones disponibles. Nunca puede hacer fallar la partida (el sink
   *  atrapa sus propios errores, ver replayFrameStore.ts). */
  capture?: ReplayCapture;
}

export interface GameRunResult {
  finalState: ArcActionState;
  steps: ArcEvaluationStep[];
  timedOut: boolean;
  deadLettered: boolean;
  error?: string;
  /** Que sabia la politica antes de la primera accion -- se loguea para poder comparar corrida a
   *  corrida si la mejora vino de la memoria y no del azar de la semilla del PRNG. */
  seedSummary: { nonOpStates: number; transitions: number; planLength: number };
  /** BL.21557 -- SENAL DENSA: nivel maximo alcanzado + niveles totales del juego. Es lo que
   *  convierte una derrota en un dato comparable en vez de un 0 indistinguible de todos los otros. */
  levelProgress: LevelProgress;
}

/** Frames que originaron cada step, en el MISMO indice que `GameRunResult.steps`. Se retienen para
 *  poder re-firmar al cerrar la partida (ver `refirmarConMascaraFinal`). */
interface FramesDelStep {
  before?: ArcFrameResponse;
  after: ArcFrameResponse;
}

/** BL.21558 -- reemplaza las firmas de TODOS los steps por las que produce la mascara de
 *  volatilidad FINAL del episodio.
 *
 *  Por que al final y no en vivo: la mascara se aprende sobre la marcha (worldModel/
 *  volatilityMask.ts), asi que los primeros steps se firmarian sin ella y los ultimos con ella --
 *  dos definiciones de "estado" mezcladas en la misma corrida, y el distilador
 *  (packages/api/prometheusActivityMemory) compararia peras con manzanas. Con una sola pasada al
 *  cerrar, los `stateSignatureBefore/After` persistidos son homogeneos entre si y comparables
 *  contra los de la corrida siguiente, que converge a la misma mascara porque el HUD del juego es
 *  el mismo. Sin esto, la mitad util de BL.21558 (que el `memorySeed` pueda disparar fuera del
 *  estado post-RESET) no llegaria a Mongo.
 *
 *  El corpus de replay (BL.21557, `arcReplayFrames`) NO se re-firma: sus documentos ya se
 *  flushearon a Mongo durante la partida. No hace falta -- guarda las grillas completas, asi que
 *  cualquier consumidor puede recalcular la firma enmascarada que quiera desde el dato crudo. */
function refirmarConMascaraFinal(
  steps: ArcEvaluationStep[],
  registro: FramesDelStep[],
  mask: VolatilityMask | null,
): void {
  if (mask === null) return;
  for (let i = 0; i < steps.length; i++) {
    const frames = registro[i];
    if (frames === undefined) continue;
    steps[i].stateSignatureAfter = computeFrameSignature(frames.after, mask);
    if (frames.before !== undefined) {
      steps[i].stateSignatureBefore = computeFrameSignature(frames.before, mask);
    }
  }
}

export async function runGame(opts: RunGameOptions): Promise<GameRunResult> {
  const registro: FramesDelStep[] = [];
  const { result, policy } = await jugarPartida(opts, registro);
  refirmarConMascaraFinal(result.steps, registro, policy.volatilityMask());
  return result;
}

async function jugarPartida(
  opts: RunGameOptions,
  registro: FramesDelStep[],
): Promise<{ result: GameRunResult; policy: IntelligentPolicy }> {
  const now = opts.now ?? Date.now;
  const deadline = now() + opts.gameTimeoutMs;
  const maxSteps = opts.maxSteps ?? DEFAULT_MAX_STEPS;
  const rng = createSeededRandom(opts.seed);
  const steps: ArcEvaluationStep[] = [];
  // Sin goalGrid: la grilla de WIN de cada juego real no se conoce de antemano -- la politica
  // opera en modo exploracion informada (modelo de mundo + active learning), ver
  // worldModel/intelligentPolicy.ts. actionBudget acota la profundidad de planificacion si en el
  // futuro se inyecta un goalGrid (ej. sub-objetivos detectados) sin requerir otro cambio aca.
  const policy = new IntelligentPolicy({
    rng,
    actionBudget: maxSteps,
    memorySeed: opts.memorySeed,
  });
  const seedSummary = policy.seedSummary();
  /* BL.21557 -- se acumula a lo largo de TODA la partida y sobrevive al final: el frame terminal de
     un GAME_OVER puede traer el contador ya en cero, y quedarse con el ultimo valor en vez del
     maximo tiraria a la basura justamente el credito parcial que este BL viene a rescatar. */
  let levelProgress: LevelProgress = EMPTY_LEVEL_PROGRESS;

  let frame: ArcFrameResponse;
  try {
    frame = await opts.client.sendCommand('RESET', {
      game_id: opts.gameId,
      card_id: opts.cardId,
    });
    opts.deadLetter.recordSuccess();
  } catch (err) {
    const deadLettered = opts.deadLetter.recordFailure();
    return {
      policy,
      result: {
        finalState: 'GAME_OVER',
        steps,
        timedOut: false,
        deadLettered,
        seedSummary,
        levelProgress,
        error: String(err instanceof Error ? err.message : err),
      },
    };
  }

  let guid: string | undefined = frame.guid;
  let stepNum = 0;
  /* BL.20861 -- firma perceptual del estado, persistida en cada step. Es lo que permite que la
     destilacion post-corrida distinga una transicion real de un no-op: sin esto el distilador cae
     por su rama de degradacion limpia y solo puede extraer el plan crudo -- incluidas las acciones
     que no cambiaron nada, que es justamente el desperdicio que queremos NO repetir en la corrida
     siguiente. La firma sale del MISMO frame que ve la politica (computeFrameSignature comparte
     extractGrid con ella), asi que lo persistido describe el estado sobre el que se decidio. */
  levelProgress = accumulateLevelProgress(levelProgress, frame);
  const nivelesReset = readFrameLevels(frame);
  const tsReset = new Date(now());
  steps.push({
    stepNum: stepNum++,
    action: 'RESET',
    reasoning: 'Inicio/reinicio del juego.',
    ts: tsReset,
    stateSignatureAfter: computeFrameSignature(frame),
    levelsCompleted: nivelesReset.maxLevelsCompleted,
    winLevels: nivelesReset.winLevels,
  });
  /* El frame del RESET se captura SIN grilla previa: su diff es el RLE completo de la pantalla
     inicial, que es la base sobre la que se reconstruye toda la partida. Sin el, los diffs
     siguientes no se pueden aplicar a nada. */
  opts.capture?.recordStep({
    stepNum: 0,
    action: 'RESET',
    availableActions: frame.available_actions ?? [],
    gridBefore: null,
    gridAfter: extractGrid(frame),
    levelsCompleted: nivelesReset.maxLevelsCompleted,
    winLevels: nivelesReset.winLevels,
    stateSignatureAfter: computeFrameSignature(frame),
    ts: tsReset,
  });
  registro.push({ after: frame });

  while (frame.state === 'NOT_FINISHED' || frame.state === 'NOT_STARTED') {
    if (now() >= deadline) {
      return {
        policy,
        result: {
          finalState: frame.state,
          steps,
          timedOut: true,
          deadLettered: false,
          seedSummary,
          levelProgress,
        },
      };
    }
    if (stepNum >= maxSteps) {
      return {
        policy,
        result: {
          finalState: frame.state,
          steps,
          timedOut: false,
          deadLettered: false,
          seedSummary,
          levelProgress,
          error: `maxSteps (${maxSteps}) alcanzado sin que el juego termine.`,
        },
      };
    }

    const decision = policy.decide(frame);
    /* Se captura ANTES de mandar el comando: `frame` se reasigna abajo y perderiamos el origen. */
    const frameBefore = frame;
    const signatureBefore = computeFrameSignature(frame);
    /* BL.21557 -- idem con la grilla y las acciones disponibles: el corpus necesita el ESTADO SOBRE
       EL QUE SE DECIDIO, no el que quedo despues. */
    const gridBefore = extractGrid(frame);
    const availableActionsBefore = frame.available_actions ?? [];

    let nextFrame: ArcFrameResponse;
    try {
      nextFrame = await opts.client.sendCommand(decision.action, {
        game_id: opts.gameId,
        guid,
        ...(decision.x !== undefined ? { x: decision.x, y: decision.y } : {}),
        reasoning: { note: decision.reasoning },
      });
      opts.deadLetter.recordSuccess();
    } catch (err) {
      const deadLettered = opts.deadLetter.recordFailure();
      if (deadLettered) {
        return {
          policy,
          result: {
            finalState: 'GAME_OVER',
            steps,
            timedOut: false,
            deadLettered: true,
            seedSummary,
            levelProgress,
            error: String(err instanceof Error ? err.message : err),
          },
        };
      }
      // Falla aislada (por debajo del tope de dead-letter): no se persiste el step fallido, se
      // reintenta con el mismo `frame`/`guid` vigentes en la proxima vuelta del loop.
      continue;
    }

    frame = nextFrame;
    guid = frame.guid;
    levelProgress = accumulateLevelProgress(levelProgress, frame);
    const niveles = readFrameLevels(frame);
    const signatureAfter = computeFrameSignature(frame);
    const ts = new Date(now());
    const stepActual = stepNum++;
    steps.push({
      stepNum: stepActual,
      action: decision.action,
      reasoning: decision.reasoning,
      ts,
      stateSignatureBefore: signatureBefore,
      stateSignatureAfter: signatureAfter,
      levelsCompleted: niveles.maxLevelsCompleted,
      winLevels: niveles.winLevels,
    });
    /* BL.21557 -- las coordenadas del click SI se mandaban a la API y se descartaban al persistir
       (medido en ft09: 32 clicks productivos de 415, coordenadas perdidas para siempre). Aca es
       donde dejan de perderse. */
    opts.capture?.recordStep({
      stepNum: stepActual,
      action: decision.action,
      ...(decision.x !== undefined ? { x: decision.x } : {}),
      ...(decision.y !== undefined ? { y: decision.y } : {}),
      availableActions: availableActionsBefore,
      gridBefore,
      gridAfter: extractGrid(frame),
      levelsCompleted: niveles.maxLevelsCompleted,
      winLevels: niveles.winLevels,
      ...(signatureBefore !== undefined ? { stateSignatureBefore: signatureBefore } : {}),
      ...(signatureAfter !== undefined ? { stateSignatureAfter: signatureAfter } : {}),
      ts,
    });
    registro.push({ before: frameBefore, after: frame });
  }

  return {
    policy,
    result: {
      finalState: frame.state,
      steps,
      timedOut: false,
      deadLettered: false,
      seedSummary,
      levelProgress,
    },
  };
}
