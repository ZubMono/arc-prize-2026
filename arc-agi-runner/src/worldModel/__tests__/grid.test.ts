/* [arc-agi-runner/worldModel/grid.test] BL.20860 -- utilidades puras sobre grillas ARC. */
import { describe, expect, it } from 'vitest';

import {
  cellDiffCount,
  cloneGrid,
  detectBackgroundColor,
  foregroundBoundingBox,
  gridDimensions,
  gridsEqual,
  gridsEqualMasked,
  hashGrid,
  hashGridMasked,
  neutralizeVolatileCells,
  type VolatilityMask,
} from '../grid';

describe('cloneGrid', () => {
  it('produce una copia profunda independiente de filas', () => {
    const original = [
      [1, 2],
      [3, 4],
    ];
    const clone = cloneGrid(original);
    clone[0][0] = 99;
    expect(original[0][0]).toBe(1);
    expect(clone).toEqual([
      [99, 2],
      [3, 4],
    ]);
  });
});

describe('gridDimensions', () => {
  it('devuelve height/width correctos', () => {
    expect(
      gridDimensions([
        [1, 2, 3],
        [4, 5, 6],
      ]),
    ).toEqual({ height: 2, width: 3 });
  });

  it('devuelve width 0 en grilla vacia', () => {
    expect(gridDimensions([])).toEqual({ height: 0, width: 0 });
  });
});

describe('gridsEqual', () => {
  it('true para grillas identicas', () => {
    expect(
      gridsEqual(
        [
          [1, 2],
          [3, 4],
        ],
        [
          [1, 2],
          [3, 4],
        ],
      ),
    ).toBe(true);
  });

  it('false si una celda difiere', () => {
    expect(
      gridsEqual(
        [
          [1, 2],
          [3, 4],
        ],
        [
          [1, 2],
          [3, 9],
        ],
      ),
    ).toBe(false);
  });

  it('false si difiere el alto', () => {
    expect(
      gridsEqual(
        [[1, 2]],
        [
          [1, 2],
          [3, 4],
        ],
      ),
    ).toBe(false);
  });

  it('false si difiere el ancho de una fila', () => {
    expect(gridsEqual([[1, 2]], [[1, 2, 3]])).toBe(false);
  });
});

describe('cellDiffCount', () => {
  it('0 para grillas identicas', () => {
    expect(cellDiffCount([[1, 2]], [[1, 2]])).toBe(0);
  });

  it('cuenta celdas distintas', () => {
    expect(cellDiffCount([[1, 2, 3]], [[1, 9, 9]])).toBe(2);
  });

  it('penaliza celdas fuera de la interseccion cuando difiere el tamano', () => {
    expect(cellDiffCount([[1, 1]], [[1, 1, 1]])).toBe(1);
  });
});

describe('detectBackgroundColor', () => {
  it('elige el color mas frecuente', () => {
    const grid = [
      [0, 0, 0],
      [0, 5, 0],
      [0, 0, 0],
    ];
    expect(detectBackgroundColor(grid)).toBe(0);
  });

  it('desempata por menor indice de color', () => {
    const grid = [
      [1, 1],
      [2, 2],
    ];
    expect(detectBackgroundColor(grid)).toBe(1);
  });
});

describe('foregroundBoundingBox', () => {
  it('devuelve null en grilla uniforme', () => {
    expect(
      foregroundBoundingBox(
        [
          [0, 0],
          [0, 0],
        ],
        0,
      ),
    ).toBeNull();
  });

  it('calcula el bbox de las celdas distintas del fondo', () => {
    const grid = [
      [0, 0, 0, 0],
      [0, 5, 5, 0],
      [0, 0, 0, 0],
    ];
    expect(foregroundBoundingBox(grid, 0)).toEqual({ minX: 1, minY: 1, maxX: 2, maxY: 1 });
  });
});

describe('hashGrid', () => {
  it('es deterministico -- mismo contenido, mismo hash', () => {
    const a = [
      [1, 2],
      [3, 4],
    ];
    const b = [
      [1, 2],
      [3, 4],
    ];
    expect(hashGrid(a)).toBe(hashGrid(b));
  });

  it('distingue grillas con contenido distinto', () => {
    expect(hashGrid([[1, 2]])).not.toBe(hashGrid([[2, 1]]));
  });

  it('distingue grillas con la misma celda pero distinta forma de filas', () => {
    // [[1],[2]] vs [[1,2]] no deben colisionar solo por concatenar valores.
    expect(hashGrid([[1], [2]])).not.toBe(hashGrid([[1, 2]]));
  });
});

// ── BL.21558 — comparacion y hash IGNORANDO las celdas volatiles ─────────────────────────────

const GRILLA_PARIDAD = [
  [1, 2, 3],
  [4, 5, 6],
  [7, 8, 9],
];
/** Ultima fila = "HUD": las dos celdas de la derecha cambian sin relacion con la accion. */
const MASCARA_PARIDAD: VolatilityMask = [
  [false, false, false],
  [false, false, false],
  [false, true, true],
];

