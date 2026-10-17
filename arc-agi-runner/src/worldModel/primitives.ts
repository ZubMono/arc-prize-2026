/* [arc-agi-runner/worldModel/primitives] BL.20860 -- generadores de candidatos DATA-DRIVEN del
   DSL (discuss-context BL.20858) a partir de un par (pre, post) observado. Cada `propose*` se
   auto-verifica (aplica y compara) antes de proponerse -- solo devuelven pasos que YA explican el
   par completo en un solo paso. `enumerateStructuralSteps` es la contraparte CIEGA (sin `post`)
   usada por synthesis.ts para componer varios pasos. Ejecucion del DSL (`applyStep`/
   `applyProgram`) y los tipos viven en primitiveOps.ts (import re-exportado aca). */

import { detectBackgroundColor, foregroundBoundingBox, gridsEqual, type Grid } from './grid';
import { applyStep, type PrimitiveContext, type ProgramStep } from './primitiveOps';

export {
  applyProgram,
  applyStep,
  type ConditionalRecolorParams,
  type CropToBBoxParams,
  type FloodFillParams,
  type ObjectExtractParams,
  type OverlayParams,
  type PrimitiveContext,
  type Program,
  type ProgramStep,
  type RecolorParams,
  type ReflectParams,
  type ReplicateParams,
  type RotateParams,
  type TranslateParams,
} from './primitiveOps';

function proposeTranslate(pre: Grid, post: Grid): ProgramStep[] {
  if (pre.length !== post.length || (pre[0]?.length ?? 0) !== (post[0]?.length ?? 0)) return [];
  const bg = detectBackgroundColor(pre);
  const bboxPre = foregroundBoundingBox(pre, bg);
  const bboxPost = foregroundBoundingBox(post, bg);
  if (!bboxPre || !bboxPost) return [];
  const wPre = bboxPre.maxX - bboxPre.minX;
  const hPre = bboxPre.maxY - bboxPre.minY;
  const wPost = bboxPost.maxX - bboxPost.minX;
  const hPost = bboxPost.maxY - bboxPost.minY;
  if (wPre !== wPost || hPre !== hPost) return [];
  const dx = bboxPost.minX - bboxPre.minX;
  const dy = bboxPost.minY - bboxPre.minY;
  if (dx === 0 && dy === 0) return [];
  const step: ProgramStep = { name: 'translate', params: { dx, dy } };
  return gridsEqual(applyStep(step, pre, {}), post) ? [step] : [];
}

function proposeReflect(pre: Grid, post: Grid): ProgramStep[] {
  const out: ProgramStep[] = [];
  for (const axis of ['horizontal', 'vertical'] as const) {
    const step: ProgramStep = { name: 'reflect', params: { axis } };
    if (gridsEqual(applyStep(step, pre, {}), post)) out.push(step);
  }
  return out;
}

function proposeRotate(pre: Grid, post: Grid): ProgramStep[] {
  const out: ProgramStep[] = [];
  for (const quarterTurns of [1, 2, 3] as const) {
    const step: ProgramStep = { name: 'rotate', params: { quarterTurns } };
    if (gridsEqual(applyStep(step, pre, {}), post)) out.push(step);
  }
  return out;
}

function proposeRecolor(pre: Grid, post: Grid): ProgramStep[] {
  if (pre.length !== post.length) return [];
  const mapping: Record<number, number> = {};
  for (let y = 0; y < pre.length; y++) {
    if (pre[y].length !== post[y].length) return [];
    for (let x = 0; x < pre[y].length; x++) {
      const from = pre[y][x];
      const to = post[y][x];
      if (mapping[from] !== undefined && mapping[from] !== to) return [];
      // @proto-safe: `from` es un valor de celda de Grid (number[][], colores ARC 0-15
      // tipados `number`), nunca una clave de string arbitraria -- no puede ser '__proto__'.
      mapping[from] = to;
    }
  }
  const nonTrivial: Record<number, number> = {};
  let hasChange = false;
  for (const [k, v] of Object.entries(mapping)) {
    if (Number(k) !== v) {
      nonTrivial[Number(k)] = v;
      hasChange = true;
    }
  }
  if (!hasChange) return [];
  return [{ name: 'recolor', params: { mapping: nonTrivial } }];
}

