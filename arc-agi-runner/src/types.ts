/* [arc-agi-runner/types] BL.20775 -- tipos del wire de la API oficial ARC-AGI-3
   (https://docs.arcprize.org/rest_overview) + mirror manual del contrato de escritura hacia
   prometheusEvaluationRuns (packages/api/prometheusEvaluationRuns/types.ts, BL.20774).

   Por que un mirror y no un import: aislamiento critico (BL.20775) -- este proyecto NO depende de
   paquetes privados del monorepo (packages/*) para poder extraerse solo si se gana el ARC Prize
   2026 (dominio publico: MIT-0/CC0, ver BL.21045). Es un limite deliberado de contrato de
   escritura, no una duplicacion de
   logica -- si el schema privado cambia, este archivo se actualiza a mano (comentado abajo por
   campo). */

// ─── Wire types de la API ARC-AGI-3 ─────────────────────────────────────────

/** Coordenada maxima valida de una grilla ARC-AGI-3 (grillas de 64x64, indices 0-63). Fuente
 *  unica -- usada por baselineAgent.ts y worldModel/intelligentPolicy.ts (BL.20860) para acotar
 *  el click de ACTION6. */
export const GRID_MAX_COORD = 63;

export type ArcActionState = 'NOT_FINISHED' | 'NOT_STARTED' | 'WIN' | 'GAME_OVER';

/** Las 7 acciones estandar de todo juego ARC-AGI-3 (docs.arcprize.org/actions). */
export type ArcSimpleAction = 'ACTION1' | 'ACTION2' | 'ACTION3' | 'ACTION4' | 'ACTION5' | 'ACTION7';
export type ArcAction = 'RESET' | ArcSimpleAction | 'ACTION6';

export interface ArcGameSummary {
  /** ID global estable (slug + hash de version), ej. "ls20-016295f7601e". */
  game_id: string;
  title: string;
}

export interface ArcFrameResponse {
  game_id: string;
  /** Session id -- debe reenviarse en cada ACTION subsiguiente del mismo intento. */
  guid: string;
  /** Uno o mas frames consecutivos: grillas de 64x64 indices de color 4-bit (0-15). */
  frame: number[][][];
  state: ArcActionState;
  levels_completed: number;
  win_levels: number;
  /** Acciones validas para el proximo comando (subset de 1..7). */
  available_actions: number[];
}

export interface ArcOpenScorecardOptions {
  source_url?: string;
  tags?: string[];
  opaque?: Record<string, unknown>;
}

export interface ArcOpenScorecardResponse {
  card_id: string;
}

/** Respuesta de cierre -- solo se tipan los campos que el runner efectivamente usa; el resto de
 *  estadisticas agregadas de ARC (environments[], totals, etc) viajan sin tipar via index signature. */
export interface ArcCloseScorecardResponse {
  card_id: string;
  score: number;
  [key: string]: unknown;
}

// ─── Mirror del contrato privado prometheusEvaluationRuns (BL.20774) ────────

/** Espejo de PrometheusEvaluationStep. */
export interface ArcEvaluationStep {
  stepNum: number;
  action: string;
  reasoning: string;
  ts: Date;
  /* BL.20861 -- firma perceptual del estado antes/despues de la accion. Opcionales por el MISMO
     motivo que en el schema privado: las corridas ya persistidas no las tienen y el distilador
     degrada limpio sin ellas. Este es el lado publico del mirror manual (ver CLAUDE.md,
     "Aislamiento critico"): si el schema privado cambia, se actualiza a mano aca -- es una
     frontera de licencia, no la regla de fuente unica del resto del repo. */
  stateSignatureBefore?: string;
  stateSignatureAfter?: string;
  /* BL.21557 -- SENAL DENSA. `levels_completed`/`win_levels` llegan en CADA frame de la API
     (ArcFrameResponse arriba) desde el dia uno y nadie los leia: el runner solo miraba `state`, asi
     que las 11 corridas persistidas hasta 2026-08-17 valen todas score 0 y no hay forma de decir si
     una version del agente es mejor que otra. Persistirlos POR STEP (no solo al final) es lo que
     permite ubicar el paso EXACTO en que se subio de nivel -- que es el unico dato de credito
     parcial que produce una partida perdida. Opcionales por el mismo motivo que las firmas: las
     corridas viejas no los tienen y todo consumidor debe degradar limpio. */
  levelsCompleted?: number;
  winLevels?: number;
}

/** Espejo de PrometheusEvaluationResult. */
export interface ArcEvaluationResult {
  success: boolean;
  /** BL.21557 -- ENTERO con credito parcial (niveles superados), ya no el 0/1 binario de BL.20775.
   *  El formato de entrega oficial lo corrobora: el submission.parquet del gateway de Kaggle tiene
   *  columnas [row_id, game_id, end_of_game, score] con `score` entero -- el leaderboard da credito
   *  parcial, asi que la metrica del premio es exactamente esta. */
  score: number;
  error?: string;
  /** BL.21557 -- nivel maximo alcanzado en la partida (max de `levels_completed` sobre los frames).
   *  Es la METRICA DE SELECCION OFFLINE: ordena dos versiones del agente aunque ninguna gane. */
  maxLevelReached?: number;
  /** BL.21557 -- niveles totales que exige el juego (`win_levels`). 0 si la API no lo informo.
   *  Sin esto, `maxLevelReached` no se puede normalizar entre juegos de distinta longitud. */
  winLevels?: number;
}

