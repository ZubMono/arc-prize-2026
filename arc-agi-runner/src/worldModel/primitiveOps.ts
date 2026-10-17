/* [arc-agi-runner/worldModel/primitiveOps] BL.20860 -- tipos del DSL de transformaciones
   grilla-a-grilla + ejecucion (`applyStep`/`applyProgram`) de cada primitivo: translate, reflect,
   rotate, recolor(mapping), floodFill, cropToBBox, overlay, replicate,
   objectExtract(conectividad/color), conditionalRecolor(predicado). Los generadores de
   candidatos data-driven (`propose*`) viven en primitives.ts (import de este modulo) -- separado
   solo para respetar el limite de 500 lineas, misma responsabilidad conceptual (el DSL). */

import { cloneGrid, detectBackgroundColor, foregroundBoundingBox, type Grid } from './grid';

// ─── Tipos del DSL ───────────────────────────────────────────────────────────

export interface TranslateParams {
  dx: number;
  dy: number;
}
export interface ReflectParams {
  /** 'horizontal' invierte columnas (espejo izquierda-derecha). 'vertical' invierte filas
   *  (espejo arriba-abajo). */
  axis: 'horizontal' | 'vertical';
}
export interface RotateParams {
  quarterTurns: 1 | 2 | 3;
}
export interface RecolorParams {
  /** Mapping color-origen -> color-destino. Colores ausentes quedan sin cambios (identidad). */
  mapping: Record<number, number>;
}
export interface FloodFillParams {
  x: number;
  y: number;
  to: number;
}
export interface CropToBBoxParams {
  backgroundColor: number;
}
export type OverlayParams = Record<string, never>;
export interface ReplicateParams {
  timesX: number;
  timesY: number;
}
export interface ObjectExtractParams {
  /** Color especifico a extraer. Si se omite: el objeto (componente 4-conexa) mas grande. */
  color?: number;
}
export interface ConditionalRecolorParams {
  from: number;
  to: number;
  /** 'border': celdas de `from` que tocan el borde de la grilla o un color distinto.
   *  'interior': el complemento. 'all': todas las celdas de `from`. */
  predicate: 'border' | 'interior' | 'all';
}

export type ProgramStep =
  | { name: 'translate'; params: TranslateParams }
  | { name: 'reflect'; params: ReflectParams }
  | { name: 'rotate'; params: RotateParams }
  | { name: 'recolor'; params: RecolorParams }
  | { name: 'floodFill'; params: FloodFillParams }
  | { name: 'cropToBBox'; params: CropToBBoxParams }
  | { name: 'overlay'; params: OverlayParams }
  | { name: 'replicate'; params: ReplicateParams }
  | { name: 'objectExtract'; params: ObjectExtractParams }
  | { name: 'conditionalRecolor'; params: ConditionalRecolorParams };

/** Composicion de pasos DSL -- ES el campo `program` de una knownTransition (ver
 *  transitionMemory.ts), no un sistema paralelo. Programa vacio = identidad (no-op). */
export type Program = ProgramStep[];

/* La union `ProgramStep['name']` se borra al compilar, pero hay consumidores que necesitan
   recorrer los primitivos en RUNTIME (el generador del fixture de paridad TS<->Python y su test,
   que exigen una cobertura minima por primitivo). Declarar el registro como Record sobre esa misma
   union hace que agregar un primitivo al DSL ROMPA la compilacion aca hasta sumarlo, y como los
   consumidores derivan de esta constante en vez de copiarse la lista, el primitivo nuevo aparece
   solo en sus chequeos de cobertura -- que es donde queremos enterarnos. */
const DSL_PRIMITIVE_REGISTRY: Record<ProgramStep['name'], true> = {
  translate: true,
  reflect: true,
  rotate: true,
  recolor: true,
  floodFill: true,
  cropToBBox: true,
  overlay: true,
  replicate: true,
  objectExtract: true,
  conditionalRecolor: true,
};

/** Nombres de TODOS los primitivos del DSL. Fuente unica -- no copiar esta lista a mano. */
export const DSL_PRIMITIVE_NAMES = Object.keys(DSL_PRIMITIVE_REGISTRY) as ReadonlyArray<
  ProgramStep['name']
>;

export interface PrimitiveContext {
  /** Grilla ancla para 'overlay' -- por diseno, el primer frame observado del episodio (ver
   *  intelligentPolicy.ts). Sin ancla, 'overlay' degrada a identidad (defensivo). */
  anchorGrid?: Grid;
}

// ─── Helpers internos de conectividad ────────────────────────────────────────

