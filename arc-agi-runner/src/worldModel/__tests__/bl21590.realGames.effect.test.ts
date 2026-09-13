/* [arc-agi-runner/worldModel/bl21590.realGames.effect.test] BL.21590 -- EFECTO del prior de
   direcciones medido sobre las mismas partidas REALES de ARC-AGI-3 que usan BL.21558/21561
   (`__fixtures__/volatilityRealGames.json`), como DELTA con-prior vs sin-prior.

   QUE SE AFIRMA. (a) CON prior el mapeo correcto existe desde el PASO CERO (la siembra), y el
   sin-prior (MechanicsMemory de BL.21561) tarda 10-12 pasos en recuperarlo -- ese es el ahorro.
   (b) Bajo la grabacion round-robin del agente viejo (rachas de a lo sumo DOS pasos iguales, el
   protocolo que FABRICA mapeos invertidos) la creencia no comete UN solo remapeo espurio: cero
   refutaciones en las cuatro partidas. (c) Las confirmaciones por corrida monotona llegan solo
   donde la grabacion repite la accion, con el paso exacto anotado. (d) ACTION5/ACTION7 quedan
   clasificadas por firma de mecanica con conteos exactos.

   POR QUE LOS NUMEROS SON EXACTOS. Contrato ejecutable con el puerto Python:
   `arc-agi3-kaggle-agent/tests/test_bl21590_real_games.py` afirma los MISMOS valores sobre la
   MISMA grabacion. Si un puerto cambia el criterio y el otro no, uno de los dos se pone en rojo. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { CreenciaDeDirecciones, IncognitasDeMecanica } from '../directionBeliefs';
import type { Grid } from '../grid';
import { MechanicsMemory } from '../mechanicsMemory';
import { detectarMecanica } from '../objectMechanics';
import { VolatilityTracker } from '../volatilityMask';

interface PasoGrabado {
  accion: string;
  accionesDisponibles: number[];
  diff: number[];
}
interface JuegoGrabado {
  gameId: string;
  alto: number;
  ancho: number;
  base: number[][];
  pasos: PasoGrabado[];
}

const FIXTURE = resolve(__dirname, '../__fixtures__/volatilityRealGames.json');
const juegos = (JSON.parse(readFileSync(FIXTURE, 'utf8')) as { juegos: JuegoGrabado[] }).juegos;

const FLECHAS = ['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4'];
const MAPEO_CANONICO: Record<string, readonly [number, number]> = {
  ACTION1: [-1, 0],
  ACTION2: [1, 0],
  ACTION3: [0, -1],
  ACTION4: [0, 1],
};

/** Magnitudes medidas sobre la grabacion vigente -- contrato de paridad con el puerto Python.
 *  `pasoSinPrior` = primer paso en que MechanicsMemory conoce la direccion de las CUATRO flechas
 *  (null = jamas); `confirmadasEn` = paso de la primera corrida monotona que confirmo cada
 *  flecha (las que faltan nunca tuvieron dos pulsaciones consecutivas con traslacion: la
 *  grabacion es round-robin y ese protocolo no fabrica corridas). */
const ESPERADO: Record<
  string,
  {
    pasoSinPrior: number | null;
    confirmadasEn: Record<string, number>;
    incognitas: Record<string, { firma: string; conteo: number }>;
  }
> = {
  'lf52-271a04aa': {
    pasoSinPrior: null, // 92 pasos y el detector solo no conoce NINGUNA direccion
    confirmadasEn: {},
    incognitas: { ACTION7: { firma: 'inerte', conteo: 14 } },
  },
  'ar25-0c556536': {
    pasoSinPrior: 12,
    confirmadasEn: { ACTION3: 27 },
    incognitas: {
      ACTION5: { firma: 'inerte', conteo: 3 },
      ACTION7: { firma: 'cambioDeEscena', conteo: 15 },
    },
  },
  'ka59-38d34dbb': {
    pasoSinPrior: 10,
    confirmadasEn: { ACTION1: 6, ACTION2: 55, ACTION4: 91 },
    incognitas: {},
  },
  'dc22-fdcac232': {
    pasoSinPrior: 10,
    confirmadasEn: { ACTION2: 6, ACTION3: 76, ACTION4: 47 },
    incognitas: {},
  },
};

