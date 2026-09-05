/* [arc-agi-runner/replayFrameStore] BL.21557 -- sink de captura del CORPUS DE REPLAY:
   recibe un paso ya jugado, lo codifica como diff RLE (replayRleDiff.ts) y lo persiste en la coleccion
   `arcReplayFrames` (schema en packages/api/arcReplayFrames, registrada en collections-registry).

   TRES INVARIANTES, en orden de importancia:

   1. LA CAPTURA NUNCA TUMBA LA PARTIDA. Todo error (codificacion, Mongo caido, indice duplicado) se
      loguea y se sigue jugando. Una partida contra la API oficial cuesta minutos de reloj y cupo de
      rate-limit; perderla por un fallo del corpus seria un pesimo negocio.
   2. PRESUPUESTO DURO DE 1MB POR PARTIDA. El diff de un frame patologico (grilla entera cambiada
      celda por celda) puede pesar ~12KB; 500 de esos serian 6MB. Cuando el acumulado supera el
      presupuesto la captura se DETIENE y lo dice una sola vez -- un corpus parcial y acotado es
      util, uno que crece sin techo se vuelve un problema de infraestructura.
   3. IDEMPOTENCIA POR {runId, stepNum}. Se escribe con upsert (indice unico del lado privado), asi
      que re-jugar el mismo runId pisa los mismos docs en vez de duplicar el corpus.
   4. `expiresAt` SOLO AL INSERTAR (BL.21749). El upsert pisa todos los campos menos ese: un frame
      nuevo nace con su purga a 30 dias, y uno que ya existe conserva lo que tenga -- incluido "no
      tener fecha", que es como se retiene a mano el corpus que no se regenera. Ver
      `operacionDeUpsertDeFrame`. */

import type { AnyBulkWriteOperation, Collection } from 'mongodb';

import { encodeGridDiff } from './replayRleDiff';
import type { ArcReplayFrame } from './types';
import type { Grid } from './worldModel/grid';

/** Frames por escritura. 25 = ~10 escrituras por partida de 250 pasos: suficientemente barato para
 *  no notarse al lado del RTT de la API, y suficientemente chico para que un crash pierda poco. */
const DEFAULT_BATCH_SIZE = 25;

/** Presupuesto de bytes por PARTIDA -- requisito explicito de BL.21557 ("una partida de 500 pasos
 *  debe entrar en <1MB"). Se mide sobre el tamano estimado de los docs, no sobre el RLE solo. */
export const DEFAULT_REPLAY_BYTE_BUDGET = 1_000_000;

/** Overhead estimado de un doc sin el RLE: claves + runId/gameId/modelId + enteros + fechas +
 *  availableActions. Medido sobre docs reales (~230B); se redondea para arriba porque subestimar el
 *  presupuesto es el unico error que rompe la garantia de 1MB. */
const DOC_OVERHEAD_BYTES = 260;

/** Retencion default del corpus. Mas corta que los 90 dias de `prometheusEvaluationRuns` a
 *  proposito: los frames pesan y se re-generan jugando, las corridas no. */
export const REPLAY_FRAMES_RETENTION_DAYS = 30;

export interface ReplayCaptureStep {
  stepNum: number;
  action: string;
  x?: number;
  y?: number;
  availableActions: number[];
  gridBefore: Grid | null;
  gridAfter: Grid | null;
  levelsCompleted: number;
  winLevels: number;
  stateSignatureBefore?: string;
  stateSignatureAfter?: string;
  ts: Date;
}

export interface ReplayCaptureStats {
  framesCapturados: number;
  framesEscritos: number;
  bytesEstimados: number;
  presupuestoAgotado: boolean;
  errores: number;
}

/** Contrato que consume gameRunner. `recordStep` es SINCRONO a proposito: el loop del juego no debe
 *  esperar a Mongo entre acciones -- el flush corre en segundo plano y se cierra con `flush()`. */
