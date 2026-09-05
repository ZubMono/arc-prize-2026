/* [arc-agi-runner/worldModel/transitionMemory] BL.20860 -- modelo de mundo tipo STRIPS aprendido
   POR ACCION: mantiene observaciones (frame_pre, frame_post) capadas y sintetiza (synthesis.ts)
   el programa DSL que las explica sin contradicciones. Confianza como distribucion Beta
   (alpha=exitos, beta=fracasos -- NUNCA un booleano, discuss-context BL.20858).

   Shape de KnownTransition espejado a proposito del futuro `prometheusActivityMemory.
   knownTransitions[]` (BL.20859, wave 1 del epico -- aun sin implementar al momento de este BL):
   el campo `program` de una KnownTransition ES el programa verificado de synthesis.ts, no un
   sistema paralelo. Esta clase vive SOLO en memoria del proceso (un episodio de juego) -- la
   persistencia entre episodios hacia esa coleccion es responsabilidad de una wave posterior que
   integre este motor con Mongo. */

import { neutralizeVolatileCells, type Grid, type VolatilityMask } from './grid';
import { MechanicsMemory, type HipotesisDeMecanica } from './mechanicsMemory';
import { detectarMecanica, type Mecanica } from './objectMechanics';
import { applyProgram, type PrimitiveContext, type Program } from './primitiveOps';
import { synthesizeProgramScored, verifyProgram, type Observation } from './synthesis';
import { VolatilityTracker } from './volatilityMask';

/** Tope de observaciones retenidas POR ACCION -- eviction FIFO simple (mas nueva reemplaza mas
 *  vieja). Analogo acotado a la eviction por confidence x recencia x generalidad prevista para
 *  la coleccion persistente (BL.20859); aca alcanza con no crecer sin cota dentro de un episodio. */
const MAX_OBSERVATIONS_PER_ACTION = 20;

/** Profundidad de sintesis usada al re-sintetizar tras cada observacion -- ver synthesis.ts. */
const SYNTHESIS_MAX_DEPTH = 3;

/** BL.21500 -- observaciones minimas antes de que un programa-identidad cuente como no-op a
 *  efectos de EXCLUIR la accion de la exploracion (ver `isKnownNoOp`). 3 y no 1 porque las
 *  acciones parametrizadas por coordenada (ACTION6, el click) son no-op en la mayoria de las
 *  celdas y significativas en unas pocas: con 1 sola observacion se perdia la accion entera.
 *  Tampoco conviene mucho mas alto: cada observacion de mas es un paso gastado del presupuesto
 *  del juego en una accion que probablemente no haga nada. */
const MIN_OBSERVATIONS_FOR_NOOP = 3;

/** BL.21558 -- cuantas REVISIONES de la mascara de volatilidad disparan una re-sintesis completa
 *  (todas las acciones, no solo la observada). Hace falta porque la mascara es una PREMISA de cada
 *  hipotesis: un programa sintetizado antes de saber que el contador del HUD era ruido explica ese
 *  ruido, y queda congelado si la accion no vuelve a observarse -- que es exactamente lo que pasa,
 *  porque un programa no trivial la manda al fondo del ranking de exploracion.
 *
 *  El tope existe para acotar el costo: cada revision cuesta una sintesis por accion. La mascara
 *  converge en las primeras decenas de pasos (la histeresis de volatilityMask.ts impide que
 *  oscile), asi que 10 revisiones cubren de sobra el arranque; pasado el tope se sigue
 *  re-sintetizando la accion observada, que es el caso barato y llega igual, solo mas tarde. */
const MAX_MASK_REVISIONS_RESYNTHESIZED = 10;

export interface KnownTransition {
  action: string;
  /** Programa DSL verificado contra TODAS las observaciones retenidas -- `null` si aun no hay
   *  una hipotesis sin contradicciones (accion todavia no comprendida). */
  program: Program | null;
  /** Beta(alpha, beta) -- exitos/fracasos de la hipotesis ACTUAL, no un booleano. */
  alpha: number;
  beta: number;
  /** Total de veces que se observo esta accion (crece mas alla de la ventana capada). */
  observationCount: number;
  /** Cuantas veces una hipotesis previamente confirmada fue contradicha por evidencia nueva. */
  contradictionCount: number;
  /** BL.21561 -- fraccion de las observaciones RETENIDAS que el programa vigente reproduce. 1 = la
   *  regla no falla nunca (lo unico que antes se aceptaba); 0.8 = falla una de cada cinco, tipico
   *  de una regla de movimiento que choca contra la pared. `0` cuando no hay programa. */
  coverage: number;
}

