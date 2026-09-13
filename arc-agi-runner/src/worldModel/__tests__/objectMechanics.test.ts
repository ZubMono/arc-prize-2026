/* [arc-agi-runner/worldModel/objectMechanics.test] BL.21561 -- los cinco detectores de mecanicas
   objeto-centricas, incluidos los casos exactos que el DSL grilla-a-grilla NO podia resolver
   (sonda del BL: objeto 2x2 que se mueve en 64x64 con paredes -> `proposeAllSteps` vacio; una sola
   celda que cambia de color -> vacio). */
import { describe, expect, it } from 'vitest';

import type { Grid, VolatilityMask } from '../grid';
import { MechanicsMemory } from '../mechanicsMemory';
import { firmaDeMecanica } from '../mechanicsSignature';
import { detectarMecanica } from '../objectMechanics';
import { proposeAllSteps } from '../primitives';

/** Tablero 64x64 con paredes en el borde (color 4), piso 2 -- la forma real de los juegos. */
function tablero(): Grid {
  return Array.from({ length: 64 }, (_, y) =>
    Array.from({ length: 64 }, (_, x) => (y === 0 || x === 0 || y === 63 || x === 63 ? 4 : 2)),
  );
}

function pintar(
  grid: Grid,
  y0: number,
  x0: number,
  alto: number,
  ancho: number,
  color: number,
): void {
  for (let y = y0; y < y0 + alto; y++) for (let x = x0; x < x0 + ancho; x++) grid[y][x] = color;
}

describe('detectarMecanica -- 1. traslacion (cursor/jugador)', () => {
  it('objeto 2x2 que se mueve una celda en 64x64 con paredes: el caso que el DSL daba vacio', () => {
    const pre = tablero();
    pintar(pre, 30, 30, 2, 2, 7);
    const post = tablero();
    pintar(post, 30, 31, 2, 2, 7);

    // La sonda del BL, ejecutable: el analizador viejo no propone NADA para este par.
    expect(proposeAllSteps(pre, post, {})).toEqual([]);

    const mecanica = detectarMecanica(pre, post);
    expect(mecanica.tipo).toBe('traslacion');
    expect(mecanica.traslacionPrincipal).toMatchObject({ dy: 0, dx: 1, alto: 2, ancho: 2 });
    expect(firmaDeMecanica(mecanica)).toBe('traslacion:0,1');
  });

  it('recupera la direccion en los cuatro sentidos, con el signo correcto', () => {
    const casos: Array<[number, number]> = [
      [-3, 0],
      [3, 0],
      [0, -3],
      [0, 3],
    ];
    for (const [dy, dx] of casos) {
      const pre = tablero();
      pintar(pre, 30, 30, 3, 3, 7);
      const post = tablero();
      pintar(post, 30 + dy, 30 + dx, 3, 3, 7);
      const mecanica = detectarMecanica(pre, post);
      expect(mecanica.traslacionPrincipal, `d=(${dy},${dx})`).toMatchObject({ dy, dx });
    }
  });

  it('NO invierte la direccion cuando el objeto se mueve a un hueco (la ambiguedad simetrica)', () => {
    /* Es el bug que la version ingenua tenia sobre dc22: "el hueco se movio al reves" satisface las
       mismas ecuaciones. Se prueba con el objeto pegado a la pared, que es donde el fondo local
       deja de ser el piso y solo la cobertura por componente contenida rompe el empate. */
    const pre = tablero();
    pintar(pre, 61, 30, 2, 2, 7);
    const post = tablero();
    pintar(post, 61, 32, 2, 2, 7);
    const mecanica = detectarMecanica(pre, post);
    expect(mecanica.traslacionPrincipal).toMatchObject({ dy: 0, dx: 2 });
  });

  it('un objeto que se mueve SOBRE otro color sigue siendo una traslacion', () => {
    const pre = tablero();
    pintar(pre, 20, 20, 2, 2, 7);
    pintar(pre, 20, 22, 2, 2, 5); // baldosa de destino de otro color
    const post = tablero();
    pintar(post, 20, 22, 2, 2, 7);
    pintar(post, 20, 20, 2, 2, 2); // deja piso
    const mecanica = detectarMecanica(pre, post);
    expect(mecanica.tipo).toBe('traslacion');
    expect(mecanica.traslacionPrincipal).toMatchObject({ dy: 0, dx: 2 });
  });

  it('ignora las celdas volatiles: la barra de progreso no rompe la deteccion', () => {
    const pre = tablero();
    pintar(pre, 30, 30, 2, 2, 7);
    const post = tablero();
    pintar(post, 30, 31, 2, 2, 7);
    post[0][10] = 9; // avance de la barra, fuera del tablero de juego
    const sinMascara = detectarMecanica(pre, post);
    expect(sinMascara.tipo).toBe('desconocida');

    const mask: VolatilityMask = Array.from({ length: 64 }, (_, y) =>
      Array.from({ length: 64 }, () => y === 0),
    );
    expect(detectarMecanica(pre, post, mask).traslacionPrincipal).toMatchObject({ dy: 0, dx: 1 });
  });
});

