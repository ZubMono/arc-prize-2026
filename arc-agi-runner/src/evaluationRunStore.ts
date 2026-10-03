/* [arc-agi-runner/evaluationRunStore] BL.20775 -- persistencia idempotente de corridas hacia la
   coleccion `prometheusEvaluationRuns` (packages/api/prometheusEvaluationRuns, BL.20774). Upsert
   por runId: los dos upserts de una misma corrida (el de apertura con status:'running' y el de
   cierre) caen sobre el MISMO doc en vez de duplicarla (indice unico
   idx_prometheusEvaluationRuns_runId_unique del lado privado).

   BL.21707 -- POR QUE EL UPDATE ESTA PARTIDO EN $setOnInsert + $set:
   hasta este BL el writer hacia `updateOne({runId}, {$set: run}, {upsert:true})`, con `run` = el
   doc ENTERO. Combinado con un runId que no era unico por corrida (`modelId:gameId:fechaUTC`), la
   segunda partida del mismo modelo sobre el mismo juego en un mismo dia sobreescribia la primera:
   mismo filtro, `$set` de todo, cero error, cero aviso. Se perdio telemetria real en produccion
   (colision medida: `prometheus-arc-baseline-v1:ar25-0c556536:2026-08-17`).

   La causa raiz se arregla en `config.ts` (runBatchId unico por corrida), pero un runId unico solo
   no alcanza: mientras el writer pise el doc entero, cualquier colision futura -- un
   `ARC_RUN_BATCH_ID` repetido a mano, un reintento del harness -- sigue pudiendo reescribir la
   IDENTIDAD de una corrida ya persistida. Por eso los campos que definen QUE corrida es esta van
   por `$setOnInsert` (se escriben al crearla y nunca mas) y solo lo que legitimamente evoluciona
   durante la partida va por `$set`. Un reintento del mismo runId actualiza avance y resultado;
   jamas puede cambiarle el gameId, el seed ni el startedAt a la corrida original. */

import type { Collection } from 'mongodb';

import { CAMPO_MARCA_RETENCION } from './politicaDeRetencion';
import type { ArcEvaluationRun } from './types';

/** Campos que definen la IDENTIDAD y el origen de la corrida: se fijan al crear el doc y no se
 *  tocan nunca mas (`$setOnInsert`). Cambiar cualquiera de estos sobre un doc existente seria
 *  reescribir la historia de una partida que ya se jugo contra la API oficial.
 *
 *  Es la fuente unica de la particion: `upsertRun` deriva de aca que va en cada operador, asi que
 *  un campo nuevo del contrato es MUTABLE por default y volverlo inmutable es agregarlo a esta
 *  lista -- nunca tocar el update a mano. */
export const CAMPOS_INMUTABLES_CORRIDA = [
  'runId',
  'modelId',
  'environmentId',
  'replayMetadata',
  'startedAt',
  'createdAt',
] as const satisfies readonly (keyof ArcEvaluationRun)[];

/** Campos que NO viajan en ningun operador: `_id` lo asigna Mongo y es inmutable por definicion
 *  (mandarlo en `$set` hace fallar el update de un doc existente). */
const CAMPOS_NO_ESCRIBIBLES = new Set<string>(['_id']);

/* BL.21749 (revision adversarial) -- CAMPOS QUE SOLO SE ESCRIBEN AL CREAR EL DOCUMENTO.
   `expiresAt` y las marcas de retencion definen si una corrida VIVE O MUERE, y por lo tanto no
   pueden viajar nunca en el `$set` de un upsert: un reintento del mismo `runId` sobre una corrida
   retenida le devolveria fecha de purga, y una marca reescrita pisaria el motivo que dejo la
   operacion de retencion. Van en `$setOnInsert`, que por definicion solo se aplica cuando el
   documento se CREA.

   Esto ademas devuelve la ATOMICIDAD que la primera version de este BL habia perdido: se habia
   partido el upsert en dos escrituras (el doc, y despues `expiresAt` con un filtro que excluia a
   los retenidos), asi que un crash entre ambas dejaba la corrida SIN fecha y SIN marca -- que es
   exactamente la patologia que este BL existe para eliminar ("sin expiresAt" significa "retenido a
   mano"). Con `$setOnInsert` vuelve a ser UN solo `updateOne`.

   Que `expiresAt` se conozca recien al cerrar la partida ya no es un problema: desde este BL lo
   calcula `index.ts` al ABRIRLA (a partir de `startedAt`, ver el comentario de `computeExpiryDate`),
   asi que viaja en el mismo insert que crea el documento. */
const CAMPOS_SOLO_AL_CREAR = new Set<string>(['expiresAt', CAMPO_MARCA_RETENCION, 'retenidoEn']);

/** Claves que envenenarian el prototipo de los acumuladores. El doc de corrida es un tipo del
 *  runner, PERO `closeRunAsCrashed` y el skip de idempotencia esparcen docs que vinieron de Mongo,
 *  y un doc de Mongo es dato externo: la particion recorre sus claves con `Object.entries`, asi que
 *  el guard va aca y no en la confianza del tipo. */
