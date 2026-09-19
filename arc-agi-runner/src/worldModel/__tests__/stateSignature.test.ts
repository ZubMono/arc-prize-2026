/* [arc-agi-runner/worldModel/stateSignature.test] BL.20860 -- firma hasheable de un estado
   (grilla + acciones disponibles) y deteccion de no-ops entre dos frames sucesivos. Idea tomada
   de arc-agi3-kaggle-agent/arc_agent/policy.py::compute_signature (BL.20783), reimplementada en
   TS sobre nuestro tipo Grid. */
import { describe, expect, it } from 'vitest';

import type { Grid, VolatilityMask } from '../grid';
import { computeStateSignature, isNoOpTransition } from '../stateSignature';

describe('computeStateSignature', () => {
  it('es deterministica -- mismo grid + mismas acciones, misma firma', () => {
    const grid: Grid = [
      [1, 2],
      [3, 4],
    ];
    expect(computeStateSignature(grid, [1, 2, 3])).toBe(computeStateSignature(grid, [1, 2, 3]));
  });

  it('distingue grillas distintas', () => {
    const a: Grid = [[1, 2]];
    const b: Grid = [[2, 1]];
    expect(computeStateSignature(a, [1])).not.toBe(computeStateSignature(b, [1]));
  });

  it('distingue el mismo grid con distintas acciones disponibles', () => {
    const grid: Grid = [[1, 2]];
    expect(computeStateSignature(grid, [1, 2])).not.toBe(computeStateSignature(grid, [1, 2, 3]));
  });

  it('el orden de las acciones no cambia la firma (se normaliza)', () => {
    const grid: Grid = [[1, 2]];
    expect(computeStateSignature(grid, [3, 1, 2])).toBe(computeStateSignature(grid, [1, 2, 3]));
  });
});

describe('isNoOpTransition', () => {
  it('true cuando el frame no cambio', () => {
    const grid: Grid = [[1, 2]];
    expect(isNoOpTransition(grid, [[1, 2]])).toBe(true);
  });

  it('false cuando el frame cambio', () => {
    const grid: Grid = [[1, 2]];
    expect(isNoOpTransition(grid, [[1, 9]])).toBe(false);
  });

  it('null antes/despues -- sin grilla conocida, no se puede afirmar no-op', () => {
    expect(isNoOpTransition(null, [[1, 2]])).toBe(false);
    expect(isNoOpTransition([[1, 2]], null)).toBe(false);
  });
});

// ── BL.21558 — firmar SOLO las celdas estables ────────────────────────────────────────────────

const GRILLA_PARIDAD: Grid = [
  [1, 2, 3],
  [4, 5, 6],
  [7, 8, 9],
];
const MASCARA_PARIDAD: VolatilityMask = [
  [false, false, false],
  [false, false, false],
  [false, true, true],
];

describe('BL.21558 -- firma enmascarada', () => {
  it('dos frames que solo difieren en el HUD comparten firma', () => {
    const a: Grid = [
      [0, 5, 0],
      [3, 1, 0],
    ];
    const b: Grid = [
      [0, 5, 0],
      [9, 7, 0],
    ];
    const mask: VolatilityMask = [
      [false, false, false],
      [true, true, false],
    ];
    // Esta es la patologia medida: 76 firmas unicas en 78 pasos, 94/94, 128/129, 100/101.
    expect(computeStateSignature(a, [1, 2])).not.toBe(computeStateSignature(b, [1, 2]));
    expect(computeStateSignature(a, [1, 2], mask)).toBe(computeStateSignature(b, [1, 2], mask));
  });

  it('las acciones disponibles siguen distinguiendo estados aunque la grilla se enmascare', () => {
    const mask: VolatilityMask = [[true, true]];
    expect(computeStateSignature([[1, 2]], [1], mask)).not.toBe(
      computeStateSignature([[1, 2]], [1, 2], mask),
    );
  });

  it('sin mascara la firma es EXACTAMENTE la historica (las corridas viejas siguen valiendo)', () => {
    expect(computeStateSignature(GRILLA_PARIDAD, [1, 2, 6], null)).toBe(
      computeStateSignature(GRILLA_PARIDAD, [1, 2, 6]),
    );
  });

  /* Valor de referencia del motor CANONICO -- el puerto Python afirma el mismo numero en
     arc-agi3-kaggle-agent/tests/test_volatility_mask.py. Ver el mismo patron en grid.test.ts. */
  it('valor de referencia para la paridad con el puerto Python', () => {
    expect(computeStateSignature(GRILLA_PARIDAD, [1, 2, 6], MASCARA_PARIDAD)).toBe(3297065176);
  });

  it('isNoOpTransition detecta el no-op que sin mascara es invisible', () => {
    const antes: Grid = [
      [0, 5],
      [1, 0],
    ];
    const despues: Grid = [
      [0, 5],
      [8, 0],
    ];
    const mask: VolatilityMask = [
      [false, false],
      [true, false],
    ];
    expect(isNoOpTransition(antes, despues)).toBe(false);
    expect(isNoOpTransition(antes, despues, mask)).toBe(true);
  });
});
