/* [arc-agi-runner/worldModel/bl21559.macroNovelty.test] BL.21559 -- contrato de las dos piezas
   nuevas, aislado y barato (los tests de EFECTO viven en bl21559.realGames.effect.test.ts y
   bl21559.displacement.effect.test.ts, que cuestan segundos porque corren el modelo de mundo
   completo). Aca se fija lo que cada pieza promete, incluida la unica afirmacion que ningun test de
   efecto puede aislar: que el desempate por novedad GANA sobre el conteo global de observaciones,
   que es literalmente el criterio que producia el ciclado. */
import { describe, expect, it } from 'vitest';

import { createSeededRandom } from '../../prng';
import { selectExploratoryAction } from '../activeLearning';
import { MACRO_MAX_STEPS, MacroCommitment } from '../macroCommitment';
import { StateNoveltyTracker } from '../stateNovelty';
import { TransitionMemory } from '../transitionMemory';

const DISPONIBLES = ['ACTION1', 'ACTION2', 'ACTION3'];

describe('MacroCommitment -- compromiso con la accion elegida', () => {
  it('repite mientras haya cambio enmascarado, hasta el tope', () => {
    const macro = new MacroCommitment();
    macro.iniciar('ACTION1');
    const emitidas: string[] = ['ACTION1'];
    for (let i = 0; i < 20; i++) {
      const siguiente = macro.continuar({
        accionAnterior: 'ACTION1',
        huboCambioEnmascarado: true,
        disponibles: DISPONIBLES,
      });
      if (siguiente === null) break;
      emitidas.push(siguiente);
    }
    // El tope cuenta el paso que abrio la macro: MACRO_MAX_STEPS pasos en total, ni uno mas.
    expect(emitidas).toHaveLength(MACRO_MAX_STEPS);
    expect(new Set(emitidas)).toEqual(new Set(['ACTION1']));
    expect(macro.accionVigente).toBeNull();
  });

  it('corta en cuanto la accion deja de cambiar el tablero -- no gasta presupuesto de mas', () => {
    const macro = new MacroCommitment();
    macro.iniciar('ACTION1');
    expect(
      macro.continuar({
        accionAnterior: 'ACTION1',
        huboCambioEnmascarado: false,
        disponibles: DISPONIBLES,
      }),
    ).toBeNull();
    expect(macro.pasosEmitidos).toBe(0);
  });

  it('corta si el juego dejo de ofrecer la accion', () => {
    const macro = new MacroCommitment();
    macro.iniciar('ACTION3');
    expect(
      macro.continuar({
        accionAnterior: 'ACTION3',
        huboCambioEnmascarado: true,
        disponibles: ['ACTION1', 'ACTION2'],
      }),
    ).toBeNull();
  });

  it('corta si en el medio se emitio otra accion (plan sembrado, RESET)', () => {
    const macro = new MacroCommitment();
    macro.iniciar('ACTION1');
    expect(
      macro.continuar({
        accionAnterior: 'ACTION2',
        huboCambioEnmascarado: true,
        disponibles: DISPONIBLES,
      }),
    ).toBeNull();
  });

  it('sin macro abierta no inventa ninguna', () => {
    const macro = new MacroCommitment();
    expect(
      macro.continuar({
        accionAnterior: 'ACTION1',
        huboCambioEnmascarado: true,
        disponibles: DISPONIBLES,
      }),
    ).toBeNull();
  });
});