const CLAVES_PELIGROSAS = new Set<string>(['__proto__', 'constructor', 'prototype']);

const INMUTABLES = new Set<string>(CAMPOS_INMUTABLES_CORRIDA);

export interface UpdateParticionado {
  $set: Record<string, unknown>;
  $setOnInsert: Record<string, unknown>;
}

/** Parte el doc de corrida en los dos operadores del upsert. PURA y exportada para que el test de
 *  regresion pueda afirmar directamente que ningun campo inmutable termino en `$set` -- que es la
 *  forma exacta en que este bug volveria. */
export function particionarActualizacion(run: ArcEvaluationRun): UpdateParticionado {
  const $set: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  const $setOnInsert: Record<string, unknown> = Object.create(null) as Record<string, unknown>;

  for (const [campo, valor] of Object.entries(run)) {
    // Guard de prototype pollution: descarta __proto__ / constructor / prototype antes de asignar.
    if (CLAVES_PELIGROSAS.has(String(campo))) continue;
    if (CAMPOS_NO_ESCRIBIBLES.has(campo)) continue;
    if (valor === undefined) continue;
    if (INMUTABLES.has(campo) || CAMPOS_SOLO_AL_CREAR.has(campo))
      $setOnInsert[campo] = valor; // @proto-safe: guard de arriba + Object.create(null)
    else $set[campo] = valor; // @proto-safe: guard de arriba + Object.create(null)
  }

  return { $set, $setOnInsert };
}

export interface EvaluationRunStore {
  /** Upsert de la corrida -- llamar tanto al arrancar (status:'running') como al cerrar
   *  (status:'completed'|'failed'). Los campos de identidad solo se escriben en el INSERT
   *  (`CAMPOS_INMUTABLES_CORRIDA`); el resto refleja el ultimo upsert. */
  upsertRun(run: ArcEvaluationRun): Promise<void>;
  findByRunId(runId: string): Promise<ArcEvaluationRun | null>;
  /** Backstop de idempotencia del runner: la corrida CERRADA CON EXITO cuyo runId empieza con
   *  `prefijoRunId` (`modelId:gameId:diaDelBatch`), o null.
   *
   *  BL.21707: antes era `isAlreadyCompleted(runId)`, comparacion EXACTA, y funcionaba solo porque
   *  el runId incluia la fecha pelada y por lo tanto se repetia entre corridas del mismo dia -- la
   *  misma propiedad que estaba destruyendo telemetria. Con el runBatchId unico esa comparacion
   *  nunca volveria a dar true y el backstop quedaria muerto EN SILENCIO: dos ticks del cron
   *  solapados (corre cada 30 min, una partida dura hasta 30) re-jugarian el mismo juego gastando
   *  presupuesto de la API. Buscar por PREFIJO conserva la semantica original ("este modelo ya
   *  completo este juego en este batch") y ademas sigue encontrando los runIds del formato viejo,
   *  cuyo tercer segmento era exactamente esa fecha.
   *
   *  Una corrida 'running' huerfana (crash sin cierre) o 'failed' NO cuenta como completada -- se
   *  debe poder reintentar. */
  findCompletedByPrefix(prefijoRunId: string): Promise<ArcEvaluationRun | null>;
}

/** Escapa los metacaracteres de regex de un prefijo de runId antes de meterlo en la consulta. El
 *  modelId sale de `ARC_RUNNER_MODEL_ID` y el gameId de la API oficial: ninguno es confiable como
 *  fragmento de expresion regular. */
export function escaparRegex(texto: string): string {
  return texto.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function createEvaluationRunStore(
  collection: Collection<ArcEvaluationRun>,
): EvaluationRunStore {
  return {
    /* UNA sola escritura, atomica. `expiresAt` y las marcas de retencion viajan en `$setOnInsert`
       (ver `CAMPOS_SOLO_AL_CREAR`), asi que ningun reintento del mismo `runId` puede devolverle
       fecha de purga a una corrida retenida ni pisarle el motivo. */
    async upsertRun(run: ArcEvaluationRun): Promise<void> {
      const { $set, $setOnInsert } = particionarActualizacion(run);
      await collection.updateOne({ runId: run.runId }, { $set, $setOnInsert }, { upsert: true });
    },

    async findByRunId(runId: string): Promise<ArcEvaluationRun | null> {
      return collection.findOne({ runId });
    },

    async findCompletedByPrefix(prefijoRunId: string): Promise<ArcEvaluationRun | null> {
      /* Regex ANCLADA al comienzo: Mongo la resuelve con el indice de runId igual que una igualdad,
         asi que el backstop sigue costando una busqueda indexada y no un scan. */
      return collection.findOne({
        runId: { $regex: `^${escaparRegex(prefijoRunId)}` },
        status: 'completed',
      });
    },
  };
}
