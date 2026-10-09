/* [arc-agi-runner/worldModel/synthesis.budget.test] BL.20861 -- el presupuesto de sintesis es lo
   que hace jugable el benchmark. Medido contra la API oficial sobre tr87-cd924810: sin el, una
   decision tardaba 40-110 SEGUNDOS sobre grillas 64x64 y el tiempo CRECIA con los pasos (el agente
   se volvia mas lento cuanto mas aprendia).

   Estos tests fijan las propiedades que producen ese resultado. Si alguien las afloja "porque la
   busqueda encuentra mas", el benchmark vuelve a ser injugable en silencio -- el sintoma es
   lentitud, no un fallo.

   BL.21029 -- se afirman en UNIDADES DE PRESUPUESTO, nunca en milisegundos. La version anterior
   cronometraba con `Date.now()` contra umbrales fijos de 1-3s: pasaba aislada pero fallaba bajo
   contencion de CPU ajena, y como el gate de push corre toda la suite del repo, un test verde en
   dev le costaba el ciclo de push completo a cualquiera que estuviera aterrizando otro BL. Un
   contador de unidades mide el TRABAJO, que es lo que el presupuesto acota, y no depende de la
   maquina que lo corra. */

import { describe, expect, it } from 'vitest';

import type { Grid } from '../grid';
import {
  DEFAULT_SYNTHESIS_BUDGET,
  searchPrograms,
  searchProgramsWithUsage,
  synthesizeProgramWithUsage,
  type SynthesisBudget,
} from '../synthesis';

/** Grilla NxN con contenido pseudo-aleatorio estable -- densa a proposito: una grilla uniforme
 *  haria que los proposers cierren en el primer intento y el test no mediria la busqueda. */
function grid(n: number, offset = 0): Grid {
  return Array.from({ length: n }, (_, y) =>
    Array.from({ length: n }, (_, x) => (x * 7 + y * 13 + offset) % 16),
  );
}

/** Par pre/post que NINGUN paso unico del DSL explica -- fuerza el peor caso: profundidad 1 falla y
 *  la busqueda tiene que decidir si escala a la BFS ciega. Es el caso COMUN en juego real.
 *
 *  Construccion: reflejo horizontal MAS un cambio local. El reflejo solo no cierra (queda una celda
 *  distinta); floodFill/recolor tampoco, porque las posiciones cambiaron. Un solo cambio de celda
 *  NO sirve para este test: `floodFill` lo explica en profundidad 1, barato y correcto. */
function parInexplicable(n: number): { pre: Grid; post: Grid } {
  const pre = grid(n, 0);
  const post = pre.map((row) => [...row].reverse());
  post[1][1] = (post[1][1] + 1) % 16;
  return { pre, post };
}