/** Espejo de PrometheusReplayMetadata. */
export interface ArcReplayMetadata {
  seed: string;
  envVersion: string;
}

/** Espejo de PrometheusEvaluationRunStatus. */
export type ArcEvaluationRunStatus = 'running' | 'completed' | 'failed';

/** Espejo de PrometheusEvaluationRun -- shape exacto que se persiste en la coleccion
 *  `prometheusEvaluationRuns` (packages/api/prometheusEvaluationRuns/types.ts). */
export interface ArcEvaluationRun {
  _id?: string;
  runId: string;
  modelId: string;
  environmentId: string;
  status: ArcEvaluationRunStatus;
  steps: ArcEvaluationStep[];
  result: ArcEvaluationResult;
  replayMetadata: ArcReplayMetadata;
  startedAt: Date;
  completedAt?: Date;
  /** TTL absoluto. AUSENTE a proposito en las corridas RETENIDAS: un documento sin `expiresAt` es
   *  invisible para el reaper de TTL, que es el interruptor nativo de MongoDB. Ver `retenidoPor`. */
  expiresAt?: Date;
  /** BL.21749 -- marca de retencion explicita. La escribe el writer AL INSERTAR una partida real
   *  contra la API oficial (`politicaDeRetencion.ts`) y `scripts/retener-corpus-arc.cjs` sobre lo
   *  que ya existia. Nunca convive con `expiresAt`: la marca dice "esto no caduca". */
  retenidoPor?: string;
  retenidoEn?: Date;
  createdAt: Date;
}

// ─── Mirror del contrato privado arcReplayFrames (BL.21557) ─────────────────

/** Espejo de ArcReplayFrame -- shape exacto que se persiste en la coleccion `arcReplayFrames`
 *  (packages/api/arcReplayFrames/types.ts).
 *
 *  COLECCION APARTE, no un campo mas de `prometheusEvaluationRuns`: ese contrato esta espejado a
 *  mano en los dos lados de una frontera de licencia (ver arriba) y ademas lo consumen el
 *  distilador y los resolvers -- meterle el corpus adentro romperia el espejo y haria crecer un
 *  doc que hoy entra comodo en el limite de 16MB. Un doc por PASO, no por partida: se escribe en
 *  streaming (si el proceso muere, lo capturado hasta ahi ya esta), y ningun doc puede crecer sin
 *  techo. */
export interface ArcReplayFrame {
  _id?: string;
  /** Mismo runId que `prometheusEvaluationRuns` -- es la clave de join con la corrida. */
  runId: string;
  gameId: string;
  modelId: string;
  /** Paso dentro de la partida; 0 es el RESET. {runId, stepNum} es unico (idempotencia). */
  stepNum: number;
  action: string;
  /** Coordenadas del click de ACTION6. Ausentes en las acciones simples -- son EL dato que se
   *  perdia antes de BL.21557. */
  x?: number;
  y?: number;
  availableActions: number[];
  gridWidth: number;
  gridHeight: number;
  /** Diff RLE pre->post (formato en replayRleDiff.ts). BSON Binary, no array de enteros. */
  diffRle: Uint8Array;
  changedCells: number;
  levelsCompleted: number;
  winLevels: number;
  /** BL.21794 -- CLASE de la transicion que produjo este frame, decidida EN LA CAPTURA:
   *  `informativo` | `inerte` (no cambio una sola celda) | `enAnimacion` (la serie es un loop: el
   *  tablero se anima solo) para los frames de la maniobra, y `sinPrevio` | `elEvento` |
   *  `posteriorAlEvento` para los que quedan fuera de ella.
   *
   *  Medido sobre las 14 ventanas del corpus: de 100 frames de contexto, 55 informativos, 27
   *  inertes y 18 de animacion en loop -- casi la mitad de los frames que un informe cuenta como
   *  evidencia NO sostienen nada. La fuente unica del criterio es `clasificar_pasos`, del agente
   *  offline; aca solo se transporta. AUSENTE en los frames capturados antes de BL.21794, y esa
   *  ausencia es informacion: el lector la declara como "clasificacion reconstruida". */
  claseDePaso?: string;
  /** BL.21794 -- firma de mecanica de esa misma transicion. Vacia fuera de la maniobra. */
  firmaDelPaso?: string;
  /** BL.21798 -- semilla DECLARADA de la partida (`--semilla` del harness offline). Es lo unico que
   *  permite saber desde el corpus si una ventana se puede volver a producir: el `runId` lleva el
   *  LOTE, y el lote no siembra nada. AUSENTE = no declarada, y se reporta asi -- rellenarla con el
   *  lote haria pasar por reproducible lo que no lo es. */
  semilla?: string;
  stateSignatureBefore?: string;
  stateSignatureAfter?: string;
  ts: Date;
  createdAt: Date;
  /** TTL absoluto (expireAfterSeconds:0) -- el corpus es voluminoso y se re-genera jugando.
   *  AUSENTE en los frames retenidos (ver `retenidoPor`). */
  expiresAt?: Date;
  /** BL.21749 -- marca de retencion explicita. La escriben la ingesta de ventanas de subida de
   *  nivel (`replayWindowIngest.ts`, que las hace nacer retenidas) y
   *  `scripts/retener-corpus-arc.cjs`. Nunca convive con `expiresAt`. */
  retenidoPor?: string;
  retenidoEn?: Date;
}
