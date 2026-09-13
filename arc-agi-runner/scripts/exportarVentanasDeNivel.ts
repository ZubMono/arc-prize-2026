/* [arc-agi-runner/scripts/exportarVentanasDeNivel] BL.21728 -- vuelca a disco las VENTANAS DE
   SUBIDA DE NIVEL reconstruidas desde `arcReplayFrames`, junto con un MANIFIESTO que las ata a lo
   que hay en la coleccion.

   NO SE INVOCA A MANO: el entrypoint es `node scripts/exportar-ventanas-nivel-arc.cjs` desde la
   raiz del monorepo, que resuelve el cluster con `resolveArcMongoUrl()` -- la fuente unica del
   ciclo ARC (BL.21499/BL.21700). Este script fail-closed si no recibe `ARC_RUNNER_MONGO_URL`.

   POR QUE UN MANIFIESTO Y NO SOLO EL JSONL. El defecto 2 de BL.21728 fue reportar una muestra
   distinta de la persistida porque el informe leia un directorio intermedio viejo. El manifiesto
   lleva el sha256 del JSONL, la corrida de la que salio cada frame y el conteo de documentos
   leidos: el consumidor (`caracterizar_completados.py`) rechaza la entrada si el hash no cierra,
   asi que un export a medias, editado a mano o mezclado con capturas sueltas NO puede pasar por
   corpus. Sin el manifiesto no hay informe: fail-closed, no fail-open con un aviso.

   EL SHA256 NO ALCANZA -- POR QUE HAY UN CENSO (correccion de BL.21728). La cadena de hash ata el
   INFORME al export, pero nunca el export a la COLECCION: un export viejo que quedo en disco, un
   bug en `ventanasDeCorpus` o el filtro de `runId` producen un corpus AUTO-CONSISTENTE que pasa
   los tres chequeos del lector. Reproducido: armando a mano un export sin las dos lineas de g50t y
   recalculando el manifiesto como lo haria este script, el informe volvia a publicar 12/7/5 sin un
   solo error y sin romper ningun hash -- o sea, exactamente el defecto que el BL vino a cerrar,
   por otro camino. El `censo` lo cierra con dos cosas que el JSONL no puede fabricar:
     1. UN SEGUNDO CAMINO PARA CONTAR LOS EVENTOS. `censoDeSubidas` cuenta las subidas de nivel
        DIRECTO sobre los documentos crudos (agrupando por runId y comparando `levelsCompleted`
        entre stepNum CONSECUTIVOS), sin decodificar RLE, sin recortar ventanas y sin pasar por
        `ventanasDeCorpus`. Si las dos cuentas no coinciden, este script FALLA: no exporta un
        corpus del que ya sabe que declara otra muestra.
     2. LO QUE EL FILTRO DEJA AFUERA. Se cuentan los documentos de la coleccion con
        `levelsCompleted > 0` que NO matchean el filtro de runId. Hoy son 0 de 165, pero nada lo
        re-verificaba: si una corrida online registrara una subida de nivel, el export la omitia en
        silencio y el informe seguia diciendo "es lo persistido". El lector fail-closea con eso.

   Uso (via wrapper):
     node scripts/exportar-ventanas-nivel-arc.cjs projects/arc-agi3-kaggle-agent/runtime_reports/corpus */

import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { mensajeSinUrlArc, resolverArcMongoUrl } from '../src/arcMongoUrl';
import { getArcRunnerMongoClient } from '../src/mongoClient';
import { censoDeSubidas, ventanasDeCorpus } from '../src/replayWindowExport';
import type { DocumentoDeCorpus } from '../src/replayWindowExport';

/** Nombre fijo de los dos archivos del export. Fijo y no parametrizable a proposito: el consumidor
 *  busca exactamente estos dos, asi que no hay forma de apuntarlo a "otro" JSONL sin manifiesto. */
export const ARCHIVO_VENTANAS = 'ventanas.jsonl';
export const ARCHIVO_MANIFIESTO = 'manifiesto.json';

/** Prefijo de `runId` de las corridas del harness local offline. Son las UNICAS que contienen
 *  subidas de nivel: el corpus online (2.456 frames) tiene cero. */
const PREFIJO_HARNESS_LOCAL = '^harness-local:';

/** Techo de documentos leidos. El corpus persistido son 277 y cada barrido agrega ~20 por evento,
 *  asi que 20.000 es dos ordenes de magnitud de margen. Existe como CINTURON, no como paginacion:
 *  si se alcanza, este script FALLA en vez de exportar un corpus truncado -- un export corto que
 *  igual se reporta como "el corpus" seria exactamente el defecto 2 de BL.21728 con otra causa. */
const LIMITE_DE_DOCUMENTOS = 20_000;

function hostDe(url: string): string {
  try {
    return new URL(url).host || '(host ilegible)';
  } catch {
    /* @no-log-ok: una URL no parseable se reporta como desconocida y NUNCA se vuelca (regla T-01:
       volcarla filtraria la password al log de cualquier corrida) */
    return '(url no parseable)';
  }
}

