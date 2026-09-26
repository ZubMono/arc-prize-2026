/* [arc-agi-runner/worldModel/synthesis] BL.20860 -- sintesis bottom-up de programas del DSL
   (discuss-context BL.20858): busqueda de composiciones cortas (profundidad <=3-4) que expliquen
   TODAS las observaciones (frame_pre, frame_post) sin contradicciones, rankeadas por prior de
   Occam (longitud + simplicidad de params).

   Estrategia de busqueda (2 niveles, ver comentario de enumerateStructuralSteps en primitives.ts
   para el razonamiento completo):
   1. Tier "finisher": los `propose*` de primitives.ts ya se auto-verifican contra UN par --
      si alguno explica pre->post en un solo paso, listo (camino rapido, cubre la mayoria de
      transformaciones ARC reales).
   2. Si ningun paso unico alcanza: busqueda en anchura acotada que expande con pasos
      "estructurales" ciegos (enumerateStructuralSteps, sin necesitar el post) y en CADA nodo
      nuevo reintenta el finisher data-driven para cerrar la brecha con un ultimo paso
      "semantico" (recolor/floodFill/overlay/conditionalRecolor/cropToBBox/objectExtract). */

import { gridsEqual, type Grid } from './grid';
import { applyStep, type PrimitiveContext, type Program, type ProgramStep } from './primitiveOps';
import { enumerateStructuralSteps, proposeAllSteps } from './primitives';
import {
  coberturaSuficiente,
  MIN_PROGRAM_COVERAGE,
  programCoverage,
  verifyProgram,
  type CoberturaDePrograma,
  type Observation,
} from './programCoverage';

/* BL.21561 -- `Observation`, `verifyProgram`, `programCoverage` y `MIN_PROGRAM_COVERAGE` viven en
   programCoverage.ts y se re-exportan aca para no cambiarle el import a ningun consumidor. */
export { coberturaSuficiente, MIN_PROGRAM_COVERAGE, programCoverage, verifyProgram };
export type { CoberturaDePrograma, Observation };

/** Profundidad de pasos ESTRUCTURALES ciegos antes del finisher final -- combinada con el
 *  finisher da una profundidad total de programa de hasta maxDepth+1 (3 structural + 1 finisher
 *  = 4), dentro del rango "<=3-4" pedido por BL.20860. */
const DEFAULT_MAX_DEPTH = 3;

/** Tope duro de expansiones de nodos. NO alcanza por si solo para acotar el computo: el costo de
 *  un nodo es proporcional al AREA de su grilla intermedia, y `replicate` (hasta 3x3) la infla --
 *  una 64x64 pasa a 192x192, y compuesta a profundidad 2 a 576x576 (331k celdas). Medido contra la
 *  API real: 40-110 SEGUNDOS por decision, creciendo con los pasos. Por eso hay dos presupuestos
 *  mas abajo, en unidades de CELDAS, que son las que se pagan. */
const MAX_NODE_EXPANSIONS = 2000;

/** Trabajo total permitido por busqueda, en celdas de grillas intermedias procesadas. Es el
 *  presupuesto que de verdad acota el tiempo: los nodos no cuestan igual entre si. */
const DEFAULT_MAX_CELLS_TOUCHED = 2_000_000;

/** Un nodo cuya grilla intermedia supera este multiplo del area objetivo se poda. Una composicion
 *  valida PUEDE necesitar agrandar y despues recortar (replicate -> cropToBBox), asi que el
 *  multiplo es generoso: 4x deja pasar replicate 2x2 y corta el 3x3 y los encadenamientos, que son
 *  justamente los que explotan. La busqueda ya era incompleta por diseno (profundidad y
 *  expansiones acotadas); esto la hace incompleta de forma ACOTADA Y MEDIBLE en vez de lenta. */
const DEFAULT_MAX_INTERMEDIATE_AREA_RATIO = 4;