function keyOf(x: number, y: number): string {
  return `${x},${y}`;
}

function floodRegion(grid: Grid, sx: number, sy: number, color: number): Array<[number, number]> {
  const h = grid.length;
  const w = grid[0]?.length ?? 0;
  const visited = new Set<string>();
  const stack: Array<[number, number]> = [[sx, sy]];
  const region: Array<[number, number]> = [];
  while (stack.length > 0) {
    const [x, y] = stack.pop() as [number, number];
    const key = keyOf(x, y);
    if (visited.has(key)) continue;
    if (x < 0 || y < 0 || x >= w || y >= h) continue;
    if (grid[y][x] !== color) continue;
    visited.add(key);
    region.push([x, y]);
    stack.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
  }
  return region;
}

/** Componentes 4-conexas de color uniforme, saltando el fondo (y, si `onlyColor` esta, todo color
 *  distinto). Devuelve las celdas de cada componente en ORDEN DE DESCUBRIMIENTO.
 *
 *  Exportada desde BL.21560: `clickFeatures.ts` deriva de aca el tamano de la componente de cada
 *  celda y si esta en su borde. Es la MISMA segmentacion que usa el DSL (`objectExtract`), no una
 *  copia -- si las dos divergieran, la politica de click estaria puntuando objetos que el modelo de
 *  mundo no ve. */
export function findComponents(
  grid: Grid,
  backgroundColor: number,
  onlyColor?: number,
): Array<Array<[number, number]>> {
  const h = grid.length;
  const w = grid[0]?.length ?? 0;
  const seen = new Set<string>();
  const components: Array<Array<[number, number]>> = [];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const color = grid[y][x];
      if (seen.has(keyOf(x, y))) continue;
      if (color === backgroundColor) continue;
      if (onlyColor !== undefined && color !== onlyColor) continue;
      const region = floodRegion(grid, x, y, color);
      for (const [rx, ry] of region) seen.add(keyOf(rx, ry));
      components.push(region);
    }
  }
  return components;
}

function bboxOfCells(cells: Array<[number, number]>) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of cells) {
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  }
  return { minX, minY, maxX, maxY };
}

// ─── apply* -- ejecucion de cada primitivo ───────────────────────────────────

function applyTranslate(params: TranslateParams, grid: Grid): Grid {
  const { dx, dy } = params;
  const bg = detectBackgroundColor(grid);
  const h = grid.length;
  const w = grid[0]?.length ?? 0;
  const out: Grid = [];
  for (let y = 0; y < h; y++) {
    const row: number[] = [];
    for (let x = 0; x < w; x++) {
      const sx = x - dx;
      const sy = y - dy;
      row.push(sy >= 0 && sy < h && sx >= 0 && sx < w ? grid[sy][sx] : bg);
    }
    out.push(row);
  }
  return out;
}

function applyReflect(params: ReflectParams, grid: Grid): Grid {
  if (params.axis === 'horizontal') return grid.map((row) => row.slice().reverse());
  return grid
    .slice()
    .reverse()
    .map((row) => row.slice());
}

function rotate90CW(grid: Grid): Grid {
  const h = grid.length;
  const w = grid[0]?.length ?? 0;
  const out: Grid = Array.from({ length: w }, () => new Array(h).fill(0));
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      out[x][h - 1 - y] = grid[y][x];
    }
  }
  return out;
}

function applyRotate(params: RotateParams, grid: Grid): Grid {
  let out = grid;
  for (let i = 0; i < params.quarterTurns; i++) out = rotate90CW(out);
  return out;
}

function applyRecolor(params: RecolorParams, grid: Grid): Grid {
  return grid.map((row) => row.map((cell) => params.mapping[cell] ?? cell));
}

function applyFloodFill(params: FloodFillParams, grid: Grid): Grid {
  const { x, y, to } = params;
  const h = grid.length;
  const w = grid[0]?.length ?? 0;
  if (y < 0 || y >= h || x < 0 || x >= w) return cloneGrid(grid);
  const fromColor = grid[y][x];
  const region = floodRegion(grid, x, y, fromColor);
  const out = cloneGrid(grid);
  for (const [rx, ry] of region) out[ry][rx] = to;
  return out;
}

function applyCropToBBox(params: CropToBBoxParams, grid: Grid): Grid {
  const bbox = foregroundBoundingBox(grid, params.backgroundColor);
  if (!bbox) return cloneGrid(grid);
  const out: Grid = [];
  for (let y = bbox.minY; y <= bbox.maxY; y++) {
    out.push(grid[y].slice(bbox.minX, bbox.maxX + 1));
  }
  return out;
}

