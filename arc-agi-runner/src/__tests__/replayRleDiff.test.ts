/* [arc-agi-runner/replayRleDiff.test] BL.21557 -- el codec del corpus de replay. Lo critico no es que
   comprima: es que decode(encode(x)) devuelva EXACTAMENTE x, porque un corpus que no se puede
   reconstruir es peor que no tener corpus (ocupa, parece util y miente). */
import { describe, expect, it } from 'vitest';

import { decodeGridDiff, encodeGridDiff, REPLAY_UNCHANGED } from '../replayRleDiff';
import type { Grid } from '../worldModel/grid';

function gridUniforme(width: number, height: number, valor: number): Grid {
  return Array.from({ length: height }, () => new Array<number>(width).fill(valor));
}

describe('encodeGridDiff / decodeGridDiff', () => {
  it('round-trip exacto sin grilla previa (caso RESET: RLE completo)', () => {
    const after: Grid = [
      [1, 1, 2],
      [3, 3, 3],
    ];
    const diff = encodeGridDiff(null, after);
    expect(diff).not.toBeNull();
    expect(decodeGridDiff(diff!.rle, null, diff!.width, diff!.height)).toEqual(after);
    expect(diff!.changedCells).toBe(6);
  });

  it('round-trip exacto de un cambio de una sola celda', () => {
    const before = gridUniforme(64, 64, 0);
    const after = gridUniforme(64, 64, 0);
    after[17][32] = 9;

    const diff = encodeGridDiff(before, after)!;
    expect(diff.changedCells).toBe(1);
    expect(decodeGridDiff(diff.rle, before, diff.width, diff.height)).toEqual(after);
  });

  it('un cambio puntual en 64x64 cuesta pocos bytes -- ES un diff, no la grilla entera', () => {
    const before = gridUniforme(64, 64, 0);
    const after = gridUniforme(64, 64, 0);
    after[10][10] = 5;

    const diff = encodeGridDiff(before, after)!;
    // 3 runs (sin cambio / celda / sin cambio) = ~9 bytes. El techo de 32 deja margen sin dejar
    // pasar una regresion a "guardar la grilla completa" (4096 celdas costarian ordenes mas).
    expect(diff.rle.length).toBeLessThan(32);
    expect(diff.runs).toBe(3);
  });

  it('sin cambios emite un unico run de "sin cambio" y reconstruye la grilla previa', () => {
    const before = gridUniforme(8, 8, 4);
    const diff = encodeGridDiff(before, gridUniforme(8, 8, 4))!;

    expect(diff.changedCells).toBe(0);
    expect(diff.runs).toBe(1);
    expect(diff.rle[diff.rle.length - 1]).toBe(REPLAY_UNCHANGED);
    expect(decodeGridDiff(diff.rle, before, 8, 8)).toEqual(before);
  });

  it('un cambio de dimensiones se codifica como RLE completo (la grilla previa no aplica)', () => {
    const before = gridUniforme(4, 4, 1);
    const after = gridUniforme(8, 8, 2);

    const diff = encodeGridDiff(before, after)!;
    expect(diff.changedCells).toBe(64);
    expect(decodeGridDiff(diff.rle, before, diff.width, diff.height)).toEqual(after);
  });

  it('devuelve null cuando el frame no trae grilla utilizable -- nunca inventa un frame vacio', () => {
    expect(encodeGridDiff(null, null)).toBeNull();
    expect(encodeGridDiff(null, [])).toBeNull();
    expect(encodeGridDiff(null, [[]])).toBeNull();
  });

  it('normaliza colores fuera de rango en vez de corromper el corpus con el centinela', () => {
    const after: Grid = [[16, 17, -1]];
    const diff = encodeGridDiff(null, after)!;
    // 16 -> 0, 17 -> 1, -1 -> 15. Ningun valor puede colisionar con REPLAY_UNCHANGED.
    expect(decodeGridDiff(diff.rle, null, 3, 1)).toEqual([[0, 1, 15]]);
  });

  it('reconstruye una cadena de 250 pasos aplicando los diffs uno atras del otro', () => {
    let actual = gridUniforme(64, 64, 0);
    const cadena: { rle: Uint8Array; width: number; height: number }[] = [];
    const esperado: Grid[] = [];

    for (let paso = 0; paso < 250; paso++) {
      const siguiente = actual.map((row) => row.slice());
      siguiente[paso % 64][(paso * 7) % 64] = (paso % 15) + 1;
      const diff = encodeGridDiff(actual, siguiente)!;
      cadena.push({ rle: diff.rle, width: diff.width, height: diff.height });
      esperado.push(siguiente);
      actual = siguiente;
    }

    let reconstruida: Grid | null = gridUniforme(64, 64, 0);
    cadena.forEach((frame, i) => {
      reconstruida = decodeGridDiff(frame.rle, reconstruida, frame.width, frame.height);
      expect(reconstruida).toEqual(esperado[i]);
    });
  });
});
