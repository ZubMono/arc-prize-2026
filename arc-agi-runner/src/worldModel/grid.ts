/* [arc-agi-runner/worldModel/grid] BL.20860 -- utilidades puras sobre grillas ARC (number[][],
   colores 4-bit 0-15). Sin dependencias de red/Mongo -- helpers deterministas reusados por
   primitives.ts, synthesis.ts, stateSignature.ts y planner.ts. */

export type Grid = number[][];

export interface BoundingBox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/** BL.21558 -- mascara de volatilidad de UN episodio: `true` en las celdas cuyo valor cambia sin
 *  relacion con la accion ejecutada (HUD, contador de pasos, animaciones de fondo). Toda
 *  comparacion "enmascarada" las IGNORA.
 *
 *  Por que existe: medido en `prometheusEvaluationRuns`, los juegos publicos de ARC-AGI-3 tienen
 *  celdas que cambian en CADA frame (ar25-0c556536: 76 firmas unicas en 78 pasos; lf52-271a04aa:
 *  94/94). Con esas celdas dentro de la comparacion, `gridsEqual` no da `true` NUNCA: no se detecta
 *  ningun no-op, la sintesis tendria que explicar tambien el contador (imposible con un DSL de
 *  tablero) y ninguna firma de estado se repite jamas.
 *
 *  Se indexa `[y][x]`. Una fila mas corta que la grilla (o ausente) se lee como "no volatil": la
 *  mascara se APRENDE en vivo (volatilityMask.ts) y puede ir por detras de un cambio de forma del
 *  frame -- ante la duda no se enmascara nada, que es el comportamiento previo a este BL. */
export type VolatilityMask = readonly (readonly boolean[])[];

/** Valor que se mezcla al hash en lugar del contenido real de una celda volatil. 16 esta FUERA del
 *  rango de colores ARC (0-15), asi que no puede colisionar con un color legitimo: dos grillas que
 *  solo difieren en celdas volatiles hashean igual, y una grilla con una celda enmascarada nunca
 *  hashea como otra que ahi tiene un color real. */
export const VOLATILE_CELL_HASH_PLACEHOLDER = 0x10;

/** Lectura tolerante de la mascara -- ver `VolatilityMask` (fuera de rango = no volatil). */
export function isVolatileCell(mask: VolatilityMask | null, y: number, x: number): boolean {
  if (mask === null) return false;
  return mask[y]?.[x] === true;
}

export function cloneGrid(grid: Grid): Grid {
  return grid.map((row) => row.slice());
}

export function gridDimensions(grid: Grid): { width: number; height: number } {
  return { height: grid.length, width: grid[0]?.length ?? 0 };
}

export function gridsEqual(a: Grid, b: Grid): boolean {
  return gridsEqualMasked(a, b, null);
}

/** Igualdad IGNORANDO las celdas volatiles (ver `VolatilityMask`). `mask === null` = igualdad
 *  estricta, identica a `gridsEqual` (que delega aca: una sola implementacion, fuente unica).
 *  La forma (alto/ancho de cada fila) se sigue comparando SIEMPRE: un cambio de tamano nunca es
 *  ruido de HUD, es otro estado. */
export function gridsEqualMasked(a: Grid, b: Grid, mask: VolatilityMask | null): boolean {
  if (a.length !== b.length) return false;
  for (let y = 0; y < a.length; y++) {
    const rowA = a[y];
    const rowB = b[y];
    if (rowA.length !== rowB.length) return false;
    for (let x = 0; x < rowA.length; x++) {
      if (rowA[x] !== rowB[x] && !isVolatileCell(mask, y, x)) return false;
    }
  }
  return true;
}

/** Distancia de Hamming entre dos grillas -- cantidad de celdas distintas. Si difieren en forma,
 *  cada celda fuera de la interseccion cuenta como distinta (penaliza cambios de tamano no
 *  explicados). Heuristica admisible-en-la-practica para el planner (nunca sobreestima el costo
 *  real de igualar dos grillas idénticas: da 0 solo si son iguales). */