describe('detectarMecanica -- 2 y 3: recoloreo, aparicion, desaparicion', () => {
  it('UNA celda que cambia de color: el otro caso que el DSL daba vacio', () => {
    const pre = tablero();
    const post = tablero();
    post[30][30] = 6;
    expect(proposeAllSteps(pre, post, {})).toEqual([]);
    const mecanica = detectarMecanica(pre, post);
    expect(mecanica.tipo).toBe('aparicion');
    expect(mecanica.cambioDeColorPrincipal).toEqual({ desde: 2, hasta: 6, celdas: 1 });
    expect(firmaDeMecanica(mecanica)).toBe('aparicion:2>6');
  });

  it('un objeto que desaparece (consumo/recoleccion)', () => {
    const pre = tablero();
    pintar(pre, 30, 30, 2, 2, 6);
    const post = tablero();
    const mecanica = detectarMecanica(pre, post);
    expect(mecanica.tipo).toBe('desaparicion');
    expect(mecanica.cambioDeColorPrincipal).toEqual({ desde: 6, hasta: 2, celdas: 4 });
  });

  it('un objeto que cambia de color en el lugar (toggle/pintado)', () => {
    const pre = tablero();
    pintar(pre, 30, 30, 2, 2, 6);
    const post = tablero();
    pintar(post, 30, 30, 2, 2, 8);
    const mecanica = detectarMecanica(pre, post);
    expect(mecanica.tipo).toBe('recoloreo');
    expect(mecanica.cambioDeColorPrincipal).toEqual({ desde: 6, hasta: 8, celdas: 4 });
  });

  it('sin cambios: sinCambio, no "desconocida"', () => {
    const grid = tablero();
    expect(
      detectarMecanica(
        grid,
        grid.map((f) => [...f]),
      ).tipo,
    ).toBe('sinCambio');
  });

  // BL.21741 (correccion): este test decia `desconocida` -- exactamente el colapso que el BL vino
  // a romper del lado Python y que este motor, el que juega contra la API oficial cada hora,
  // seguia teniendo. "Ni pude comparar las grillas" y "mire los clusters y no supe nombrarlos" son
  // dos cosas distintas y aguas abajo llevan a inferencias OPUESTAS.
  it('grillas de forma distinta: formaIncompatible, NO "desconocida", sin lanzar', () => {
    const mecanica = detectarMecanica([[1, 2]], [[1], [2]]);
    expect(mecanica.tipo).toBe('formaIncompatible');
    expect(mecanica.tipo).not.toBe('desconocida');
    expect(mecanica.celdasCambiadas).toBe(0);
  });
});