describe('StateNoveltyTracker -- novedad por conteo sobre la firma enmascarada', () => {
  it('una accion nunca probada desde este estado gana a una ya probada', () => {
    const novedad = new StateNoveltyTracker();
    novedad.registrarVisita('S1');
    novedad.registrarTransicion('S1', 'ACTION1', 'S2');
    expect(novedad.comparar('S1', 'ACTION2', 'ACTION1')).toBeLessThan(0);
    expect(novedad.hayAccionSinProbar('S1', DISPONIBLES)).toBe(true);
  });

  it('entre dos ya probadas gana la que lleva al estado MENOS visitado', () => {
    const novedad = new StateNoveltyTracker();
    for (let i = 0; i < 5; i++) novedad.registrarVisita('S2');
    novedad.registrarVisita('S3');
    novedad.registrarTransicion('S1', 'ACTION1', 'S2'); // destino con 5 visitas
    novedad.registrarTransicion('S1', 'ACTION2', 'S3'); // destino con 1 visita
    expect(novedad.comparar('S1', 'ACTION2', 'ACTION1')).toBeLessThan(0);
    expect(novedad.visitasDe('S2')).toBe(5);
  });

  it('a igual destino desempata la menos intentada desde ese estado', () => {
    const novedad = new StateNoveltyTracker();
    novedad.registrarVisita('S2');
    novedad.registrarTransicion('S1', 'ACTION1', 'S2');
    novedad.registrarTransicion('S1', 'ACTION1', 'S2');
    novedad.registrarTransicion('S1', 'ACTION2', 'S2');
    expect(novedad.comparar('S1', 'ACTION2', 'ACTION1')).toBeLessThan(0);
    expect(novedad.intentosDe('S1', 'ACTION1')).toBe(2);
  });

  it('dos igual de novedosas empatan -- no inventa un orden', () => {
    const novedad = new StateNoveltyTracker();
    expect(novedad.comparar('S1', 'ACTION1', 'ACTION2')).toBe(0);
  });
});

describe('BL.21559 -- la novedad le GANA al conteo global, que es lo que producia el ciclado', () => {
  it('elige la accion que lleva a un estado nuevo aunque sea la MAS observada', () => {
    /* Escenario minimo del defecto: dos acciones sin regla confirmada (rango de incertidumbre 0,
       como TODAS en juego real). ACTION1 se observo mas veces, asi que el criterio viejo --
       menos-observada primero -- elegiria ACTION2 siempre. Pero desde ESTE estado ACTION2 devuelve
       a un estado ya pisado y ACTION1 nunca se probo. */
    const memory = new TransitionMemory();
    for (let i = 0; i < 4; i++) memory.recordObservation('ACTION1', [[1, 1]], [[9, 8]]);
    memory.recordObservation('ACTION2', [[2, 2]], [[3, 7]]);
    expect(memory.getObservationCount('ACTION1')).toBeGreaterThan(
      memory.getObservationCount('ACTION2'),
    );

    const novedad = new StateNoveltyTracker();
    for (let i = 0; i < 6; i++) novedad.registrarVisita('S_VISITADO');
    novedad.registrarVisita('S_ACTUAL');
    novedad.registrarTransicion('S_ACTUAL', 'ACTION2', 'S_VISITADO');

    const disponibles = ['ACTION1', 'ACTION2'];
    const conNovedad = createSeededRandom('bl21559-novedad');
    const sinNovedad = createSeededRandom('bl21559-novedad');
    let vecesNueva = 0;
    let vecesVieja = 0;
    for (let i = 0; i < 100; i++) {
      if (
        selectExploratoryAction(disponibles, memory, conNovedad, {
          novelty: { tracker: novedad, signature: 'S_ACTUAL' },
        }) === 'ACTION1'
      ) {
        vecesNueva++;
      }
      if (selectExploratoryAction(disponibles, memory, sinNovedad) === 'ACTION1') vecesVieja++;
    }
    // eslint-disable-next-line no-console -- magnitud del criterio nuevo contra el viejo
    console.log(
      `[BL.21559] accion hacia estado NUEVO elegida ${vecesNueva}/100 con novedad, ` +
        `${vecesVieja}/100 con el criterio viejo (menos-observada)`,
    );
    expect(vecesNueva).toBe(100);
    expect(vecesVieja).toBe(0);
  });

  it('sin firma de estado (frame sin grilla) se comporta como antes de este BL', () => {
    const memory = new TransitionMemory();
    for (let i = 0; i < 4; i++) memory.recordObservation('ACTION1', [[1, 1]], [[9, 8]]);
    memory.recordObservation('ACTION2', [[2, 2]], [[3, 7]]);
    const novedad = new StateNoveltyTracker();
    const rng = createSeededRandom('bl21559-sin-firma');
    for (let i = 0; i < 50; i++) {
      const elegida = selectExploratoryAction(['ACTION1', 'ACTION2'], memory, rng, {
        novelty: { tracker: novedad, signature: null },
      });
      expect(elegida).toBe('ACTION2'); // la menos observada, criterio previo intacto
    }
  });
});
