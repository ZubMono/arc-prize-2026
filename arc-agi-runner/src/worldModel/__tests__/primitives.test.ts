/* [arc-agi-runner/worldModel/primitives.test] BL.20860 -- DSL de primitivas puras grilla-a-grilla
   (translate, reflect, rotate, recolor, floodFill, cropToBBox, overlay, replicate, objectExtract,
   conditionalRecolor) + generadores de candidatos data-driven (proposeAllSteps) usados por la
   sintesis de programas (synthesis.ts). */
import { describe, expect, it } from 'vitest';

import type { Grid } from '../grid';
import { applyProgram, applyStep, enumerateStructuralSteps, proposeAllSteps } from '../primitives';

describe('applyStep -- translate', () => {
  it('desplaza el contenido y rellena con el color de fondo detectado', () => {
    const grid: Grid = [
      [0, 0, 0],
      [0, 5, 0],
      [0, 0, 0],
    ];
    const result = applyStep({ name: 'translate', params: { dx: 1, dy: 0 } }, grid, {});
    expect(result).toEqual([
      [0, 0, 0],
      [0, 0, 5],
      [0, 0, 0],
    ]);
  });
});

describe('applyStep -- reflect', () => {
  it('horizontal invierte el orden de columnas', () => {
    const grid: Grid = [[1, 2, 3]];
    expect(applyStep({ name: 'reflect', params: { axis: 'horizontal' } }, grid, {})).toEqual([
      [3, 2, 1],
    ]);
  });

  it('vertical invierte el orden de filas', () => {
    const grid: Grid = [[1], [2], [3]];
    expect(applyStep({ name: 'reflect', params: { axis: 'vertical' } }, grid, {})).toEqual([
      [3],
      [2],
      [1],
    ]);
  });
});

describe('applyStep -- rotate', () => {
  it('90 grados horario cambia dimensiones y reordena celdas', () => {
    const grid: Grid = [
      [1, 2],
      [3, 4],
    ];
    // fila superior [1,2] pasa a ser la columna derecha, de arriba a abajo
    expect(applyStep({ name: 'rotate', params: { quarterTurns: 1 } }, grid, {})).toEqual([
      [3, 1],
      [4, 2],
    ]);
  });

  it('360 grados (4 giros) es identidad -- via 2+1+1 encadenado', () => {
    const grid: Grid = [
      [1, 2],
      [3, 4],
    ];
    let result = grid;
    for (let i = 0; i < 4; i++) {
      result = applyStep({ name: 'rotate', params: { quarterTurns: 1 } }, result, {});
    }
    expect(result).toEqual(grid);
  });
});

describe('applyStep -- recolor', () => {
  it('remapea colores segun mapping, deja el resto igual', () => {
    const grid: Grid = [[1, 2, 3]];
    expect(applyStep({ name: 'recolor', params: { mapping: { 1: 9 } } }, grid, {})).toEqual([
      [9, 2, 3],
    ]);
  });
});

describe('applyStep -- floodFill', () => {
  it('rellena solo la region 4-conexa desde la semilla', () => {
    const grid: Grid = [
      [1, 1, 0],
      [1, 0, 2],
      [0, 0, 2],
    ];
    const result = applyStep({ name: 'floodFill', params: { x: 0, y: 0, to: 7 } }, grid, {});
    expect(result).toEqual([
      [7, 7, 0],
      [7, 0, 2],
      [0, 0, 2],
    ]);
  });
});

describe('applyStep -- cropToBBox', () => {
  it('recorta al bbox del foreground', () => {
    const grid: Grid = [
      [0, 0, 0],
      [0, 5, 5],
      [0, 0, 0],
    ];
    expect(applyStep({ name: 'cropToBBox', params: { backgroundColor: 0 } }, grid, {})).toEqual([
      [5, 5],
    ]);
  });
});

describe('applyStep -- overlay', () => {
  it('compone foreground sobre anchorGrid cuando hay fondo', () => {
    const grid: Grid = [
      [0, 3],
      [0, 0],
    ];
    const anchor: Grid = [
      [1, 1],
      [1, 1],
    ];
    const result = applyStep({ name: 'overlay', params: {} }, grid, { anchorGrid: anchor });
    expect(result).toEqual([
      [1, 3],
      [1, 1],
    ]);
  });
});

describe('applyStep -- replicate', () => {
  it('tilea la grilla timesX x timesY', () => {
    const grid: Grid = [[1, 2]];
    expect(applyStep({ name: 'replicate', params: { timesX: 2, timesY: 2 } }, grid, {})).toEqual([
      [1, 2, 1, 2],
      [1, 2, 1, 2],
    ]);
  });
});

