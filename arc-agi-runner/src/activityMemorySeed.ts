/* [arc-agi-runner/activityMemorySeed] BL.20861 -- lado PUBLICO de la memoria que persiste entre
   corridas. Espejo manual de packages/api/prometheusActivityMemory/{types,seed}.ts.

   Por que un espejo y no un import: aislamiento critico (ver CLAUDE.md) -- este proyecto no puede
   depender de packages/* porque se abre bajo licencia de dominio publico si se compite por el ARC
   Prize 2026 (MIT-0/CC0, ver BL.21045). Es el TERCER
   lado del mirror manual, junto al contrato de escritura de types.ts y a computeRunExpiryDate.

   A diferencia de esos dos, aca se espeja LOGICA (los umbrales de filtrado), no solo un shape. Ese
   riesgo esta cubierto por activityMemorySeed.contract.test.ts: lee el archivo privado COMO TEXTO
   (sin importarlo -- cero acoplamiento de runtime) y falla si los umbrales divergen. Si el
   proyecto se extrae standalone y el archivo privado no existe, ese test se saltea solo. */

/** Acciones que no producen cambio en un estado dado -- el agente las salta en vez de gastarlas. */
export interface SeededNonOp {
  fromStateSignature: string;
  action: string;
}

/** Plan que ya llevo al exito. Sin score embebido: el score vive solo en
 *  prometheusEvaluationRuns.result.score (regla critica de BL.20859). */
export interface SeededPlan {
  actions: string[];
  validatedByRuns: number;
}

export interface SeededTransition {
  fromStateSignature: string;
  action: string;
  toStateSignature: string;
}

export interface ActivityMemorySeed {
  activityId: string;
  nonOps: SeededNonOp[];
  plans: SeededPlan[];
  transitions: SeededTransition[];
  /** true si la memoria no tenia nada utilizable -- arranque frio (el caso NORMAL en la corrida 1
   *  de una actividad, nunca un error). */
  isCold: boolean;
  /** BL.21499 -- true cuando NO existia documento de memoria para esta actividad.
   *
   *  `isCold` refleja UTILIDAD, no EXISTENCIA: da true tanto para "primera vez que se juega"
   *  como para "ya se jugo pero la memoria quedo vacia", y esos dos casos exigen acciones
   *  opuestas (el primero es normal y se resuelve solo; el segundo significa que el destilador
   *  no esta corriendo). Sin este campo son indistinguibles desde afuera, que es exactamente lo
   *  que oculto durante una semana que el ciclo de destilacion nunca proceso una corrida de ARC:
   *  el log decia "en frio" partida tras partida y se leia como si fuera siempre la primera. */
  sinDocumento: boolean;
}

/* ─── Umbrales espejados de packages/api/prometheusActivityMemory/seed.ts ─────────────────────
   Si cambian alla, cambian aca: activityMemorySeed.contract.test.ts falla el build si divergen. */

/** Confianza minima para sembrar una transicion. Beta(1,1) da 0.5, asi que 0.6 exige evidencia
 *  POSITIVA neta -- sembrar con basura es peor que no sembrar (el agente evitaria lo que funciona). */
export const SEED_MIN_CONFIDENCE = 0.6;

/** Un no-op con 1 sola observacion podria ser ruido del entorno (frame identico por lag, no por la
 *  accion). Se exige confirmacion independiente antes de dejar de probar esa accion. */
export const SEED_MIN_NONOP_CONFIRMATIONS = 2;

/** Media de una Beta(successes, failures) con prior uniforme -- espejo de evictionPolicy.ts. */
export function betaMean(confidence: { successes: number; failures: number }): number {
  const alpha = confidence.successes + 1;
  const beta = confidence.failures + 1;
  return alpha / (alpha + beta);
}

/** Semilla fria valida -- lo que ve una actividad nunca jugada.
 *  `sinDocumento` por defecto true: este helper representa justamente el caso "no habia doc".
 *  Se puede forzar a false para el caso "el doc existia pero no aporto nada" (BL.21499). */
export function coldSeed(activityId: string, sinDocumento = true): ActivityMemorySeed {
  return { activityId, nonOps: [], plans: [], transitions: [], isCold: true, sinDocumento };
}

/** Shape MINIMO del doc de memoria que este proyecto necesita leer. Deliberadamente parcial: el
 *  doc privado tiene invariants/subGoals/stats/locks que el runner no consume, y tipar solo lo
 *  usado achica la superficie del espejo que hay que mantener a mano. */
export interface ActivityMemoryDocLike {
  activityId: string;
  knownTransitions?: Array<{
    fromStateSignature: string;
    action: string;
    toStateSignature: string;
    confidence: { successes: number; failures: number };
  }>;
  nonOpActions?: Array<{ fromStateSignature: string; action: string; confirmedCount: number }>;
  successfulPlans?: Array<{ actions: string[]; evaluationRefs?: Array<{ runId: string }> }>;
}

/**
 * Construye la semilla desde el doc de memoria. Espejo funcional de
 * `buildActivityMemorySeed` -- funcion PURA: filtrar por confianza es politica, no I/O.
 *
 * `null` (actividad nunca vista) devuelve semilla fria en vez de lanzar.
 */
export function buildSeedFromDoc(
  doc: ActivityMemoryDocLike | null,
  activityId: string,
): ActivityMemorySeed {
  if (doc === null) return coldSeed(activityId);

  const nonOps = (doc.nonOpActions ?? [])
    .filter((n) => n.confirmedCount >= SEED_MIN_NONOP_CONFIRMATIONS)
    .map((n) => ({ fromStateSignature: n.fromStateSignature, action: n.action }));

  const transitions = (doc.knownTransitions ?? [])
    .filter((t) => betaMean(t.confidence) >= SEED_MIN_CONFIDENCE)
    .map((t) => ({
      fromStateSignature: t.fromStateSignature,
      action: t.action,
      toStateSignature: t.toStateSignature,
    }));

  /* Orden: primero el plan mas corto; a igual largo, el mas validado. El largo manda porque ARC
     penaliza cada accion de mas de forma CUADRATICA (score = min(humano/agente,1)^2) -- un plan 2
     acciones mas corto vale mas que uno con una validacion extra. */
  const plans = (doc.successfulPlans ?? [])
    .filter((p) => p.actions.length > 0)
    .map((p) => ({ actions: p.actions, validatedByRuns: (p.evaluationRefs ?? []).length }))
    .sort((a, b) => a.actions.length - b.actions.length || b.validatedByRuns - a.validatedByRuns);

  return {
    activityId: doc.activityId,
    nonOps,
    plans,
    transitions,
    isCold: nonOps.length === 0 && plans.length === 0 && transitions.length === 0,
    // El doc EXISTE (el early-return de arriba cubre el caso null), asi que si esta semilla sale
    // fria no es "primera vez": es memoria registrada que no aporto nada utilizable.
    sinDocumento: false,
  };
}