function applyOverlay(_params: OverlayParams, grid: Grid, ctx: PrimitiveContext): Grid {
  if (!ctx.anchorGrid) return cloneGrid(grid);
  const bg = detectBackgroundColor(grid);
  const anchor = ctx.anchorGrid;
  return grid.map((row, y) =>
    row.map((cell, x) => (cell !== bg ? cell : (anchor[y]?.[x] ?? cell))),
  );
}

function applyReplicate(params: ReplicateParams, grid: Grid): Grid {
  const { timesX, timesY } = params;
  const h = grid.length;
  const w = grid[0]?.length ?? 0;
  const out: Grid = [];
  for (let y = 0; y < h * timesY; y++) {
    const row: number[] = [];
    for (let x = 0; x < w * timesX; x++) {
      row.push(grid[y % h][x % w]);
    }
    out.push(row);
  }
  return out;
}

function applyObjectExtract(params: ObjectExtractParams, grid: Grid): Grid {
  const bg = detectBackgroundColor(grid);
  const components = findComponents(grid, bg, params.color);
  if (components.length === 0) return cloneGrid(grid);
  const withBBox = components.map((cells) => ({ cells, bbox: bboxOfCells(cells) }));
  withBBox.sort((a, b) => {
    if (b.cells.length !== a.cells.length) return b.cells.length - a.cells.length;
    if (a.bbox.minY !== b.bbox.minY) return a.bbox.minY - b.bbox.minY;
    return a.bbox.minX - b.bbox.minX;
  });
  const chosen = withBBox[0];
  const chosenSet = new Set(chosen.cells.map(([x, y]) => keyOf(x, y)));
  const out: Grid = [];
  for (let y = chosen.bbox.minY; y <= chosen.bbox.maxY; y++) {
    const row: number[] = [];
    for (let x = chosen.bbox.minX; x <= chosen.bbox.maxX; x++) {
      row.push(chosenSet.has(keyOf(x, y)) ? grid[y][x] : bg);
    }
    out.push(row);
  }
  return out;
}

function applyConditionalRecolor(params: ConditionalRecolorParams, grid: Grid): Grid {
  const { from, to, predicate } = params;
  const h = grid.length;
  const w = grid[0]?.length ?? 0;
  const out = cloneGrid(grid);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (grid[y][x] !== from) continue;
      const touchesEdge = x === 0 || y === 0 || x === w - 1 || y === h - 1;
      let isBorder = touchesEdge;
      if (!isBorder) {
        const neighbors: Array<[number, number]> = [
          [x + 1, y],
          [x - 1, y],
          [x, y + 1],
          [x, y - 1],
        ];
        for (const [nx, ny] of neighbors) {
          if (grid[ny][nx] !== from) {
            isBorder = true;
            break;
          }
        }
      }
      const shouldRecolor =
        predicate === 'all' ||
        (predicate === 'border' && isBorder) ||
        (predicate === 'interior' && !isBorder);
      if (shouldRecolor) out[y][x] = to;
    }
  }
  return out;
}

/** Ejecuta un unico paso del DSL sobre `grid`. Nunca lanza -- primitivos con params invalidos
 *  (fuera de rango, sin ancla, etc.) degradan a un no-op defensivo (clon sin cambios). */
export function applyStep(step: ProgramStep, grid: Grid, ctx: PrimitiveContext): Grid {
  switch (step.name) {
    case 'translate':
      return applyTranslate(step.params, grid);
    case 'reflect':
      return applyReflect(step.params, grid);
    case 'rotate':
      return applyRotate(step.params, grid);
    case 'recolor':
      return applyRecolor(step.params, grid);
    case 'floodFill':
      return applyFloodFill(step.params, grid);
    case 'cropToBBox':
      return applyCropToBBox(step.params, grid);
    case 'overlay':
      return applyOverlay(step.params, grid, ctx);
    case 'replicate':
      return applyReplicate(step.params, grid);
    case 'objectExtract':
      return applyObjectExtract(step.params, grid);
    case 'conditionalRecolor':
      return applyConditionalRecolor(step.params, grid);
    default: {
      const exhaustive: never = step;
      return exhaustive;
    }
  }
}

/** Ejecuta un programa (secuencia de pasos) sobre `grid`. Programa vacio = identidad. */
export function applyProgram(program: Program, grid: Grid, ctx: PrimitiveContext): Grid {
  return program.reduce<Grid>((acc, step) => applyStep(step, acc, ctx), cloneGrid(grid));
}