describe('applyStep -- objectExtract', () => {
  it('extrae el objeto mas grande y aisla el resto del bbox al fondo', () => {
    const grid: Grid = [
      [0, 5, 0, 3],
      [0, 5, 0, 0],
      [0, 0, 0, 0],
    ];
    const result = applyStep({ name: 'objectExtract', params: {} }, grid, {});
    expect(result).toEqual([[5], [5]]);
  });
});

describe('applyStep -- conditionalRecolor', () => {
  it('predicate border recolorea solo celdas del color en el borde del objeto', () => {
    const grid: Grid = [
      [5, 5, 5],
      [5, 5, 5],
      [5, 5, 5],
    ];
    const result = applyStep(
      { name: 'conditionalRecolor', params: { from: 5, to: 9, predicate: 'border' } },
      grid,
      {},
    );
    expect(result).toEqual([
      [9, 9, 9],
      [9, 5, 9],
      [9, 9, 9],
    ]);
  });

  it('predicate interior recolorea el complemento del borde', () => {
    const grid: Grid = [
      [5, 5, 5],
      [5, 5, 5],
      [5, 5, 5],
    ];
    const result = applyStep(
      { name: 'conditionalRecolor', params: { from: 5, to: 9, predicate: 'interior' } },
      grid,
      {},
    );
    expect(result).toEqual([
      [5, 5, 5],
      [5, 9, 5],
      [5, 5, 5],
    ]);
  });
});

describe('applyProgram', () => {
  it('programa vacio es identidad', () => {
    const grid: Grid = [[1, 2]];
    expect(applyProgram([], grid, {})).toEqual(grid);
  });

  it('compone pasos en orden', () => {
    const grid: Grid = [
      [0, 0],
      [0, 5],
    ];
    const program = [
      { name: 'reflect' as const, params: { axis: 'horizontal' as const } },
      { name: 'recolor' as const, params: { mapping: { 5: 9 } } },
    ];
    expect(applyProgram(program, grid, {})).toEqual([
      [0, 0],
      [9, 0],
    ]);
  });
});

describe('proposeAllSteps', () => {
  it('propone translate cuando el foreground se desplazo', () => {
    const pre: Grid = [
      [0, 5, 0],
      [0, 0, 0],
    ];
    const post: Grid = [
      [0, 0, 5],
      [0, 0, 0],
    ];
    const proposals = proposeAllSteps(pre, post, {});
    expect(proposals).toContainEqual({ name: 'translate', params: { dx: 1, dy: 0 } });
    // toda propuesta debe explicar post exactamente al aplicarse sobre pre
    for (const step of proposals) {
      expect(applyStep(step, pre, {})).toEqual(post);
    }
  });

  it('propone recolor cuando cambian colores celda a celda con mapping consistente', () => {
    const pre: Grid = [[1, 2, 1]];
    const post: Grid = [[9, 2, 9]];
    const proposals = proposeAllSteps(pre, post, {});
    expect(proposals).toContainEqual({ name: 'recolor', params: { mapping: { 1: 9 } } });
  });

  it('no propone recolor si el mismo color de origen mapea a dos destinos distintos', () => {
    const pre: Grid = [[1, 1]];
    const post: Grid = [[9, 8]];
    const proposals = proposeAllSteps(pre, post, {});
    expect(proposals.some((s) => s.name === 'recolor')).toBe(false);
  });

  it('propone floodFill solo cuando el cambio es una region 4-conexa completa', () => {
    const pre: Grid = [
      [1, 1, 0],
      [1, 0, 0],
    ];
    const post: Grid = [
      [7, 7, 0],
      [7, 0, 0],
    ];
    const proposals = proposeAllSteps(pre, post, {});
    expect(proposals.some((s) => s.name === 'floodFill')).toBe(true);
  });

  it('devuelve lista vacia si pre y post son identicos (lo cubre el programa vacio)', () => {
    const grid: Grid = [[1, 2]];
    expect(proposeAllSteps(grid, grid, {})).toEqual([]);
  });
});

describe('enumerateStructuralSteps', () => {
  it('devuelve un conjunto acotado y determinista de pasos candidatos', () => {
    const grid: Grid = [
      [0, 0],
      [0, 1],
    ];
    const steps = enumerateStructuralSteps(grid);
    expect(steps.length).toBeGreaterThan(0);
    expect(steps.length).toBeLessThan(60);
    // deterministico: dos llamadas devuelven el mismo orden
    expect(enumerateStructuralSteps(grid)).toEqual(steps);
  });
});