/** Area maxima de grilla para la que se intenta la BFS estructural CIEGA. Por encima solo corre el
 *  tier data-driven de profundidad 1.
 *
 *  No es una heuristica de escritorio: medido contra la API oficial sobre `tr87-cd924810`, en 10
 *  transiciones reales de 64x64 la BFS profunda explico CERO y costo entre 6 y 56 segundos cada vez
 *  (profundidad 1: 12-196ms, tambien cero). El motivo es de dominio -- en ARC-AGI-3 una accion
 *  produce un cambio LOCAL y semantico (un cursor que se mueve, una celda que cambia), no una
 *  transformacion geometrica de la grilla entera, que es lo unico que la enumeracion ciega
 *  (translate/reflect/rotate/replicate) sabe expresar. Pagar el peor caso por un espacio que no
 *  contiene la respuesta es costo puro.
 *
 *  1024 = 32x32 deja pasar entera la busqueda para las grillas de ARC-AGI-1/2 (<=30x30), donde las
 *  transformaciones globales SI son la respuesta, y para los entornos sinteticos chicos. La corrida
 *  en vivo de 64x64 (4096) queda con profundidad 1, que es donde puede haber señal. */
const DEFAULT_MAX_STRUCTURAL_SEARCH_AREA = 1024;

/** Cuantas pasadas sobre la grilla cuesta UN barrido de `proposeAllSteps` -- una por proposer
 *  data-driven. Se usa para cobrar el barrido en las MISMAS unidades (celdas) que
 *  `maxCellsTouched`, de modo que las dos perillas sean comparables entre si. */
const PROPOSER_PASSES_PER_SWEEP = 10;

/** Trabajo total permitido en barridos de ENTRADA -- el `proposeAllSteps` de profundidad 1 que
 *  `searchWithCounter` paga UNA VEZ por semilla, antes de decidir si escala a la BFS. En celdas.
 *
 *  BL.21026/BL.21029: este era el UNICO trabajo sin presupuesto, y por eso revivia en 64x64 el bug
 *  que BL.20861 creia muerto. Sobre una grilla por encima de `maxStructuralSearchArea` la busqueda
 *  retorna ANTES de descontar expansiones o celdas, asi que el contador compartido de
 *  `synthesizeProgram` nunca bajaba y cada semilla del historial pagaba un barrido entero: medido
 *  en 64x64, 22ms con 1 observacion y 1861ms con 100 -- crecimiento LINEAL con lo aprendido,
 *  exactamente la regresion que el presupuesto existia para impedir. En 30x30, donde la BFS si
 *  corre y descuenta, el costo ya era plano (140ms vs 150ms): por eso los tests no lo veian.
 *
 *  Cubre SOLO el barrido de entrada, no los finishers de adentro de la BFS: esos ya estan acotados
 *  por expansiones y celdas, y cobrarlos contra esta misma perilla recortaria la busqueda en
 *  grillas chicas ~40x (un finisher sobre una intermedia inflada cuesta 10x lo que el nodo).
 *
 *  500k celdas ~= 12 semillas de 64x64 (4096 celdas x 10 proposers = 40960 c/u), o sea ~225ms de
 *  techo por decision. Las semillas se prueban de la mas reciente a la mas vieja -- que es donde
 *  suele estar la evidencia util -- asi que lo que se corta es la cola larga del historial. */
const DEFAULT_MAX_SEED_SWEEP_CELLS = 500_000;

/** Presupuesto de una busqueda. Inyectable para que el harness offline de Kaggle (9h totales, sin
 *  internet) pueda aflojarlo y una corrida en vivo contra la API pueda apretarlo, sin tocar la
 *  logica de busqueda. */
export interface SynthesisBudget {
  maxNodeExpansions: number;
  maxCellsTouched: number;
  maxIntermediateAreaRatio: number;
  maxStructuralSearchArea: number;
  maxSeedSweepCells: number;
}

export const DEFAULT_SYNTHESIS_BUDGET: SynthesisBudget = {
  maxNodeExpansions: MAX_NODE_EXPANSIONS,
  maxCellsTouched: DEFAULT_MAX_CELLS_TOUCHED,
  maxIntermediateAreaRatio: DEFAULT_MAX_INTERMEDIATE_AREA_RATIO,
  maxStructuralSearchArea: DEFAULT_MAX_STRUCTURAL_SEARCH_AREA,
  maxSeedSweepCells: DEFAULT_MAX_SEED_SWEEP_CELLS,
};

