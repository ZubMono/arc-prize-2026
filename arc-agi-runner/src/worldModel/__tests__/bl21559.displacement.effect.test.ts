/* [arc-agi-runner/worldModel/bl21559.displacement.effect.test] BL.21559 -- la mitad CAUSAL de la
   medicion: aca el entorno RESPONDE a la accion que la politica eligio, cosa que la evaluacion en
   sombra sobre las partidas grabadas (bl21559.realGames.effect.test.ts) no puede hacer -- no existe
   simulador de ARC-AGI-3 y una trayectoria grabada solo sabe que paso con la accion que se ejecuto.

   QUE MIDE, y por que esa magnitud. DESPLAZAMIENTO NETO del marcador: cuan lejos del punto de
   partida llego el agente en el episodio. Es la traduccion literal del defecto reportado -- "arriba
   + abajo + izquierda + derecha se cancelan exacto y el agente termina el episodio donde empezo" --
   y no depende de ninguna interpretacion del ranking: o el bicho se movio, o no.

   POR QUE EL ENTORNO ES SINTETICO PERO EL RUIDO ES REAL. Las reglas del tablero son de juguete
   (`SyntheticGridEnv`: ACTION1..4 mueven una celda, ACTION5 nunca hace nada), pero el RUIDO es la
   forma medida en la API oficial: una BARRA DE PROGRESO que enciende una celda nueva por paso, que
   es lo que se encontro en las cuatro partidas reales (lf52 fila 0, ar25 columna 63, ka59 y dc22
   fila 63). Sin ese ruido el test no probaria nada del camino real, porque es justo la barra la que
   decide cuando la macro corta.

   LA REFERENCIA "CODIGO VIEJO" no es una reimplementacion: es `selectExploratoryAction` sin
   opciones -- exactamente la funcion de produccion en su forma previa a este BL -- cableada al
   mismo entorno y alimentando la misma clase `TransitionMemory`. La unica diferencia entre las dos
   ramas es lo que agrega BL.21559. */
import { describe, expect, it } from 'vitest';

import { SyntheticGridEnv } from '../../__tests__/support/syntheticGridEnv';
import { createSeededRandom } from '../../prng';
import type { ArcAction } from '../../types';
import { selectExploratoryAction } from '../activeLearning';
import type { Grid } from '../grid';
import { IntelligentPolicy } from '../intelligentPolicy';
import { extractGrid } from '../stateSignature';
import { TransitionMemory } from '../transitionMemory';

/** 30 pasos alcanzan: la mascara de la barra se forma alrededor del paso 17 (12 transiciones
 *  minimas + 16 celdas de barra encendidas) y el desplazamiento ya quedo decidido mucho antes. Mas
 *  pasos solo encarecerian la sintesis, que corre sobre la grilla entera en cada observacion. */
const PASOS = 30;
/** Tablero de 3x16: el ancho lo fija la barra (16 celdas es el minimo para que se la reconozca como
 *  tal) y el alto se deja en el minimo util, porque la sintesis del modelo de mundo cuesta por
 *  celda y este archivo corre dos episodios completos por semilla. */
const ALTO = 3;
const ANCHO = 16;
const INICIO = { x: 8, y: 1 };
const SEEDS = ['bl21559-d1', 'bl21559-d2', 'bl21559-d3'];

function crearEntorno(): SyntheticGridEnv {
  return new SyntheticGridEnv({
    size: ALTO,
    width: ANCHO,
    start: INICIO,
    // `endless` apaga el WIN: la partida no termina nunca, igual que las cuatro partidas reales
    // medidas (todas agotaron el presupuesto sin ganar). Un episodio que termina en 6 pasos no mide
    // desplazamiento.
    target: { x: 0, y: 0 },
    endless: true,
    progressBar: true,
  });
}

function distanciaAlInicio(p: { x: number; y: number }): number {
  return Math.abs(p.x - INICIO.x) + Math.abs(p.y - INICIO.y);
}

interface Episodio {
  /** Lo mas lejos del inicio que llego el marcador en todo el episodio. */
  distanciaMaxima: number;
  /** Distancia al inicio en el ultimo paso -- el "termino donde empezo" del reporte. */
  distanciaFinal: number;
  acciones: string[];
}

/** Episodio con la politica de produccion (macro-acciones + novedad). Sin `goalGrid`, que es el
 *  caso REAL contra la API de ARC: la grilla de WIN no se conoce de antemano. */
