/* [arc-agi-runner/worldModel/intelligentPolicy] BL.20860 -- reemplaza la politica RANDOM de
   baselineAgent.ts por planificacion real sobre un modelo de mundo aprendido (discuss-context
   BL.20858): DSL de primitivas (primitives.ts) -> sintesis de programas (synthesis.ts) ->
   operadores tipo STRIPS con confianza Beta (transitionMemory.ts) + active learning
   (activeLearning.ts) -> planificacion A-estrella acotada por presupuesto (planner.ts), con
   fallback ANYTIME greedy y, en ultima instancia, exploracion informada (nunca al azar puro --
   `rng` solo desempata de forma reproducible). El scoring de ARC-AGI-3 penaliza CUADRATICAMENTE
   cada accion de mas (min(acciones_humano/acciones_agente,1)^2): planificar sobre un modelo
   aprendido vence a ensayo y error.

   BL.21559 -- la rama de exploracion ya no elige desde cero en cada paso: se COMPROMETE con la
   accion elegida mientras siga produciendo cambio enmascarado (macroCommitment.ts) y desempata por
   NOVEDAD de estado en vez de por reparto parejo de acciones (stateNovelty.ts). Las dos piezas
   viven solo en esa rama: con `goalGrid` conocido manda el planner, igual que antes.

   Stateful: UNA instancia por partida (mismo contrato que ExplorationPolicy en
   arc-agi3-kaggle-agent/arc_agent/policy.py, BL.20783, reusando su idea de firma de estado y
   deteccion de no-ops -- ver stateSignature.ts). `decide()` es el unico punto de entrada:
   primero atribuye el resultado de la accion ANTERIOR al modelo de mundo (comparando el frame
   actual contra el que precedio a esa decision), despues elige la proxima accion. */

import type { ActivityMemorySeed } from '../activityMemorySeed';
import type { ArcAction, ArcFrameResponse } from '../types';
import { RECONSIDERATION_PER_STEP_EPSILON, selectExploratoryAction } from './activeLearning';
import { regionQueCambio } from './clickFeatures';
import { ClickMemory } from './clickMemory';
import { gridsEqualMasked, type BoundingBox, type Grid, type VolatilityMask } from './grid';
import { MACRO_MAX_STEPS, MacroCommitment } from './macroCommitment';
import { planActions } from './planner';
import type { PrimitiveContext } from './primitiveOps';
import { StateNoveltyTracker } from './stateNovelty';
import { computeStateSignature, extractGrid } from './stateSignature';
import { TransitionMemory } from './transitionMemory';

export interface ArcActionDecision {
  action: ArcAction;
  /** Solo presente cuando action === 'ACTION6' (accion compleja x,y). */
  x?: number;
  y?: number;
  /** Razonamiento declarado -- persistido en steps[].reasoning (transparencia/auditoria). */
  reasoning: string;
}

export interface IntelligentPolicyOptions {
  rng: () => number;
  /** Grilla objetivo conocida -- habilita planificacion real (A-estrella, ver planner.ts). Sin
   *  ella (caso real de ARC-AGI-3 contra la API oficial, donde no se conoce de antemano la
   *  grilla de WIN) la politica opera en modo exploracion informada -- ya muy por encima de la
   *  politica random gracias al modelo de mundo aprendido y al filtro de no-ops. */
  goalGrid?: Grid;
  maxPlanDepth?: number;
  /** Presupuesto TOTAL de acciones del episodio -- acota la profundidad de planificacion. */
  actionBudget?: number;
  maxExpansions?: number;
  /** BL.20861 -- conocimiento destilado de corridas ANTERIORES sobre esta misma actividad. Sin el,
   *  la politica arranca en frio (comportamiento previo). Con el, la corrida N+1 puede reejecutar
   *  el camino efectivo que gano en la corrida N y saltear las acciones ya probadas inutiles. */
  memorySeed?: ActivityMemorySeed;
}

/** Motivo por el que se abandono el replay del plan sembrado -- se persiste en el `reasoning` del
 *  step para que la corrida sea auditable sin re-derivar nada. */
