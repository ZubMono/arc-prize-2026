/* [arc-agi-runner/worldModel/bl21593.realGames.effect.test] BL.21593 -- EFECTO del posterior
   jerarquico sobre las mismas partidas REALES de ARC-AGI-3 (`__fixtures__/volatilityRealGames.
   json`), como DELTA contra la maquina de estados de BL.21590 sola.

   QUE SE AFIRMA, con numeros exactos (paridad con test_bl21593_real_games.py del puerto Python):
   (a) DELTA "acciones hasta mapeo resuelto": con el posterior las cuatro flechas quedan
       resueltas en 5-14 pasos; con SOLO los estados terminales de BL.21590 NINGUNA de las
       cuatro partidas resuelve jamas el mapeo completo sobre esta grabacion round-robin.
   (b) El posterior llega a las respuestas CORRECTAS: mapeo canonico al 0.98 donde las flechas
       mueven (ar25/ka59/dc22) e `inerte` via arquetipo flechasSinMapeo donde no (lf52).
   (c) La pared se VE en dato real: lf52 tiene 44 fallos de flecha con pared presente en la
       direccion canonica -- quedan explicados y no cuentan contra el mapeo.
   (d) Cero remapeos espurios bajo el protocolo que fabrica mapeos invertidos. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { CreenciaDeDirecciones } from '../directionBeliefs';
import type { Grid } from '../grid';
import { ARQUETIPO_MUEVE, ARQUETIPO_SIN_MAPEO, ARQUETIPOS } from '../mechanicsPosterior';
import { detectarMecanica } from '../objectMechanics';
import { VolatilityTracker } from '../volatilityMask';
import {
  contextoDePared,
  PARED_PRESENTE,
  profundidadDeSondeo,
  RastreadorDeAvatar,
} from '../wallPerception';

interface PasoGrabado {
  accion: string;
  accionesDisponibles: number[];
  diff: number[];
}
interface JuegoGrabado {
  gameId: string;
  base: number[][];
  pasos: PasoGrabado[];
}

const FIXTURE = resolve(__dirname, '../__fixtures__/volatilityRealGames.json');
const juegos = (JSON.parse(readFileSync(FIXTURE, 'utf8')) as { juegos: JuegoGrabado[] }).juegos;

const ESTADOS_TERMINALES_21590 = ['confirmada', 'remapeada', 'observada', 'sinEvidencia'];
const NOMBRE_DE_DIRECCION = new Map<string, string>([
  ['-1,0', 'arriba'],
  ['1,0', 'abajo'],
  ['0,-1', 'izquierda'],
  ['0,1', 'derecha'],
]);
const CANONICO: Record<string, readonly [number, number]> = {
  ACTION1: [-1, 0],
  ACTION2: [1, 0],
  ACTION3: [0, -1],
  ACTION4: [0, 1],
};

/** Magnitudes medidas sobre la grabacion vigente -- contrato de paridad con el puerto Python. */
const ESPERADO: Record<
  string,
  {
    pasoResueltoPosterior: number;
    dominantes: Record<string, string>;
    arquetipo: string;
    fallosConParedCanonica: number;
  }
> = {
  'lf52-271a04aa': {
    pasoResueltoPosterior: 14,
    dominantes: { ACTION1: 'inerte', ACTION2: 'inerte', ACTION3: 'inerte', ACTION4: 'inerte' },
    arquetipo: ARQUETIPO_SIN_MAPEO,
    fallosConParedCanonica: 44,
  },
  'ar25-0c556536': {
    pasoResueltoPosterior: 7,
    dominantes: { ACTION1: 'arriba', ACTION2: 'abajo', ACTION3: 'izquierda', ACTION4: 'derecha' },
    arquetipo: ARQUETIPO_MUEVE,
    fallosConParedCanonica: 1,
  },
  'ka59-38d34dbb': {
    pasoResueltoPosterior: 5,
    dominantes: { ACTION1: 'arriba', ACTION2: 'abajo', ACTION3: 'izquierda', ACTION4: 'derecha' },
    arquetipo: ARQUETIPO_MUEVE,
    fallosConParedCanonica: 0,
  },
  'dc22-fdcac232': {
    pasoResueltoPosterior: 5,
    dominantes: { ACTION1: 'arriba', ACTION2: 'abajo', ACTION3: 'izquierda', ACTION4: 'derecha' },
    arquetipo: ARQUETIPO_MUEVE,
    fallosConParedCanonica: 0,
  },
};

function reconstruir(juego: JuegoGrabado): Grid[] {
  const grillas: Grid[] = [juego.base.map((fila) => [...fila])];
  for (const paso of juego.pasos) {
    const siguiente = grillas[grillas.length - 1].map((fila) => [...fila]);
    for (let i = 0; i < paso.diff.length; i += 3) {
      siguiente[paso.diff[i]][paso.diff[i + 1]] = paso.diff[i + 2];
    }
    grillas.push(siguiente);
  }
  return grillas;
}

