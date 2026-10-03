/* [arc-agi-runner/worldModel/bl21558.realGames.effect.test] BL.21558 -- el test que la primera
   version de este fix no tenia y por eso paso verde con efecto CERO.

   QUE MIDE. Partidas REALES de ARC-AGI-3 grabadas contra la API oficial
   (`__fixtures__/volatilityRealGames.json`, generado por `scripts/generateVolatilityRealFixture.ts`)
   pasadas por el MISMO `VolatilityTracker` que corre en produccion. Se comparan tres magnitudes con
   mascara y sin mascara sobre la MISMA trayectoria: no-ops detectados, firmas de estado unicas y
   celdas enmascaradas.

   POR QUE HACE FALTA DATO REAL. El entorno sintetico simulaba el HUD como "dos celdas que cambian
   en cada paso", y con esa forma el criterio por frecuencia alcanzaba. El ruido REAL de ARC-AGI-3
   resulto ser otro: una BARRA de progreso donde se enciende UNA celda nueva por paso, asi que cada
   celda cambia una sola vez en todo el episodio y ningun criterio por frecuencia puede verla.
   Medido antes de agregar la deteccion por barrido: 0 celdas enmascaradas en los cuatro juegos.

   ADEMAS ES UN TEST DE SEGURIDAD. La mascara tiene que ver la barra y NADA MAS: se afirma que lo
   enmascarado es una linea de una celda de ancho y una fraccion minuscula del frame. Enmascarar
   tablero seria peor que no enmascarar nada -- dejaria al agente ciego justo donde esta la señal. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import type { Grid } from '../grid';
import { computeStateSignature, isNoOpTransition } from '../stateSignature';
import { SWEEP_MIN_CELLS, VolatilityTracker } from '../volatilityMask';

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

/** Magnitudes medidas sobre la grabacion vigente. Son ademas el CONTRATO DE PARIDAD con el puerto
 *  Python: `arc-agi3-kaggle-agent/tests/test_bl21558_real_games.py` afirma exactamente los mismos
 *  valores sobre exactamente la misma grabacion, asi que si un puerto cambia el criterio y el otro
 *  no, uno de los dos se pone en rojo. Regenerar el fixture obliga a re-medir a mano en los dos
 *  lados -- que es justo lo que se quiere que cueste. */
const ESPERADO: Record<
  string,
  {
    celdas: number;
    noOpsSinMascara: number;
    noOpsConMascara: number;
    firmasSinMascara: number;
    firmasConMascara: number;
  }
> = {
  'lf52-271a04aa': {
    celdas: 64,
    noOpsSinMascara: 0,
    noOpsConMascara: 90,
    firmasSinMascara: 92,
    firmasConMascara: 3,
  },
  'ar25-0c556536': {
    celdas: 64,
    noOpsSinMascara: 4,
    noOpsConMascara: 7,
    firmasSinMascara: 78,
    firmasConMascara: 19,
  },
  'ka59-38d34dbb': {
    celdas: 64,
    noOpsSinMascara: 5,
    noOpsConMascara: 6,
    firmasSinMascara: 95,
    firmasConMascara: 9,
  },
  'dc22-fdcac232': {
    celdas: 64,
    noOpsSinMascara: 5,
    noOpsConMascara: 9,
    firmasSinMascara: 123,
    firmasConMascara: 9,
  },
};

/** Reconstruye la secuencia de grillas de la partida aplicando los diffs sobre la grilla base. */
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
  celdasEnmascaradas: number;
  noOpsSinMascara: number;
  noOpsConMascara: number;
  firmasSinMascara: number;
  firmasConMascara: number;
  filasEnmascaradas: Set<number>;
  columnasEnmascaradas: Set<number>;
}

function medir(juego: JuegoGrabado): Medicion {
  const grillas = reconstruir(juego);
  const tracker = new VolatilityTracker();
  for (let i = 0; i < juego.pasos.length; i++) {
    tracker.observe(juego.pasos[i].accion, grillas[i], grillas[i + 1]);
  }
  const mask = tracker.mask;

  let noOpsSinMascara = 0;
  let noOpsConMascara = 0;
  for (let i = 0; i < juego.pasos.length; i++) {
    if (isNoOpTransition(grillas[i], grillas[i + 1], null) === true) noOpsSinMascara++;
    if (isNoOpTransition(grillas[i], grillas[i + 1], mask) === true) noOpsConMascara++;
  }

  const firmasSinMascara = new Set<number>();
  const firmasConMascara = new Set<number>();
  for (let i = 0; i < juego.pasos.length; i++) {
    const disponibles = juego.pasos[i].accionesDisponibles;
    firmasSinMascara.add(computeStateSignature(grillas[i + 1], disponibles, null));
    firmasConMascara.add(computeStateSignature(grillas[i + 1], disponibles, mask));
  }

  const filasEnmascaradas = new Set<number>();
  const columnasEnmascaradas = new Set<number>();
  for (let y = 0; y < juego.alto; y++) {
    for (let x = 0; x < juego.ancho; x++) {
      if (mask?.[y]?.[x] === true) {
        filasEnmascaradas.add(y);
        columnasEnmascaradas.add(x);
      }
    }
  }

  return {
    celdasEnmascaradas: tracker.volatileCellCount(),
    noOpsSinMascara,
    noOpsConMascara,
    firmasSinMascara: firmasSinMascara.size,
    firmasConMascara: firmasConMascara.size,
    filasEnmascaradas,
    columnasEnmascaradas,
  };
}