export class TransitionMemory {
  private readonly observations = new Map<string, Observation[]>();
  private readonly transitions = new Map<string, KnownTransition>();
  private readonly ctx: PrimitiveContext;
  /** BL.21558 -- que celdas del frame cambian sin relacion con la accion (HUD/contador). Vive aca
   *  y no en la politica porque se aprende del MISMO flujo de observaciones que alimenta la
   *  sintesis: una sola fuente, imposible que las dos se desincronicen. */
  private readonly volatility = new VolatilityTracker();
  /** BL.21561 -- analizador OBJETO-CENTRICO (objectMechanics.ts). Corre sobre el MISMO flujo de
   *  observaciones que la sintesis DSL y es el que de verdad nombra la mecanica de la accion: en
   *  dato real el DSL confirma la identidad y nada mas, mientras que este recupera el mapeo
   *  ACTION1..4 -> arriba/abajo/izquierda/derecha en los cuatro juegos medidos. */
  private readonly mechanics = new MechanicsMemory();
  /** Version de la mascara con la que estan sintetizadas las hipotesis vigentes. */
  private maskVersionSincronizada = 0;
  private revisionesResintetizadas = 0;

  constructor(ctx: PrimitiveContext = {}) {
    this.ctx = ctx;
  }

  /** Registra el efecto observado de `action`: `pre` -> `post`. Actualiza (o sintetiza desde
   *  cero) la KnownTransition de esa accion.
   *
   *  BL.21558 -- la ventana guarda las grillas CRUDAS y el enmascarado se aplica recien al
   *  sintetizar/verificar. Guardar ya neutralizado seria un bug sutil: la mascara CRECE durante el
   *  episodio, y las observaciones viejas habrian quedado congeladas con una mascara mas chica --
   *  o sea, con ruido de HUD adentro que ninguna hipotesis puede explicar, envenenando la sintesis
   *  justo cuando por fin se sabe que ignorar. */
  recordObservation(action: string, pre: Grid, post: Grid): void {
    this.volatility.observe(action, pre, post);

    const window = this.observations.get(action) ?? [];
    window.push({ pre, post });
    if (window.length > MAX_OBSERVATIONS_PER_ACTION) window.shift();
    this.observations.set(action, window);

    const mask = this.volatility.mask;
    /* BL.21561 -- el analizador objeto-centrico ve el par CRUDO con la mascara vigente: no
       necesita que le neutralicen nada porque ya ignora las celdas volatiles el mismo. */
    this.mechanics.observe(action, pre, post, mask);

    const maskedWindow = maskObservations(window, mask);
    const lastObservation = maskedWindow[maskedWindow.length - 1];

    /* BL.21558 -- la mascara cambio: toda hipotesis vigente se dedujo bajo OTRAS premisas y hay
       que rehacerla. Sin esto el fix no llega a la partida: medido en el entorno sintetico con
       HUD, la accion inerte se observaba en el paso 4 (mascara todavia vacia), la sintesis
       encontraba un programa de UN paso que "explicaba" el avance del contador, y ese programa no
       trivial la mandaba al fondo del ranking -- 1 sola aparicion en 80 pasos, calcado del
       ACTION6 que aparece 1 vez en 78 pasos de ar25-0c556536. */
    const mascaraCambio = this.volatility.version !== this.maskVersionSincronizada;
    if (mascaraCambio) {
      this.maskVersionSincronizada = this.volatility.version;
      if (this.revisionesResintetizadas < MAX_MASK_REVISIONS_RESYNTHESIZED) {
        this.revisionesResintetizadas += 1;
        this.resintetizarOtrasAcciones(action, mask);
      }
    }

    const previous = this.transitions.get(action);
    const observationCount = (previous?.observationCount ?? 0) + 1;
    let alpha = previous?.alpha ?? 1;
    let beta = previous?.beta ?? 1;
    let contradictionCount = previous?.contradictionCount ?? 0;
    let program = previous?.program ?? null;
    let coverage = previous?.coverage ?? 0;

    const hadConfirmedProgram = previous !== undefined && previous.program !== null;
    /* Con la mascara recien cambiada NO se acepta la hipotesis previa aunque verifique contra la
       ultima observacion: se dedujo mirando celdas que ahora se sabe que son ruido, asi que se
       rehace sobre la ventana COMPLETA reenmascarada. */
    const stillHolds =
      hadConfirmedProgram &&
      !mascaraCambio &&
      verifyProgram(previous!.program as Program, [lastObservation], this.ctx);

    if (stillHolds) {
      alpha += 1;
    } else {
      /* Una hipotesis descartada por CAMBIO DE PREMISAS (la mascara) no es una contradiccion de la
         evidencia: no dice nada sobre lo predecible que es la accion. Contarla como fracaso
         hundiria la confianza de acciones que nunca fallaron. */
      if (hadConfirmedProgram && !mascaraCambio) contradictionCount += 1;
      /* BL.21561 -- se acepta el programa de MAYOR cobertura y sus fallos se contabilizan en beta
         en vez de matar la hipotesis. alpha/beta describen la hipotesis VIGENTE, y esta es NUEVA:
         se recalculan desde su propia evidencia sobre la ventana, con prior Beta(1,1). */
      const puntuado = synthesizeProgramScored(maskedWindow, this.ctx, SYNTHESIS_MAX_DEPTH);
      program = puntuado.program;
      alpha = 1 + puntuado.aciertos;
      beta = 1 + puntuado.fallos;
    }
    coverage = program === null ? 0 : coberturaDeBeta(alpha, beta);

    this.transitions.set(action, {
      action,
      program,
      alpha,
      beta,
      observationCount,
      contradictionCount,
      coverage,
    });
  }