/** Consumo REAL de una busqueda, en unidades de presupuesto. Existe para que el costo se pueda
 *  afirmar de forma DETERMINISTA: los tests de BL.20861 median milisegundos contra umbrales fijos,
 *  asi que fallaban bajo contencion de CPU ajena y bloqueaban el push de todo el repo sin que
 *  hubiera regresion alguna (BL.21029). Un contador de unidades no depende de la maquina. */
export interface SynthesisUsage {
  expansionsUsed: number;
  cellsUsed: number;
  /** Celdas de barridos de ENTRADA -- lo que se cobra contra `maxSeedSweepCells`. */
  seedSweepCellsUsed: number;
  /** Barridos data-driven totales, de entrada y finishers. Observabilidad, no se cobra. */
  proposerSweeps: number;
  /** Alguna perilla corto la busqueda antes de agotar el espacio alcanzable. */
  budgetExhausted: boolean;
}

function areaOf(grid: Grid): number {
  return grid.length * (grid[0]?.length ?? 0);
}

/** Contador MUTABLE de presupuesto restante. Existe para que `synthesizeProgram` pueda repartir un
 *  unico presupuesto entre todas sus semillas en vez de darle uno entero a cada una. Nunca se
 *  expone: los callers pasan un `SynthesisBudget` inmutable y cada uno arranca con el suyo. */
interface BudgetCounter {
  expansionsLeft: number;
  cellsLeft: number;
  seedSweepCellsLeft: number;
  maxIntermediateAreaRatio: number;
  maxStructuralSearchArea: number;
  expansionsUsed: number;
  cellsUsed: number;
  seedSweepCellsUsed: number;
  proposerSweeps: number;
}

function counterFrom(budget: SynthesisBudget): BudgetCounter {
  return {
    expansionsLeft: budget.maxNodeExpansions,
    cellsLeft: budget.maxCellsTouched,
    seedSweepCellsLeft: budget.maxSeedSweepCells,
    maxIntermediateAreaRatio: budget.maxIntermediateAreaRatio,
    maxStructuralSearchArea: budget.maxStructuralSearchArea,
    expansionsUsed: 0,
    cellsUsed: 0,
    seedSweepCellsUsed: 0,
    proposerSweeps: 0,
  };
}

function usageFrom(counter: BudgetCounter): SynthesisUsage {
  return {
    expansionsUsed: counter.expansionsUsed,
    cellsUsed: counter.cellsUsed,
    seedSweepCellsUsed: counter.seedSweepCellsUsed,
    proposerSweeps: counter.proposerSweeps,
    budgetExhausted: sinCreditoParaOtraSemilla(counter),
  };
}

/** Corte de la BFS ciega: solo las perillas que ella consume. NO mira el credito de semillas -- si
 *  lo hiciera, el barrido de entrada que se acaba de cobrar podria apagar la BFS de esa misma
 *  semilla, que tiene expansiones y celdas de sobra. */
function sinCreditoParaLaBFS(counter: BudgetCounter): boolean {
  return counter.expansionsLeft <= 0 || counter.cellsLeft <= 0;
}

/** Corte del loop de semillas de `synthesizeProgram`. Suma el credito de barridos de entrada: sin
 *  eso, sobre una grilla por encima de `maxStructuralSearchArea` la BFS retorna sin gastar nada, el
 *  contador queda intacto para siempre y el historial entero se recorre a costo lineal (BL.21026). */
function sinCreditoParaOtraSemilla(counter: BudgetCounter): boolean {
  return sinCreditoParaLaBFS(counter) || counter.seedSweepCellsLeft <= 0;
}

/** Barrido de ENTRADA (profundidad 1), cobrado contra el presupuesto compartido de la sintesis.
 *  Devuelve vacio -- sin recorrer la grilla -- cuando ya no queda credito: eso es lo que corta la
 *  cola larga del historial de observaciones. */
function sweepSeedProposers(
  pre: Grid,
  post: Grid,
  ctx: PrimitiveContext,
  counter: BudgetCounter,
): ProgramStep[] {
  if (counter.seedSweepCellsLeft <= 0) return [];
  const costo = Math.max(areaOf(pre), areaOf(post)) * PROPOSER_PASSES_PER_SWEEP;
  counter.seedSweepCellsLeft -= costo;
  counter.seedSweepCellsUsed += costo;
  counter.proposerSweeps++;
  return proposeAllSteps(pre, post, ctx);
}

