/* [arc-agi-runner/worldModel/volatilityMask.test] BL.21558 -- que celdas aprende a ignorar el
   modelo de mundo. Los dos errores posibles NO son simetricos y por eso hay tests de los dos
   lados: no enmascarar el HUD es el bug que este BL arregla (el agente no detecta ningun no-op);
   enmascarar el TABLERO seria mucho peor (el agente quedaria ciego donde esta la señal), asi que
   la mayor parte de este archivo prueba que celdas del juego NO entran a la mascara. */
import { describe, expect, it } from 'vitest';

import { SYNTHETIC_GRID_SIZE, SyntheticGridEnv } from '../../__tests__/support/syntheticGridEnv';
import type { ArcAction } from '../../types';
import { extractGrid } from '../stateSignature';
import { VOLATILITY_MIN_TRANSITIONS, VolatilityTracker } from '../volatilityMask';

const FILA_HUD = SYNTHETIC_GRID_SIZE; // el HUD es la fila extra que agrega el entorno sintetico
const ACCIONES: ArcAction[] = ['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4', 'ACTION5'];

/** Corre `pasos` transiciones round-robin sobre el entorno sintetico y las alimenta al tracker.
 *  Round-robin y no al azar: garantiza que TODAS las acciones (incluida ACTION5, la inerte)
 *  aporten evidencia, que es la condicion que separa el HUD del tablero. */
function correr(tracker: VolatilityTracker, pasos: number, hud: boolean): SyntheticGridEnv {
  const env = new SyntheticGridEnv({
    start: { x: 2, y: 2 },
    target: { x: 4, y: 4 },
    hud,
    endless: true,
  });
  let frame = env.reset();
  for (let i = 0; i < pasos; i++) {
    const accion = ACCIONES[i % ACCIONES.length];
    const pre = extractGrid(frame)!;
    frame = env.step(accion);
    tracker.observe(accion, pre, extractGrid(frame)!);
  }
  return env;
}