type PlanAbandonReason = 'accion-no-disponible' | 'transicion-sin-efecto' | 'plan-agotado';

export class IntelligentPolicy {
  private readonly rng: () => number;
  private readonly goalGrid?: Grid;
  private readonly maxPlanDepth: number;
  private readonly actionBudget?: number;
  private readonly maxExpansions?: number;
  private readonly ctx: PrimitiveContext = {};
  private readonly memory = new TransitionMemory(this.ctx);

  private prevGrid: Grid | null = null;
  private prevAction: string | null = null;
  private stepCount = 0;

  /* ── BL.21559: compromiso y novedad ────────────────────────────────────────────────────────── */

  /** Macro-accion en curso -- vive ENTRE llamadas a `decide()`, que es la unica forma de que exista
   *  compromiso: la API se consulta una vez por accion. Ver macroCommitment.ts. */
  private readonly macro = new MacroCommitment();
  /** Conteo de visitas por estado y por par (estado, accion) sobre la firma ENMASCARADA -- es el
   *  desempate de la exploracion desde este BL. Ver stateNovelty.ts. */
  private readonly novedad = new StateNoveltyTracker();
  private prevSignature: string | null = null;

  /* ── BL.21560: DONDE clickear ──────────────────────────────────────────────────────────────── */

  /** Memoria de clicks del episodio -- (firma, x, y) probadas, plantillas de los que funcionaron y
   *  ranker de coordenadas con los priors ajustados offline. Ver clickMemory.ts. */
  private readonly clicks = new ClickMemory();
  /** Coordenada del ULTIMO ACTION6 emitido, en celdas de grilla. Es lo que permite atribuirle el
   *  resultado: sin ella, el par (accion, resultado) no dice nada de un click (BL.21518 lo
   *  documentaba como el motivo por el que ACTION6 no podia marcarse no-op). */
  private prevClick: { x: number; y: number } | null = null;
  /** Rectangulo que cambio en la ultima transicion -- feature `enRegionQueCambio` del ranker. */
  private regionCambiada: BoundingBox | null = null;
  /** Version de la mascara con la que se calculo `prevSignature`. Dos firmas de versiones distintas
   *  son hashes de DOS definiciones de "estado": registrar una transicion entre ellas guardaria un
   *  destino que no describe nada (mismo criterio que `_record_outcome` en el puerto Python). */
  private prevMaskVersion = 0;

  /* ── Estado derivado de la semilla (BL.20861) ──────────────────────────────────────────────
     Se materializa UNA vez en el constructor: `decide()` corre una vez por accion contra la API
     real, y rearmar los indices en cada llamada seria trabajo cuadratico sobre datos inmutables. */

  /** firma de estado -> acciones que ya se confirmaron inutiles ahi. */
  private readonly seededNonOps = new Map<string, Set<string>>();
  /** "firma|accion" -> firma destino conocida. Usado para no volver a un estado ya visitado. */
  private readonly seededTransitions = new Map<string, string>();
  /** Cola del plan ganador mas corto -- se consume accion por accion mientras no diverja. */
  private planQueue: string[] = [];
  private planTotalLength = 0;
  private planAbandonedBecause: PlanAbandonReason | null = null;
  /** Firmas ya visitadas en ESTE episodio -- evita ciclos usando las transiciones sembradas. */
  private readonly visitedSignatures = new Set<string>();
  /** La ultima accion emitida salio del plan sembrado -- habilita la guarda de divergencia. */
  private lastActionCameFromPlan = false;

