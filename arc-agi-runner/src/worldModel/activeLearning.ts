/* [arc-agi-runner/worldModel/activeLearning] BL.20860 -- elige la proxima accion a PROBAR
   maximizando informacion sobre reglas del modelo de mundo AUN NO confirmadas (active learning),
   en vez de explorar a ciegas como baselineAgent.ts. Prioridad: (1) acciones sin programa
   confirmado todavia (maxima incertidumbre) sobre (2) acciones ya confirmadas (repetirlas no
   ensena nada nuevo); dentro de cada grupo, la MENOS observada primero. No-ops conocidos se
   excluyen salvo que sean la unica opcion -- misma idea de `rank_candidates` en
   arc-agi3-kaggle-agent/arc_agent/policy.py (BL.20783), reencuadrada como reduccion de
   incertidumbre del modelo en vez de solo conteo de visitas. */

import { CLICK_PRIORS } from './clickPriors';
import type { StateNoveltyTracker } from './stateNovelty';
import type { TransitionMemory } from './transitionMemory';

/** BL.21559 -- contexto de NOVEDAD para el desempate. Opcional a proposito: sin grilla no hay firma
 *  y sin firma no hay novedad que medir, y ahi la seleccion tiene que seguir funcionando igual que
 *  antes de este BL. */
export interface NoveltyContext {
  tracker: StateNoveltyTracker;
  /** Firma ENMASCARADA del estado actual, o `null` si el frame no trae grilla. */
  signature: string | null;
}

export interface ExploratoryOptions {
  novelty?: NoveltyContext;
  /** BL.21559 -- el turno de reconsideracion de los grupos relegados ya se sorteo AFUERA, por PASO
   *  y no por seleccion. Ver `resolverSorteo`. Omitirlo conserva el comportamiento previo. */
  turnoDeReconsideracion?: boolean;
  /** BL.21560 -- primera decision de la partida: no hay ni una observacion propia todavia, asi que
   *  el desempate final lo da el orden de acciones por efectividad MEDIDA en partidas reales
   *  (`CLICK_PRIORS.ordenAcciones`). Ver `prioridadPorPriors`. */
  priorDeArranque?: boolean;
}

/** BL.21500 -- probabilidad de reconsiderar los no-ops conocidos en una decision dada.
 *  `isKnownNoOp` ya exige varias observaciones (transitionMemory.ts), pero ese filtro sigue
 *  siendo ABSORBENTE: una vez que una accion entra, no vuelve a salir nunca, porque al no
 *  elegirse jamas tampoco vuelve a observarse. En ARC-AGI-3 eso es incorrecto: el efecto de una
 *  accion depende del ESTADO (una palanca que no hacia nada empieza a hacerlo cuando se abre una
 *  puerta), asi que "no hizo nada 3 veces" no es "no hara nada nunca". Un epsilon chico rompe la
 *  absorcion sin costar casi presupuesto: 1 de cada 20 decisiones vuelve a mirar el conjunto
 *  completo.
 *
 *  BL.21558 -- el mismo turno cubre ahora al OTRO grupo relegado: las acciones con una regla NO
 *  trivial ya confirmada. Antes de este BL nunca se confirmaba ninguna (el HUD lo impedia, ver
 *  volatilityMask.ts) y el grupo estaba siempre vacio; con la mascara funcionando pasa a llenarse,
 *  y el sort por incertidumbre lo dejaria fuera de la partida: el agente usaria SOLO las acciones
 *  que no entiende, que es la peor forma posible de jugar. Medido en el entorno sintetico con HUD:
 *  la unica accion con regla confirmada caia a 1 aparicion en 80 pasos. */
const NOOP_REEXPLORATION_EPSILON = 0.05;

/** El presupuesto de reconsideracion se reparte MITAD y MITAD entre los dos grupos relegados. No
 *  alcanza con juntarlos en un solo turno: adentro del turno rige el mismo orden por
 *  incertidumbre, y los no-ops (identidad = rango 0) le ganarian siempre a las de regla
 *  confirmada (rango 1), que es exactamente la relegacion que el turno viene a romper. */
const CONFIRMED_REEXPLORATION_EPSILON = NOOP_REEXPLORATION_EPSILON / 2;