function correrPoliticaNueva(seed: string): Episodio {
  const env = crearEntorno();
  const policy = new IntelligentPolicy({ rng: createSeededRandom(seed), actionBudget: PASOS });
  let frame = env.reset();
  let distanciaMaxima = 0;
  const acciones: string[] = [];
  for (let i = 0; i < PASOS; i++) {
    const decision = policy.decide(frame);
    acciones.push(decision.action);
    frame = decision.action === 'RESET' ? env.reset() : env.step(decision.action as ArcAction);
    distanciaMaxima = Math.max(distanciaMaxima, distanciaAlInicio(env.markerPosition));
  }
  return { distanciaMaxima, distanciaFinal: distanciaAlInicio(env.markerPosition), acciones };
}

/** Episodio con la regla ANTERIOR a este BL: la misma `selectExploratoryAction`, invocada sin
 *  opciones (sin novedad, sin turno externo) y sin compromiso entre pasos. El resto del cableado --
 *  alimentar `TransitionMemory` con (accion, pre, post) -- es el que hace `IntelligentPolicy`. */
function correrReglaVieja(seed: string): Episodio {
  const env = crearEntorno();
  const memoria = new TransitionMemory({});
  const rng = createSeededRandom(seed);
  let frame = env.reset();
  let prevGrid: Grid | null = null;
  let prevAccion: string | null = null;
  let distanciaMaxima = 0;
  const acciones: string[] = [];
  for (let i = 0; i < PASOS; i++) {
    const grid = extractGrid(frame);
    if (prevGrid !== null && prevAccion !== null && grid !== null) {
      memoria.recordObservation(prevAccion, prevGrid, grid);
    }
    const disponibles = frame.available_actions.map((n) => `ACTION${n}`);
    const accion = selectExploratoryAction(disponibles, memoria, rng);
    acciones.push(accion);
    prevGrid = grid;
    prevAccion = accion;
    frame = env.step(accion as ArcAction);
    distanciaMaxima = Math.max(distanciaMaxima, distanciaAlInicio(env.markerPosition));
  }
  return { distanciaMaxima, distanciaFinal: distanciaAlInicio(env.markerPosition), acciones };
}

function rachaMaxima(secuencia: string[]): number {
  let maxima = 1;
  let actual = 1;
  for (let i = 1; i < secuencia.length; i++) {
    if (secuencia[i] === secuencia[i - 1]) {
      actual++;
      if (actual > maxima) maxima = actual;
    } else {
      actual = 1;
    }
  }
  return maxima;
}

const episodios = SEEDS.map((seed) => ({
  seed,
  vieja: correrReglaVieja(seed),
  nueva: correrPoliticaNueva(seed),
}));

describe('BL.21559 -- el agente se MUEVE: desplazamiento con el entorno respondiendo', () => {
  it('la regla vieja termina el episodio practicamente donde empezo', () => {
    for (const { seed, vieja } of episodios) {
      // eslint-disable-next-line no-console -- magnitud medida, se quiere ver en el reporter
      console.log(
        `[BL.21559][${seed}] regla vieja -- distancia maxima ${vieja.distanciaMaxima}, ` +
          `distancia final ${vieja.distanciaFinal}, racha maxima ${rachaMaxima(vieja.acciones)}`,
      );
      /* Cuatro direcciones repartidas parejo se cancelan: el marcador oscila alrededor del inicio y
         no llega a mas de dos celdas en 30 pasos, con un tablero que le permitiria llegar a ocho. */
      expect(vieja.distanciaMaxima, `${seed}: la regla vieja se movio`).toBeLessThanOrEqual(3);
    }
  });

  it('con macro-acciones el agente recorre el tablero -- 3x mas lejos, en TODAS las semillas', () => {
    for (const { seed, nueva, vieja } of episodios) {
      // eslint-disable-next-line no-console -- magnitud medida, se quiere ver en el reporter
      console.log(
        `[BL.21559][${seed}] politica nueva -- distancia maxima ${nueva.distanciaMaxima}, ` +
          `distancia final ${nueva.distanciaFinal}, racha maxima ${rachaMaxima(nueva.acciones)}`,
      );
      expect(
        nueva.distanciaMaxima,
        `${seed}: la macro no desplazo al agente`,
      ).toBeGreaterThanOrEqual(6);
      expect(nueva.distanciaMaxima).toBeGreaterThan(vieja.distanciaMaxima * 3);
    }
  });

  it('el compromiso se ve en la secuencia: rachas largas donde antes no habia ninguna', () => {
    for (const { seed, vieja, nueva } of episodios) {
      // La regla vieja no puede pasar de 2 seguidas salvo empate del barajado.
      expect(rachaMaxima(vieja.acciones), `${seed}`).toBeLessThanOrEqual(3);
      expect(rachaMaxima(nueva.acciones), `${seed}`).toBeGreaterThanOrEqual(6);
    }
  });
});
