/* [arc-agi-runner/worldModel/bl21561.realGames.effect.test] BL.21561 -- el test que decide si el
   analizador objeto-centrico SIRVE, medido sobre las mismas partidas REALES de ARC-AGI-3 que usa
   BL.21558 (`__fixtures__/volatilityRealGames.json`, grabadas contra la API oficial).

   POR QUE ESTE TEST Y NO UNO SINTETICO. Dos veces (BL.21500 y el primer intento de BL.21558) un
   cambio paso todos sus tests y tuvo efecto CERO sobre dato real. La regla ahora es que el efecto
   se mide sobre las partidas grabadas o no se mide. Aca se contrastan las DOS implementaciones
   sobre exactamente los mismos pares (pre, post):
   - `proposeAllSteps` (el DSL grilla-a-grilla, BL.20860): 0 propuestas en los 4 juegos.
   - `detectarMecanica` (este BL): 290 traslaciones detectadas y el mapeo canonico de direcciones
     recuperado en 3 de los 4 juegos, sin una sola contradiccion.

   POR QUE LOS NUMEROS SON EXACTOS. Son un contrato ejecutable con el puerto Python:
   `arc-agi3-kaggle-agent/tests/test_bl21561_real_games.py` afirma los MISMOS valores sobre la
   MISMA grabacion. Si un puerto cambia el criterio y el otro no, uno de los dos se pone en rojo. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import type { Grid } from '../grid';
import { MechanicsMemory } from '../mechanicsMemory';
import { detectarMecanica } from '../objectMechanics';
import { proposeAllSteps } from '../primitives';
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

/** Magnitudes medidas sobre la grabacion vigente -- contrato de paridad con el puerto Python. */
const ESPERADO: Record<
  string,
  { traslaciones: number; sinCambio: number; direcciones: Record<string, string> }
> = {
  'lf52-271a04aa': {
    // La partida grabada no movio NADA en 90 de 92 pasos (corrobora el round-robin del agente
    // viejo): hay una sola traslacion y por eso ninguna direccion llega a confirmarse.
    traslaciones: 1,
    sinCambio: 90,
    direcciones: {},
  },
  'ar25-0c556536': {
    traslaciones: 76,
    sinCambio: 7,
    direcciones: { ACTION1: '-3,0', ACTION2: '3,0', ACTION3: '0,-3', ACTION4: '0,3' },
  },
  'ka59-38d34dbb': {
    traslaciones: 94,
    sinCambio: 6,
    direcciones: { ACTION1: '-3,0', ACTION2: '3,0', ACTION3: '0,-3', ACTION4: '0,3' },
  },
  'dc22-fdcac232': {
    traslaciones: 119,
    sinCambio: 9,
    direcciones: { ACTION1: '-2,0', ACTION2: '2,0', ACTION3: '0,-2', ACTION4: '0,2' },
  },
};

/** Pasos por juego en los que se le pide una propuesta al DSL viejo. Es una MUESTRA porque
 *  `proposeAllSteps` recorre la grilla diez veces por par y no hace falta pagar 400 pasos para
 *  medir un cero: si en 30 pasos consecutivos no propone nada, el punto esta hecho. */
const MUESTRA_DSL = 30;

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
  traslaciones: number;
  sinCambio: number;
  direcciones: Record<string, string>;
  pasosConPropuestaDSL: number;
  memoria: MechanicsMemory;
}

function medir(juego: JuegoGrabado): Medicion {
  const grillas = reconstruir(juego);
  const tracker = new VolatilityTracker();
  for (let i = 0; i < juego.pasos.length; i++) {
    tracker.observe(juego.pasos[i].accion, grillas[i], grillas[i + 1]);
  }
  const mask = tracker.mask;

  const memoria = new MechanicsMemory();
  let traslaciones = 0;
  let sinCambio = 0;
  for (let i = 0; i < juego.pasos.length; i++) {
    const mecanica = detectarMecanica(grillas[i], grillas[i + 1], mask);
    if (mecanica.tipo === 'traslacion') traslaciones++;
    if (mecanica.tipo === 'sinCambio') sinCambio++;
    memoria.observe(juego.pasos[i].accion, grillas[i], grillas[i + 1], mask);
  }

  const direcciones: Record<string, string> = {};
  for (const accion of memoria.getMovementActions()) {
    const d = memoria.getDirection(accion) as { dy: number; dx: number };
    direcciones[accion] = `${d.dy},${d.dx}`;
  }

  let pasosConPropuestaDSL = 0;
  const muestra = Math.min(juego.pasos.length, MUESTRA_DSL);
  for (let i = 0; i < muestra; i++) {
    if (proposeAllSteps(grillas[i], grillas[i + 1], {}).length > 0) pasosConPropuestaDSL++;
  }

  return { traslaciones, sinCambio, direcciones, pasosConPropuestaDSL, memoria };
}

const mediciones = new Map(juegos.map((j) => [j.gameId, medir(j)]));