  constructor(opts: IntelligentPolicyOptions) {
    this.rng = opts.rng;
    this.goalGrid = opts.goalGrid;
    this.maxPlanDepth = opts.maxPlanDepth ?? 6;
    this.actionBudget = opts.actionBudget;
    this.maxExpansions = opts.maxExpansions;

    const seed = opts.memorySeed;
    if (seed !== undefined) {
      for (const nonOp of seed.nonOps) {
        const key = nonOp.fromStateSignature;
        const set = this.seededNonOps.get(key) ?? new Set<string>();
        set.add(nonOp.action);
        this.seededNonOps.set(key, set);
      }
      for (const t of seed.transitions) {
        this.seededTransitions.set(`${t.fromStateSignature}|${t.action}`, t.toStateSignature);
      }
      /* Solo el plan MAS CORTO: buildSeedFromDoc ya los ordena por largo ascendente y el score de
         ARC penaliza cada accion de mas de forma cuadratica. Probar varios planes en secuencia
         costaria mas acciones que el ahorro que darian. */
      const best = seed.plans[0];
      if (best !== undefined && best.actions.length > 0) {
        /* Se filtra RESET: la corrida ya arranca con un RESET propio (gameRunner.ts) y repetirlo
           volveria al estado inicial gastando una accion -- exactamente lo contrario del objetivo. */
        this.planQueue = best.actions.filter((a) => a !== 'RESET');
        this.planTotalLength = this.planQueue.length;
      }
    }
  }

  /** BL.21558 -- mascara de volatilidad aprendida hasta ahora. La expone para que el runner firme
   *  los steps persistidos sobre las MISMAS celdas estables: una firma que incluye el contador de
   *  HUD no vuelve a matchear nunca y deja la memoria entre corridas sin poder disparar. */
  volatilityMask(): VolatilityMask | null {
    return this.memory.getVolatilityMask();
  }

  /** Resumen para logging del arranque -- que sabe la politica antes de la primera accion. */
  seedSummary(): { nonOpStates: number; transitions: number; planLength: number } {
    return {
      nonOpStates: this.seededNonOps.size,
      transitions: this.seededTransitions.size,
      planLength: this.planTotalLength,
    };
  }

