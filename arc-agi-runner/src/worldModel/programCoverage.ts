/* [arc-agi-runner/worldModel/programCoverage] BL.21561 -- cuanto de la evidencia explica un
   programa del DSL. Separado de synthesis.ts (limite de 500 lineas) pero conceptualmente parte de
   la sintesis: es el criterio con el que se acepta o se descarta una hipotesis.

   POR QUE DEJO DE SER UN BOOLEANO. `verifyProgram` exigia que TODAS las observaciones encajaran con
   cero contradicciones, asi que una regla CORRECTA moria en la primera observacion que no encajaba
   -- y en ARC-AGI-3 esa observacion llega siempre: es el choque contra la pared. "Mover a la
   izquierda" explica 9 de cada 10 pasos y falla el decimo porque el cursor ya estaba pegado al
   borde; con cero tolerancia el agente concluye que no entiende la accion y vuelve a explorar al
   azar. La cobertura puntuada conserva la regla y manda los fallos a la Beta(alpha, beta), que es
   donde el modelo de mundo ya representa la incertidumbre. */

import { gridsEqual, type Grid } from './grid';
import { applyProgram, type PrimitiveContext, type Program } from './primitiveOps';

/** Un par (frame_pre, frame_post) observado tras ejecutar una accion. Vive aca y no en
 *  synthesis.ts porque este modulo es el que lo consume primero; synthesis.ts lo re-exporta para
 *  que sus consumidores historicos no cambien de import. */
export interface Observation {
  pre: Grid;
  post: Grid;
}

/** Cobertura minima para aceptar un programa como hipotesis vigente. Por debajo, la "regla" no
 *  explica ni dos de cada tres observaciones: es ruido y conviene decir `null`. */
export const MIN_PROGRAM_COVERAGE = 0.6;

export interface CoberturaDePrograma {
  aciertos: number;
  fallos: number;
  /** aciertos / (aciertos + fallos). Sin observaciones vale 1 (nada que contradiga). */
  cobertura: number;
}

/** Cuenta cuantas observaciones reproduce el programa y cuantas no -- la evidencia con la que se
 *  alimenta la Beta(alpha, beta) de la transicion. */
export function programCoverage(
  program: Program,
  observations: Observation[],
  ctx: PrimitiveContext = {},
): CoberturaDePrograma {
  let aciertos = 0;
  let fallos = 0;
  for (const obs of observations) {
    if (gridsEqual(applyProgram(program, obs.pre, ctx), obs.post)) aciertos++;
    else fallos++;
  }
  const total = aciertos + fallos;
  return { aciertos, fallos, cobertura: total === 0 ? 1 : aciertos / total };
}

/** Igual que `programCoverage` pero ABANDONA en cuanto el candidato ya no puede llegar a
 *  `minCoverage` (devuelve `null`). Es lo que mantiene el costo de la sintesis donde estaba: la
 *  verificacion de cero tolerancia cortaba en el PRIMER fallo, y contar siempre las N
 *  observaciones multiplicaba por N el precio de descartar un candidato malo -- medido, el test de
 *  episodio completo de BL.21558 pasaba de 9s a mas de 30s bajo carga.
 *
 *  Recorre de la observacion MAS NUEVA a la mas vieja: tras una contradiccion, la evidencia que
 *  descarta al candidato suele ser la ultima, asi que el abandono llega en el primer paso. */
export function coberturaSuficiente(
  program: Program,
  observations: Observation[],
  ctx: PrimitiveContext = {},
  minCoverage = MIN_PROGRAM_COVERAGE,
): CoberturaDePrograma | null {
  const total = observations.length;
  if (total === 0) return { aciertos: 0, fallos: 0, cobertura: 1 };
  const fallosTolerados = Math.floor(total * (1 - minCoverage));
  let aciertos = 0;
  let fallos = 0;
  for (let i = total - 1; i >= 0; i--) {
    const obs = observations[i];
    if (gridsEqual(applyProgram(program, obs.pre, ctx), obs.post)) aciertos++;
    else if (++fallos > fallosTolerados) return null;
  }
  return { aciertos, fallos, cobertura: aciertos / total };
}

/** Verificacion de CERO tolerancia. Sigue siendo la regla dura para preguntas de "esto encaja
 *  exacto?" -- por ejemplo, si la hipotesis vigente sobrevive a la ultima observacion. La
 *  SELECCION de hipotesis ya no la usa: ver `synthesizeProgramScored` en synthesis.ts. */
export function verifyProgram(
  program: Program,
  observations: Observation[],
  ctx: PrimitiveContext = {},
): boolean {
  return observations.every((obs) => gridsEqual(applyProgram(program, obs.pre, ctx), obs.post));
}