async function main(): Promise<void> {
  // @bounded-ok: los argumentos de la linea de comandos, no una coleccion
  const destino = resolve(process.argv.slice(2).find((a) => !a.startsWith('--')) ?? '');
  if (destino === resolve('')) {
    throw new Error('[ventanas-export] falta el directorio destino del export.');
  }
  const uri = resolverArcMongoUrl();
  if (uri.length === 0) throw new Error(mensajeSinUrlArc('exportarVentanasDeNivel'));

  const cliente = await getArcRunnerMongoClient(uri);
  let docs: DocumentoDeCorpus[];
  let baseDeDatos: string;
  let documentosDeLaColeccion = 0;
  let conNivelFueraDelFiltro = 0;
  try {
    const db = cliente.db();
    baseDeDatos = db.databaseName;
    const coleccion = db.collection('arcReplayFrames');
    docs = (await coleccion
      .find({ runId: { $regex: PREFIJO_HARNESS_LOCAL } })
      .sort({ runId: 1, stepNum: 1 })
      .limit(LIMITE_DE_DOCUMENTOS)
      .toArray()) as unknown as DocumentoDeCorpus[];
    // Lo que el filtro deja AFUERA, contado en la coleccion y no inferido del export. Es la unica
    // forma de que el informe pueda decir "es lo persistido" sin que sea un acto de fe.
    documentosDeLaColeccion = await coleccion.countDocuments({});
    conNivelFueraDelFiltro = await coleccion.countDocuments({
      levelsCompleted: { $gt: 0 },
      runId: { $not: { $regex: PREFIJO_HARNESS_LOCAL } },
    });
  } finally {
    await cliente.close();
  }
  if (docs.length >= LIMITE_DE_DOCUMENTOS) {
    throw new Error(
      `[ventanas-export] se alcanzo el techo de ${LIMITE_DE_DOCUMENTOS} documentos: el export ` +
        'estaria TRUNCADO y el informe declararia una muestra que no es la persistida. Subir ' +
        'LIMITE_DE_DOCUMENTOS o paginar antes de volver a correrlo.',
    );
  }

  const censo = censoDeSubidas(docs);
  const ventanas = ventanasDeCorpus(docs);

  // FAIL-CLOSED: dos caminos independientes tienen que contar lo mismo. Si no, el export estaria
  // publicando una muestra que ni el propio script puede confirmar.
  const transicionesDelCenso = [...censo.transiciones].sort();
  const transicionesDeLasVentanas = [
    ...new Set(ventanas.map((v) => `${v.juego}:nivel${v.nivelNuevo}`)),
  ].sort();
  if (censo.eventos !== ventanas.length) {
    throw new Error(
      `[ventanas-export] el censo directo sobre los documentos cuenta ${censo.eventos} subida(s) ` +
        `de nivel y ventanasDeCorpus reconstruyo ${ventanas.length}. Son dos caminos ` +
        'independientes sobre los MISMOS documentos: la diferencia es un bug de reconstruccion o ' +
        'un export a medias, y publicar el corpus asi seria repetir el defecto 2 de BL.21728.',
    );
  }
  if (transicionesDelCenso.join('|') !== transicionesDeLasVentanas.join('|')) {
    throw new Error(
      `[ventanas-export] las transiciones del censo [${transicionesDelCenso.join(', ')}] no son ` +
        `las de las ventanas [${transicionesDeLasVentanas.join(', ')}].`,
    );
  }
  const lineas =
    ventanas.map((v) => JSON.stringify(v)).join('\n') + (ventanas.length > 0 ? '\n' : '');
  const sha256 = createHash('sha256').update(lineas, 'utf8').digest('hex');

  const transiciones = [...new Set(ventanas.map((v) => `${v.juego}:nivel${v.nivelNuevo}`))].sort();
  const manifiesto = {
    origen: 'arcReplayFrames',
    host: hostDe(uri),
    baseDeDatos,
    filtroRunId: PREFIJO_HARNESS_LOCAL,
    documentosLeidos: docs.length,
    documentosConNivel: docs.filter((d) => d.levelsCompleted > 0).length,
    corridas: [...new Set(docs.map((d) => d.runId))].sort(),
    juegos: [...new Set(ventanas.map((v) => v.juego))].sort(),
    ventanas: ventanas.length,
    transicionesDistintas: transiciones,
    // EL CENSO: lo unico del manifiesto que NO se puede derivar del JSONL. Ver el encabezado.
    censo: {
      eventosDeSubidaEnLosDocumentos: censo.eventos,
      transicionesEnLosDocumentos: transicionesDelCenso,
      subidasSinPredecesor: censo.subidasSinPredecesor,
      documentosDeLaColeccion,
      documentosConNivelFueraDelFiltro: conNivelFueraDelFiltro,
    },
    archivo: ARCHIVO_VENTANAS,
    sha256,
    exportadoEn: new Date().toISOString(),
  };

  mkdirSync(destino, { recursive: true });
  writeFileSync(join(destino, ARCHIVO_VENTANAS), lineas, 'utf8');
  writeFileSync(
    join(destino, ARCHIVO_MANIFIESTO),
    JSON.stringify(manifiesto, null, 2) + '\n',
    'utf8',
  );

  console.log(
    `[ventanas-export] ${docs.length} documento(s) -> ${ventanas.length} ventana(s), ` +
      `${manifiesto.juegos.length} juego(s), ${transiciones.length} transicion(es) distinta(s).`,
  );
  console.log(
    `[ventanas-export] censo directo: ${censo.eventos} subida(s) de nivel (coinciden con las ` +
      `ventanas), ${censo.subidasSinPredecesor} sin frame previo persistido | coleccion: ` +
      `${documentosDeLaColeccion} documento(s), ${conNivelFueraDelFiltro} con nivel FUERA del ` +
      `filtro ${PREFIJO_HARNESS_LOCAL}.`,
  );
  console.log(`[ventanas-export] destino: ${destino} (sha256 ${sha256.slice(0, 12)}...)`);
}

void main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