export function cellDiffCount(a: Grid, b: Grid): number {
  const height = Math.max(a.length, b.length);
  let diff = 0;
  for (let y = 0; y < height; y++) {
    const rowA = a[y] ?? [];
    const rowB = b[y] ?? [];
    const width = Math.max(rowA.length, rowB.length);
    for (let x = 0; x < width; x++) {
      if ((rowA[x] ?? -1) !== (rowB[x] ?? -1)) diff++;
    }
  }
  return diff;
}

/** Color de fondo -- el mas frecuente en la grilla (heuristica estandar ARC: el fondo domina el
 *  area). Empate: el de menor indice de color, para determinismo. */
export function detectBackgroundColor(grid: Grid): number {
  const counts = new Map<number, number>();
  for (const row of grid) {
    for (const cell of row) {
      counts.set(cell, (counts.get(cell) ?? 0) + 1);
    }
  }
  let best = 0;
  let bestCount = -1;
  for (const [color, count] of [...counts.entries()].sort((a, b) => a[0] - b[0])) {
    if (count > bestCount) {
      best = color;
      bestCount = count;
    }
  }
  return best;
}

/** Bounding box de las celdas que NO son `backgroundColor`. `null` si la grilla es uniforme
 *  (no hay foreground). */
export function foregroundBoundingBox(grid: Grid, backgroundColor: number): BoundingBox | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (let y = 0; y < grid.length; y++) {
    for (let x = 0; x < grid[y].length; x++) {
      if (grid[y][x] !== backgroundColor) {
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        minY = Math.min(minY, y);
        maxY = Math.max(maxY, y);
      }
    }
  }
  if (maxX < minX) return null;
  return { minX, minY, maxX, maxY };
}

/** Hash entero estable (FNV-1a, con separador de fila para no colisionar grillas de distinta
 *  forma con el mismo contenido concatenado). Usado por stateSignature.ts para detectar estados
 *  repetidos y por transitionMemory.ts para deduplicar observaciones identicas. */
export function hashGrid(grid: Grid): number {
  return hashGridMasked(grid, null);
}

/** Hash que IGNORA el contenido de las celdas volatiles: cada una aporta
 *  `VOLATILE_CELL_HASH_PLACEHOLDER` en vez de su color, asi que la posicion sigue contando (la
 *  forma no se pierde) pero el valor cambiante no. `mask === null` reproduce `hashGrid` bit a bit
 *  -- las firmas ya persistidas de corridas viejas siguen siendo comparables consigo mismas. */
export function hashGridMasked(grid: Grid, mask: VolatilityMask | null): number {
  let hash = 0x811c9dc5;
  for (let y = 0; y < grid.length; y++) {
    const row = grid[y];
    for (let x = 0; x < row.length; x++) {
      hash ^= isVolatileCell(mask, y, x) ? VOLATILE_CELL_HASH_PLACEHOLDER : row[x];
      hash = Math.imul(hash, 0x01000193);
    }
    hash ^= 0xff; // separador de fila -- evita que [[1],[2]] colisione con [[1,2]]
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** Copia de `target` con las celdas volatiles reemplazadas por el valor que tienen en `reference`.
 *  Es la forma de meter la mascara en un consumidor que NO la conoce: `synthesizeProgram` recibe
 *  `(pre, neutralizeVolatileCells(pre, post, mask))` y ve un par donde las celdas de HUD son
 *  identicas, con lo cual solo tiene que explicar el cambio REAL del tablero. Sin esto habria que
 *  cablear la mascara por todo el DSL y romper la paridad con el port Python.
 *
 *  `mask === null` devuelve un clon fiel (nunca la misma referencia: quien recibe el resultado
 *  puede mutarlo sin corromper la ventana de observaciones). Celdas fuera de `reference` conservan
 *  su valor de `target` -- sin referencia no hay con que neutralizar. */
export function neutralizeVolatileCells(
  reference: Grid,
  target: Grid,
  mask: VolatilityMask | null,
): Grid {
  return target.map((row, y) =>
    row.map((cell, x) => {
      if (!isVolatileCell(mask, y, x)) return cell;
      const referenceCell = reference[y]?.[x];
      return referenceCell === undefined ? cell : referenceCell;
    }),
  );
}