describe('VolatilityTracker -- deteccion de celdas no estacionarias', () => {
  it('sin evidencia suficiente no enmascara nada (comportamiento previo a BL.21558)', () => {
    const tracker = new VolatilityTracker();
    correr(tracker, VOLATILITY_MIN_TRANSITIONS - 1, true);
    expect(tracker.mask).toBeNull();
    expect(tracker.volatileCellCount()).toBe(0);
  });

  it('aprende EXACTAMENTE las celdas del HUD y ninguna del tablero', () => {
    const tracker = new VolatilityTracker();
    correr(tracker, 40, true);

    const mask = tracker.mask;
    expect(mask).not.toBeNull();
    // Las dos celdas del contador -- las unicas que cambian en todos los pasos bajo TODAS las
    // acciones, incluida la accion inerte ACTION5.
    expect(mask![FILA_HUD][0]).toBe(true);
    expect(mask![FILA_HUD][1]).toBe(true);
    expect(tracker.volatileCellCount()).toBe(2);

    // Ninguna celda del tablero: el marcador cambia bajo las acciones de movimiento pero NUNCA
    // bajo ACTION5, y esa asimetria es justamente la que lo salva de la mascara.
    for (let y = 0; y < SYNTHETIC_GRID_SIZE; y++) {
      for (let x = 0; x < SYNTHETIC_GRID_SIZE; x++) {
        expect(mask![y]?.[x] ?? false, `celda de tablero (${x},${y}) enmascarada`).toBe(false);
      }
    }
    // El resto de la fila de HUD es fondo constante: no cambia nunca, tampoco es volatil.
    for (let x = 2; x < SYNTHETIC_GRID_SIZE; x++) {
      expect(mask![FILA_HUD][x]).toBe(false);
    }
  });

  it('sin HUD no inventa volatilidad -- el mismo entorno, misma cantidad de pasos', () => {
    const tracker = new VolatilityTracker();
    correr(tracker, 40, false);
    expect(tracker.mask).toBeNull();
    expect(tracker.volatileCellCount()).toBe(0);
  });

  it('UNA sola accion nunca alcanza: no se puede distinguir "cambia siempre" de "esta accion la cambia"', () => {
    const tracker = new VolatilityTracker();
    // ACTION1 cambia la celda en todas sus transiciones -- pero es la unica accion observada.
    for (let i = 0; i < 20; i++) {
      tracker.observe('ACTION1', [[i % 10, 3]], [[(i + 1) % 10, 3]]);
    }
    expect(tracker.mask).toBeNull();
  });

  it('una celda que cambia bajo TODAS las acciones si entra a la mascara', () => {
    const tracker = new VolatilityTracker();
    for (let i = 0; i < 20; i++) {
      const accion = i % 2 === 0 ? 'ACTION1' : 'ACTION2';
      tracker.observe(accion, [[i % 10, 3]], [[(i + 1) % 10, 3]]);
    }
    const mask = tracker.mask;
    expect(mask).not.toBeNull();
    expect(mask![0][0]).toBe(true);
    expect(mask![0][1]).toBe(false); // la celda constante queda comparable
  });

  it('se desactiva entera si lo volatil superara la mitad del frame (fail-safe)', () => {
    const tracker = new VolatilityTracker();
    // Las DOS celdas cambian siempre bajo las dos acciones -> 100% del frame seria volatil.
    for (let i = 0; i < 20; i++) {
      const accion = i % 2 === 0 ? 'ACTION1' : 'ACTION2';
      tracker.observe(accion, [[i % 10, i % 7]], [[(i + 1) % 10, (i + 1) % 7]]);
    }
    // Un frame que muta entero pase lo que pase no es un HUD ruidoso: no es observable con este
    // modelo, y enmascararlo dejaria al agente decidiendo sobre nada.
    expect(tracker.mask).toBeNull();
    expect(tracker.volatileCellCount()).toBe(0);
  });

  it('la version cambia cuando cambia el conjunto de celdas volatiles, y solo entonces', () => {
    const tracker = new VolatilityTracker();
    correr(tracker, 40, true);
    const version = tracker.version;
    expect(version).toBeGreaterThan(0);

    // Mas evidencia del MISMO tipo no mueve la mascara -> la version queda quieta y lo firmado
    // antes sigue siendo comparable con lo firmado despues.
    const env = new SyntheticGridEnv({
      start: { x: 1, y: 1 },
      target: { x: 4, y: 4 },
      hud: true,
      endless: true,
    });
    let frame = env.reset();
    for (let i = 0; i < 20; i++) {
      const accion = ACCIONES[i % ACCIONES.length];
      const pre = extractGrid(frame)!;
      frame = env.step(accion);
      tracker.observe(accion, pre, extractGrid(frame)!);
    }
    expect(tracker.version).toBe(version);
  });

  it('tolera grillas que cambian de forma sin lanzar', () => {
    const tracker = new VolatilityTracker();
    tracker.observe('ACTION1', [[1]], [[1, 2]]);
    tracker.observe(
      'ACTION2',
      [
        [1, 2],
        [3, 4],
      ],
      [[9]],
    );
    tracker.observe('ACTION1', [], []);
    expect(() => tracker.mask).not.toThrow();
  });
});

/* La familia 2 del criterio (ver volatilityMask.ts): la barra de progreso. Existe porque la familia
   1 medida contra frames REALES de ARC-AGI-3 enmascaraba CERO celdas en los cuatro juegos del BL --
   el ruido real no es un digito que parpadea sino una barra que avanza una celda por paso, y cada
   una de sus celdas cambia UNA sola vez en todo el episodio. Los casos negativos de este bloque son
   la mitad importante: enmascarar tablero deja al agente ciego. */
