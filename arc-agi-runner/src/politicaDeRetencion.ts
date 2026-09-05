/* [arc-agi-runner/politicaDeRetencion] BL.21749 (revision adversarial) -- QUE SE GUARDA PARA
   SIEMPRE Y QUE CADUCA, decidido en el WRITER y no a mano despues.

   ─── EL AGUJERO QUE ESTE ARCHIVO TAPA ──────────────────────────────────────────────────────────
   BL.21749 retuvo una FOTO: las 40 corridas reales que existian el 2026-08-19 y los 5.490 frames.
   Pero el cron `scripts/cron/arc-live-game-run.cjs` corre CADA HORA (`26 * * * *`) y juega partidas
   REALES contra la API oficial de ARC-AGI-3 con `modelId: 'prometheus-arc-baseline-v1'`. Cada una
   nacia con `expiresAt = completedAt + 90 dias` y SIN marca de retencion, sobre el indice
   `idx_prometheusEvaluationRuns_expiresAt_ttl` que esta VIVO en produccion. O sea que la bomba se
   re-armaba sola una vez por hora, y la unica defensa era que un humano se acordara de correr
   `scripts/retener-corpus-arc.cjs --caso partidas-reales` antes de que pasaran 90 dias.

   ─── LA REGLA, Y DONDE SE APLICA ───────────────────────────────────────────────────────────────
   Una corrida contra la API OFICIAL no se regenera: se jugo una vez, con presupuesto real, y
   volver a jugarla devuelve OTRA partida. Por eso NACE RETENIDA -- sin `expiresAt` y con
   `retenidoPor`/`retenidoEn` escritos en el mismo INSERT que la crea. No hay ventana entre
   "existe" y "esta protegida", y no hace falta ningun proceso que la retenga despues.

   Lo que SI caduca, y por que no es una inconsistencia:
     - los FRAMES de esas partidas (`arcReplayFrames`, hasta 500 documentos por partida) conservan
       su TTL de 30 dias. Lo irreemplazable de una partida es su RESULTADO -- score, niveles,
       seed, envVersion, pasos -- y eso vive en el documento de la corrida, que es uno solo y pesa
       ~1KB. Retener ademas el video completo de cada partida horaria hincharia la coleccion sin
       agregar una medicion nueva. Un lote de frames que si importe se retiene explicitamente con
       `scripts/retener-corpus-arc.cjs --caso <caso> --corte <fecha>`.
     - las corridas de modelos SINTETICOS (`agente-novato-referencia`, `prometheus-baseline`) siguen
       caducando a los 90 dias: se regeneran corriendo el baseline.

   Cambiar el horizonte GLOBAL de una coleccion sigue siendo una decision de producto. Esto no lo es:
   es no ponerle fecha de muerte a lo que el propio `archivePolicy.ts` llama "el registro historico
   que no se regenera".

   ESPEJO: `MODELOS_DE_PARTIDA_REAL` y `CAMPO_MARCA_RETENCION` son copia de
   `scripts/lib/retencionCorpusArc.cjs` (`MODELO_PARTIDAS_REALES`, `CAMPO_MARCA_RETENCION`), copiada
   y no importada por la frontera de licencia MIT-0 de este sub-proyecto -- mismo criterio que el
   mirror de `types.ts` y de `arcMongoUrl.ts`. La divergencia la caza el test de paridad
   `scripts/lib/__tests__/retencionCorpusArc.test.cjs`, que lee ESTE archivo. */

/** Campo que marca una corrida/frame RETENIDO a mano. Espejo del monorepo privado. */
export const CAMPO_MARCA_RETENCION = 'retenidoPor';

/** `modelId`s cuyas corridas son partidas REALES contra la API oficial de ARC-AGI-3. */
export const MODELOS_DE_PARTIDA_REAL = ['prometheus-arc-baseline-v1'] as const;

/** Motivo que queda escrito en cada corrida real. Se lee solo: explica por que no caduca. */
export const MOTIVO_RETENCION_PARTIDA_REAL =
  'BL.21749 — partida REAL contra la API oficial de ARC-AGI-3, retenida AL NACER por el writer ' +
  '(projects/arc-agi-runner/src/politicaDeRetencion.ts). Se jugo una sola vez con presupuesto real: ' +
  're-jugarla devuelve OTRA partida, no esta. Sin expiresAt el TTL ' +
  'idx_prometheusEvaluationRuns_expiresAt_ttl no la alcanza. Los frames de la partida SI caducan a ' +
  'los 30 dias (son hasta 500 docs por partida y la medicion vive en este documento).';

/** Motivo de los frames de VENTANAS DE SUBIDA DE NIVEL ingestados desde el harness local. */
export const MOTIVO_RETENCION_VENTANA_DE_NIVEL =
  'BL.21749 — ventana de SUBIDA DE NIVEL capturada por el harness local offline (BL.21695) e ' +
  'ingestada por replayWindowIngest.ts. Retenida AL NACER: son los unicos frames del corpus con ' +
  'levelsCompleted > 0 (el unico registro de como se ve GANAR) y por eso no dependen de que alguien ' +
  'se acuerde de correr la retencion antes de que el TTL de 30 dias los alcance.';

/** PURA: ¿esta corrida es una partida real contra la API oficial (y por lo tanto no regenerable)? */
export function esCorridaNoRegenerable(modelId: string): boolean {
  return (MODELOS_DE_PARTIDA_REAL as readonly string[]).includes(modelId);
}

/** Las marcas que se escriben en un documento que nace retenido. */
export interface MarcasDeRetencion {
  retenidoPor: string;
  retenidoEn: Date;
}

/** PURA: las marcas de retencion de un documento. `ahora` explicito para que el test las fije. */
export function marcasDeRetencion(motivo: string, ahora: Date): MarcasDeRetencion {
  return { retenidoPor: motivo, retenidoEn: ahora };
}

/** PURA: la parte de retencion de una corrida — o `expiresAt`, o las marcas, NUNCA las dos cosas.
 *  Devolverlas juntas seria contradictorio: la marca dice "esto no caduca" y `expiresAt` es
 *  exactamente la fecha en que el reaper lo borra. */
export function retencionDeCorrida(
  modelId: string,
  ahora: Date,
  expiresAt: Date,
): { expiresAt: Date } | MarcasDeRetencion {
  return esCorridaNoRegenerable(modelId)
    ? marcasDeRetencion(MOTIVO_RETENCION_PARTIDA_REAL, ahora)
    : { expiresAt };
}