  getTransition(action: string): KnownTransition | undefined {
    return this.transitions.get(action);
  }

  getKnownTransitions(): KnownTransition[] {
    return [...this.transitions.values()];
  }

  /** Confianza actual (0-1) en la hipotesis vigente de `action`. Prior uniforme (0.5) si nunca
   *  se observo. */
  getConfidence(action: string): number {
    const t = this.transitions.get(action);
    if (!t) return 0.5;
    return t.alpha / (t.alpha + t.beta);
  }

  /** Predice el resultado de aplicar `action` sobre `grid` usando el programa confirmado --
   *  `null` si la accion aun no tiene una hipotesis sin contradicciones. */
  predict(action: string, grid: Grid): Grid | null {
    const t = this.transitions.get(action);
    if (!t || t.program === null) return null;
    return applyProgram(t.program, grid, this.ctx);
  }

  /** True si la accion tiene un programa confirmado y ese programa es la identidad (no cambia
   *  nada) -- no-op conocido, tal como `no_op_actions` en policy.py (BL.20783) pero derivado del
   *  mismo mecanismo de sintesis, no de un chequeo separado.
   *
   *  BL.21500 -- exige MIN_OBSERVATIONS_FOR_NOOP observaciones antes de afirmarlo. Con una sola,
   *  `synthesizeProgram` devuelve el programa vacio en cuanto ve un pre===post (la identidad
   *  explica esa unica observacion a la perfeccion), y `activeLearning` retiraba la accion de
   *  los candidatos PARA SIEMPRE. Medido en juego real (ar25-0c556536): ACTION6 -- el click, la
   *  accion mas expresiva del juego -- se probo UNA vez en el paso 2 y no volvio a usarse en los
   *  76 pasos restantes. En ARC-AGI-3 ACTION6 se parametriza por coordenadas: es no-op donde no
   *  hay nada y significativa en otro lado, asi que una observacion NUNCA alcanza para
   *  descartarla. La sintesis sigue concluyendo identidad igual (`getTransition().program` no
   *  cambia); lo que cambia es cuando esa conclusion habilita a EXCLUIR la accion. */
  isKnownNoOp(action: string): boolean {
    const t = this.transitions.get(action);
    if (t?.program === undefined || t.program === null || t.program.length !== 0) return false;
    /* BL.21561 -- con cobertura puntuada, un programa puede ser "el que mejor explica" sin explicar
       todo. Para EXCLUIR una accion se sigue exigiendo evidencia exacta: una identidad que falla
       una de cada cinco veces significa que la accion SI hace algo a veces. */
    if (t.coverage < 1) return false;
    /* Y si el analizador objeto-centrico vio a esta accion mover un objeto, no es un no-op por
       mas que la ventana retenida de la sintesis diga identidad. */
    if (this.mechanics.getDirection(action) !== null) return false;
    return t.observationCount >= MIN_OBSERVATIONS_FOR_NOOP;
  }

  getObservationCount(action: string): number {
    return this.transitions.get(action)?.observationCount ?? 0;
  }

