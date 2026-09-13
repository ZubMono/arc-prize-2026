/* [arc-agi-runner/scripts/exportClickCorpus] BL.21560 -- exporta el corpus REAL de clicks desde la
   coleccion `arcReplayFrames` (BL.21557) al fixture
   src/worldModel/__fixtures__/clickRealFrames.json.

   POR QUE existe. El ranker de coordenadas se ajusta por regresion logistica contra clicks REALES
   con su resultado REAL ("el click cambio la grilla"), etiqueta auto-supervisada que no exige haber
   ganado nunca. Ese dato vive en Mongo, y ni los tests ni el ajuste pueden depender de una base:
   tienen que ser reproducibles offline y en CI. Asi que el corpus entra al repositorio como
   fixture, igual que volatilityRealGames.json (BL.21558) -- misma leccion, mismo remedio.

   QUE EXPORTA. Por corrida: la grilla completa del primer frame y, por paso, la accion, la
   coordenada clickeada y el DIFF contra el paso anterior. Diffs y no grillas: una partida cruda son
   ~350 x 4096 numeros; en diffs entra en decenas de KB (casi todo click no cambia nada).
   NO exporta runId ni modelId: el fixture describe COMO se comporta un tablero, no quien lo jugo.

   Correr (requiere acceso a la Mongo donde el runner persistio el corpus):
     cd projects/arc-agi-runner && npx tsx scripts/exportClickCorpus.ts
   Filtro opcional por juego: ARC_CLICK_CORPUS_GAME_IDS (CSV). */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import { mensajeSinUrlArc, resolverArcMongoUrl } from '../src/arcMongoUrl';
import { getArcRunnerMongoClient } from '../src/mongoClient';
import { decodeGridDiff } from '../src/replayRleDiff';
import type { ArcReplayFrame } from '../src/types';
import type { Grid } from '../src/worldModel/grid';

const RUTA_FIXTURE = resolve(__dirname, '../src/worldModel/__fixtures__/clickRealFrames.json');

interface PasoDeClick {
  accion: string;
  /** Coordenada clickeada -- ausente en acciones que no son ACTION6. */
  x?: number;
  y?: number;
  /** Diff contra el paso anterior, aplanado: [y, x, valor, y, x, valor, ...]. */
  diff: number[];
}

interface PartidaDeClicks {
  gameId: string;
  alto: number;
  ancho: number;
  base: number[][];
  pasos: PasoDeClick[];
}

function diffEntre(pre: Grid, post: Grid): number[] {
  const plano: number[] = [];
  for (let y = 0; y < post.length; y++) {
    for (let x = 0; x < post[y].length; x++) {
      if (pre[y]?.[x] !== post[y][x]) plano.push(y, x, post[y][x]);
    }
  }
  return plano;
}

/** El driver de Mongo devuelve los Buffer como `Binary`, no como `Uint8Array`. Sin esta
 *  normalizacion `decodeGridDiff` recibe un array vacio y reconstruye grillas de ceros: el fixture
 *  saldria sintacticamente valido y semanticamente basura (cero clicks productivos en un corpus que
 *  tiene 32). Se acepta cualquiera de las tres formas y se falla ruidoso ante una cuarta. */
function aBytes(valor: unknown): Uint8Array {
  if (valor instanceof Uint8Array) return valor;
  const interno = (valor as { buffer?: unknown }).buffer;
  if (interno instanceof Uint8Array) return interno;
  if (interno instanceof ArrayBuffer) return new Uint8Array(interno);
  throw new Error('[corpus-clicks] diffRle en un formato no reconocido -- corpus ilegible.');
}

/** Reconstruye una corrida completa aplicando los diffs RLE en orden de stepNum. El primer doc
 *  (RESET) trae el RLE completo de la pantalla inicial: es la base.
 *
 *  CORTA EN EL PRIMER HUECO de `stepNum` (BL.21695). El diff de un paso se codifica contra el paso
 *  ANTERIOR, asi que la cadena solo es reconstruible si los pasos son CONSECUTIVOS: si falta uno,
 *  todos los siguientes se decodifican contra una grilla equivocada y el fixture sale
 *  sintacticamente valido y semanticamente basura -- el mismo modo de falla que ya se pago con los
 *  `Binary` sin normalizar. Antes de BL.21695 la coleccion solo tenia partidas completas del runner
 *  online (contiguas desde el paso 0); ahora tambien tiene VENTANAS sueltas del harness local, que
 *  por definicion dejan huecos. */