/** BL.21559 -- probabilidad POR PASO de abrir un turno de reconsideracion cuando el llamador usa
 *  macro-acciones. Es EL MISMO presupuesto de BL.21500, solo que medido donde corresponde: por paso
 *  de juego y no por decision de la politica. Fuente unica -- la politica no lo redefine. */
export const RECONSIDERATION_PER_STEP_EPSILON = NOOP_REEXPLORATION_EPSILON;

/** 0 = maxima incertidumbre, se prueba primero. 1 = ya hay una regla NO trivial confirmada.
 *
 *  BL.21558 -- el programa VACIO es la IDENTIDAD, no una regla aprendida. `synthesizeProgram`
 *  (synthesis.ts) lo devuelve apenas ve un `pre` igual al `post`, o sea con UNA sola observacion
 *  no-op. Contarlo como "confirmada" (el codigo viejo: `program !== null` -> rango 1) mandaba esa
 *  accion al fondo del sort PARA SIEMPRE, porque en juego real ninguna otra accion llega nunca a
 *  confirmar un programa y todas se quedan en rango 0. Medido: ACTION6 -- el click, la accion mas
 *  expresiva del juego -- aparece EXACTAMENTE 1 vez en ar25 (78 pasos), ka59 (101), dc22 (129) y
 *  cd82 (101), incluida una corrida posterior a BL.21500.
 *
 *  Por que no alcanzaba con BL.21500: aquel fix subio a 3 las observaciones que exige
 *  `isKnownNoOp` y agrego un epsilon de reexploracion, pero el epsilon solo reconsidera acciones
 *  que YA son no-ops conocidos (3+ observaciones) y la relegacion pasaba con la PRIMERA. La
 *  escotilla de escape era inalcanzable por construccion. Aca la identidad vuelve al rango de
 *  maxima incertidumbre y el desempate por menos-observada la devuelve al ciclo: una accion que no
 *  hizo nada una vez es, justamente, la menos entendida de todas. */
function uncertaintyRank(action: string, memory: TransitionMemory): 0 | 1 {
  const transition = memory.getTransition(action);
  if (!transition || transition.program === null) return 0;
  return transition.program.length === 0 ? 0 : 1;
}

/** BL.21559 -- valor efectivo del sorteo de reconsideracion.
 *
 *  POR QUE EXISTE. Los dos epsilon de arriba estan expresados "por DECISION", y hasta este BL cada
 *  decision era exactamente un paso. Con macro-acciones (macroCommitment.ts) una decision cubre
 *  hasta `MACRO_MAX_STEPS` pasos, asi que el presupuesto de reconsideracion por PASO se dividia por
 *  ocho y los grupos relegados desaparecian de la partida. Medido en la reproduccion de las
 *  partidas reales con el modelo de mundo real: ACTION6 pasaba de 5 apariciones a 0 en
 *  ka59-38d34dbb y ACTION7 de 9 a 0 en ar25-0c556536 -- justo la relegacion que BL.21558 habia
 *  arreglado. Con el turno sorteado POR PASO afuera, el presupuesto vuelve a ser el mismo de antes
 *  de las macros.
 *
 *  `undefined` = nadie sorteo afuera, rige el comportamiento previo (el epsilon se evalua aca).
 *  `true` = el turno YA salio; el sorteo interno deja de decidir SI hay turno y pasa a decidir a
 *  cual de los dos grupos le toca, reescalandose al rango del epsilon donde vive ese reparto mitad
 *  y mitad. `false` = no hay turno en este paso. En los tres casos se consume un numero del PRNG,
 *  que es la condicion de reproducibilidad. */
function resolverSorteo(sorteoCrudo: number, turnoExterno: boolean | undefined): number {
  if (turnoExterno === undefined) return sorteoCrudo;
  return turnoExterno ? sorteoCrudo * NOOP_REEXPLORATION_EPSILON : 1;
}

