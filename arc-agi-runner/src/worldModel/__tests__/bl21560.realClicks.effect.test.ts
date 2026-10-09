/* [arc-agi-runner/worldModel/__tests__/bl21560.realClicks.effect] BL.21560 -- el efecto del ranker
   de coordenadas y de la memoria de clicks, medido sobre la partida REAL grabada en
   __fixtures__/clickRealFrames.json (corrida ft09-0d8bbf25 contra la API oficial).

   POR QUE DATO REAL Y NO GRILLAS SINTETICAS. Ya paso dos veces (BL.21500 y el primer intento de
   BL.21558) que un cambio "verde en los tests" tuviera efecto CERO contra frames reales. Aca la
   trampa concreta es que el MISMO dibujo (una ficha 6x6 de color 9) aparece dos veces en pantalla:
   como panel decorativo, donde el click no hace nada, y como ficha del tablero, donde siempre
   funciona. Ninguna grilla sintetica razonable reproduce eso -- el dato si.

   LOS NUMEROS SON UN CONTRATO. Regenerar el corpus (scripts/exportClickCorpus.ts) o los priors
   (arc-agi3-kaggle-agent/scripts/fit_click_priors.py) obliga a re-medirlos a mano en los DOS
   puertos -- que es exactamente lo que se quiere que cueste. El espejo Python vive en
   arc-agi3-kaggle-agent/tests/test_bl21560_real_clicks.py y afirma los mismos valores. */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { ClickMemory } from '../clickMemory';
import { CLICK_PRIORS } from '../clickPriors';
import { construirTableroDeFeatures, puntuarCelda, sigmoide, regionQueCambio } from '../clickFeatures';
import type { Grid } from '../grid';
import { computeStateSignature } from '../stateSignature';

interface PasoDeClick {
  accion: string;
  x?: number;
  y?: number;
  diff: number[];
}

interface PartidaDeClicks {
  gameId: string;
  base: number[][];
  pasos: PasoDeClick[];
}

const RUTA = resolve(__dirname, '../__fixtures__/clickRealFrames.json');
const CORPUS = JSON.parse(readFileSync(RUTA, 'utf-8')) as { partidas: PartidaDeClicks[] };

/** Acciones disponibles de la partida grabada: ft09 es CLICK-ONLY (la unica accion es ACTION6), que
 *  es justamente lo que reduce el juego al problema de donde clickear. */
const ACCIONES_DISPONIBLES = [6];

function aplicarDiff(grid: Grid, diff: number[]): Grid {
  const nueva = grid.map((fila) => fila.slice());
  for (let i = 0; i < diff.length; i += 3) nueva[diff[i]][diff[i + 1]] = diff[i + 2];
  return nueva;
}

interface ClickReal {
  grid: Grid;
  gridPrevia: Grid | null;
  x: number;
  y: number;
  productivo: boolean;
}

/** Reconstruye la secuencia real de (grilla, click, resultado). La grilla de cada paso es la que el
 *  agente TENIA DELANTE al decidir; el resultado es el diff que produjo su click. */
function clicksReales(): ClickReal[] {
  const salida: ClickReal[] = [];
  for (const partida of CORPUS.partidas) {
    let grid: Grid = partida.base.map((fila) => fila.slice());
    let previa: Grid | null = null;
    for (const paso of partida.pasos) {
      const siguiente = aplicarDiff(grid, paso.diff);
      if (paso.x !== undefined && paso.y !== undefined) {
        salida.push({ grid, gridPrevia: previa, x: paso.x, y: paso.y, productivo: paso.diff.length > 0 });
      }
      previa = grid;
      grid = siguiente;
    }
  }
  return salida;
}

const CLICKS = clicksReales();

/** Coordenadas con resultado OBSERVADO en el corpus. Se comprueba abajo que ninguna aparece con los
 *  dos resultados: en esta partida la etiqueta es consistente por coordenada, y eso es lo que
 *  habilita usarla como oraculo para evaluar decisiones contrafacticas. */
function oraculo(): Map<string, boolean> {
  const mapa = new Map<string, boolean>();
  for (const c of CLICKS) mapa.set(`${c.x},${c.y}`, (mapa.get(`${c.x},${c.y}`) ?? false) || c.productivo);
  return mapa;
}

const ORACULO = oraculo();