describe('BL.21558 -- efecto de la mascara sobre partidas REALES de ARC-AGI-3', () => {
  it('el fixture trae las cuatro partidas medidas en el BL', () => {
    expect(juegos.map((j) => j.gameId).sort()).toEqual([
      'ar25-0c556536',
      'dc22-fdcac232',
      'ka59-38d34dbb',
      'lf52-271a04aa',
    ]);
    for (const juego of juegos) expect(juego.pasos.length).toBeGreaterThan(60);
  });

  it('en el agregado de las cuatro partidas la deteccion de no-ops se multiplica', () => {
    let sinMascara = 0;
    let conMascara = 0;
    for (const juego of juegos) {
      const m = medir(juego);
      sinMascara += m.noOpsSinMascara;
      conMascara += m.noOpsConMascara;
    }
    // eslint-disable-next-line no-console -- magnitud medida sobre dato real
    console.log(
      `[BL.21558][agregado] no-ops detectados en las 4 partidas -- sin mascara: ${sinMascara}, con mascara: ${conMascara}`,
    );
    /* El agregado y no el por-juego: cuantos no-ops CONTIENE una trayectoria depende de la propia
       politica, y con la mascara andando el agente deja de repetir la accion inerte (por eso en
       ka59 o dc22 quedan pocos). Lo que no depende de la politica es que sobre la MISMA trayectoria
       la mascara descubra los no-ops que la barra tapaba: 14 -> 112 en la grabacion vigente. */
    expect(conMascara).toBeGreaterThan(sinMascara * 3);
  });

  it('lf52 -- el caso extremo: la barra tapaba el 100% de los no-ops', () => {
    const lf52 = juegos.find((j) => j.gameId === 'lf52-271a04aa');
    expect(lf52).toBeDefined();
    const m = medir(lf52 as JuegoGrabado);
    // La barra avanza en TODOS los pasos: sin mascara no hay un solo no-op detectable en 92 pasos,
    // aunque casi ninguna accion cambie el tablero.
    expect(m.noOpsSinMascara).toBe(0);
    expect(m.noOpsConMascara).toBeGreaterThan((lf52 as JuegoGrabado).pasos.length * 0.7);
  });

  for (const juego of juegos) {
    describe(juego.gameId, () => {
      const medicion = medir(juego);
      const celdasDelFrame = juego.alto * juego.ancho;

      it('las magnitudes coinciden EXACTAMENTE con las del puerto Python', () => {
        const esperado = ESPERADO[juego.gameId];
        expect(esperado, `falta el esperado de ${juego.gameId}`).toBeDefined();
        expect({
          celdas: medicion.celdasEnmascaradas,
          noOpsSinMascara: medicion.noOpsSinMascara,
          noOpsConMascara: medicion.noOpsConMascara,
          firmasSinMascara: medicion.firmasSinMascara,
          firmasConMascara: medicion.firmasConMascara,
        }).toEqual(esperado);
      });

      it('la mascara se ACTIVA -- con el criterio por frecuencia solo eran 0 celdas', () => {
        // eslint-disable-next-line no-console -- magnitud medida sobre dato real, se quiere ver
        console.log(
          `[BL.21558][${juego.gameId}] ${juego.pasos.length} pasos | celdas enmascaradas ` +
            `${medicion.celdasEnmascaradas}/${celdasDelFrame} | no-ops ${medicion.noOpsSinMascara} -> ` +
            `${medicion.noOpsConMascara} | firmas unicas ${medicion.firmasSinMascara} -> ` +
            `${medicion.firmasConMascara}`,
        );
        expect(medicion.celdasEnmascaradas).toBeGreaterThanOrEqual(SWEEP_MIN_CELLS);
      });

      it('enmascara una LINEA y nada mas -- el tablero queda entero', () => {
        // Una barra de progreso ocupa una fila o una columna; cualquier otra cosa seria tablero.
        const esLinea =
          medicion.filasEnmascaradas.size === 1 || medicion.columnasEnmascaradas.size === 1;
        expect(esLinea, 'lo enmascarado no es una linea de una celda de ancho').toBe(true);
        // Techo duro: el ruido del HUD no puede pasar del 5% del frame. Medido: 64/4096 = 1.56%.
        expect(medicion.celdasEnmascaradas).toBeLessThan(celdasDelFrame * 0.05);
      });

      it('la mascara solo puede AGREGAR no-ops detectados, nunca sacar', () => {
        // Invariante direccional: ignorar celdas no puede volver distintos dos frames que ya eran
        // iguales. Es lo que garantiza que el fix no pierda deteccion en ningun juego.
        expect(medicion.noOpsConMascara).toBeGreaterThanOrEqual(medicion.noOpsSinMascara);
      });

      it('las firmas de estado vuelven a repetirse', () => {
        // Sin mascara, casi una firma nueva por paso: la memoria por-estado (y el memorySeed entre
        // corridas) no puede disparar nunca fuera del estado post-RESET.
        expect(medicion.firmasSinMascara).toBeGreaterThan(juego.pasos.length * 0.7);
        // Con mascara la firma vuelve a describir el ESTADO del tablero.
        expect(medicion.firmasConMascara).toBeLessThan(medicion.firmasSinMascara * 0.5);
      });
    });
  }
});
