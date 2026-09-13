/* [arc-agi-runner/worldModel/transitionMemory.test] BL.20860 -- modelo de mundo tipo STRIPS
   aprendido: por cada accion, mantiene observaciones (frame_pre, frame_post), sintetiza el
   programa DSL que las explica (synthesis.ts) y trackea confianza Beta (exitos/fracasos, NO
   booleano). El campo `program` de una KnownTransition ES el programa verificado -- no un
   sistema paralelo. */
import { describe, expect, it } from 'vitest';

import type { Grid } from '../grid';
import { TransitionMemory } from '../transitionMemory';

describe('TransitionMemory', () => {
  it('sin observaciones: sin transicion conocida, confianza neutra (prior uniforme)', () => {
    const mem = new TransitionMemory();
    expect(mem.getTransition('ACTION1')).toBeUndefined();
    expect(mem.getConfidence('ACTION1')).toBe(0.5);
    expect(mem.predict('ACTION1', [[1]])).toBeNull();
  });

  it('confirma un programa tras observaciones consistentes y predice con el', () => {
    const mem = new TransitionMemory();
    mem.recordObservation('ACTION1', [[1, 2]], [[9, 2]]);
    mem.recordObservation('ACTION1', [[2, 1]], [[2, 9]]);
    mem.recordObservation('ACTION1', [[1, 1]], [[9, 9]]);

    const transition = mem.getTransition('ACTION1');
    expect(transition?.program).not.toBeNull();
    expect(mem.predict('ACTION1', [[1, 3]])).toEqual([[9, 3]]);
    expect(mem.getConfidence('ACTION1')).toBeGreaterThan(0.5);
  });

  it('detecta un no-op consistente (program vacio / identidad)', () => {
    const mem = new TransitionMemory();
    mem.recordObservation('ACTION5', [[1, 2]], [[1, 2]]);
    mem.recordObservation('ACTION5', [[3, 3]], [[3, 3]]);
    // BL.21500: la SINTESIS concluye identidad ya con estas 2 observaciones -- eso no cambio, y
    // `predict` lo refleja. Lo que ahora exige 3 observaciones es `isKnownNoOp`, que es la
    // puerta que habilita a EXCLUIR la accion de la exploracion (ver activeLearning.ts).
    expect(mem.predict('ACTION5', [[7]])).toEqual([[7]]);
    expect(mem.isKnownNoOp('ACTION5')).toBe(false);

    mem.recordObservation('ACTION5', [[5, 5]], [[5, 5]]);
    expect(mem.isKnownNoOp('ACTION5')).toBe(true);
  });

  it('una contradiccion incrementa beta y contradictionCount, y re-sintetiza', () => {
    const mem = new TransitionMemory();
    mem.recordObservation('ACTION2', [[1, 2]], [[9, 2]]);
    mem.recordObservation('ACTION2', [[1, 1]], [[9, 9]]);
    const before = mem.getTransition('ACTION2');
    expect(before?.program).not.toBeNull();
    expect(before?.coverage).toBe(1);
    const betaBefore = before?.beta ?? 0;
    const contradictionsBefore = before?.contradictionCount ?? 0;

    // contradice el mapping 1->9 confirmado
    mem.recordObservation('ACTION2', [[1, 1]], [[8, 8]]);

    const after = mem.getTransition('ACTION2');
    expect(after?.beta).toBeGreaterThan(betaBefore);
    expect(after?.contradictionCount).toBeGreaterThan(contradictionsBefore);
    /* BL.21561 -- la hipotesis SOBREVIVE con cobertura 2/3 en vez de morir. Antes, una sola
       observacion discordante dejaba `program` en null; en ARC-AGI-3 esa observacion es el choque
       contra la pared y llegaba siempre, asi que ninguna regla de movimiento podia confirmarse. La
       contradiccion no se pierde: se contabiliza en beta y en `coverage`. */
    expect(after?.program).toEqual([{ name: 'recolor', params: { mapping: { 1: 9 } } }]);
    expect(after?.coverage).toBeCloseTo(2 / 3, 10);
    // y la confianza baja, que es lo que la Beta tiene que reflejar
    expect(mem.getConfidence('ACTION2')).toBeLessThan(
      (before?.alpha ?? 1) / ((before?.alpha ?? 1) + (before?.beta ?? 1)),
    );
  });

  it('BL.21561 -- cobertura por debajo del minimo: no hay hipotesis (2 observaciones opuestas)', () => {
    const mem = new TransitionMemory();
    mem.recordObservation('ACTION4', [[1, 1]], [[9, 9]]);
    mem.recordObservation('ACTION4', [[1, 1]], [[8, 8]]);
    // 1/2 = 0.5 < MIN_PROGRAM_COVERAGE: aceptar eso seria llamar regla a una moneda.
    expect(mem.getTransition('ACTION4')?.program).toBeNull();
    expect(mem.getTransition('ACTION4')?.coverage).toBe(0);
  });

  it('observationCount crece con cada llamada, incluso mas alla de la ventana capada', () => {
    const mem = new TransitionMemory();
    const grid: Grid = [[4, 4]];
    for (let i = 0; i < 25; i++) {
      mem.recordObservation('ACTION3', grid, grid); // no-op consistente
    }
    expect(mem.getTransition('ACTION3')?.observationCount).toBe(25);
    expect(mem.isKnownNoOp('ACTION3')).toBe(true);
  });

  it('getKnownTransitions devuelve todas las acciones registradas', () => {
    const mem = new TransitionMemory();
    mem.recordObservation('ACTION1', [[1]], [[1]]);
    mem.recordObservation('ACTION2', [[1]], [[2]]);
    const all = mem.getKnownTransitions();
    expect(all.map((t) => t.action).sort()).toEqual(['ACTION1', 'ACTION2']);
  });
});