describe('BL.21560 -- clicks REALES de ARC-AGI-3: la tasa de acierto antes y despues', () => {
  it('el corpus trae la patologia medida: 346 clicks, 32 productivos, 117 coordenadas repetidas', () => {
    expect(CLICKS.length).toBe(346);
    const productivos = CLICKS.filter((c) => c.productivo).length;
    expect(productivos).toBe(32);

    const vistas = new Set<string>();
    let repetidas = 0;
    let sobreFallida = 0;
    const fallidas = new Set<string>();
    for (const c of CLICKS) {
      const clave = `${c.x},${c.y}`;
      if (vistas.has(clave)) repetidas++;
      if (fallidas.has(clave)) sobreFallida++;
      vistas.add(clave);
      if (!c.productivo) fallidas.add(clave);
    }
    expect(repetidas).toBe(117);
    expect(sobreFallida).toBe(106);
    /* 9,2% -- y no es mala suerte: la heuristica previa sorteaba uniformemente entre ~410 celdas de
       "borde de color" de las cuales ~36 son esquinas de ficha. 36/410 = 8,8%. */
    expect(productivos / CLICKS.length).toBeCloseTo(0.0925, 4);
  });

  it('la etiqueta es consistente por coordenada -- ninguna funciona y falla en la misma partida', () => {
    const productivas = new Set(CLICKS.filter((c) => c.productivo).map((c) => `${c.x},${c.y}`));
    const muertas = new Set(CLICKS.filter((c) => !c.productivo).map((c) => `${c.x},${c.y}`));
    const ambiguas = [...productivas].filter((k) => muertas.has(k));
    expect(ambiguas).toEqual([]);
    expect(productivas.size).toBe(21);
  });

  it('el ranker separa los clicks productivos de los muertos sobre los MISMOS clicks reales', () => {
    /* Metrica sin contrafactuales: se puntua cada click que el agente REALMENTE hizo y se mide
       cuantos de los que el ranker habria aprobado eran productivos. */
    let aprobados = 0;
    let aprobadosProductivos = 0;
    for (const c of CLICKS) {
      const tablero = construirTableroDeFeatures(c.grid, {
        regionCambiada: regionQueCambio(c.gridPrevia, c.grid),
      });
      const prob = sigmoide(puntuarCelda(tablero.features(c.x, c.y), CLICK_PRIORS.pesosClick));
      if (prob < CLICK_PRIORS.umbralesDetectores.probabilidadMinimaDeClick) continue;
      aprobados++;
      if (c.productivo) aprobadosProductivos++;
    }
    /* Los 32 productivos entran y ningun muerto se cuela: precision 1,00 contra la tasa base de
       0,092. Es el filtro que convierte "clickear en un borde" en "clickear en una ficha". */
    expect(aprobados).toBe(32);
    expect(aprobadosProductivos).toBe(32);
  });

  it('la politica nueva elige coordenadas productivas donde la vieja acertaba 1 de 11', () => {
    /* Evaluacion off-policy conservadora: se recorre la MISMA trayectoria real (la politica no
       puede cambiar el tablero, asi que no se inventa ninguna transicion) y en cada paso se le pide
       a la memoria de clicks su coordenada. El resultado se clasifica con el oraculo observado; una
       coordenada sin observar se cuenta como DESCONOCIDA y se le realimenta "no hubo cambio", que es
       el lado pesimista: castiga a la politica nueva quitandole plantillas que quizas merecia. */
    const memoria = new ClickMemory();
    const rng = (): number => 0.5;
    let productivos = 0;
    let muertos = 0;
    let desconocidos = 0;
    const emitidas = new Set<string>();
    let repetidas = 0;

    for (const c of CLICKS) {
      const firma = String(computeStateSignature(c.grid, ACCIONES_DISPONIBLES, null));
      const objetivo = memoria.elegirObjetivo(
        c.grid,
        firma,
        rng,
        regionQueCambio(c.gridPrevia, c.grid),
      );
      const clave = `${firma}|${objetivo.x},${objetivo.y}`;
      if (emitidas.has(clave)) repetidas++;
      emitidas.add(clave);

      const etiqueta = ORACULO.get(`${objetivo.x},${objetivo.y}`);
      if (etiqueta === undefined) desconocidos++;
      else if (etiqueta) productivos++;
      else muertos++;
      memoria.registrarResultado(firma, objetivo.x, objetivo.y, etiqueta === true, c.grid);
    }

    console.log(
      `[BL.21560][ft09] politica nueva -- productivos ${productivos}, muertos ${muertos}, ` +
        `desconocidos ${desconocidos}, plantillas ${memoria.plantillasAprendidas} ` +
        `(grabado: 32 productivos de 346)`,
    );
    /* Nunca repite un (firma, x, y): es la garantia estructural de la capa de memoria, y por si
       sola borra los 106 clicks que el agente gasto sobre coordenadas ya fallidas. */
    expect(repetidas).toBe(0);
    /* Clicks sobre una coordenada que el corpus vio fallar: 106 -> 1. El unico que queda es un
       artefacto de la realimentacion pesimista de esta simulacion (a las coordenadas desconocidas se
       les responde "no hubo cambio", lo que crea anti-plantillas que el juego real no crearia). */
    expect(muertos).toBe(1);
    /* 232 aciertos comprobados sobre los mismos 346 pasos, contra los 32 que la partida grabo:
       67,1% contra 9,2%. Los 113 restantes caen en coordenadas que el corpus nunca probo (no se
       cuentan como acierto aunque sean celdas de la misma ficha), asi que 67,1% es un PISO. */
    expect(productivos).toBe(232);
    expect(desconocidos).toBe(113);
    expect(memoria.plantillasAprendidas).toBe(7);
  });
});