interface Medicion {
  creencia: CreenciaDeDirecciones;
  sembradas: string[];
  pasoResueltoPosterior: number | null;
  pasoResueltoEstados: number | null;
  fallosConPared: number;
}

/** El MISMO pipeline que la politica del agente: mascara del episodio, detector de BL.21561,
 *  contexto de pared del rastreador y creencia con posterior. */
function medir(juego: JuegoGrabado): Medicion {
  const grillas = reconstruir(juego);
  const trackerVol = new VolatilityTracker();
  juego.pasos.forEach((paso, i) => trackerVol.observe(paso.accion, grillas[i], grillas[i + 1]));
  const mask = trackerVol.mask;

  const creencia = new CreenciaDeDirecciones();
  creencia.sembrar(juego.pasos[0].accionesDisponibles);
  const sembradas = creencia.accionesSembradas();
  const avatar = new RastreadorDeAvatar();

  let pasoResueltoPosterior: number | null = null;
  let pasoResueltoEstados: number | null = null;
  let fallosConPared = 0;
  juego.pasos.forEach((paso, i) => {
    const mecanica = detectarMecanica(grillas[i], grillas[i + 1], mask);
    let pared = null;
    if (sembradas.includes(paso.accion) && mecanica.traslacionPrincipal === null) {
      pared = contextoDePared(
        grillas[i],
        avatar.caja,
        avatar.piso,
        profundidadDeSondeo(creencia.magnitudDe(paso.accion)),
      );
      const canonica = creencia.direccionDe(paso.accion);
      const nombre =
        canonica === null ? undefined : NOMBRE_DE_DIRECCION.get(`${canonica[0]},${canonica[1]}`);
      if (nombre !== undefined && pared[nombre] === PARED_PRESENTE) fallosConPared += 1;
    }
    creencia.observar(paso.accion, mecanica, pared);
    avatar.observar(mecanica, grillas[i + 1]);
    if (pasoResueltoPosterior === null && sembradas.every((a) => creencia.resuelta(a))) {
      pasoResueltoPosterior = i + 1;
    }
    if (
      pasoResueltoEstados === null &&
      sembradas.every((a) => ESTADOS_TERMINALES_21590.includes(creencia.estadoDe(a)))
    ) {
      pasoResueltoEstados = i + 1;
    }
  });
  return { creencia, sembradas, pasoResueltoPosterior, pasoResueltoEstados, fallosConPared };
}

const mediciones = new Map<string, Medicion>(juegos.map((j) => [j.gameId, medir(j)]));

describe('BL.21593 -- posterior jerarquico sobre las partidas reales (paridad con Python)', () => {
  it('DELTA: el posterior resuelve el mapeo completo en 5-14 pasos; los estados de BL.21590 solos, JAMAS', () => {
    for (const [gameId, esperado] of Object.entries(ESPERADO)) {
      const m = mediciones.get(gameId) as Medicion;
      expect(m.pasoResueltoPosterior, gameId).toBe(esperado.pasoResueltoPosterior);
      expect(m.pasoResueltoEstados, gameId).toBeNull(); // la baseline no llega nunca
    }
  });

  it('el posterior llega a las respuestas CORRECTAS con confianza > 0.9', () => {
    for (const [gameId, esperado] of Object.entries(ESPERADO)) {
      const posterior = (mediciones.get(gameId) as Medicion).creencia.posterior;
      for (const [accion, mecanica] of Object.entries(esperado.dominantes)) {
        const dominante = posterior.mecanicaDominante(accion) as [string, number];
        expect(dominante[0], `${gameId} ${accion}`).toBe(mecanica);
        expect(dominante[1], `${gameId} ${accion}`).toBeGreaterThan(0.9);
      }
      const arquetipo = posterior.posteriorDeArquetipo();
      let dominanteA: string = ARQUETIPOS[0];
      for (const a of ARQUETIPOS) if (arquetipo[a] > arquetipo[dominanteA]) dominanteA = a;
      expect(dominanteA, gameId).toBe(esperado.arquetipo);
      expect(arquetipo[esperado.arquetipo], gameId).toBeGreaterThan(0.9);
    }
  });

  it('la pared se VE en dato real: los fallos explicados existen en la grabacion', () => {
    for (const [gameId, esperado] of Object.entries(ESPERADO)) {
      expect((mediciones.get(gameId) as Medicion).fallosConPared, gameId).toBe(
        esperado.fallosConParedCanonica,
      );
    }
  });

  it('cero remapeos espurios bajo el round-robin que fabrica mapeos invertidos', () => {
    for (const [gameId, m] of mediciones) {
      for (const accion of m.sembradas) {
        expect(m.creencia.estadoDe(accion), `${gameId} ${accion}`).not.toBe('remapeada');
        const direccion = m.creencia.posterior.direccionDe(accion);
        if (direccion !== null) {
          expect(direccion, `${gameId} ${accion}`).toEqual(CANONICO[accion]);
        }
      }
    }
  });
});