/** Barrido "finisher" dentro de la BFS. No se cobra -- ya lo acotan expansiones y celdas -- pero se
 *  cuenta para poder afirmar el trabajo total sin cronometro. */
function sweepFinisherProposers(
  pre: Grid,
  post: Grid,
  ctx: PrimitiveContext,
  counter: BudgetCounter,
): ProgramStep[] {
  counter.proposerSweeps++;
  return proposeAllSteps(pre, post, ctx);
}

function programKey(program: Program): string {
  return JSON.stringify(program);
}

/** Puntaje de complejidad para el ranking Occam: la LONGITUD domina (menos pasos = mejor), y a
 *  igual longitud se prefiere el programa mas "general" -- menos parametros hardcodeados
 *  (mappings chicos, desplazamientos cortos, predicados simples). */
function programComplexity(program: Program): number {
  let score = program.length * 1000;
  for (const step of program) {
    switch (step.name) {
      case 'translate':
        score += Math.abs(step.params.dx) + Math.abs(step.params.dy);
        break;
      case 'recolor':
        // Primitivo mas general para un swap de color puro (sin dependencia posicional) --
        // costo bajo para que gane el desempate frente a conditionalRecolor cuando ambos
        // explican el mismo par (border/interior coinciden con 'todas las celdas' cuando esas
        // celdas resultan estar todas en el borde, ambiguedad tipica con una sola observacion).
        score += Object.keys(step.params.mapping).length;
        break;
      case 'floodFill':
        score += 3;
        break;
      case 'conditionalRecolor':
        // predicate 'all' es redundante con recolor(mapping) para un swap de un solo color --
        // se penaliza mas fuerte. border/interior expresan semantica POSICIONAL que recolor no
        // puede capturar; siguen costando mas que recolor para que este gane los empates, pero
        // se eligen igual cuando son la UNICA explicacion disponible (recolor no sobrevive).
        score += step.params.predicate === 'all' ? 5 : 3;
        break;
      case 'objectExtract':
        score += step.params.color !== undefined ? 1 : 0;
        break;
      case 'replicate':
        score += step.params.timesX + step.params.timesY;
        break;
      case 'reflect':
      case 'rotate':
      case 'cropToBBox':
      case 'overlay':
        score += 1;
        break;
      default:
        break;
    }
  }
  return score;
}

function rankPrograms(programs: Program[]): Program[] {
  return [...programs].sort((a, b) => {
    const diff = programComplexity(a) - programComplexity(b);
    if (diff !== 0) return diff;
    return programKey(a).localeCompare(programKey(b)); // desempate deterministico
  });
}

/** Busca programas (composiciones bottom-up, profundidad acotada) que expliquen `pre -> post`
 *  para UN par observado -- devuelve todos los sobrevivientes encontrados, rankeados por Occam.
 *  Semilla de candidatos para `synthesizeProgram`, que despues verifica contra el historial
 *  COMPLETO de observaciones. */
export function searchPrograms(
  pre: Grid,
  post: Grid,
  ctx: PrimitiveContext = {},
  maxDepth: number = DEFAULT_MAX_DEPTH,
  budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
): Program[] {
  return searchProgramsWithUsage(pre, post, ctx, maxDepth, budget).programs;
}

/** Igual que `searchPrograms` pero devuelve ademas el consumo de presupuesto. Es la unica forma de
 *  afirmar el costo sin cronometro (BL.21029). */
export function searchProgramsWithUsage(
  pre: Grid,
  post: Grid,
  ctx: PrimitiveContext = {},
  maxDepth: number = DEFAULT_MAX_DEPTH,
  budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
): { programs: Program[]; usage: SynthesisUsage } {
  const counter = counterFrom(budget);
  const programs = searchWithCounter(pre, post, ctx, maxDepth, counter);
  return { programs, usage: usageFrom(counter) };
}

