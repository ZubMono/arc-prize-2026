/* [arc-agi-runner/worldModel/__tests__/bl21560.clickTargeting] BL.21560 -- las tres capas que
   deciden DONDE clickear, cada una probada por separado: features de celda, plantilla de parche y
   memoria por (firma, x, y). El efecto agregado sobre dato REAL vive en
   bl21560.realClicks.effect.test.ts.

   Las grillas de aca son MINIATURAS del caso real (una ficha rodeada por el marco de un tablero
   contra la misma ficha rodeada por el fondo), no inventos: reproducen a escala la unica estructura
   que separa un click productivo de uno muerto en las partidas medidas. Espejo exacto de
   arc-agi3-kaggle-agent/tests/test_bl21560_click_targeting.py. */

import { describe, expect, it } from 'vitest';

import {
  CLICK_FEATURE_NAMES,
  construirTableroDeFeatures,
  extraerParche,
  puntuarCelda,
  regionQueCambio,
  similitudDeParche,
} from '../clickFeatures';
import {
  BONO_POR_PLANTILLA,
  ClickMemory,
  PENALIZACION_POR_ANTI_PLANTILLA,
} from '../clickMemory';
import { CLICK_PRIORS } from '../clickPriors';
import type { Grid } from '../grid';
import { IntelligentPolicy } from '../intelligentPolicy';
import type { ArcFrameResponse } from '../../types';

const FONDO = 5;
const MARCO = 4;
const FICHA = 9;
/** 12x12 y no 8x8 para que el FONDO siga siendo el color mayoritario con el marco puesto (108
 *  celdas contra 36): `detectBackgroundColor` elige el mas frecuente y en una grilla chica el marco
 *  lo destronaba -- justo el tipo de detalle que solo se ve corriendo. */
const LADO = 12;

function grillaConFichaEnMarco(): Grid {
  const grid: Grid = Array.from({ length: LADO }, () => new Array<number>(LADO).fill(FONDO));
  for (let y = 3; y < 9; y++) for (let x = 3; x < 9; x++) grid[y][x] = MARCO;
  for (let y = 4; y < 6; y++) for (let x = 4; x < 6; x++) grid[y][x] = FICHA;
  return grid;
}

function grillaConFichaSuelta(): Grid {
  const grid: Grid = Array.from({ length: LADO }, () => new Array<number>(LADO).fill(FONDO));
  for (let y = 4; y < 6; y++) for (let x = 4; x < 6; x++) grid[y][x] = FICHA;
  return grid;
}

function indice(nombre: string): number {
  return (CLICK_FEATURE_NAMES as readonly string[]).indexOf(nombre);
}

describe('BL.21560 -- features de celda para elegir el click', () => {
  it('el orden de las features es un contrato posicional con los priors', () => {
    expect(CLICK_FEATURE_NAMES.length).toBe(CLICK_PRIORS.pesosClick.length);
    expect(CLICK_FEATURE_NAMES[0]).toBe('sesgo');
  });

  it('el vecindario separa la ficha del tablero del panel decorativo', () => {
    const dentro = construirTableroDeFeatures(grillaConFichaEnMarco());
    const suelta = construirTableroDeFeatures(grillaConFichaSuelta());
    const i = indice('componenteRodeadaDeFondo');
    // Misma ficha, mismo color, mismo tamano: lo unico que cambia es que toca el fondo.
    expect(dentro.features(4, 4)[i]).toBe(0);
    expect(suelta.features(4, 4)[i]).toBe(1);
    expect(dentro.tamanoDeComponente(4, 4)).toBe(4);
    expect(suelta.tamanoDeComponente(4, 4)).toBe(4);
  });

  it('describe borde, fondo y region que cambio', () => {
    const tablero = construirTableroDeFeatures(grillaConFichaEnMarco(), {
      regionCambiada: { minX: 4, minY: 4, maxX: 5, maxY: 5 },
    });
    const esquina = tablero.features(4, 4);
    expect(esquina[indice('esBordeDeComponente')]).toBe(1);
    expect(esquina[indice('bordeDeColor')]).toBe(0.5);
    expect(esquina[indice('enRegionQueCambio')]).toBe(1);
    expect(tablero.features(0, 0)[indice('esColorDeFondo')]).toBe(1);
    expect(tablero.features(0, 0)[indice('enRegionQueCambio')]).toBe(0);
  });

  it('con los pesos ajustados la ficha del tablero puntua mas alto que la suelta', () => {
    const dentro = puntuarCelda(
      construirTableroDeFeatures(grillaConFichaEnMarco()).features(4, 4),
      CLICK_PRIORS.pesosClick,
    );
    const suelta = puntuarCelda(
      construirTableroDeFeatures(grillaConFichaSuelta()).features(4, 4),
      CLICK_PRIORS.pesosClick,
    );
    expect(dentro).toBeGreaterThan(suelta);
  });

  it('regionQueCambio devuelve el rectangulo o null', () => {
    const a = grillaConFichaEnMarco();
    const b = a.map((fila) => fila.slice());
    expect(regionQueCambio(a, b)).toBeNull();
    b[3][4] = FICHA;
    b[5][6] = FICHA;
    expect(regionQueCambio(a, b)).toEqual({ minX: 4, minY: 3, maxX: 6, maxY: 5 });
    expect(regionQueCambio(null, b)).toBeNull();
  });
});

