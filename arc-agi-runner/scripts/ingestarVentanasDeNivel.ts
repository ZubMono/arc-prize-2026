/* [arc-agi-runner/scripts/ingestarVentanasDeNivel] BL.21695 paso 1 -- sube a `arcReplayFrames` las
   ventanas de subida de nivel capturadas por el harness local offline.

   NO SE INVOCA A MANO. El entrypoint es `node scripts/ingestar-ventanas-nivel-arc.cjs` desde la
   raiz del monorepo: ahi vive `resolveArcMongoUrl()` (scripts/lib/arcMongoUrl.cjs), la FUENTE UNICA
   de a que cluster escribe el ciclo ARC, y esa fuente no se puede importar desde aca -- este
   sub-proyecto se abre bajo MIT-0 y no importa nada del monorepo privado (aislamiento critico, ver
   CLAUDE.md). El wrapper resuelve la URL, la pasa por `ARC_RUNNER_MONGO_URL` y este script la
   consume; asi la URL se decide en UN solo lugar y nadie adivina cluster.

   La coleccion es SOLO-PRODUCCION desde BL.21700 (packages/api/collections-scope.ts): escribirla en
   development es justamente el error que ese BL vino a cerrar.

   Uso (via wrapper):
     node scripts/ingestar-ventanas-nivel-arc.cjs projects/arc-agi3-kaggle-agent/runtime_reports/ventanas
     node scripts/ingestar-ventanas-nivel-arc.cjs <dir|archivo.jsonl> --dry-run */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { getArcRunnerMongoClient } from '../src/mongoClient';
import { operacionDeUpsertDeFrame } from '../src/replayFrameStore';
import { documentosDeVentanas, parsearVentanas } from '../src/replayWindowIngest';
import type { VentanaDeNivel } from '../src/replayWindowIngest';
import type { ArcReplayFrame } from '../src/types';

/* NO hay constante de "frames por escritura". La habia (`TAMANO_DE_LOTE = 25`, copiada de
   `replayFrameStore.ts`) y era el defecto: cortar cada 25 documentos partia ventanas de 21 por la
   mitad. La unidad de escritura es la VENTANA — ver `escribir`. */

function archivosJsonl(ruta: string): string[] {
  const absoluta = resolve(ruta);
  const info = statSync(absoluta);
  if (info.isFile()) return [absoluta];
  return readdirSync(absoluta)
    .filter((n) => n.endsWith('.jsonl'))
    .sort()
    .map((n) => join(absoluta, n));
}

function leerVentanas(rutas: string[]): { ventanas: VentanaDeNivel[]; descartadas: number } {
  const ventanas: VentanaDeNivel[] = [];
  let descartadas = 0;
  for (const archivo of rutas) {
    const parseado = parsearVentanas(readFileSync(archivo, 'utf8'));
    ventanas.push(...parseado.ventanas);
    descartadas += parseado.descartadas;
    console.log(
      `[ventanas-nivel] ${archivo}: ${parseado.ventanas.length} ventana(s)` +
        (parseado.descartadas > 0 ? `, ${parseado.descartadas} linea(s) descartada(s)` : ''),
    );
  }
  return { ventanas, descartadas };
}

/**
 * Escribe UNA ventana por `bulkWrite`, ORDENADO.
 *
 * BL.21849 — POR QUE LA VENTANA Y NO UN LOTE DE 25. Los frames de una ventana estan ENCADENADOS:
 * el primero lleva el RLE completo de la grilla y los demas son diffs contra el anterior de la
 * MISMA ventana (`documentosDeVentana`). Una ventana sin su primer frame es INDECODIFICABLE, y la
 * version anterior aplanaba todas las ventanas de todos los slices en un array y lo cortaba cada 25
 * documentos: una ventana de 21 cruzaba el borde y un corte a mitad (timeout de 15 min del
 * spawnSync del ingestor de Fargate, `timeout 900s` del cron, OOM) dejaba media ventana en Atlas.
 * Con `ordered: false`, ademas, un documento invalido no abortaba a los otros 24 del lote, asi que
 * se podia perder justo el PRIMER frame y conservar el resto.
 *
 * `ordered: true` es deliberado y difiere del sink online: aca el lote ES una cadena. Si el primer
 * frame falla, los siguientes no se escriben y queda una ventana ausente (recuperable re-ingestando)
 * en vez de una ventana sin cabeza (silenciosamente rota). Una ventana que falla no aborta a las
 * demas: cada una tiene su propia escritura.
 *
 * NO es una transaccion — no se afirma que lo sea. Es la unidad de escritura mas chica que preserva
 * la decodificabilidad, y el upsert por {runId, stepNum} hace que re-ingestar la complete.
 */