function reconstruir(juego: JuegoGrabado): Grid[] {
  const grillas: Grid[] = [juego.base.map((fila) => [...fila])];
  for (const paso of juego.pasos) {
    const anterior = grillas[grillas.length - 1];
    const siguiente = anterior.map((fila) => [...fila]);
    for (let i = 0; i < paso.diff.length; i += 3) {
      siguiente[paso.diff[i]][paso.diff[i + 1]] = paso.diff[i + 2];
    }
    grillas.push(siguiente);
  }
  return grillas;
}

interface Medicion {
  creencia: CreenciaDeDirecciones;
  incognitas: IncognitasDeMecanica;
  confirmadasEn: Record<string, number>;
  pasoSinPrior: number | null;
}

function medir(juego: JuegoGrabado): Medicion {
  const grillas = reconstruir(juego);
  const tracker = new VolatilityTracker();
  juego.pasos.forEach((paso, i) => tracker.observe(paso.accion, grillas[i], grillas[i + 1]));
  const mask = tracker.mask;

  const creencia = new CreenciaDeDirecciones();
  const incognitas = new IncognitasDeMecanica();
  const memoria = new MechanicsMemory();
  creencia.sembrar(juego.pasos[0].accionesDisponibles);
  const sembradas = creencia.accionesSembradas();

  const confirmadasEn: Record<string, number> = {};
  let pasoSinPrior: number | null = null;
  juego.pasos.forEach((paso, i) => {
    const mecanica = detectarMecanica(grillas[i], grillas[i + 1], mask);
    creencia.observar(paso.accion, mecanica);
    incognitas.observar(paso.accion, mecanica);
    memoria.observe(paso.accion, grillas[i], grillas[i + 1], mask);
    for (const a of sembradas) {
      if (confirmadasEn[a] === undefined && creencia.estadoDe(a) === 'confirmada') {
        confirmadasEn[a] = i + 1;
      }
    }
    if (pasoSinPrior === null && sembradas.every((a) => memoria.getDirection(a) !== null)) {
      pasoSinPrior = i + 1;
    }
  });
  return { creencia, incognitas, confirmadasEn, pasoSinPrior };
}

const mediciones = new Map<string, Medicion>(juegos.map((j) => [j.gameId, medir(j)]));

describe('BL.21590 -- prior de direcciones sobre las partidas reales (paridad con Python)', () => {
  it('el fixture trae las cuatro partidas', () => {
    expect([...mediciones.keys()].sort()).toEqual([
      'ar25-0c556536',
      'dc22-fdcac232',
      'ka59-38d34dbb',
      'lf52-271a04aa',
    ]);
  });

  it('DELTA: con prior el mapeo canonico existe desde el paso CERO; sin prior tarda 10-12 pasos', () => {
    for (const [gameId, m] of mediciones) {
      // La siembra deja el mapeo canonico completo antes de la primera accion.
      expect(m.creencia.accionesSembradas()).toEqual(FLECHAS);
      expect(m.creencia.mapeo()).toEqual(MAPEO_CANONICO);
      expect(m.pasoSinPrior).toBe(ESPERADO[gameId].pasoSinPrior);
      if (m.pasoSinPrior !== null) {
        expect(m.pasoSinPrior).toBeGreaterThanOrEqual(10); // el redescubrimiento que el prior ahorra
      }
    }
  });

  it('cero remapeos espurios bajo el round-robin que fabrica mapeos invertidos', () => {
    for (const [gameId, m] of mediciones) {
      for (const a of FLECHAS) {
        expect(m.creencia.refutacionesDe(a), `${gameId} ${a}`).toBe(0);
        expect(m.creencia.estadoDe(a), `${gameId} ${a}`).not.toBe('remapeada');
      }
    }
  });

  it('las confirmaciones por corrida monotona llegan en el paso exacto medido', () => {
    for (const [gameId, m] of mediciones) {
      expect(m.confirmadasEn, gameId).toEqual(ESPERADO[gameId].confirmadasEn);
    }
  });

  it('ACTION5/ACTION7 quedan clasificadas por firma de mecanica con conteos exactos', () => {
    for (const [gameId, m] of mediciones) {
      for (const [accion, esperado] of Object.entries(ESPERADO[gameId].incognitas)) {
        expect(m.incognitas.dominanteDe(accion), `${gameId} ${accion}`).toBe(esperado.firma);
        expect(
          m.incognitas.conteosDe(accion)[esperado.firma as 'inerte'],
          `${gameId} ${accion}`,
        ).toBe(esperado.conteo);
      }
    }
  });
});