function searchWithCounter(
  pre: Grid,
  post: Grid,
  ctx: PrimitiveContext,
  maxDepth: number,
  counter: BudgetCounter,
): Program[] {
  const found = new Map<string, Program>();

  if (gridsEqual(pre, post)) {
    found.set(programKey([]), []);
    return rankPrograms([...found.values()]);
  }

  for (const step of sweepSeedProposers(pre, post, ctx, counter)) {
    found.set(programKey([step]), [step]);
  }
  if (found.size > 0) return rankPrograms([...found.values()]);

  const areaBase = Math.max(areaOf(pre), areaOf(post));

  /* Grilla demasiado grande para que la BFS ciega valga lo que cuesta (ver
     DEFAULT_MAX_STRUCTURAL_SEARCH_AREA). Devolver vacio aca NO es una perdida de capacidad: el
     resultado con BFS sobre estas grillas tambien era vacio, solo que 40 segundos despues. */
  if (areaBase > counter.maxStructuralSearchArea) return [];

  /* Area maxima tolerada para una grilla intermedia. Se toma sobre el MAYOR entre pre y post: si la
     transformacion buscada agranda (post > pre), el margen se mide contra el destino real. */
  const maxIntermediateArea = areaBase * counter.maxIntermediateAreaRatio;

  let frontier: Array<{ program: Program; grid: Grid }> = [{ program: [], grid: pre }];

  for (
    let depth = 0;
    depth < maxDepth && found.size === 0 && !sinCreditoParaLaBFS(counter);
    depth++
  ) {
    const nextFrontier: Array<{ program: Program; grid: Grid }> = [];
    for (const node of frontier) {
      if (sinCreditoParaLaBFS(counter)) break;
      for (const structuralStep of enumerateStructuralSteps(node.grid)) {
        if (sinCreditoParaLaBFS(counter)) break;
        counter.expansionsLeft--;
        counter.expansionsUsed++;

        const nextGrid = applyStep(structuralStep, node.grid, ctx);
        const nextArea = areaOf(nextGrid);
        /* Poda ANTES de pagar el finisher: proposeAllSteps recorre la grilla diez veces (una por
           proposer), asi que un nodo inflado cuesta un orden de magnitud mas que uno normal. */
        if (nextArea > maxIntermediateArea) continue;
        counter.cellsLeft -= nextArea;
        counter.cellsUsed += nextArea;

        const nextProgram = [...node.program, structuralStep];

        for (const finisherStep of sweepFinisherProposers(nextGrid, post, ctx, counter)) {
          const fullProgram = [...nextProgram, finisherStep];
          found.set(programKey(fullProgram), fullProgram);
        }

        nextFrontier.push({ program: nextProgram, grid: nextGrid });
      }
    }
    frontier = nextFrontier;
  }

  return rankPrograms([...found.values()]);
}

/** Sintetiza el MEJOR programa que explica TODAS las observaciones de una accion, o `null` si
 *  ninguna composicion de profundidad acotada lo logra sin contradicciones. Siembra la busqueda
 *  desde cada observacion (empezando por las mas recientes -- suelen ser la evidencia mas fresca
 *  tras una contradiccion) hasta encontrar al menos un sobreviviente verificado contra el
 *  historial completo. */
export function synthesizeProgram(
  observations: Observation[],
  ctx: PrimitiveContext = {},
  maxDepth: number = DEFAULT_MAX_DEPTH,
  budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
): Program | null {
  return synthesizeProgramWithUsage(observations, ctx, maxDepth, budget).program;
}

/** Igual que `synthesizeProgram` pero devuelve ademas el consumo de presupuesto de la sintesis
 *  COMPLETA -- la unidad en la que se afirma que el costo no crece con el historial (BL.21029). */
export function synthesizeProgramWithUsage(
  observations: Observation[],
  ctx: PrimitiveContext = {},
  maxDepth: number = DEFAULT_MAX_DEPTH,
  budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
): { program: Program | null; usage: SynthesisUsage } {
  /* El presupuesto es de la SINTESIS entera, no de cada semilla: si no fuera asi, el costo creceria
     linealmente con el historial de observaciones (medido: 51s en el paso 2, 110s en el paso 8) y
     el agente se volveria mas lento cuanto mas aprende -- exactamente al reves de lo que se busca. */
  const scored = synthesizeProgramScored(observations, ctx, maxDepth, budget);
  return { program: scored.program, usage: scored.usage };
}

export interface ProgramaPuntuado extends CoberturaDePrograma {
  program: Program | null;
  usage: SynthesisUsage;
}