  /** Decide la proxima accion dado el frame actual -- unico punto de entrada, con estado
   *  interno acumulado a lo largo del episodio. */
  decide(frame: ArcFrameResponse): ArcActionDecision {
    const currentGrid = extractGrid(frame);

    if (
      this.prevAction !== null &&
      this.prevGrid !== null &&
      currentGrid !== null &&
      frame.state !== 'NOT_STARTED'
    ) {
      this.memory.recordObservation(this.prevAction, this.prevGrid, currentGrid);
    }

    if (currentGrid !== null && this.ctx.anchorGrid === undefined) {
      this.ctx.anchorGrid = currentGrid;
    }

    if (frame.state === 'NOT_STARTED' || frame.available_actions.length === 0) {
      this.prevGrid = null;
      this.prevAction = null;
      this.prevSignature = null;
      /* BL.21560 -- el RESET corta la atribucion del click: el frame que viene ya no es consecuencia
         de el. Las coordenadas ya probadas SI se conservan -- estan indexadas por firma de estado,
         asi que el estado post-RESET las reencuentra solas si vuelve a ser el mismo. */
      this.prevClick = null;
      this.regionCambiada = null;
      /* BL.21559 -- un RESET rompe la continuidad de la trayectoria: la accion de la macro ya no
         puede evaluarse contra el estado que la motivo. */
      this.macro.cancelar();
      /* Un RESET invalida el plan sembrado: sus acciones se destilaron desde el estado inicial de
         OTRA corrida y, tras reiniciar, el prefijo ya consumido dejo de valer. Reiniciar la cola
         completa seria peor -- no sabemos si el RESET es por el mismo motivo. Se abandona. */
      this.abandonPlan('transicion-sin-efecto');
      return {
        action: 'RESET',
        reasoning: 'Estado NOT_STARTED o sin acciones disponibles -- se reinicia el juego.',
      };
    }

    const available = frame.available_actions.map((n) => `ACTION${n}` as ArcAction);
    /* BL.21558 -- la mascara sale del modelo de mundo, que ya se acaba de actualizar con la
       transicion anterior: firmar y comparar usan EXACTAMENTE las mismas celdas que la sintesis
       considera informativas. Mientras no haya evidencia suficiente es `null` y todo se comporta
       como antes de este BL. */
    const mask = this.memory.getVolatilityMask();
    const maskVersion = this.memory.getVolatilityVersion();
    const signature =
      currentGrid !== null
        ? String(computeStateSignature(currentGrid, frame.available_actions, mask))
        : null;

    /* BL.21559 -- la transicion anterior, leida IGNORANDO las celdas volatiles. Es a la vez el
       criterio de corte de la macro-accion y la definicion de "el tablero se movio". Sin grilla en
       alguno de los dos lados no hay evidencia: se asume que no hubo cambio, que es el lado del
       error que corta el compromiso en vez de sostenerlo a ciegas. */
    const huboCambioEnmascarado =
      this.prevGrid !== null &&
      currentGrid !== null &&
      !gridsEqualMasked(this.prevGrid, currentGrid, mask);

    /* BL.21560 -- se le atribuye el resultado al click anterior ANTES de pisar `prevSignature`: la
       clave de la memoria es la firma del estado DESDE EL QUE se clickeo, no la del que quedo. */
    if (this.prevClick !== null && this.prevAction === 'ACTION6' && this.prevSignature !== null) {
      this.clicks.registrarResultado(
        this.prevSignature,
        this.prevClick.x,
        this.prevClick.y,
        huboCambioEnmascarado,
        this.prevGrid,
      );
    }
    this.regionCambiada = regionQueCambio(this.prevGrid, currentGrid);

    if (signature !== null) {
      if (
        this.prevSignature !== null &&
        this.prevAction !== null &&
        maskVersion === this.prevMaskVersion
      ) {
        this.novedad.registrarTransicion(this.prevSignature, this.prevAction, signature);
      }
      this.novedad.registrarVisita(signature);
      this.visitedSignatures.add(signature);
    }
    this.prevSignature = signature;
    this.prevMaskVersion = maskVersion;

    /* La accion anterior venia del plan y no cambio NADA: el mundo diverge de lo que el plan
       asumia. Los planes se destilan por camino EFECTIVO (packages/api/prometheusActivityMemory/
       distill.ts::effectiveActionPath), asi que toda accion de un plan sano cambia el estado; una
       que no lo hace es evidencia de divergencia. Falso positivo posible solo con planes viejos
       destilados ANTES de que existieran las firmas (transcripcion cruda, con no-ops adentro) --
       y ahi abandonar tambien es lo correcto, porque ese plan gasta acciones de mas. */
    if (
      this.lastActionCameFromPlan &&
      this.prevGrid !== null &&
      currentGrid !== null &&
      gridsEqualMasked(this.prevGrid, currentGrid, mask)
    ) {
      this.abandonPlan('transicion-sin-efecto');
    }

    const planned = this.nextPlannedAction(available);
    if (planned !== null) {
      /* El plan sembrado es conocimiento DURO de una corrida que ya gano: mientras dure, manda el
         plan y no hay compromiso exploratorio que sostener. */
      this.macro.cancelar();
      this.stepCount += 1;
      this.prevGrid = currentGrid;
      this.prevAction = planned.action;
      this.lastActionCameFromPlan = true;
      if (planned.action === 'ACTION6') return this.conCoordenada(planned, currentGrid, signature);
      return planned;
    }
    this.lastActionCameFromPlan = false;

    const decision = this.chooseAction(currentGrid, this.usableActions(available, signature), {
      signature,
      huboCambioEnmascarado,
    });

    this.stepCount += 1;
    this.prevGrid = currentGrid;
    this.prevAction = decision.action;

    if (decision.action === 'ACTION6') return this.conCoordenada(decision, currentGrid, signature);
    this.prevClick = null;
    return decision;
  }

  /** BL.21560 -- completa un ACTION6 con la coordenada que elige la memoria de clicks, y la recuerda
   *  para poder atribuirle el resultado en la proxima llamada. */
  private conCoordenada(
    decision: ArcActionDecision,
    grid: Grid | null,
    signature: string | null,
  ): ArcActionDecision {
    const objetivo = this.clicks.elegirObjetivo(grid, signature, this.rng, this.regionCambiada);
    this.prevClick = { x: objetivo.x, y: objetivo.y };
    return {
      ...decision,
      x: objetivo.xApi,
      y: objetivo.yApi,
      reasoning: `${decision.reasoning} Coordenada (${objetivo.xApi},${objetivo.yApi}): ${objetivo.motivo}.`,
    };
  }