describe('VolatilityTracker -- contador de barrido (barra de progreso)', () => {
  const ANCHO = 24;
  const ALTO = 4;

  /** Grilla con una barra en la fila 0 llena hasta `hasta` (exclusivo) y un marcador opcional. */
  function grilla(hasta: number, marcador?: { y: number; x: number }): number[][] {
    const g = Array.from({ length: ALTO }, () => new Array(ANCHO).fill(0));
    for (let x = 0; x < hasta; x++) g[0][x] = 1;
    if (marcador) g[marcador.y][marcador.x] = 5;
    return g;
  }

  it('una barra que avanza una celda por paso ENTRA a la mascara', () => {
    const tracker = new VolatilityTracker();
    for (let i = 0; i < ANCHO; i++) {
      const accion = `ACTION${(i % 3) + 1}`;
      tracker.observe(accion, grilla(i, { y: 2, x: 3 }), grilla(i + 1, { y: 2, x: 3 }));
    }
    const mask = tracker.mask;
    expect(mask).not.toBeNull();
    expect(tracker.volatileCellCount()).toBe(ANCHO);
    for (let x = 0; x < ANCHO; x++) expect(mask![0][x]).toBe(true);
    // Ni una celda fuera de la barra: el marcador quieto y el fondo siguen siendo comparables.
    for (let y = 1; y < ALTO; y++) {
      for (let x = 0; x < ANCHO; x++) {
        expect(mask![y][x], `celda de tablero (${x},${y}) enmascarada`).toBe(false);
      }
    }
  });

  it('un objeto que se MUEVE nunca entra, aunque se mueva en todos los pasos', () => {
    // El falso positivo mas caro: dos celdas ADYACENTES cambian juntas (de donde sale y a donde
    // llega), asi que ningun cambio ocurre en soledad y la region nunca es candidata.
    const tracker = new VolatilityTracker();
    for (let i = 0; i < ANCHO; i++) {
      const accion = `ACTION${(i % 3) + 1}`;
      tracker.observe(
        accion,
        grilla(0, { y: 2, x: i % (ANCHO - 1) }),
        grilla(0, { y: 2, x: (i % (ANCHO - 1)) + 1 }),
      );
    }
    expect(tracker.mask).toBeNull();
  });

  it('una region 2D que se enciende de a una celda NO entra (no es una linea)', () => {
    // Caso "simon dice": celdas sueltas de un bloque del tablero que se prenden una por paso.
    // Cada cambio ocurre en soledad, pero la forma delata que no es una barra.
    const tracker = new VolatilityTracker();
    const encendidas: [number, number][] = [];
    for (let y = 0; y < 5; y++) for (let x = 0; x < 5; x++) encendidas.push([y, x]);
    const conBloque = (n: number): number[][] => {
      const g = Array.from({ length: 8 }, () => new Array(8).fill(0));
      for (let i = 0; i < n; i++) g[encendidas[i][0]][encendidas[i][1]] = 3;
      return g;
    };
    for (let i = 0; i < encendidas.length; i++) {
      tracker.observe(`ACTION${(i % 3) + 1}`, conBloque(i), conBloque(i + 1));
    }
    expect(tracker.mask).toBeNull();
  });

  it('una barra demasiado corta NO entra -- hace falta una region, no un par de celdas', () => {
    const tracker = new VolatilityTracker();
    const corta = (hasta: number): number[][] => {
      const g = Array.from({ length: ALTO }, () => new Array(ANCHO).fill(0));
      for (let x = 0; x < hasta; x++) g[0][x] = 1;
      return g;
    };
    for (let i = 0; i < 10; i++) {
      tracker.observe(`ACTION${(i % 3) + 1}`, corta(i), corta(i + 1));
    }
    expect(tracker.mask).toBeNull();
  });

  it('una sola accion observada nunca alcanza tampoco para la barra', () => {
    const tracker = new VolatilityTracker();
    for (let i = 0; i < ANCHO; i++) tracker.observe('ACTION1', grilla(i), grilla(i + 1));
    expect(tracker.mask).toBeNull();
  });

  it('una barra que ya avanzo lo suficiente sobrevive a una racha sin avanzar (histeresis)', () => {
    const tracker = new VolatilityTracker();
    for (let i = 0; i < ANCHO; i++) {
      tracker.observe(
        `ACTION${(i % 3) + 1}`,
        grilla(i, { y: 2, x: 3 }),
        grilla(i + 1, { y: 2, x: 3 }),
      );
    }
    expect(tracker.volatileCellCount()).toBe(ANCHO);
    const versionEstable = tracker.version;

    // La barra se congela: el ratio baja de 1.0 hacia el umbral de salida. Mientras siga por encima
    // de SWEEP_EXIT_RATIO la mascara NO se mueve -- si oscilara, las firmas volverian a ser
    // irrepetibles, que es el defecto que este modulo existe para arreglar.
    for (let i = 0; i < 20; i++) {
      tracker.observe(
        `ACTION${(i % 3) + 1}`,
        grilla(ANCHO, { y: 2, x: 3 }),
        grilla(ANCHO, { y: 2, x: 3 }),
      );
    }
    expect(tracker.volatileCellCount()).toBe(ANCHO);
    expect(tracker.version).toBe(versionEstable);
  });
});
