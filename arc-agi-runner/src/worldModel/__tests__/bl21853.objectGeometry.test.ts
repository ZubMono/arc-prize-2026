/* [arc-agi-runner/worldModel/bl21853.objectGeometry.test] BL.21853 (revision) -- el contrato de
   `objetosQueTocan` cuando la componente supera el tope.

   POR QUE EXISTE. El fixture dorado de paridad (`mechanicsParity.json`) trabaja con grillas de a
   lo sumo 8x8, asi que NO puede ejercitar un tope de 256 celdas: los dos motores se equivocaban
   igual y el banco daba verde (RFM-09). El defecto medido en la revision de BL.21853: al pasarse
   el tope el flood CORTABA, el resto de la componente quedaba sin marcar y una semilla posterior
   lo volvia a recorrer, emitiendo un PEDAZO del tablero como si fuera un objeto -- y la salida
   pasaba a depender de QUE celdas cambiaron, no solo de la grilla.

   Corredor 4-conexo de 304 celdas en 64x64 con tope 256: antes del arreglo, con las dos semillas
   salia un "objeto" de 47 celdas; con una sola, []. */
import { describe, expect, it } from 'vitest';

import type { Grid } from '../grid';
import { MAX_CELDAS_DE_OBJETO_ENTERO, objetosQueTocan } from '../objectGeometry';

type Celda = [number, number];

function grilla(alto: number, ancho: number, fondo = 0): Grid {
  return Array.from({ length: alto }, () => Array.from({ length: ancho }, () => fondo));
}

/** Corredor de 1 celda de ancho y 304 celdas, todo una sola componente 4-conexa. */
function corredor(grid: Grid): Celda[] {
  const camino: Celda[] = [];
  for (let i = 0; i < 300; i++) {
    const fila = Math.floor(i / 60);
    const col = i % 60;
    camino.push([fila * 2, fila % 2 === 0 ? col : 59 - col]);
  }
  for (let fila = 0; fila < 4; fila++) camino.push([fila * 2 + 1, fila % 2 === 0 ? 59 : 0]);
  for (const [y, x] of camino) grid[y][x] = 3;
  return camino;
}

describe('objetosQueTocan -- la componente que supera el tope se descarta ENTERA', () => {
  it('no emite un pedazo de la componente grande aunque haya varias semillas adentro', () => {
    const grid = grilla(64, 64);
    const camino = corredor(grid);
    expect(camino.length).toBeGreaterThan(MAX_CELDAS_DE_OBJETO_ENTERO);
    expect(objetosQueTocan(grid, 0, [camino[0]], MAX_CELDAS_DE_OBJETO_ENTERO)).toEqual([]);
    expect(objetosQueTocan(grid, 0, [camino[290]], MAX_CELDAS_DE_OBJETO_ENTERO)).toEqual([]);
    expect(objetosQueTocan(grid, 0, [camino[0], camino[290]], MAX_CELDAS_DE_OBJETO_ENTERO)).toEqual(
      [],
    );
  });

  it('descartar la componente grande no tapa a un objeto chico que toca otra semilla', () => {
    const grid = grilla(64, 64);
    for (let y = 0; y < 30; y++) for (let x = 0; x < 30; x++) grid[y][x] = 3; // 900 celdas
    for (const [y, x] of [
      [40, 40],
      [40, 41],
      [41, 40],
      [41, 41],
    ] as Celda[]) {
      grid[y][x] = 7;
    }
    const objetos = objetosQueTocan(
      grid,
      0,
      [
        [0, 0],
        [40, 40],
      ],
      MAX_CELDAS_DE_OBJETO_ENTERO,
    );
    expect(objetos).toEqual([
      [
        [40, 40],
        [40, 41],
        [41, 40],
        [41, 41],
      ],
    ]);
  });
});