describe('BL.21560 -- memoria de clicks del episodio', () => {
  it('no repite una coordenada en el mismo estado', () => {
    const grid = grillaConFichaEnMarco();
    const memoria = new ClickMemory();
    const elegidas = new Set<string>();
    for (let i = 0; i < 6; i++) {
      const objetivo = memoria.elegirObjetivo(grid, 'firma-1', () => 0);
      elegidas.add(`${objetivo.x},${objetivo.y}`);
      memoria.registrarResultado('firma-1', objetivo.x, objetivo.y, false, grid);
    }
    expect(elegidas.size).toBe(6);
  });

  it('la misma coordenada vuelve a ser elegible si cambia la firma', () => {
    const grid = grillaConFichaEnMarco();
    const memoria = new ClickMemory();
    const primera = memoria.elegirObjetivo(grid, 'firma-1', () => 0);
    memoria.registrarResultado('firma-1', primera.x, primera.y, false, grid);
    const segunda = memoria.elegirObjetivo(grid, 'firma-1', () => 0);
    expect([segunda.x, segunda.y]).not.toEqual([primera.x, primera.y]);
    const otroEstado = memoria.elegirObjetivo(grid, 'firma-2', () => 0);
    expect([otroEstado.x, otroEstado.y]).toEqual([primera.x, primera.y]);
  });

  it('un click con efecto ilumina las celdas con el mismo parche', () => {
    const ancho = 12;
    const grid: Grid = Array.from({ length: 14 }, () => new Array<number>(ancho).fill(FONDO));
    for (let y = 3; y < 7; y++) for (let x = 1; x < 11; x++) grid[y][x] = MARCO;
    for (const x0 of [2, 7]) {
      for (let y = 4; y < 6; y++) for (let x = x0; x < x0 + 2; x++) grid[y][x] = FICHA;
    }

    const memoria = new ClickMemory();
    // Esquina INFERIOR DERECHA de la segunda ficha: otro parche, nunca deberia recibir el bono.
    const otraEsquina = 5 * ancho + 8;
    const sinPlantilla = memoria.puntajesPorCelda(grid)[otraEsquina];
    memoria.registrarResultado('firma-1', 2, 4, true, grid);
    expect(memoria.plantillasAprendidas).toBe(1);
    // La esquina HOMOLOGA de la otra ficha (misma orientacion) sube exactamente el bono.
    const conPlantilla = memoria.puntajesPorCelda(grid)[4 * ancho + 7];
    const soloPrior = puntuarCelda(
      construirTableroDeFeatures(grid).features(7, 4),
      CLICK_PRIORS.pesosClick,
    );
    expect(conPlantilla).toBeCloseTo(soloPrior + BONO_POR_PLANTILLA, 10);
    expect(memoria.puntajesPorCelda(grid)[otraEsquina]).toBe(sinPlantilla);
  });

  it('dos clicks muertos con el mismo parche descartan TODA la clase de celdas', () => {
    /* Es lo que evita barrer una region grande e inerte celda por celda: medido contra la API
       oficial en lp85-305b61c3, sin esto el agente gasto 403 de 499 clicks en la cenefa decorativa
       del borde. Con anti-plantillas, la misma partida acerto 13 de 79 (16,5% contra el 4,2% de la
       corrida grabada). */
    const grid = grillaConFichaEnMarco();
    const memoria = new ClickMemory();
    // (0,5) y (0,7) son interiores del fondo: mismo parche uniforme.
    const antes = memoria.puntajesPorCelda(grid)[9 * LADO + 0];
    memoria.registrarResultado('f', 0, 5, false, grid);
    expect(memoria.antiPlantillasAprendidas).toBe(0); // un solo fallo puede ser ruido
    memoria.registrarResultado('f', 0, 7, false, grid);
    expect(memoria.antiPlantillasAprendidas).toBe(1);
    // Una TERCERA celda con el mismo parche, nunca clickeada, ya quedo descartada.
    expect(memoria.puntajesPorCelda(grid)[9 * LADO + 0]).toBeCloseTo(
      antes - PENALIZACION_POR_ANTI_PLANTILLA,
      10,
    );
  });

  it('un click con efecto desmiente la anti-plantilla del mismo parche', () => {
    const grid = grillaConFichaEnMarco();
    const memoria = new ClickMemory();
    memoria.registrarResultado('f', 0, 5, false, grid);
    memoria.registrarResultado('f', 0, 7, false, grid);
    expect(memoria.antiPlantillasAprendidas).toBe(1);
    memoria.registrarResultado('f', 0, 9, true, grid);
    expect(memoria.antiPlantillasAprendidas).toBe(0);
    expect(memoria.plantillasAprendidas).toBe(1);
  });

  it('la plantilla se toma de la grilla PREVIA al click, y solo cuando hubo efecto', () => {
    const grid = grillaConFichaEnMarco();
    const memoria = new ClickMemory();
    memoria.registrarResultado('firma-1', 4, 4, true, grid);
    expect(memoria.plantillasAprendidas).toBe(1);
    expect(similitudDeParche(extraerParche(grid, 4, 4), extraerParche(grid, 4, 4))).toBe(1);
    memoria.registrarResultado('firma-1', 7, 7, false, grid);
    expect(memoria.plantillasAprendidas).toBe(1);
  });

  it('elegirObjetivo consume EXACTAMENTE un numero del rng', () => {
    const grid = grillaConFichaEnMarco();
    const memoria = new ClickMemory();
    let consumidos = 0;
    const rng = (): number => {
      consumidos++;
      return 0.5;
    };
    memoria.elegirObjetivo(grid, 'firma-1', rng);
    expect(consumidos).toBe(1);
    memoria.registrarResultado('firma-1', 4, 4, true, grid);
    memoria.elegirObjetivo(grid, 'firma-1', rng);
    expect(consumidos).toBe(2);
  });
});

describe('BL.21560 -- la politica atribuye el resultado al click que lo produjo', () => {
  function frame(grid: Grid, acciones: number[] = [6]): ArcFrameResponse {
    return {
      game_id: 'juego',
      guid: 'g',
      frame: [grid],
      state: 'NOT_FINISHED',
      available_actions: acciones,
    } as ArcFrameResponse;
  }

  it('no vuelve a clickear la misma coordenada mientras el tablero no cambie', () => {
    const grid = grillaConFichaEnMarco();
    const policy = new IntelligentPolicy({ rng: () => 0.5 });
    const emitidas = new Set<string>();
    for (let i = 0; i < 8; i++) {
      const decision = policy.decide(frame(grid));
      expect(decision.action).toBe('ACTION6');
      emitidas.add(`${decision.x},${decision.y}`);
    }
    /* Sin memoria de clicks, un rng constante devolvia SIEMPRE la misma coordenada: ese era,
       literalmente, el defecto medido (117 repeticiones en 346 clicks reales). */
    expect(emitidas.size).toBe(8);
  });
});