describe('BL.21558 -- gridsEqualMasked', () => {
  it('sin mascara es identica a gridsEqual (una sola implementacion)', () => {
    const a = [
      [1, 2],
      [3, 4],
    ];
    const b = [
      [1, 2],
      [3, 9],
    ];
    expect(gridsEqualMasked(a, a, null)).toBe(gridsEqual(a, a));
    expect(gridsEqualMasked(a, b, null)).toBe(gridsEqual(a, b));
  });

  it('dos frames que solo difieren en el HUD son el MISMO estado', () => {
    const antes = [
      [1, 2, 3],
      [4, 5, 6],
      [7, 0, 0],
    ];
    const despues = [
      [1, 2, 3],
      [4, 5, 6],
      [7, 4, 9],
    ];
    // Este es el nucleo del BL: sin mascara, `gridsEqual` no da true NUNCA y no se detecta un
    // solo no-op en toda la partida.
    expect(gridsEqual(antes, despues)).toBe(false);
    expect(gridsEqualMasked(antes, despues, MASCARA_PARIDAD)).toBe(true);
  });

  it('un cambio en una celda ESTABLE sigue siendo un cambio de estado', () => {
    const antes = [
      [1, 2, 3],
      [4, 5, 6],
      [7, 0, 0],
    ];
    const despues = [
      [1, 2, 3],
      [4, 9, 6],
      [7, 4, 9],
    ];
    expect(gridsEqualMasked(antes, despues, MASCARA_PARIDAD)).toBe(false);
  });

  it('un cambio de FORMA nunca es ruido de HUD', () => {
    expect(gridsEqualMasked([[1, 2]], [[1, 2, 3]], [[true, true, true]])).toBe(false);
    expect(gridsEqualMasked([[1]], [[1], [1]], [[true], [true]])).toBe(false);
  });
});

describe('BL.21558 -- hashGridMasked', () => {
  it('sin mascara reproduce hashGrid bit a bit (las firmas viejas siguen valiendo)', () => {
    expect(hashGridMasked(GRILLA_PARIDAD, null)).toBe(hashGrid(GRILLA_PARIDAD));
  });

  it('colapsa el contenido volatil: dos HUD distintos, un solo hash', () => {
    const a = [
      [1, 2, 3],
      [4, 5, 6],
      [7, 8, 9],
    ];
    const b = [
      [1, 2, 3],
      [4, 5, 6],
      [7, 0, 1],
    ];
    expect(hashGrid(a)).not.toBe(hashGrid(b));
    expect(hashGridMasked(a, MASCARA_PARIDAD)).toBe(hashGridMasked(b, MASCARA_PARIDAD));
  });

  it('el placeholder no colisiona con ningun color real (0-15)', () => {
    // Si el relleno de una celda volatil fuera un color legitimo, una grilla enmascarada podria
    // hashear igual que otra que ahi tiene ese color de verdad.
    for (let color = 0; color <= 15; color++) {
      const conColor = [[color, color]];
      expect(hashGridMasked([[0, 0]], [[true, true]])).not.toBe(hashGrid(conColor));
    }
  });

  /* Valores de referencia del motor CANONICO. El puerto Python
     (arc-agi3-kaggle-agent/tests/test_volatility_mask.py) afirma EXACTAMENTE los mismos numeros:
     es el contrato de paridad de la mascara, del mismo modo que dslParity.json lo es del DSL. Si
     alguno de los dos lados cambia la aritmetica, uno de los dos tests se pone en rojo. */
  it('valor de referencia para la paridad con el puerto Python', () => {
    expect(hashGrid(GRILLA_PARIDAD)).toBe(4166473219);
    expect(hashGridMasked(GRILLA_PARIDAD, MASCARA_PARIDAD)).toBe(767370346);
  });
});

describe('BL.21558 -- neutralizeVolatileCells', () => {
  it('copia el valor del pre en las celdas volatiles y deja el resto intacto', () => {
    const pre = [
      [1, 2, 3],
      [4, 5, 6],
      [7, 0, 0],
    ];
    const post = [
      [1, 2, 3],
      [4, 9, 6],
      [7, 4, 8],
    ];
    expect(neutralizeVolatileCells(pre, post, MASCARA_PARIDAD)).toEqual([
      [1, 2, 3],
      [4, 9, 6], // el cambio real del tablero se conserva
      [7, 0, 0], // el HUD queda igual al de `pre` -> la sintesis no tiene que explicarlo
    ]);
  });

  it('sin mascara devuelve un clon, nunca la misma referencia', () => {
    const post = [[1, 2]];
    const resultado = neutralizeVolatileCells([[0, 0]], post, null);
    expect(resultado).toEqual(post);
    expect(resultado).not.toBe(post);
    expect(resultado[0]).not.toBe(post[0]);
  });

  it('celda sin equivalente en el pre conserva su valor', () => {
    expect(neutralizeVolatileCells([[1]], [[1, 7]], [[true, true]])).toEqual([[1, 7]]);
  });
});
