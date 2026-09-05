/* [arc-agi-runner/baselineAgent] BL.20775 -- politica de decision del agente baseline MVP: elige
   uniformemente entre las acciones disponibles via un PRNG semillado (reproducible). Alcance MVP
   deliberado (BL.20770-W1C): sin percepcion de la grilla ni planificacion -- eso es una wave
   posterior (harness de aprendizaje real, ver discuss-context de BL.20770). Este agente existe para
   validar el pipeline end-to-end (API, persistencia, timeouts, dead-letter) contra los 25 juegos
   publicos, no para maximizar score. */

import { GRID_MAX_COORD } from './types';
import type { ArcAction, ArcFrameResponse } from './types';

export interface ArcActionDecision {
  action: ArcAction;
  /** Solo presente cuando action === 'ACTION6' (accion compleja x,y). */
  x?: number;
  y?: number;
  /** Razonamiento declarado -- persistido en steps[].reasoning (transparencia/auditoria de replay). */
  reasoning: string;
}

/** Decide la proxima accion dado el frame actual. Pura respecto de `rng` -- mismo frame + mismo
 *  estado del rng producen siempre la misma decision. */
export function decideNextAction(frame: ArcFrameResponse, rng: () => number): ArcActionDecision {
  if (frame.state === 'NOT_STARTED' || frame.available_actions.length === 0) {
    return {
      action: 'RESET',
      reasoning: 'Estado NOT_STARTED o sin acciones disponibles -- se reinicia el juego.',
    };
  }

  const choiceIndex = Math.floor(rng() * frame.available_actions.length);
  const actionNumber = frame.available_actions[choiceIndex];
  const action = `ACTION${actionNumber}` as ArcAction;

  if (action === 'ACTION6') {
    const x = Math.floor(rng() * (GRID_MAX_COORD + 1));
    const y = Math.floor(rng() * (GRID_MAX_COORD + 1));
    return {
      action,
      x,
      y,
      reasoning:
        `Heuristica baseline: ACTION6 (click complejo) en (${x},${y}) elegido al azar entre ` +
        `${frame.available_actions.length} acciones disponibles (seed reproducible).`,
    };
  }

  return {
    action,
    reasoning:
      `Heuristica baseline: ${action} elegida al azar entre ${frame.available_actions.length} ` +
      'acciones disponibles (seed reproducible).',
  };
}