describe('BL.21561 -- mecanicas de objeto sobre partidas REALES de ARC-AGI-3', () => {
  it('el fixture trae las cuatro partidas medidas en el BL', () => {
    expect(juegos.map((j) => j.gameId).sort()).toEqual([
      'ar25-0c556536',
      'dc22-fdcac232',
      'ka59-38d34dbb',
      'lf52-271a04aa',
    ]);
  });

  it('CRITERIO DE ACEPTACION: cursor detectado en al menos 3 juegos, con direcciones confirmadas', () => {
    const conCursor = juegos.filter(
      (j) => Object.keys((mediciones.get(j.gameId) as Medicion).direcciones).length > 0,
    );
    // eslint-disable-next-line no-console -- magnitud medida sobre dato real, se quiere ver
    console.log(
      `[BL.21561] juegos con direccion de cursor confirmada: ${conCursor.length}/${juegos.length} -- ` +
        conCursor
          .map(
            (j) =>
              `${j.gameId} ${JSON.stringify((mediciones.get(j.gameId) as Medicion).direcciones)}`,
          )
          .join(' | '),
    );
    expect(conCursor.length).toBeGreaterThanOrEqual(3);
  });

  it('el DSL grilla-a-grilla no propone NADA en ninguna de las cuatro partidas', () => {
    /* Es la evidencia de que esto es un REEMPLAZO y no una mejora incremental: sobre los mismos
       pares, el analizador viejo devuelve el conjunto vacio en el 100% de la muestra. */
    for (const juego of juegos) {
      expect(
        (mediciones.get(juego.gameId) as Medicion).pasosConPropuestaDSL,
        `${juego.gameId} deberia dar 0 propuestas del DSL viejo`,
      ).toBe(0);
    }
  });

  it('en el agregado detecta cientos de traslaciones donde el DSL detectaba cero', () => {
    let total = 0;
    for (const juego of juegos) total += (mediciones.get(juego.gameId) as Medicion).traslaciones;
    // eslint-disable-next-line no-console -- magnitud medida sobre dato real
    console.log(`[BL.21561][agregado] traslaciones detectadas en las 4 partidas: ${total}`);
    expect(total).toBeGreaterThan(250);
  });

  for (const juego of juegos) {
    describe(juego.gameId, () => {
      const medicion = mediciones.get(juego.gameId) as Medicion;
      const esperado = ESPERADO[juego.gameId];

      it('las magnitudes coinciden EXACTAMENTE con las del puerto Python', () => {
        expect(esperado, `falta el esperado de ${juego.gameId}`).toBeDefined();
        expect({
          traslaciones: medicion.traslaciones,
          sinCambio: medicion.sinCambio,
          direcciones: medicion.direcciones,
        }).toEqual(esperado);
      });

      it('cada paso queda clasificado: traslacion, sinCambio o desconocida', () => {
        expect(medicion.traslaciones + medicion.sinCambio).toBeLessThanOrEqual(juego.pasos.length);
      });

      it('DETECTOR 4 -- la arena es una fraccion chica del frame; el resto es marco estatico', () => {
        const caja = medicion.memoria.getActiveBoundingBox();
        expect(caja).not.toBeNull();
        const celdasDelFrame = juego.alto * juego.ancho;
        const estaticas = medicion.memoria.getStaticCellCount();
        // eslint-disable-next-line no-console -- magnitud medida sobre dato real
        console.log(
          `[BL.21561][${juego.gameId}] traslaciones ${medicion.traslaciones}/${juego.pasos.length} | ` +
            `arena y[${caja?.minY}..${caja?.maxY}] x[${caja?.minX}..${caja?.maxX}] | ` +
            `celdas estaticas ${estaticas}/${celdasDelFrame}`,
        );
        // En los 4 juegos medidos, mas del 80% del frame no cambia NUNCA: es decorado.
        expect(estaticas).toBeGreaterThan(celdasDelFrame * 0.8);
      });

      it('DETECTOR 5 -- no inventa contadores donde no los hay', () => {
        /* Ninguna de las 4 partidas tiene un color cuya cuenta se mueva siempre en el mismo
           sentido (la barra de progreso, que si lo haria, ya la come la mascara de BL.21558).
           Que el detector devuelva vacio ACA es la prueba de que no dispara por cualquier cosa;
           que dispare cuando corresponde se prueba en objectMechanics.test.ts. */
        expect(medicion.memoria.getCounters()).toEqual([]);
      });
    });
  }
});

describe('BL.21561 -- las direcciones recuperadas son el mapeo canonico de ARC-AGI-3', () => {
  it('ACTION1=arriba ACTION2=abajo ACTION3=izquierda ACTION4=derecha en los 3 juegos con cursor', () => {
    /* No esta cableado en ningun lado: el analizador es parametrico sobre objetos y deltas y NO
       mira el game_id. Que los tres juegos coincidan en el mismo mapeo es el resultado, no la
       premisa -- y es lo que permite planificar un camino en vez de tantear al azar. */
    for (const gameId of ['ar25-0c556536', 'ka59-38d34dbb', 'dc22-fdcac232']) {
      const direcciones = (mediciones.get(gameId) as Medicion).direcciones;
      const signo = (s: string): [number, number] => {
        const [dy, dx] = s.split(',').map(Number);
        return [Math.sign(dy), Math.sign(dx)];
      };
      expect(signo(direcciones.ACTION1), `${gameId} ACTION1`).toEqual([-1, 0]);
      expect(signo(direcciones.ACTION2), `${gameId} ACTION2`).toEqual([1, 0]);
      expect(signo(direcciones.ACTION3), `${gameId} ACTION3`).toEqual([0, -1]);
      expect(signo(direcciones.ACTION4), `${gameId} ACTION4`).toEqual([0, 1]);
    }
  });
});
