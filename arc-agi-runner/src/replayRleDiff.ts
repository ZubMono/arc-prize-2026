/* [arc-agi-runner/replayRleDiff] BL.21557 -- codec RLE del DIFF entre dos grillas ARC.

   POR QUE EXISTE: hasta BL.21557 el runner mandaba las coordenadas x,y de cada ACTION6 a la API y
   las DESCARTABA al persistir (gameRunner.ts solo guardaba stepNum/action/reasoning/ts + firmas).
   Medido en la corrida ft09: 32 clicks PRODUCTIVOS de 415, y esas 32 coordenadas -- junto con lo
   que cambio en la pantalla -- se perdieron para siempre. Sin frames no se puede recomputar
   NINGUNA feature a posteriori: cada idea nueva obliga a re-jugar la partida contra la API real.

   POR QUE DIFF Y NO GRILLA COMPLETA: una partida son hasta 500 pasos x 64x64 celdas = 2.048.000
   celdas. Guardar grillas enteras no entra en el presupuesto de 1MB por partida que exige el
   corpus. Casi todo paso de ARC-AGI-3 cambia un punado de celdas (mover un sprite, pintar una
   casilla), asi que el diff es dos ordenes de magnitud mas chico.

   FORMATO (bytes, no array BSON -- un array de N enteros paga ~8 bytes por elemento entre clave e
   indice; un Buffer paga 1 byte por byte):
     secuencia de runs, cada run = varint(longitud) ++ byte(valor)
     valor 0..15  -> color de la celda DESPUES de la accion (indice de color 4-bit de ARC)
     valor 16     -> REPLAY_UNCHANGED: esas celdas quedaron igual que en la grilla anterior
   Los runs recorren la grilla en orden row-major (index = y * width + x) y cubren TODAS las celdas
   (width*height), asi que la reconstruccion no necesita mas metadata que width/height y la grilla
   previa. Un tramo sin cambios cuesta ~3 bytes sin importar cuantas celdas abarque -- de ahi que
   esto sea un diff aunque el recorrido sea completo. Y cuando TODO cambia (transicion de nivel,
   RESET) degrada solo a un RLE de la grilla nueva, que es exactamente lo que hace falta guardar en
   ese caso: sin la grilla base no hay replay posible.

   Sin dependencias del monorepo privado (aislamiento critico, ver CLAUDE.md): esta es la FUENTE
   UNICA del codec -- packages/api/arcReplayFrames documenta el formato y no lo reimplementa. */

import type { Grid } from './worldModel/grid';

/** Valor centinela de "esta celda no cambio". 16 porque los colores de ARC son 4-bit (0..15), asi
 *  que es el primer valor libre y sigue entrando en un byte. */
export const REPLAY_UNCHANGED = 16;

/** Cantidad de colores validos de una grilla ARC (indices 0..15). */
export const REPLAY_COLOR_COUNT = 16;

export interface EncodedGridDiff {
  /** Runs codificados (ver FORMATO arriba). Listo para persistir como BSON Binary. */
  rle: Buffer;
  width: number;
  height: number;
  /** Celdas que efectivamente cambiaron -- metrica barata de "cuanto movio" esta accion. */
  changedCells: number;
  /** Cantidad de runs emitidos -- proxy directo del costo en bytes, util para diagnosticar. */
  runs: number;
}

function writeVarint(out: number[], value: number): void {
  let v = value >>> 0;
  while (v >= 0x80) {
    out.push((v & 0x7f) | 0x80);
    v >>>= 7;
  }
  out.push(v);
}

function readVarint(bytes: Uint8Array, cursor: { i: number }): number {
  let result = 0;
  let shift = 0;
  while (cursor.i < bytes.length) {
    const byte = bytes[cursor.i++];
    result |= (byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) return result >>> 0;
    shift += 7;
  }
  return result >>> 0;
}