export interface ReplayCapture {
  recordStep(step: ReplayCaptureStep): void;
  flush(): Promise<void>;
  stats(): ReplayCaptureStats;
}

export interface ReplayFrameStoreOptions {
  runId: string;
  gameId: string;
  modelId: string;
  batchSize?: number;
  byteBudget?: number;
  retentionDays?: number;
  now?: () => number;
  log?: (msg: string) => void;
}

/** Instante de purga de un frame: captura + retencion. Exportada porque el puente de ventanas de
 *  nivel (`replayWindowIngest.ts`) escribe frames por otra via y debe aplicar LA MISMA politica --
 *  BL.21749 la unifico aca en vez de recalcular los milisegundos en cada writer. */
export function calcularExpiracionDeFrame(
  capturadoEn: Date | number,
  retentionDays: number = REPLAY_FRAMES_RETENTION_DAYS,
): Date {
  const instante = capturadoEn instanceof Date ? capturadoEn.getTime() : capturadoEn;
  const dias = Math.max(1, Math.trunc(retentionDays));
  return new Date(instante + dias * 24 * 60 * 60 * 1000);
}

/* [operacionDeUpsertDeFrame] BL.21749 -- LA UNICA forma en que un frame se escribe a Mongo.
 *
 * `expiresAt` y las marcas de retencion (`retenidoPor`/`retenidoEn`) van en `$setOnInsert` y NUNCA
 * en `$set`, y esa diferencia es el corpus entero:
 *   - INSERT (frame nuevo): nace con lo que decida su writer -- el sink online le pone fecha de
 *     purga a 30 dias (BL.21557: los frames de una partida se regeneran jugando), la ingesta de
 *     ventanas de subida de nivel lo hace nacer RETENIDO (`replayWindowIngest.ts`).
 *   - MATCH (el doc ya existe): ni la fecha ni las marcas se tocan. Los 5.490 frames retenidos por
 *     BL.21700 y BL.21749 no tienen `expiresAt` a proposito -- es el interruptor nativo del TTL de
 *     MongoDB -- y un `$set` los volveria a poner en la lista de borrado del reaper; una marca
 *     reescrita, ademas, pisaria el motivo que dejo la operacion de retencion. Re-jugar un runId o
 *     re-ingestar una ventana ya cargada NO puede reactivar una bomba que se desactivo a mano.
 * El resto de los campos si se pisan: el upsert por {runId, stepNum} es la idempotencia de
 * BL.21557 y sigue igual. */
export function operacionDeUpsertDeFrame(
  frame: ArcReplayFrame,
): AnyBulkWriteOperation<ArcReplayFrame> {
  const { expiresAt, retenidoPor, retenidoEn, ...mutables } = frame;
  const soloAlCrear: Record<string, unknown> = {};
  if (expiresAt) soloAlCrear.expiresAt = expiresAt;
  if (retenidoPor) soloAlCrear.retenidoPor = retenidoPor;
  if (retenidoEn) soloAlCrear.retenidoEn = retenidoEn;
  return {
    updateOne: {
      filter: { runId: frame.runId, stepNum: frame.stepNum },
      update: {
        $set: mutables,
        ...(Object.keys(soloAlCrear).length > 0 ? { $setOnInsert: soloAlCrear } : {}),
      },
      upsert: true,
    },
  } as AnyBulkWriteOperation<ArcReplayFrame>;
}