describe('presupuesto de sintesis (BL.20861 -- lo que hace jugable el benchmark)', () => {
  it('una grilla 64x64 NO entra en la BFS ciega: cero expansiones, no "pocas"', () => {
    const { pre, post } = parInexplicable(64);
    const { programs, usage } = searchProgramsWithUsage(pre, post, {}, 3);

    expect(programs).toEqual([]);
    /* La afirmacion fuerte: la BFS no corrio NADA. Antes esto se infuria de un cronometro, que no
       distingue "no expandio" de "expandio poco en una maquina rapida". */
    expect(usage.expansionsUsed).toBe(0);
    expect(usage.cellsUsed).toBe(0);
    // El unico trabajo pagado es el barrido de entrada de profundidad 1, donde SI puede haber señal.
    expect(usage.proposerSweeps).toBe(1);
  });

  it('una grilla chica SI usa la busqueda completa -- cero regresion donde la BFS si sirve', () => {
    /* 8x8 esta muy por debajo del umbral: aca las transformaciones globales del DSL son la
       respuesta (caso ARC-AGI-1/2 y entornos sinteticos), y la busqueda debe correr entera. */
    const pre = grid(8, 0);
    const post = pre.map((row) => [...row].reverse()); // reflect horizontal: explicable
    expect(searchPrograms(pre, post, {}, 3).length).toBeGreaterThan(0);
  });

  it('una grilla 30x30 inexplicable SI expande la BFS -- el presupuesto no la asfixia', () => {
    /* Contracara del test de 64x64: donde la BFS vale lo que cuesta, tiene que correr de verdad.
       Fija la capacidad que BL.21026 podria haber recortado sin que nadie lo notara al agregar la
       perilla de barridos de entrada. Con un tope chico de expansiones alcanza para demostrar que
       la BFS ARRANCA, que es la propiedad -- correrla entera solo agregaria segundos de CPU. */
    const { pre, post } = parInexplicable(30);
    const { usage } = searchProgramsWithUsage(pre, post, {}, 3, {
      ...DEFAULT_SYNTHESIS_BUDGET,
      maxNodeExpansions: 5,
    });

    expect(usage.expansionsUsed).toBeGreaterThan(0);
    expect(usage.cellsUsed).toBeGreaterThan(0);
    /* Los finishers de adentro de la BFS NO se cobran contra maxSeedSweepCells: si se cobraran, el
       credito se agotaria en un puñado de nodos y la busqueda quedaria ~40x mas corta. */
    expect(usage.proposerSweeps).toBeGreaterThan(1);
    expect(usage.seedSweepCellsUsed).toBe(30 * 30 * 10); // un solo barrido de entrada
  });

  it('el umbral de area es el que decide, no el tamano absoluto', () => {
    const { pre, post } = parInexplicable(64);

    // Con el default, 4096 > maxStructuralSearchArea: la BFS ni arranca.
    const conDefault = searchProgramsWithUsage(pre, post, {}, 3).usage;
    expect(conDefault.expansionsUsed).toBe(0);

    /* MISMA grilla, mismo todo: lo unico que se mueve es el umbral de area. Las expansiones se
       acotan a 2 porque lo que se afirma es que la BFS arranca, no cuanto corre. */
    const generoso: SynthesisBudget = {
      ...DEFAULT_SYNTHESIS_BUDGET,
      maxStructuralSearchArea: 10_000,
      maxNodeExpansions: 2,
    };
    const conUmbralAlto = searchProgramsWithUsage(pre, post, {}, 3, generoso).usage;
    expect(conUmbralAlto.expansionsUsed).toBeGreaterThan(0);
  });

  it('el presupuesto de celdas corta la busqueda aunque queden expansiones disponibles', () => {
    const { pre, post } = parInexplicable(30);
    const sinCeldas: SynthesisBudget = {
      ...DEFAULT_SYNTHESIS_BUDGET,
      maxNodeExpansions: 100_000,
      maxCellsTouched: 1,
    };
    const { programs, usage } = searchProgramsWithUsage(pre, post, {}, 3, sinCeldas);

    expect(programs).toEqual([]);
    expect(usage.budgetExhausted).toBe(true);
    /* Corto por celdas, no por expansiones: quedaron 100k disponibles y uso un puñado. Es la
       propiedad real -- las expansiones solas no acotan, porque un nodo inflado cuesta 300x uno
       normal. */
    expect(usage.expansionsUsed).toBeLessThan(100);
  });

  it('el costo NO crece con el historial de observaciones (el bug original, en 30x30)', () => {
    /* Antes de BL.20861 cada semilla recibia un presupuesto entero, asi que sintetizar con 20
       observaciones costaba ~20x lo que con 1: el agente se degradaba a medida que aprendia. */
    const { pre, post } = parInexplicable(30);
    const acotado: SynthesisBudget = { ...DEFAULT_SYNTHESIS_BUDGET, maxNodeExpansions: 5 };
    const uso = (k: number) =>
      synthesizeProgramWithUsage(
        Array.from({ length: k }, () => ({ pre, post })),
        {},
        3,
        acotado,
      ).usage;

    const una = uso(1);
    const muchas = uso(20);

    /* El presupuesto es de la sintesis ENTERA: 20 observaciones identicas no pueden costar un
       multiplo de lo que cuesta 1. Se afirma sobre el trabajo, no sobre el reloj. */
    expect(muchas.expansionsUsed).toBe(una.expansionsUsed);
    expect(muchas.cellsUsed).toBe(una.cellsUsed);
    expect(muchas.proposerSweeps).toBe(una.proposerSweeps);
  });

  it('el costo NO crece con el historial en 64x64 tampoco -- la grilla del juego real (BL.21026)', () => {
    /* La regresion que el test de 30x30 NO podia ver, y que por eso vivio hasta BL.21026: sobre una
       grilla por encima de maxStructuralSearchArea la BFS retorna sin gastar expansiones ni celdas,
       asi que el contador compartido nunca bajaba y el loop de semillas recorria el historial
       ENTERO pagando un barrido de entrada por observacion. Medido antes del fix: 22ms con 1
       observacion y 1861ms con 100 -- lineal, justo en el unico tamaño de grilla que ARC-AGI-3 usa
       en vivo. */
    const { pre, post } = parInexplicable(64);
    const costoBarrido = 64 * 64 * 10;
    /* Credito para 3 barridos en vez de los ~12 del default: la propiedad afirmada es que el
       consumo se DETIENE en el credito, y se demuestra igual de bien con 3 -- pagar 12 barridos de
       64x64 solo agrega CPU a un test que ya no mide tiempo. */
    const acotado: SynthesisBudget = {
      ...DEFAULT_SYNTHESIS_BUDGET,
      maxSeedSweepCells: costoBarrido * 3,
    };
    const uso = (k: number) =>
      synthesizeProgramWithUsage(
        Array.from({ length: k }, () => ({ pre, post })),
        {},
        3,
        acotado,
      ).usage;

    const pocas = uso(6);
    const muchas = uso(20);

    // 3x el historial no puede costar mas trabajo: el techo lo pone el presupuesto, no el largo.
    expect(muchas.proposerSweeps).toBe(pocas.proposerSweeps);
    expect(muchas.seedSweepCellsUsed).toBe(pocas.seedSweepCellsUsed);
    expect(muchas.budgetExhausted).toBe(true);

    /* Y el techo es el declarado: nunca se pasa de un barrido por encima del credito (el que lo
       agota). Sin esto, "no crece" podria cumplirse en un numero absurdamente alto. */
    expect(muchas.seedSweepCellsUsed).toBeLessThanOrEqual(acotado.maxSeedSweepCells + costoBarrido);
  });

  it('una sola observacion en 64x64 paga un solo barrido -- el cap no penaliza el caso barato', () => {
    const { pre, post } = parInexplicable(64);
    const usage = synthesizeProgramWithUsage([{ pre, post }], {}, 3).usage;

    expect(usage.proposerSweeps).toBe(1);
    expect(usage.budgetExhausted).toBe(false);
  });

  it('el default expone las cinco perillas -- ninguna queda hardcodeada dentro de la busqueda', () => {
    expect(DEFAULT_SYNTHESIS_BUDGET).toEqual({
      maxNodeExpansions: expect.any(Number),
      maxCellsTouched: expect.any(Number),
      maxIntermediateAreaRatio: expect.any(Number),
      maxStructuralSearchArea: expect.any(Number),
      maxSeedSweepCells: expect.any(Number),
    });
    // 64x64 (la grilla de ARC-AGI-3 en vivo) DEBE quedar fuera de la BFS ciega.
    expect(DEFAULT_SYNTHESIS_BUDGET.maxStructuralSearchArea).toBeLessThan(64 * 64);
    // 30x30 (ARC-AGI-1/2) DEBE seguir adentro.
    expect(DEFAULT_SYNTHESIS_BUDGET.maxStructuralSearchArea).toBeGreaterThanOrEqual(30 * 30);
    /* El credito de barridos de entrada tiene que alcanzar para varias semillas de 64x64 -- si
       cayera por debajo de un barrido, la sintesis quedaria muerta en el juego real -- pero tiene
       que seguir siendo un TECHO: si se aflojara a cientos de barridos volveria el costo lineal
       con el historial que BL.21026 encontro (100 observaciones = 1861ms). */
    const barridoDe64 = 64 * 64 * 10;
    expect(DEFAULT_SYNTHESIS_BUDGET.maxSeedSweepCells).toBeGreaterThan(barridoDe64 * 3);
    expect(DEFAULT_SYNTHESIS_BUDGET.maxSeedSweepCells).toBeLessThan(barridoDe64 * 40);
  });
});