describe('MechanicsMemory -- evidencia Beta por accion', () => {
  function moverCursor(y: number, x: number): Grid {
    const g = tablero();
    pintar(g, y, x, 2, 2, 7);
    return g;
  }

  it('confirma la direccion tras dos observaciones coherentes', () => {
    const memoria = new MechanicsMemory();
    expect(memoria.getDirection('ACTION3')).toBeNull();
    memoria.observe('ACTION3', moverCursor(30, 30), moverCursor(30, 28));
    expect(memoria.getDirection('ACTION3'), 'una sola observacion no confirma').toBeNull();
    memoria.observe('ACTION3', moverCursor(30, 28), moverCursor(30, 26));
    expect(memoria.getDirection('ACTION3')).toEqual({ dy: 0, dx: -2 });
    expect(memoria.getMovementActions()).toEqual(['ACTION3']);
  });

  it('un choque contra la pared NO mata la regla -- solo mueve la Beta', () => {
    /* Es el caso que rompia verifyProgram: la regla correcta moria en la primera observacion que
       no encajaba. Aca sobrevive con cobertura 3/4 y el fallo queda contabilizado en beta. */
    const memoria = new MechanicsMemory();
    memoria.observe('ACTION3', moverCursor(30, 30), moverCursor(30, 28));
    memoria.observe('ACTION3', moverCursor(30, 28), moverCursor(30, 26));
    memoria.observe('ACTION3', moverCursor(30, 26), moverCursor(30, 24));
    const pegado = moverCursor(30, 1);
    memoria.observe('ACTION3', pegado, pegado); // choque: no se mueve nada
    const h = memoria.getHypothesis('ACTION3');
    expect(h?.firma).toBe('traslacion:0,-2');
    expect(h?.alpha).toBe(4);
    expect(h?.beta).toBe(2);
    expect(h?.cobertura).toBeCloseTo(0.75, 10);
    expect(memoria.getDirection('ACTION3')).toEqual({ dy: 0, dx: -2 });
  });

  it('una accion inerte se reconoce sin pasar por la sintesis DSL', () => {
    const memoria = new MechanicsMemory();
    const g = moverCursor(30, 30);
    memoria.observe('ACTION5', g, g);
    memoria.observe('ACTION5', g, g);
    expect(memoria.isInertAction('ACTION5')).toBe(true);
    expect(memoria.getDirection('ACTION5')).toBeNull();
  });

  it('DETECTOR 4 -- la arena es el bbox de lo que cambio; el marco queda estatico', () => {
    const memoria = new MechanicsMemory();
    memoria.observe('ACTION3', moverCursor(30, 30), moverCursor(30, 28));
    memoria.observe('ACTION3', moverCursor(30, 28), moverCursor(30, 26));
    expect(memoria.getActiveBoundingBox()).toEqual({ minY: 30, maxY: 31, minX: 26, maxX: 31 });
    expect(memoria.isStaticCell(0, 0)).toBe(true);
    expect(memoria.isStaticCell(30, 30)).toBe(false);
    expect(memoria.getStaticCellCount()).toBe(64 * 64 - 12);
  });

  it('DETECTOR 5 -- un color que solo crece es un contador (puntaje/vidas)', () => {
    const memoria = new MechanicsMemory();
    let anterior = tablero();
    for (let i = 1; i <= 4; i++) {
      const siguiente = tablero();
      pintar(siguiente, 5, 5, 1, i, 3); // la barra de vidas crece una celda por paso
      memoria.observe('ACTION1', anterior, siguiente);
      anterior = siguiente;
    }
    const contadores = memoria.getCounters();
    expect(contadores.map((c) => c.color)).toContain(3);
    const contador = contadores.find((c) => c.color === 3);
    expect(contador?.direccion).toBe('sube');
    expect(contador?.cambios).toBeGreaterThanOrEqual(3);
    // 4 frames observados = 3 deltas (+1 cada uno): el primero solo fija la linea de base.
    expect(contador?.delta).toBe(3);
  });

  it('DETECTOR 5 -- un color que sube y baja NO es un contador', () => {
    const memoria = new MechanicsMemory();
    const chico = tablero();
    pintar(chico, 5, 5, 1, 1, 3);
    const grande = tablero();
    pintar(grande, 5, 5, 1, 4, 3);
    for (let i = 0; i < 4; i++) {
      memoria.observe('ACTION1', chico, grande);
      memoria.observe('ACTION1', grande, chico);
    }
    expect(memoria.getCounters().some((c) => c.color === 3)).toBe(false);
  });
});