/** Normaliza una celda al rango 0..15. La API oficial nunca deberia mandar otra cosa, pero un
 *  valor fuera de rango colisionaria con REPLAY_UNCHANGED y corromperia el replay entero en
 *  silencio -- preferimos un color equivocado en una celda a un corpus indecodificable. */
function normalizeColor(value: number | undefined): number {
  const n = Number.isFinite(value) ? Math.trunc(value as number) : 0;
  return ((n % REPLAY_COLOR_COUNT) + REPLAY_COLOR_COUNT) % REPLAY_COLOR_COUNT;
}

function sameShape(before: Grid | null, height: number, width: number): before is Grid {
  if (before === null || before.length !== height) return false;
  for (let y = 0; y < height; y++) {
    if ((before[y]?.length ?? -1) !== width) return false;
  }
  return true;
}

/** Codifica el diff `before -> after`. `before === null` (o de otra forma) produce el RLE completo
 *  de `after` -- el caso del RESET y de cualquier cambio de dimensiones. Devuelve `null` cuando
 *  `after` no trae grilla utilizable: nunca se inventa un frame vacio, porque un frame falso en el
 *  corpus es peor que un frame ausente (el ausente se detecta por el hueco en stepNum). */
export function encodeGridDiff(before: Grid | null, after: Grid | null): EncodedGridDiff | null {
  if (!after || after.length === 0) return null;
  const height = after.length;
  const width = after[0]?.length ?? 0;
  if (width === 0) return null;

  const base = sameShape(before, height, width) ? before : null;
  const bytes: number[] = [];
  let runValue = -1;
  let runLength = 0;
  let changedCells = 0;
  let runs = 0;

  const flushRun = (): void => {
    if (runLength === 0) return;
    writeVarint(bytes, runLength);
    bytes.push(runValue);
    runs++;
  };

  for (let y = 0; y < height; y++) {
    const rowAfter = after[y] ?? [];
    const rowBefore = base?.[y];
    for (let x = 0; x < width; x++) {
      const nuevo = normalizeColor(rowAfter[x]);
      const igual = rowBefore !== undefined && normalizeColor(rowBefore[x]) === nuevo;
      if (!igual) changedCells++;
      const valor = igual ? REPLAY_UNCHANGED : nuevo;
      if (valor === runValue) {
        runLength++;
      } else {
        flushRun();
        runValue = valor;
        runLength = 1;
      }
    }
  }
  flushRun();

  return { rle: Buffer.from(bytes), width, height, changedCells, runs };
}

/** Reconstruye la grilla POSTERIOR a partir del diff y de la grilla previa. `before` ausente (o de
 *  otra forma) hace que las celdas REPLAY_UNCHANGED se reconstruyan como 0: solo puede pasar si se
 *  decodifica un frame intermedio sin haber reproducido la cadena desde el RESET, y devolver un 0
 *  explicito es mas honesto que fallar (el llamador ve la grilla base incompleta, no una excepcion
 *  a mitad de un replay de 500 pasos). */
export function decodeGridDiff(
  rle: Uint8Array,
  before: Grid | null,
  width: number,
  height: number,
): Grid {
  const salida: Grid = [];
  for (let y = 0; y < height; y++) salida.push(new Array<number>(width).fill(0));
  if (width <= 0 || height <= 0) return salida;

  const base = sameShape(before, height, width) ? before : null;
  const total = width * height;
  const cursor = { i: 0 };
  let celda = 0;

  while (cursor.i < rle.length && celda < total) {
    const longitud = readVarint(rle, cursor);
    if (cursor.i >= rle.length) break;
    const valor = rle[cursor.i++];
    for (let k = 0; k < longitud && celda < total; k++, celda++) {
      const y = Math.floor(celda / width);
      const x = celda % width;
      salida[y][x] = valor === REPLAY_UNCHANGED ? normalizeColor(base?.[y]?.[x] ?? 0) : valor;
    }
  }

  return salida;
}