  /** Descarta el resto del plan sembrado. Idempotente: solo el PRIMER motivo se conserva, que es
   *  el que explica por que se dejo de confiar en la memoria. */
  private abandonPlan(reason: PlanAbandonReason): void {
    if (this.planQueue.length === 0 && this.planAbandonedBecause !== null) return;
    if (this.planAbandonedBecause === null) this.planAbandonedBecause = reason;
    this.planQueue = [];
    this.lastActionCameFromPlan = false;
  }

  /** Proxima accion del plan sembrado, o `null` si no hay plan vigente. Abandona el plan si su
   *  siguiente accion no esta disponible en el estado actual -- señal inequivoca de divergencia. */
  private nextPlannedAction(available: ArcAction[]): ArcActionDecision | null {
    const next = this.planQueue[0];
    if (next === undefined) return null;

    if (!available.includes(next as ArcAction)) {
      this.abandonPlan('accion-no-disponible');
      return null;
    }

    this.planQueue.shift();
    const consumidas = this.planTotalLength - this.planQueue.length;
    return {
      action: next as ArcAction,
      reasoning:
        `Memoria de actividad: paso ${consumidas}/${this.planTotalLength} del camino efectivo ` +
        'que ya llevo al exito en una corrida anterior (BL.20861).',
    };
  }

  /** Acciones que vale la pena considerar en este estado, filtrando con la memoria sembrada.
   *
   *  Dos filtros, ambos con la MISMA guarda: si dejarian el conjunto vacio, no se aplican. Quedarse
   *  sin acciones que probar es estrictamente peor que probar una dudosa -- el agente perderia el
   *  juego por inaccion en vez de por una accion mala.
   *
   *  1. No-ops confirmados en esta firma exacta: no cambian nada, gastar una es puro costo.
   *  2. Acciones cuya transicion conocida devuelve a un estado YA visitado este episodio: ciclo. */
  private usableActions(available: ArcAction[], signature: string | null): ArcAction[] {
    if (signature === null) return available;

    const nonOps = this.seededNonOps.get(signature);
    let usable = available;
    if (nonOps !== undefined) {
      const filtered = usable.filter((a) => !nonOps.has(a));
      if (filtered.length > 0) usable = filtered;
    }

    if (this.seededTransitions.size > 0) {
      const noCiclo = usable.filter((a) => {
        const destino = this.seededTransitions.get(`${signature}|${a}`);
        return destino === undefined || !this.visitedSignatures.has(destino);
      });
      if (noCiclo.length > 0) usable = noCiclo;
    }

    return usable;
  }