/** Crea el sink de captura contra una coleccion `arcReplayFrames`. */
export function createReplayFrameStore(
  collection: Pick<Collection<ArcReplayFrame>, 'bulkWrite'>,
  opts: ReplayFrameStoreOptions,
): ReplayCapture {
  const batchSize = Math.max(1, opts.batchSize ?? DEFAULT_BATCH_SIZE);
  const byteBudget = Math.max(0, opts.byteBudget ?? DEFAULT_REPLAY_BYTE_BUDGET);
  const retentionDays = Math.max(1, opts.retentionDays ?? REPLAY_FRAMES_RETENTION_DAYS);
  const now = opts.now ?? Date.now;
  const log = opts.log ?? ((msg: string) => console.warn(`[arc-agi-runner/replay] ${msg}`));

  let buffer: ArcReplayFrame[] = [];
  let pending: Promise<void> = Promise.resolve();
  const estado: ReplayCaptureStats = {
    framesCapturados: 0,
    framesEscritos: 0,
    bytesEstimados: 0,
    presupuestoAgotado: false,
    errores: 0,
  };

  async function escribir(lote: ArcReplayFrame[]): Promise<void> {
    if (lote.length === 0) return;
    try {
      await collection.bulkWrite(
        // BL.21749: la operacion la arma `operacionDeUpsertDeFrame` -- `expiresAt` va por
        // `$setOnInsert`, asi que re-jugar un runId nunca le devuelve fecha de purga a un frame
        // retenido a mano.
        lote.map((frame) => operacionDeUpsertDeFrame(frame)),
        // Sin orden: un doc problematico no debe abortar los otros 24 del lote.
        { ordered: false },
      );
      estado.framesEscritos += lote.length;
    } catch (err) {
      estado.errores++;
      log(
        `no se pudo persistir un lote de ${lote.length} frame(s) de ${opts.runId}: ` +
          `${err instanceof Error ? err.message : String(err)}. La partida continua.`,
      );
    }
  }

  function encolarFlush(lote: ArcReplayFrame[]): void {
    pending = pending.then(() => escribir(lote));
  }

  return {
    recordStep(step: ReplayCaptureStep): void {
      if (estado.presupuestoAgotado) return;
      try {
        const diff = encodeGridDiff(step.gridBefore, step.gridAfter);
        // Sin grilla utilizable no hay frame que guardar: el hueco en stepNum es la senal honesta.
        if (!diff) return;

        const bytes = diff.rle.length + DOC_OVERHEAD_BYTES;
        if (estado.bytesEstimados + bytes > byteBudget) {
          estado.presupuestoAgotado = true;
          log(
            `presupuesto de ${byteBudget} bytes agotado en ${opts.runId} tras ` +
              `${estado.framesCapturados} frame(s) -- se detiene la captura del corpus (la partida sigue).`,
          );
          return;
        }

        const instante = now();
        buffer.push({
          runId: opts.runId,
          gameId: opts.gameId,
          modelId: opts.modelId,
          stepNum: step.stepNum,
          action: step.action,
          ...(step.x !== undefined ? { x: step.x } : {}),
          ...(step.y !== undefined ? { y: step.y } : {}),
          availableActions: [...step.availableActions],
          gridWidth: diff.width,
          gridHeight: diff.height,
          diffRle: diff.rle,
          changedCells: diff.changedCells,
          levelsCompleted: step.levelsCompleted,
          winLevels: step.winLevels,
          ...(step.stateSignatureBefore !== undefined
            ? { stateSignatureBefore: step.stateSignatureBefore }
            : {}),
          ...(step.stateSignatureAfter !== undefined
            ? { stateSignatureAfter: step.stateSignatureAfter }
            : {}),
          ts: step.ts,
          createdAt: new Date(instante),
          expiresAt: calcularExpiracionDeFrame(instante, retentionDays),
        });
        estado.framesCapturados++;
        estado.bytesEstimados += bytes;

        if (buffer.length >= batchSize) {
          const lote = buffer;
          buffer = [];
          encolarFlush(lote);
        }
      } catch (err) {
        estado.errores++;
        log(
          `error capturando el step ${step.stepNum} de ${opts.runId}: ` +
            `${err instanceof Error ? err.message : String(err)}. La partida continua.`,
        );
      }
    },

    async flush(): Promise<void> {
      if (buffer.length > 0) {
        const lote = buffer;
        buffer = [];
        encolarFlush(lote);
      }
      await pending;
    },

    stats(): ReplayCaptureStats {
      return { ...estado };
    },
  };
}