function proposeFloodFill(pre: Grid, post: Grid): ProgramStep[] {
  if (pre.length !== post.length) return [];
  const diffs: Array<[number, number]> = [];
  for (let y = 0; y < pre.length; y++) {
    if (pre[y].length !== post[y].length) return [];
    for (let x = 0; x < pre[y].length; x++) {
      if (pre[y][x] !== post[y][x]) diffs.push([x, y]);
    }
  }
  if (diffs.length === 0) return [];
  const fromColors = new Set(diffs.map(([x, y]) => pre[y][x]));
  const toColors = new Set(diffs.map(([x, y]) => post[y][x]));
  if (fromColors.size !== 1 || toColors.size !== 1) return [];
  const [seedX, seedY] = diffs[0];
  const fromColor = pre[seedY][seedX];
  const region = floodRegionForProposal(pre, seedX, seedY, fromColor);
  if (region.length !== diffs.length) return [];
  const regionSet = new Set(region.map(([x, y]) => `${x},${y}`));
  for (const [x, y] of diffs) {
    if (!regionSet.has(`${x},${y}`)) return [];
  }
  const to = [...toColors][0];
  const step: ProgramStep = { name: 'floodFill', params: { x: seedX, y: seedY, to } };
  return gridsEqual(applyStep(step, pre, {}), post) ? [step] : [];
}

/** Recalcula la region 4-conexa desde una semilla -- misma logica que floodRegion interno de
 *  primitiveOps.ts, reimplementada aca (sin exportar internals) para poder VERIFICAR que el
 *  diff observado es EXACTAMENTE una region completa antes de proponer floodFill. */
function floodRegionForProposal(
  grid: Grid,
  sx: number,
  sy: number,
  color: number,
): Array<[number, number]> {
  const h = grid.length;
  const w = grid[0]?.length ?? 0;
  const visited = new Set<string>();
  const stack: Array<[number, number]> = [[sx, sy]];
  const region: Array<[number, number]> = [];
  while (stack.length > 0) {
    const [x, y] = stack.pop() as [number, number];
    const key = `${x},${y}`;
    if (visited.has(key)) continue;
    if (x < 0 || y < 0 || x >= w || y >= h) continue;
    if (grid[y][x] !== color) continue;
    visited.add(key);
    region.push([x, y]);
    stack.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
  }
  return region;
}

function proposeCropToBBox(pre: Grid, post: Grid): ProgramStep[] {
  const backgroundColor = detectBackgroundColor(pre);
  const step: ProgramStep = { name: 'cropToBBox', params: { backgroundColor } };
  return gridsEqual(applyStep(step, pre, {}), post) ? [step] : [];
}

function proposeOverlay(pre: Grid, post: Grid, ctx: PrimitiveContext): ProgramStep[] {
  if (!ctx.anchorGrid) return [];
  const step: ProgramStep = { name: 'overlay', params: {} };
  return gridsEqual(applyStep(step, pre, ctx), post) ? [step] : [];
}

function proposeReplicate(pre: Grid, post: Grid): ProgramStep[] {
  const preH = pre.length;
  const preW = pre[0]?.length ?? 0;
  const postH = post.length;
  const postW = post[0]?.length ?? 0;
  if (preH === 0 || preW === 0) return [];
  if (postH % preH !== 0 || postW % preW !== 0) return [];
  const timesY = postH / preH;
  const timesX = postW / preW;
  if (timesX === 1 && timesY === 1) return [];
  if (timesX > 6 || timesY > 6) return [];
  const step: ProgramStep = { name: 'replicate', params: { timesX, timesY } };
  return gridsEqual(applyStep(step, pre, {}), post) ? [step] : [];
}

function proposeObjectExtract(pre: Grid, post: Grid): ProgramStep[] {
  const bg = detectBackgroundColor(pre);
  const colors = new Set<number>();
  for (const row of pre) {
    for (const c of row) {
      if (c !== bg) colors.add(c);
    }
  }
  const candidates: Array<number | undefined> = [undefined, ...[...colors].sort((a, b) => a - b)];
  const out: ProgramStep[] = [];
  for (const color of candidates) {
    const step: ProgramStep = {
      name: 'objectExtract',
      params: color === undefined ? {} : { color },
    };
    if (gridsEqual(applyStep(step, pre, {}), post)) out.push(step);
  }
  return out;
}