async function escribir(
  grupos: ArcReplayFrame[][],
  uri: string,
): Promise<{ escritos: number; ventanasEscritas: number; ventanasFallidas: string[] }> {
  const client = await getArcRunnerMongoClient(uri);
  const coleccion = client.db().collection<ArcReplayFrame>('arcReplayFrames');
  let escritos = 0;
  let ventanasEscritas = 0;
  const ventanasFallidas: string[] = [];
  try {
    for (const grupo of grupos) {
      const etiqueta = `${grupo[0].runId}@${grupo[0].stepNum}`;
      try {
        const resultado = await coleccion.bulkWrite(
          // BL.21749: la MISMA operacion que usa el sink online. `expiresAt` viaja en `$setOnInsert`,
          // asi que re-ingestar un JSONL ya cargado NO le devuelve fecha de purga a los frames que se
          // retuvieron a mano (`retenidoPor`) -- que es exactamente el corpus de subidas de nivel.
          grupo.map((frame) => operacionDeUpsertDeFrame(frame)),
          { ordered: true },
        );
        // `matchedCount` YA incluye a los modificados: sumar los tres contaba DOS VECES cada
        // documento que ya existia (34 documentos se reportaban como 68 al re-ingestar un dia).
        escritos += resultado.upsertedCount + resultado.matchedCount;
        ventanasEscritas += 1;
      } catch (error) {
        // Una ventana que falla se NOMBRA y no aborta a las demas. Al final el proceso sale != 0:
        // una ingesta parcial que sale 0 es corpus perdido en silencio.
        console.error(`[ventanas-nivel] ventana ${etiqueta} NO se escribio:`, error);
        ventanasFallidas.push(etiqueta);
      }
    }
  } finally {
    await client.close();
  }
  return { escritos, ventanasEscritas, ventanasFallidas };
}

async function main(): Promise<void> {
  const argumentos = process.argv.slice(2);
  const ensayo = argumentos.includes('--dry-run');
  const entrada = argumentos.find((a) => !a.startsWith('--'));
  if (entrada === undefined) {
    throw new Error(
      '[ventanas-nivel] falta la ruta al JSONL (o al directorio con los .jsonl) de ventanas.',
    );
  }

  const { ventanas, descartadas } = leerVentanas(archivosJsonl(entrada));
  if (ventanas.length === 0) {
    console.log(`[ventanas-nivel] nada que ingestar (${descartadas} linea(s) invalida(s)).`);
    return;
  }

  const { grupos, resumen } = documentosDeVentanas(ventanas, new Date());
  console.log(
    `[ventanas-nivel] ${resumen.ventanas} ventana(s) -> ${resumen.documentos} documento(s), ` +
      `${resumen.documentosConNivel} con levelsCompleted > 0, juegos: ${resumen.juegos.join(', ')}`,
  );

  if (ensayo) {
    console.log('[ventanas-nivel] --dry-run: no se escribio nada.');
    return;
  }

  const uri = (process.env.ARC_RUNNER_MONGO_URL ?? '').trim();
  if (uri.length === 0) {
    throw new Error(
      '[ventanas-nivel] falta ARC_RUNNER_MONGO_URL. Este script no resuelve el cluster por su ' +
        'cuenta a proposito: invocalo por `node scripts/ingestar-ventanas-nivel-arc.cjs`, que lo ' +
        'resuelve con resolveArcMongoUrl() -- la fuente unica del ciclo ARC.',
    );
  }
  const { escritos, ventanasEscritas, ventanasFallidas } = await escribir(grupos, uri);
  console.log(
    `[ventanas-nivel] ${escritos} documento(s) escritos en arcReplayFrames ` +
      `(${ventanasEscritas}/${grupos.length} ventana(s) completas).`,
  );
  if (ventanasFallidas.length > 0) {
    throw new Error(
      `[ventanas-nivel] ${ventanasFallidas.length} ventana(s) NO se escribieron: ` +
        `${ventanasFallidas.join(', ')}. Re-correr la ingesta las completa (upsert por {runId, stepNum}).`,
    );
  }
}

void main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
