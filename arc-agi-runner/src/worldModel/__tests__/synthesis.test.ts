/* [arc-agi-runner/worldModel/synthesis.test] BL.20860 -- sintesis bottom-up de programas DSL:
   busqueda acotada (profundidad <=3-4), verificacion contra TODOS los pares observados, y ranking
   por prior de Occam (longitud + simplicidad de params). */
import { describe, expect, it } from 'vitest';

import type { Grid } from '../grid';
import { applyProgram } from '../primitiveOps';
import {
  MIN_PROGRAM_COVERAGE,
  programCoverage,
  searchPrograms,
  synthesizeProgram,
  synthesizeProgramScored,
  verifyProgram,
} from '../synthesis';

describe('searchPrograms', () => {
  it('encuentra el programa identidad cuando pre === post', () => {
    const grid: Grid = [[1, 2]];
    const programs = searchPrograms(grid, grid, {});
    expect(programs).toContainEqual([]);
  });

  it('encuentra un programa de un paso (recolor) cuando alcanza', () => {
    const pre: Grid = [[1, 2, 1]];
    const post: Grid = [[9, 2, 9]];
    const programs = searchPrograms(pre, post, {});
    expect(programs.length).toBeGreaterThan(0);
    expect(programs[0]).toEqual([{ name: 'recolor', params: { mapping: { 1: 9 } } }]);
  });

  it('compone 2 pasos (translate + recolor) cuando ningun paso unico alcanza', () => {
    const pre: Grid = [[0, 5, 0]];
    const post: Grid = [[0, 0, 9]];
    const programs = searchPrograms(pre, post, {}, 3);
    expect(programs.length).toBeGreaterThan(0);
    // el mejor candidato debe reproducir el post exactamente
    expect(applyProgram(programs[0], pre, {})).toEqual(post);
    expect(programs[0].length).toBe(2);
  });

  it('devuelve lista vacia si ninguna composicion dentro de la profundidad explica el par', () => {
    // el mismo color de origen (1) mapea a DOS destinos distintos segun la fila -- ningun
    // primitivo del DSL puede expresar un recolor dependiente de posicion, y la forma/bbox
    // resultante de cualquier transformo geometrico no coincide con el post.
    const pre: Grid = [
      [1, 2],
      [1, 3],
    ];
    const post: Grid = [
      [9, 2],
      [8, 3],
    ];
    const programs = searchPrograms(pre, post, {}, 1);
    expect(programs).toEqual([]);
  });

  it('rankea programas sobrevivientes por longitud ascendente (prior de Occam)', () => {
    const pre: Grid = [[1, 1]];
    const post: Grid = [[1, 1]];
    // pre === post: el UNICO sobreviviente natural es la identidad, longitud 0
    const programs = searchPrograms(pre, post, {});
    expect(programs[0]).toEqual([]);
  });
});

describe('verifyProgram', () => {
  it('true cuando el programa reproduce TODAS las observaciones', () => {
    const program = [{ name: 'recolor' as const, params: { mapping: { 1: 9 } } }];
    const observations = [
      { pre: [[1, 2]] as Grid, post: [[9, 2]] as Grid },
      { pre: [[1, 1]] as Grid, post: [[9, 9]] as Grid },
    ];
    expect(verifyProgram(program, observations, {})).toBe(true);
  });

  it('false si UNA sola observacion contradice al programa (cero tolerancia)', () => {
    const program = [{ name: 'recolor' as const, params: { mapping: { 1: 9 } } }];
    const observations = [
      { pre: [[1, 2]] as Grid, post: [[9, 2]] as Grid },
      { pre: [[1, 1]] as Grid, post: [[8, 8]] as Grid }, // contradice el mapping 1->9
    ];
    expect(verifyProgram(program, observations, {})).toBe(false);
  });
});