  private chooseAction(
    currentGrid: Grid | null,
    available: ArcAction[],
    contexto: { signature: string | null; huboCambioEnmascarado: boolean },
  ): ArcActionDecision {
    if (currentGrid !== null && this.goalGrid !== undefined) {
      const remainingBudget =
        this.actionBudget !== undefined
          ? Math.max(0, this.actionBudget - this.stepCount)
          : undefined;
      const result = planActions({
        currentGrid,
        availableActions: available,
        memory: this.memory,
        goalGrid: this.goalGrid,
        maxDepth: this.maxPlanDepth,
        budget: remainingBudget,
        maxExpansions: this.maxExpansions,
      });

      if (result.plan !== null && result.plan.length > 0) {
        const stepsRestantes = result.plan.length - 1;
        this.macro.cancelar();
        return {
          action: result.plan[0] as ArcAction,
          reasoning:
            `Plan de ${result.plan.length} paso(s) sobre el modelo de mundo aprendido ` +
            `(distancia heuristica actual: ${result.currentDistance}). Restan ${stepsRestantes} ` +
            'paso(s) tras esta accion.',
        };
      }
      if (result.fallbackAction !== undefined) {
        this.macro.cancelar();
        return {
          action: result.fallbackAction as ArcAction,
          reasoning:
            'Sin plan completo dentro del presupuesto -- fallback ANYTIME: accion que mas ' +
            `reduce la distancia heuristica al objetivo (${result.currentDistance}).`,
        };
      }
    }

    /* BL.21559 -- COMPROMISO antes que eleccion nueva. Mientras la accion vigente siga moviendo el
       tablero (con la mascara puesta) se la repite: es lo que convierte "probar ACTION1" en
       "avanzar hasta chocar". Sin esto, la eleccion desde cero en cada paso producia ciclado
       perfecto y las direcciones se cancelaban entre si -- ver macroCommitment.ts.

       SOLO SIN OBJETIVO CONOCIDO, que es el caso REAL contra la API de ARC (gameRunner.ts nunca
       inyecta `goalGrid`: la grilla de WIN no se conoce de antemano). Con objetivo manda el planner,
       y esta rama existe ahi para ALIMENTARLO con observaciones variadas -- justo lo que una macro
       no da: toda macro termina, por definicion, en el paso que dejo de producir cambio, o sea
       contra una pared, y le mete a cada accion una observacion de borde que el DSL no sabe explicar
       (traslacion con recorte). Con el programa en `null` el planner se queda sin modelo. Medido en
       el benchmark de BL.20860: con la macro activa en modo objetivo, seed-5 pasaba de resolver en
       <= 21 acciones a agotar el presupuesto de 400. */
    /* El turno de reconsideracion de los grupos relegados (no-ops conocidos y acciones con regla ya
       confirmada) se sortea POR PASO y no por seleccion: una macro cubre hasta 8 pasos y sin esto el
       presupuesto de BL.21500 se dividia por 8. Cuando sale, la macro cede -- ver
       `resolverSorteo` en activeLearning.ts, donde esta la magnitud medida. */
    const turnoDeReconsideracion = this.rng() < RECONSIDERATION_PER_STEP_EPSILON;
    if (turnoDeReconsideracion) this.macro.cancelar();

    const repetida =
      this.goalGrid !== undefined
        ? null
        : this.macro.continuar({
            accionAnterior: this.prevAction,
            huboCambioEnmascarado: contexto.huboCambioEnmascarado,
            disponibles: available,
          });
    if (repetida !== null) {
      return {
        action: repetida as ArcAction,
        reasoning:
          `Macro-accion: ${repetida} sigue cambiando el tablero (paso ` +
          `${this.macro.pasosEmitidos}/${MACRO_MAX_STEPS} del compromiso) -- se repite hasta que ` +
          'deje de tener efecto, en vez de rotar y deshacer el avance.',
      };
    }

    const chosen = selectExploratoryAction(available, this.memory, this.rng, {
      novelty: { tracker: this.novedad, signature: contexto.signature },
      turnoDeReconsideracion,
      /* BL.21560 -- prior de arranque: solo mientras no se ejecuto ninguna accion en la partida. */
      priorDeArranque: this.prevAction === null,
    });
    if (this.goalGrid === undefined) this.macro.iniciar(chosen);
    const transition = this.memory.getTransition(chosen);
    if (transition !== undefined && transition.program?.length === 0) {
      /* BL.21558 -- la identidad NO es una regla aprendida: es "todavia no le vimos efecto". Se
         declara asi en el reasoning persistido para que la auditoria de la corrida no lea
         "confirmada" donde el modelo en realidad no sabe nada. */
      return {
        action: chosen as ArcAction,
        reasoning:
          `Exploracion activa: ${chosen} no mostro efecto en sus ${transition.observationCount} ` +
          'observacion(es) -- identidad, o sea maxima incertidumbre: se vuelve a probar.',
      };
    }
    if (transition === undefined || transition.program === null) {
      return {
        action: chosen as ArcAction,
        reasoning:
          `Exploracion activa: ${chosen} aun no tiene una regla de transicion confirmada -- ` +
          'se prueba para reducir la incertidumbre del modelo de mundo.',
      };
    }
    const confidence = this.memory.getConfidence(chosen).toFixed(2);
    return {
      action: chosen as ArcAction,
      reasoning:
        `Exploracion activa: ${chosen} ya tiene una regla confirmada (confianza ${confidence}) ` +
        'pero sin objetivo conocido para planificar -- se prioriza la accion menos observada.',
    };
  }
}
