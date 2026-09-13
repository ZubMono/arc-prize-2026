/* [arc-agi-runner/worldModel/stateSignature] BL.20860 -- firma hasheable de un estado (grilla +
   acciones disponibles) y deteccion de no-ops entre frames sucesivos. Idea reusada de
   arc-agi3-kaggle-agent/arc_agent/policy.py::compute_signature (BL.20783, politica con memoria
   intra-episodio) -- reimplementada aca sobre nuestro tipo Grid en vez de reusar el codigo
   directamente (aislamiento critico del proyecto, ver CLAUDE.md: sin dependencias cruzadas entre
   projects/arc-agi-runner y projects/arc-agi3-kaggle-agent). */

import type { ArcFrameResponse } from '../types';
import { gridsEqualMasked, hashGridMasked, type Grid, type VolatilityMask } from './grid';

/** Grilla observable de un frame: la API devuelve UNA O MAS capas consecutivas (`frame.frame` es
 *  `number[][][]`) y la ultima es el estado visible tras aplicar el comando. `null` cuando el
 *  frame no trae capas o la ultima viene vacia -- ningun consumidor debe asumir grilla presente.
 *  Fuente unica: la usan la politica (intelligentPolicy.ts) y el runner (gameRunner.ts), que
 *  DEBEN coincidir en que es "el estado" o la firma persistida describiria otra cosa que la que
 *  vio quien decidio. */
export function extractGrid(frame: ArcFrameResponse): Grid | null {
  const layers = frame.frame;
  if (!layers || layers.length === 0) return null;
  const last = layers[layers.length - 1];
  if (!last || last.length === 0) return null;
  return last;
}

/** Firma de un frame completo, lista para persistir en `ArcEvaluationStep`. `null` (frame sin
 *  grilla) devuelve `undefined` en vez de una firma inventada: el distilador trata el campo
 *  ausente como "sin evidencia" y no como "no hubo cambio", que es exactamente lo correcto --
 *  afirmar una firma falsa marcaria transiciones reales como no-ops. */
export function computeFrameSignature(
  frame: ArcFrameResponse,
  mask: VolatilityMask | null = null,
): string | undefined {
  const grid = extractGrid(frame);
  if (grid === null) return undefined;
  return String(computeStateSignature(grid, frame.available_actions ?? [], mask));
}

/** Firma entera estable de un estado -- combina el hash de la grilla con las acciones
 *  disponibles (normalizadas: orden no importa, se ordenan antes de mezclar). Dos frames con la
 *  MISMA firma se consideran el mismo estado a efectos de memoria de exploracion
 *  (activeLearning.ts) y deduplicacion de nodos visitados (planner.ts).
 *
 *  BL.21558 -- `mask` firma SOLO las celdas estables. Sin ella, un contador de HUD que avanza en
 *  cada frame hace que ninguna firma se repita jamas (medido: 150 firmas de origen distintas en
 *  153 transiciones destiladas de ar25-0c556536) y toda la memoria por-estado queda inerte. El
 *  default `null` conserva la firma historica exacta -- las corridas ya persistidas siguen siendo
 *  comparables consigo mismas. */
export function computeStateSignature(
  grid: Grid,
  availableActions: number[],
  mask: VolatilityMask | null = null,
): number {
  let hash = hashGridMasked(grid, mask);
  const sorted = [...availableActions].sort((a, b) => a - b);
  for (const action of sorted) {
    hash ^= action + 0x9e3779b9 + (hash << 6) + (hash >>> 2);
    hash = hash >>> 0;
  }
  return hash;
}

/** True cuando una accion NO cambio nada visible en la grilla -- no-op observado. `null` en
 *  cualquiera de los dos lados (sin grilla previa/actual conocida) nunca se afirma no-op: no hay
 *  evidencia suficiente.
 *
 *  BL.21558 -- con `mask`, "nada visible" excluye las celdas volatiles. Ese es el punto: sin
 *  mascara, en ar25-0c556536 se detecto UN solo no-op en 77 pasos pese a que la politica hacia
 *  round-robin contra las paredes del tablero. */
export function isNoOpTransition(
  before: Grid | null,
  after: Grid | null,
  mask: VolatilityMask | null = null,
): boolean {
  if (before === null || after === null) return false;
  return gridsEqualMasked(before, after, mask);
}