  /** Rehace la hipotesis de todas las acciones MENOS la que se esta observando (esa la rehace el
   *  flujo normal de `recordObservation`, que ya tiene la ventana actualizada). Se sintetiza sobre
   *  la ventana cruda reenmascarada con la mascara nueva, y la confianza vuelve al prior: alpha y
   *  beta describen los exitos/fracasos de la hipotesis VIGENTE, y esta es otra. */
  private resintetizarOtrasAcciones(actual: string, mask: VolatilityMask | null): void {
    for (const [accion, window] of this.observations) {
      if (accion === actual) continue;
      const previa = this.transitions.get(accion);
      if (previa === undefined) continue;
      const puntuado = synthesizeProgramScored(
        maskObservations(window, mask),
        this.ctx,
        SYNTHESIS_MAX_DEPTH,
      );
      const alpha = 1 + puntuado.aciertos;
      const beta = 1 + puntuado.fallos;
      this.transitions.set(accion, {
        ...previa,
        program: puntuado.program,
        alpha,
        beta,
        coverage: puntuado.program === null ? 0 : coberturaDeBeta(alpha, beta),
      });
    }
  }

  /** BL.21558 -- mascara de volatilidad vigente (`null` mientras no haya evidencia suficiente).
   *  La exponen la politica y el runner para firmar estados y comparar frames sobre las MISMAS
   *  celdas que el modelo de mundo considera informativas. */
  getVolatilityMask(): VolatilityMask | null {
    return this.volatility.mask;
  }

  /** Version del conjunto de celdas volatiles -- cambia cuando la mascara cambia. Quien compare
   *  dos firmas calculadas en momentos distintos tiene que verificar que sean de la MISMA version,
   *  o estaria comparando hashes de dos definiciones de "estado". */
  getVolatilityVersion(): number {
    return this.volatility.version;
  }

  /** Celdas actualmente enmascaradas -- solo para observabilidad (logs y tests de efecto). */
  getVolatileCellCount(): number {
    return this.volatility.volatileCellCount();
  }

  /** BL.21561 -- mecanica de objetos dominante de `action` (traslacion / recoloreo / aparicion /
   *  desaparicion / sinCambio) con su Beta. `undefined` si la accion nunca se observo. */
  getMechanic(action: string): HipotesisDeMecanica | undefined {
    return this.mechanics.getHypothesis(action);
  }

  /** BL.21561 -- direccion (dy,dx) que `action` imprime al objeto controlado, o `null` si no
   *  mueve nada / falta evidencia. ES el mapeo ACTION1..5 -> direccion que el DSL global nunca
   *  pudo dar sobre dato real. */
  getMovementDirection(action: string): { dy: number; dx: number } | null {
    return this.mechanics.getDirection(action);
  }

  /** BL.21561 -- analizador objeto-centrico completo: detectores de marco estatico (4) y de
   *  contadores monotonos (5), ademas de las hipotesis por accion. */
  getMechanicsMemory(): MechanicsMemory {
    return this.mechanics;
  }

  /** BL.21561 -- mecanica detectada para un par suelto, sin registrarla. Util para inspeccionar
   *  una transicion candidata con la mascara ya aprendida del episodio. */
  analyzeTransition(pre: Grid, post: Grid): Mecanica {
    return detectarMecanica(pre, post, this.volatility.mask);
  }
}

/** Aplica la mascara a una ventana de observaciones: cada `post` pasa a tener, en las celdas
 *  volatiles, el mismo valor que su `pre`. Asi la sintesis solo tiene que explicar el cambio REAL
 *  del tablero -- y un paso que solo movio el contador queda como identidad, que es justo lo que
 *  habilita a detectar el no-op. Sin mascara devuelve la ventana tal cual (cero copias). */
/** Cobertura de la hipotesis VIGENTE derivada de su propia Beta: `alpha-1` son sus aciertos y
 *  `beta-1` sus fallos, contados desde que se sintetizo. No se recalcula aplicando el programa a
 *  la ventana entera en cada paso a proposito -- eso multiplicaba por 20 el costo de
 *  `recordObservation` y hacia que un episodio completo se pasara del presupuesto de la suite. */
function coberturaDeBeta(alpha: number, beta: number): number {
  const aciertos = alpha - 1;
  const fallos = beta - 1;
  const total = aciertos + fallos;
  return total <= 0 ? 1 : aciertos / total;
}

function maskObservations(window: Observation[], mask: VolatilityMask | null): Observation[] {
  if (mask === null) return window;
  return window.map((obs) => ({
    pre: obs.pre,
    post: neutralizeVolatileCells(obs.pre, obs.post, mask),
  }));
}