function reconstruirPartida(docs: ArcReplayFrame[]): PartidaDeClicks | null {
  const ordenados = [...docs].sort((a, b) => a.stepNum - b.stepNum);
  const primero = ordenados[0];
  if (primero === undefined) return null;

  let previa: Grid | null = null;
  const pasos: PasoDeClick[] = [];
  let base: Grid | null = null;
  let esperado = primero.stepNum;

  for (const doc of ordenados) {
    if (doc.stepNum !== esperado) {
      console.error(
        `[corpus-clicks] ${doc.runId}: hueco en stepNum (${esperado} -> ${doc.stepNum}), ` +
          'se corta la reconstruccion aca -- la cadena de diffs no es reconstruible tras un hueco.',
      );
      break;
    }
    esperado = doc.stepNum + 1;
    const actual = decodeGridDiff(aBytes(doc.diffRle), previa, doc.gridWidth, doc.gridHeight);
    if (base === null) {
      base = actual;
    } else if (previa !== null) {
      pasos.push({
        accion: doc.action,
        ...(doc.x !== undefined ? { x: doc.x, y: doc.y } : {}),
        diff: diffEntre(previa, actual),
      });
    }
    previa = actual;
  }

  if (base === null) return null;
  return {
    gameId: primero.gameId,
    alto: base.length,
    ancho: base[0]?.length ?? 0,
    base,
    pasos,
  };
}

async function main(): Promise<void> {
  /* BL.21700 -- este script tenia su PROPIA precedencia (`ARC_RUNNER_MONGO_URL ?? MONGO_URL`),
     distinta de la del runner y de la del monorepo: tres reglas para una sola pregunta. Con
     MONGO_URL heredada de .env.development exportaba el corpus del cluster equivocado. Ahora usa
     la misma resolucion que todo el ciclo. */
  const uri = resolverArcMongoUrl();
  if (uri.length === 0) {
    throw new Error(mensajeSinUrlArc('es donde el runner persistio arcReplayFrames'));
  }
  const filtro = (process.env.ARC_CLICK_CORPUS_GAME_IDS ?? '')
    .split(',')
    .map((g) => g.trim())
    .filter((g) => g.length > 0);

  const client = await getArcRunnerMongoClient(uri);
  const coleccion = client.db().collection<ArcReplayFrame>('arcReplayFrames');
  const docs = await coleccion
    .find(filtro.length > 0 ? { gameId: { $in: filtro } } : {})
    .sort({ runId: 1, stepNum: 1 })
    .toArray();

  const porCorrida = new Map<string, ArcReplayFrame[]>();
  for (const doc of docs) {
    const lote = porCorrida.get(doc.runId) ?? [];
    lote.push(doc);
    porCorrida.set(doc.runId, lote);
  }

  const partidas: PartidaDeClicks[] = [];
  for (const [runId, lote] of porCorrida) {
    const partida = reconstruirPartida(lote);
    if (partida === null) {
      console.error(`[corpus-clicks] ${runId}: sin frame base utilizable, se omite`);
      continue;
    }
    const clicks = partida.pasos.filter((p) => p.x !== undefined).length;
    const productivos = partida.pasos.filter((p) => p.x !== undefined && p.diff.length > 0).length;
    console.log(
      `[corpus-clicks] ${partida.gameId}: ${partida.pasos.length} paso(s), ${clicks} click(s), ` +
        `${productivos} productivo(s)`,
    );
    partidas.push(partida);
  }

  mkdirSync(dirname(RUTA_FIXTURE), { recursive: true });
  writeFileSync(
    RUTA_FIXTURE,
    `${JSON.stringify(
      {
        generadoPor: 'projects/arc-agi-runner/scripts/exportClickCorpus.ts',
        descripcion:
          'BL.21560 -- clicks REALES de ARC-AGI-3 con su resultado real, grabados en diffs desde la ' +
          'coleccion arcReplayFrames. Etiqueta auto-supervisada: "el click cambio la grilla". ' +
          'Grabacion pura: ningun valor calculado por el motor -- las magnitudes esperadas viven en ' +
          'los tests de los dos puertos.',
        partidas,
      },
      null,
      0,
    )}\n`,
  );
  console.log(`[corpus-clicks] escrito ${RUTA_FIXTURE} (${partidas.length} partida(s))`);
  await client.close();
}

void main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