export function selectExploratoryAction(
  availableActions: string[],
  memory: TransitionMemory,
  rng: () => number,
  opciones?: ExploratoryOptions,
): string {
  if (availableActions.length === 0) {
    throw new Error(
      'selectExploratoryAction: se requiere al menos una accion disponible (invariante del llamador).',
    );
  }

  // BL.21500: el epsilon se consume SIEMPRE (antes de cualquier rama) para que la secuencia del
  // PRNG dependa solo de la cantidad de decisiones y no de que acciones haya disponibles --
  // condicion para que `replayMetadata.seed` reproduzca la misma partida.
  const sorteoCrudo = rng();
  const sorteo = resolverSorteo(sorteoCrudo, opciones?.turnoDeReconsideracion);
  const novelty = opciones?.novelty;
  const nonNoOp = availableActions.filter((a) => !memory.isKnownNoOp(a));
  const noOps = availableActions.filter((a) => memory.isKnownNoOp(a));
  const confirmadas = availableActions.filter(
    (a) => !memory.isKnownNoOp(a) && uncertaintyRank(a, memory) === 1,
  );

  // Turno completo para UNO de los dos grupos relegados (ver los epsilon de arriba): es lo unico
  // que los devuelve al ciclo de observacion. Si el grupo sorteado esta vacio se decide normal --
  // nunca se pierde la decision.
  const turnoDeNoOps = sorteo < CONFIRMED_REEXPLORATION_EPSILON && noOps.length > 0;
  const turnoDeConfirmadas =
    !turnoDeNoOps && sorteo < NOOP_REEXPLORATION_EPSILON && confirmadas.length > 0;

  const candidates = turnoDeNoOps
    ? noOps
    : turnoDeConfirmadas
      ? confirmadas
      : nonNoOp.length > 0
        ? nonNoOp
        : availableActions;

  // Barajado reproducible (Fisher-Yates con rng inyectado) -- rompe empates sin sesgo posicional
  // antes del sort estable por (incertidumbre, menos-observada).
  const shuffled = [...candidates];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }

  const firma = novelty?.signature ?? null;

  shuffled.sort((a, b) => {
    const rankDiff = uncertaintyRank(a, memory) - uncertaintyRank(b, memory);
    if (rankDiff !== 0) return rankDiff;

    /* BL.21559 -- NOVEDAD antes que reparto parejo. El criterio viejo (solo la linea de abajo)
       ordenaba por observaciones GLOBALES de la accion, y como en juego real `uncertaintyRank` vale
       0 para todas, era el unico desempate: rotacion estricta, medida como ciclado perfecto en las
       tres partidas reales (ver stateNovelty.ts). Aca gana la accion que lleva a un estado menos
       visitado -- o que nunca se probo desde ESTE estado. */
    if (novelty !== undefined && firma !== null) {
      const noveltyDiff = novelty.tracker.comparar(firma, a, b);
      if (noveltyDiff !== 0) return noveltyDiff;
    }

    /* Ultimo recurso, y solo cuando la novedad no puede separarlas (sin firma, o dos acciones
       igual de novedosas): el conteo global de observaciones. Mantiene el orden deterministico y es
       el comportamiento previo a este BL. */
    const observadas = memory.getObservationCount(a) - memory.getObservationCount(b);
    if (observadas !== 0 || opciones?.priorDeArranque !== true) return observadas;
    return prioridadPorPriors(a) - prioridadPorPriors(b);
  });

  return shuffled[0];
}

/** BL.21560 -- prioridad de una accion segun la efectividad MEDIDA en las partidas reales grabadas
 *  (`CLICK_PRIORS.ordenAcciones`: fraccion de pasos en que la accion movio el tablero). Menor = mejor.
 *
 *  SOLO SE APLICA EN LA PRIMERA DECISION DE LA PARTIDA, y el motivo es una medicion del puerto
 *  Python (el espejo exacto de esta funcion): usarla como desempate permanente convierte la
 *  exploracion en una sola accion repetida. Cuando ninguna firma de estado se repite -- el caso de
 *  varios juegos publicos -- todas las acciones empatan en novedad y en observaciones en TODOS los
 *  pasos, con lo que el ultimo componente deja de ser un desempate y pasa a ser el criterio unico:
 *  la racha maxima saltaba a 24 de 24 pasos con la misma accion. Un prior es para cuando no hay
 *  evidencia; en cuanto la hay, manda la evidencia. */
function prioridadPorPriors(action: string): number {
  const indice = CLICK_PRIORS.ordenAcciones.indexOf(action);
  return indice < 0 ? CLICK_PRIORS.ordenAcciones.length : indice;
}
