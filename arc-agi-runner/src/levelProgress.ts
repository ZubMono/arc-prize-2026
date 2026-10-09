/* [arc-agi-runner/levelProgress] BL.21557 -- SENAL DENSA: convierte `levels_completed`/`win_levels`
   (que la API manda en CADA frame y nadie leia) en la metrica de seleccion offline del agente.

   EL PROBLEMA QUE RESUELVE: hasta BL.21557 `result.score` se persistia BINARIO (1 si WIN, 0 si no).
   Las 11 corridas acumuladas en `prometheusEvaluationRuns` valen todas 0, o sea que el harness no
   podia responder la unica pregunta que importa -- "esta version es mejor que la anterior?" -- y
   toda mejora del agente se evaluaba a ciegas.

   POR QUE ESTA ES LA METRICA CORRECTA Y NO UNA INVENCION NUESTRA: el submission.parquet que produce
   el gateway oficial de Kaggle tiene columnas [row_id, game_id, end_of_game, score] con `score`
   ENTERO. El leaderboard del premio da CREDITO PARCIAL por niveles superados. Alinear la metrica
   offline con la del premio evita optimizar una cosa y ser evaluado por otra.

   Modulo PURO (sin red, sin Mongo, sin estado global): lo usan gameRunner.ts (acumulacion en vivo)
   e index.ts (score final + ranking del batch), y se testea sin infraestructura. */

import type { ArcEvaluationRun, ArcFrameResponse } from './types';

/** Progreso de niveles acumulado durante UNA partida. */
export interface LevelProgress {
  /** Maximo `levels_completed` observado. MAXIMO y no "el ultimo": un GAME_OVER puede devolver un
   *  frame con el contador ya reseteado, y perder el pico seria perder justo el credito parcial. */
  maxLevelsCompleted: number;
  /** `win_levels` informado por el juego (niveles totales para ganar). 0 = la API no lo informo. */
  winLevels: number;
}

export const EMPTY_LEVEL_PROGRESS: LevelProgress = Object.freeze({
  maxLevelsCompleted: 0,
  winLevels: 0,
});

/** Entero >= 0 a partir de un campo del wire que podria venir ausente, negativo o no numerico. */
function toCounter(value: unknown): number {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.trunc(n);
}

/** Lectura defensiva de los contadores de un frame. */
export function readFrameLevels(frame: ArcFrameResponse): LevelProgress {
  return {
    maxLevelsCompleted: toCounter(frame?.levels_completed),
    winLevels: toCounter(frame?.win_levels),
  };
}

/** Acumula el progreso de un frame nuevo sobre el acumulado. `winLevels` se queda con el maximo
 *  visto (>0): algunos juegos lo informan recien cuando arranca el primer nivel, y un 0 tardio no
 *  debe borrar el total ya conocido. */
export function accumulateLevelProgress(
  acumulado: LevelProgress,
  frame: ArcFrameResponse,
): LevelProgress {
  const actual = readFrameLevels(frame);
  return {
    maxLevelsCompleted: Math.max(acumulado.maxLevelsCompleted, actual.maxLevelsCompleted),
    winLevels: Math.max(acumulado.winLevels, actual.winLevels),
  };
}

/** Score ENTERO con credito parcial, alineado con el `score` del submission.parquet oficial.
 *  Una victoria nunca puede puntuar menos que 1 aunque el juego no informe niveles: sin ese piso,
 *  un juego de un solo nivel que reporta `levels_completed: 0` al ganar valdria lo mismo que una
 *  derrota, y la regresion frente al comportamiento binario anterior pasaria inadvertida. */
export function computeRunScore(progreso: LevelProgress, won: boolean): number {
  const base = Math.max(0, Math.trunc(progreso.maxLevelsCompleted));
  return won ? Math.max(base, 1) : base;
}

/** Fraccion de juego completada [0,1]. `winLevels` 0 (juego que no lo informa) devuelve 1 si gano y
 *  0 si no: es lo unico que se puede afirmar sin conocer el total. */
export function completionRatio(progreso: LevelProgress, won: boolean): number {
  if (progreso.winLevels <= 0) return won ? 1 : 0;
  const ratio = progreso.maxLevelsCompleted / progreso.winLevels;
  return Math.min(1, Math.max(0, ratio));
}

export interface RunLevelSummary {
  runId: string;
  environmentId: string;
  modelId: string;
  maxLevelReached: number;
  winLevels: number;
  score: number;
  success: boolean;
}

/** Resumen por corrida a partir de lo persistido. Tolera corridas viejas (anteriores a BL.21557)
 *  sin los campos nuevos: caen a 0, que es literalmente lo que se sabe de ellas. */
export function summarizeRun(run: ArcEvaluationRun): RunLevelSummary {
  return {
    runId: run.runId,
    environmentId: run.environmentId,
    modelId: run.modelId,
    maxLevelReached: toCounter(run.result?.maxLevelReached),
    winLevels: toCounter(run.result?.winLevels),
    score: toCounter(run.result?.score),
    success: Boolean(run.result?.success),
  };
}

/** METRICA DE SELECCION OFFLINE. Ordena corridas de mejor a peor: primero score (credito parcial),
 *  luego fraccion de juego completada (desempata entre juegos de distinta longitud), luego victoria
 *  y finalmente runId para que el orden sea TOTAL y estable -- dos ejecuciones del selector sobre el
 *  mismo conjunto deben elegir el mismo ganador o la comparacion entre versiones no es reproducible. */
export function rankRunsByLevelProgress(runs: ArcEvaluationRun[]): RunLevelSummary[] {
  return runs.map(summarizeRun).sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    const ratioA = completionRatio(
      { maxLevelsCompleted: a.maxLevelReached, winLevels: a.winLevels },
      a.success,
    );
    const ratioB = completionRatio(
      { maxLevelsCompleted: b.maxLevelReached, winLevels: b.winLevels },
      b.success,
    );
    if (ratioB !== ratioA) return ratioB - ratioA;
    if (a.success !== b.success) return a.success ? -1 : 1;
    return a.runId.localeCompare(b.runId);
  });
}

/** Agregado del batch, para el log de cierre. `totalScore` es la suma de credito parcial: es el
 *  numero que hay que ver SUBIR entre versiones del agente. */
export function summarizeBatchLevels(runs: ArcEvaluationRun[]): {
  totalScore: number;
  bestRun: RunLevelSummary | null;
  runsConProgreso: number;
} {
  const ranking = rankRunsByLevelProgress(runs);
  return {
    totalScore: ranking.reduce((acc, r) => acc + r.score, 0),
    bestRun: ranking[0] ?? null,
    runsConProgreso: ranking.filter((r) => r.score > 0).length,
  };
}

/** Linea de log en espanol para el cierre del batch (texto visible: siempre espanol). */
export function formatBatchLevelSummary(runs: ArcEvaluationRun[]): string {
  const { totalScore, bestRun, runsConProgreso } = summarizeBatchLevels(runs);
  if (!bestRun) return 'senal densa: sin corridas en el batch.';
  const mejor =
    bestRun.score > 0
      ? `mejor: ${bestRun.environmentId} con nivel ${bestRun.maxLevelReached}` +
        (bestRun.winLevels > 0 ? `/${bestRun.winLevels}` : '')
      : 'mejor: ninguna corrida supero un solo nivel';
  return (
    `senal densa: score total ${totalScore} (credito parcial por niveles), ` +
    `${runsConProgreso}/${runs.length} corrida(s) con progreso. ${mejor}.`
  );
}