/** BL.21561 -- sintesis por COBERTURA PUNTUADA en vez de por verificacion de cero tolerancia: se
 *  acepta el programa que explica MAS observaciones (por encima de `minCoverage`) y se devuelven
 *  sus aciertos/fallos para que quien lo use los contabilice en alpha/beta.
 *
 *  El presupuesto de busqueda NO cambia: el recorrido de semillas se sigue cortando en cuanto
 *  aparece un candidato de cobertura 1, que es exactamente la condicion con la que cortaba antes.
 *  Los candidatos parciales se puntuan al pasar, sin gastar una expansion de mas.
 *
 *  La IDENTIDAD (programa vacio) es la unica que se exige exacta: aceptarla parcialmente equivale
 *  a declarar no-op una accion que a veces SI hace algo, y eso la borra de la exploracion -- el
 *  lockout que BL.21500 tuvo que desarmar. */
export function synthesizeProgramScored(
  observations: Observation[],
  ctx: PrimitiveContext = {},
  maxDepth: number = DEFAULT_MAX_DEPTH,
  budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
  minCoverage: number = MIN_PROGRAM_COVERAGE,
): ProgramaPuntuado {
  const counter = counterFrom(budget);
  if (observations.length === 0) {
    return { program: null, aciertos: 0, fallos: 0, cobertura: 0, usage: usageFrom(counter) };
  }

  /* DOS PASADAS, y la primera es identica a la de antes de este BL. Pasada 1: verificacion de cero
     tolerancia con corte en el primer fallo -- si hay un programa que explica TODO, se devuelve sin
     pagar un centavo mas que el codigo viejo (es el caso comun, y es el que corre 80 veces por
     episodio en los tests de efecto). Pasada 2, SOLO si la pasada 1 no encontro nada -- o sea,
     exactamente cuando el codigo viejo devolvia `null` --: se puntua por cobertura a los candidatos
     ya enumerados, sin volver a buscar. Asi la tolerancia parcial no le cuesta nada al camino
     feliz. */
  const candidatos = new Map<string, Program>();
  const exactos = new Map<string, Program>();
  const seedOrder = [...observations].reverse();

  for (const seed of seedOrder) {
    /* Corta tambien por el tier data-driven: en grillas por encima de maxStructuralSearchArea la
       BFS retorna sin gastar expansiones ni celdas, asi que ESTA es la unica perilla que frena el
       recorrido del historial (BL.21026). */
    if (sinCreditoParaOtraSemilla(counter)) break;
    for (const candidate of searchWithCounter(seed.pre, seed.post, ctx, maxDepth, counter)) {
      const key = programKey(candidate);
      if (candidatos.has(key)) continue;
      candidatos.set(key, candidate);
      if (verifyProgram(candidate, observations, ctx)) exactos.set(key, candidate);
    }
    if (exactos.size > 0) break;
  }

  if (exactos.size > 0) {
    const program = rankPrograms([...exactos.values()])[0];
    return {
      program,
      aciertos: observations.length,
      fallos: 0,
      cobertura: 1,
      usage: usageFrom(counter),
    };
  }

  const parciales = new Map<string, { program: Program; puntaje: CoberturaDePrograma }>();
  for (const [key, program] of candidatos) {
    /* La IDENTIDAD no se acepta parcialmente: aceptarla equivale a declarar no-op una accion que a
       veces SI hace algo, y eso la borra de la exploracion (el lockout de BL.21500). Si fuera
       exacta ya habria salido por `exactos`. */
    if (program.length === 0) continue;
    const puntaje = coberturaSuficiente(program, observations, ctx, minCoverage);
    if (puntaje !== null) parciales.set(key, { program, puntaje });
  }
  if (parciales.size === 0) {
    return { program: null, aciertos: 0, fallos: 0, cobertura: 0, usage: usageFrom(counter) };
  }

  let mejorCobertura = -1;
  for (const { puntaje } of parciales.values()) {
    if (puntaje.cobertura > mejorCobertura) mejorCobertura = puntaje.cobertura;
  }
  const mejores = [...parciales.values()].filter((e) => e.puntaje.cobertura === mejorCobertura);
  const program = rankPrograms(mejores.map((e) => e.program))[0];
  const puntaje = (parciales.get(programKey(program)) as { puntaje: CoberturaDePrograma }).puntaje;
  return { program, ...puntaje, usage: usageFrom(counter) };
}