describe('synthesizeProgram', () => {
  it('null cuando no hay observaciones', () => {
    expect(synthesizeProgram([], {})).toBeNull();
  });

  it('sintetiza un programa consistente con multiples observaciones del mismo mapping', () => {
    const observations = [
      { pre: [[1, 2]] as Grid, post: [[9, 2]] as Grid },
      { pre: [[2, 1]] as Grid, post: [[2, 9]] as Grid },
      { pre: [[1, 1]] as Grid, post: [[9, 9]] as Grid },
    ];
    const program = synthesizeProgram(observations, {});
    expect(program).not.toBeNull();
    for (const obs of observations) {
      expect(applyProgram(program as never, obs.pre, {})).toEqual(obs.post);
    }
  });

  it('detecta un no-op consistente (identidad) como programa confirmado', () => {
    const observations = [
      { pre: [[3, 3]] as Grid, post: [[3, 3]] as Grid },
      { pre: [[1, 2]] as Grid, post: [[1, 2]] as Grid },
    ];
    expect(synthesizeProgram(observations, {})).toEqual([]);
  });

  it('null si las observaciones se contradicen entre si y ninguna composicion las reconcilia', () => {
    const observations = [
      { pre: [[1, 1]] as Grid, post: [[9, 9]] as Grid }, // sugiere 1->9
      { pre: [[1, 1]] as Grid, post: [[8, 8]] as Grid }, // mismo pre, post distinto -- imposible de reconciliar
    ];
    // cobertura 1/2 = 0.5 < MIN_PROGRAM_COVERAGE: llamarle regla a una moneda seria peor que nada
    expect(synthesizeProgram(observations, {})).toBeNull();
  });
});

describe('BL.21561 -- cobertura puntuada en vez de verificacion de cero tolerancia', () => {
  const program = [{ name: 'recolor' as const, params: { mapping: { 1: 9 } } }];

  it('programCoverage cuenta aciertos y fallos en vez de devolver un booleano', () => {
    const observations = [
      { pre: [[1, 2]] as Grid, post: [[9, 2]] as Grid },
      { pre: [[1, 1]] as Grid, post: [[9, 9]] as Grid },
      { pre: [[1, 1]] as Grid, post: [[8, 8]] as Grid },
    ];
    expect(programCoverage(program, observations, {})).toEqual({
      aciertos: 2,
      fallos: 1,
      cobertura: 2 / 3,
    });
    // el booleano viejo sigue existiendo y sigue siendo implacable
    expect(verifyProgram(program, observations, {})).toBe(false);
  });

  it('sin observaciones la cobertura es 1 (nada que contradiga)', () => {
    expect(programCoverage(program, [], {})).toEqual({ aciertos: 0, fallos: 0, cobertura: 1 });
  });

  it('acepta la regla que explica 2 de 3 -- la observacion del choque no la mata', () => {
    const observations = [
      { pre: [[1, 2]] as Grid, post: [[9, 2]] as Grid },
      { pre: [[1, 1]] as Grid, post: [[9, 9]] as Grid },
      { pre: [[1, 1]] as Grid, post: [[8, 8]] as Grid },
    ];
    const puntuado = synthesizeProgramScored(observations, {});
    expect(puntuado.program).toEqual(program);
    expect(puntuado.aciertos).toBe(2);
    expect(puntuado.fallos).toBe(1);
    expect(puntuado.cobertura).toBeGreaterThanOrEqual(MIN_PROGRAM_COVERAGE);
  });

  it('la IDENTIDAD nunca se acepta parcialmente: seria declarar no-op una accion que hace algo', () => {
    const observations = [
      { pre: [[3, 3]] as Grid, post: [[3, 3]] as Grid },
      { pre: [[3, 3]] as Grid, post: [[3, 3]] as Grid },
      { pre: [[1, 1]] as Grid, post: [[9, 9]] as Grid },
    ];
    const puntuado = synthesizeProgramScored(observations, {});
    expect(puntuado.program).not.toEqual([]);
  });

  it('por debajo del minimo de cobertura devuelve null', () => {
    const observations = [
      { pre: [[1, 1]] as Grid, post: [[9, 9]] as Grid },
      { pre: [[1, 1]] as Grid, post: [[8, 8]] as Grid },
    ];
    const puntuado = synthesizeProgramScored(observations, {});
    expect(puntuado.program).toBeNull();
    expect(puntuado.cobertura).toBe(0);
  });
});