function proposeConditionalRecolor(pre: Grid, post: Grid): ProgramStep[] {
  if (pre.length !== post.length) return [];
  const diffs: Array<[number, number]> = [];
  for (let y = 0; y < pre.length; y++) {
    if (pre[y].length !== post[y].length) return [];
    for (let x = 0; x < pre[y].length; x++) {
      if (pre[y][x] !== post[y][x]) diffs.push([x, y]);
    }
  }
  if (diffs.length === 0) return [];
  const fromColors = new Set(diffs.map(([x, y]) => pre[y][x]));
  const toColors = new Set(diffs.map(([x, y]) => post[y][x]));
  if (fromColors.size !== 1 || toColors.size !== 1) return [];
  const from = [...fromColors][0];
  const to = [...toColors][0];
  const out: ProgramStep[] = [];
  for (const predicate of ['all', 'border', 'interior'] as const) {
    const step: ProgramStep = { name: 'conditionalRecolor', params: { from, to, predicate } };
    if (gridsEqual(applyStep(step, pre, {}), post)) out.push(step);
  }
  return out;
}

/** Genera TODOS los candidatos data-driven de un solo paso que expliquen `pre -> post` -- cada
 *  uno auto-verificado. Usado como "finisher" en cada nodo de la busqueda de synthesis.ts (tanto
 *  en profundidad 0 como para cerrar la brecha tras expandir pasos estructurales). */
export function proposeAllSteps(pre: Grid, post: Grid, ctx: PrimitiveContext): ProgramStep[] {
  if (gridsEqual(pre, post)) return [];
  return [
    ...proposeTranslate(pre, post),
    ...proposeReflect(pre, post),
    ...proposeRotate(pre, post),
    ...proposeRecolor(pre, post),
    ...proposeFloodFill(pre, post),
    ...proposeCropToBBox(pre, post),
    ...proposeOverlay(pre, post, ctx),
    ...proposeReplicate(pre, post),
    ...proposeObjectExtract(pre, post),
    ...proposeConditionalRecolor(pre, post),
  ];
}

/** Enumeracion CIEGA y acotada de pasos "estructurales" (geometricos, sin necesitar el `post`
 *  final) -- usada por synthesis.ts para EXPANDIR la busqueda mas alla de profundidad 1, ya que
 *  los `propose*` data-driven solo pueden inferir params comparando contra el `post` final (que
 *  en una composicion de 2+ pasos no coincide con el resultado de un paso intermedio). Los
 *  primitivos "semanticos" (recolor/floodFill/overlay/conditionalRecolor) se excluyen aca a
 *  proposito -- solo se prueban como finisher data-driven (proposeAllSteps), nunca a ciegas. */
export function enumerateStructuralSteps(grid: Grid): ProgramStep[] {
  const steps: ProgramStep[] = [];
  // Incluye 0 en cada eje por separado para cubrir desplazamientos puramente horizontales o
  // verticales (dx=0 XOR dy=0) -- solo se excluye (0,0), que seria un no-op.
  const deltas = [-2, -1, 0, 1, 2];
  for (const dx of deltas) {
    for (const dy of deltas) {
      if (dx === 0 && dy === 0) continue;
      steps.push({ name: 'translate', params: { dx, dy } });
    }
  }
  for (const axis of ['horizontal', 'vertical'] as const) {
    steps.push({ name: 'reflect', params: { axis } });
  }
  for (const quarterTurns of [1, 2, 3] as const) {
    steps.push({ name: 'rotate', params: { quarterTurns } });
  }
  for (const timesX of [1, 2, 3]) {
    for (const timesY of [1, 2, 3]) {
      if (timesX === 1 && timesY === 1) continue;
      steps.push({ name: 'replicate', params: { timesX, timesY } });
    }
  }
  steps.push({ name: 'cropToBBox', params: { backgroundColor: detectBackgroundColor(grid) } });
  steps.push({ name: 'objectExtract', params: {} });
  return steps;
}
