/* [arc-agi-runner/deadLetterTracker] BL.20775 -- cuenta fallas de API CONSECUTIVAS por juego; al
   alcanzar el tope (diseno: 3) marca el juego como dead-letter -- el runner deja de reintentar ESE
   juego y sigue con el siguiente en vez de colgarse reintentando indefinidamente. */

export interface DeadLetterTracker {
  /** Registra una falla de API. Devuelve true si esta llamada dispara el dead-letter. */
  recordFailure(): boolean;
  /** Registra un exito -- reinicia el contador de fallas consecutivas (no revierte un dead-letter
   *  ya disparado: una vez marcado, el juego queda descartado para esta corrida). */
  recordSuccess(): void;
  isDeadLettered(): boolean;
  failureCount(): number;
}

/** Crea un tracker de dead-letter con tope `maxFailures` de fallas consecutivas. */
export function createDeadLetterTracker(maxFailures: number): DeadLetterTracker {
  let failures = 0;
  let deadLettered = false;

  return {
    recordFailure(): boolean {
      failures += 1;
      if (failures >= maxFailures) deadLettered = true;
      return deadLettered;
    },
    recordSuccess(): void {
      failures = 0;
    },
    isDeadLettered(): boolean {
      return deadLettered;
    },
    failureCount(): number {
      return failures;
    },
  };
}
