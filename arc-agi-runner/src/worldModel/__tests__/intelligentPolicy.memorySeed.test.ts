/* [arc-agi-runner/worldModel/intelligentPolicy.memorySeed.test] BL.20861 -- CONSUMO de la memoria
   entre corridas. Es la mitad que hace que destilar sirva: sin esto la memoria es un archivo
   muerto. El criterio de exito del BL es que la corrida N+1 sobre la misma actividad use MENOS
   acciones que la N, y eso solo pasa si la politica arranca sabiendo que funciono y que no. */

import { describe, expect, it } from 'vitest';

import type { ActivityMemorySeed } from '../../activityMemorySeed';
import { createSeededRandom } from '../../prng';
import type { ArcFrameResponse } from '../../types';
import type { Grid } from '../grid';
import { IntelligentPolicy } from '../intelligentPolicy';
import { computeStateSignature } from '../stateSignature';

const ACCIONES = [1, 2, 3, 4];

function frame(grid: Grid, availableActions: number[] = ACCIONES): ArcFrameResponse {
  return {
    game_id: 'g1',
    guid: 'guid-1',
    frame: [grid],
    state: 'NOT_FINISHED',
    levels_completed: 0,
    win_levels: 0,
    available_actions: availableActions,
  };
}

/** Grilla 3x3 con una unica celda marcada -- cambiar la marca cambia la firma perceptual. */
function gridConMarca(valor: number): Grid {
  return [
    [0, 0, 0],
    [0, valor, 0],
    [0, 0, 0],
  ];
}

function firmaDe(grid: Grid, availableActions: number[] = ACCIONES): string {
  return String(computeStateSignature(grid, availableActions));
}

function seed(overrides: Partial<ActivityMemorySeed> = {}): ActivityMemorySeed {
  return { activityId: 'g1', nonOps: [], plans: [], transitions: [], isCold: false, ...overrides };
}

describe('IntelligentPolicy con memoria de actividad (BL.20861)', () => {
  describe('replay del plan ganador', () => {
    it('reejecuta el camino efectivo de la corrida anterior, en orden', () => {
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s1'),
        memorySeed: seed({
          plans: [{ actions: ['ACTION3', 'ACTION1', 'ACTION4'], validatedByRuns: 1 }],
        }),
      });

      /* Cada paso ve una grilla DISTINTA: el mundo avanza, asi que la guarda de divergencia no se
         dispara y el plan se consume completo. */
      expect(policy.decide(frame(gridConMarca(1))).action).toBe('ACTION3');
      expect(policy.decide(frame(gridConMarca(2))).action).toBe('ACTION1');
      expect(policy.decide(frame(gridConMarca(3))).action).toBe('ACTION4');
    });

    it('el reasoning del step declara que la accion vino de la memoria (auditabilidad)', () => {
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s2'),
        memorySeed: seed({ plans: [{ actions: ['ACTION2', 'ACTION3'], validatedByRuns: 2 }] }),
      });
      const decision = policy.decide(frame(gridConMarca(1)));
      expect(decision.reasoning).toContain('Memoria de actividad');
      expect(decision.reasoning).toContain('1/2');
    });

    it('elige el plan MAS CORTO (primero del array, ya ordenado por buildSeedFromDoc)', () => {
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s3'),
        memorySeed: seed({
          plans: [
            { actions: ['ACTION4'], validatedByRuns: 1 },
            { actions: ['ACTION1', 'ACTION2', 'ACTION3'], validatedByRuns: 9 },
          ],
        }),
      });
      expect(policy.seedSummary().planLength).toBe(1);
      expect(policy.decide(frame(gridConMarca(1))).action).toBe('ACTION4');
    });

    it('filtra el RESET del plan -- gameRunner ya hizo uno y repetirlo vuelve al inicio', () => {
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s4'),
        memorySeed: seed({
          plans: [{ actions: ['RESET', 'ACTION2', 'ACTION3'], validatedByRuns: 1 }],
        }),
      });
      expect(policy.seedSummary().planLength).toBe(2);
      expect(policy.decide(frame(gridConMarca(1))).action).toBe('ACTION2');
    });

    it('agotado el plan cae a exploracion, sin quedarse sin accion', () => {
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s5'),
        memorySeed: seed({ plans: [{ actions: ['ACTION2'], validatedByRuns: 1 }] }),
      });
      expect(policy.decide(frame(gridConMarca(1))).action).toBe('ACTION2');
      const siguiente = policy.decide(frame(gridConMarca(2)));
      expect(['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4']).toContain(siguiente.action);
      expect(siguiente.reasoning).not.toContain('Memoria de actividad');
    });

    it('ACTION6 del plan sigue recibiendo coordenadas x,y', () => {
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s6'),
        memorySeed: seed({ plans: [{ actions: ['ACTION6'], validatedByRuns: 1 }] }),
      });
      const decision = policy.decide(frame(gridConMarca(1), [1, 6]));
      expect(decision.action).toBe('ACTION6');
      expect(decision.x).toBeGreaterThanOrEqual(0);
      expect(decision.y).toBeGreaterThanOrEqual(0);
    });
  });

  describe('guardas de divergencia -- abandonar un plan que ya no aplica', () => {
    it('abandona si la accion siguiente del plan no esta disponible', () => {
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s7'),
        memorySeed: seed({ plans: [{ actions: ['ACTION4', 'ACTION1'], validatedByRuns: 1 }] }),
      });

      // ACTION4 no esta entre las disponibles -> divergencia inequivoca.
      const decision = policy.decide(frame(gridConMarca(1), [1, 2]));
      expect(decision.action).not.toBe('ACTION4');
      expect(decision.reasoning).not.toContain('Memoria de actividad');

      // Y no se retoma despues: el plan quedo abandonado, no pausado.
      const siguiente = policy.decide(frame(gridConMarca(2)));
      expect(siguiente.reasoning).not.toContain('Memoria de actividad');
    });

    it('abandona si una accion del plan no cambia nada (el mundo diverge del plan)', () => {
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s8'),
        memorySeed: seed({
          plans: [{ actions: ['ACTION1', 'ACTION2', 'ACTION3'], validatedByRuns: 1 }],
        }),
      });

      const estable = gridConMarca(1);
      expect(policy.decide(frame(estable)).action).toBe('ACTION1');
      // MISMA grilla: ACTION1 no produjo efecto -> el plan ya no describe este mundo.
      const decision = policy.decide(frame(estable));
      expect(decision.reasoning).not.toContain('Memoria de actividad');
    });

    it('un RESET a mitad del plan lo abandona (el prefijo consumido dejo de valer)', () => {
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s9'),
        memorySeed: seed({
          plans: [{ actions: ['ACTION1', 'ACTION2', 'ACTION3'], validatedByRuns: 1 }],
        }),
      });

      expect(policy.decide(frame(gridConMarca(1))).action).toBe('ACTION1');
      expect(policy.decide({ ...frame(gridConMarca(2)), state: 'NOT_STARTED' }).action).toBe(
        'RESET',
      );
      const trasReset = policy.decide(frame(gridConMarca(3)));
      expect(trasReset.reasoning).not.toContain('Memoria de actividad');
    });
  });

  describe('filtro de no-ops confirmados', () => {
    it('no elige una accion confirmada inutil en ESA firma de estado', () => {
      const grid = gridConMarca(7);
      const firma = firmaDe(grid);
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s10'),
        memorySeed: seed({
          nonOps: [
            { fromStateSignature: firma, action: 'ACTION1' },
            { fromStateSignature: firma, action: 'ACTION2' },
            { fromStateSignature: firma, action: 'ACTION3' },
          ],
        }),
      });

      // De 4 disponibles, 3 son no-ops conocidos -> queda ACTION4.
      expect(policy.decide(frame(grid)).action).toBe('ACTION4');
    });

    it('el filtro es POR estado: la misma accion sigue disponible en otra firma', () => {
      const gridA = gridConMarca(7);
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s11'),
        memorySeed: seed({
          nonOps: [
            { fromStateSignature: firmaDe(gridA), action: 'ACTION1' },
            { fromStateSignature: firmaDe(gridA), action: 'ACTION2' },
            { fromStateSignature: firmaDe(gridA), action: 'ACTION3' },
          ],
        }),
      });

      // Otra grilla -> otra firma -> el filtro no aplica y puede volver a elegir cualquiera.
      const elegidas = new Set<string>();
      for (let i = 0; i < 12; i++) {
        elegidas.add(policy.decide(frame(gridConMarca(i % 5))).action);
      }
      expect(elegidas.size).toBeGreaterThan(1);
    });

    it('NUNCA deja al agente sin acciones: si todas son no-ops, no filtra ninguna', () => {
      const grid = gridConMarca(7);
      const firma = firmaDe(grid);
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s12'),
        memorySeed: seed({
          nonOps: ACCIONES.map((n) => ({ fromStateSignature: firma, action: `ACTION${n}` })),
        }),
      });

      const decision = policy.decide(frame(grid));
      expect(['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4']).toContain(decision.action);
    });
  });

  describe('evasion de ciclos con transiciones sembradas', () => {
    it('evita la accion que devuelve a un estado ya visitado este episodio', () => {
      const gridA = gridConMarca(1);
      const gridB = gridConMarca(2);
      const firmaA = firmaDe(gridA);
      const firmaB = firmaDe(gridB);

      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s13'),
        memorySeed: seed({
          transitions: [
            // Desde B, tres de las cuatro acciones vuelven a A (ciclo). Solo ACTION4 avanza.
            { fromStateSignature: firmaB, action: 'ACTION1', toStateSignature: firmaA },
            { fromStateSignature: firmaB, action: 'ACTION2', toStateSignature: firmaA },
            { fromStateSignature: firmaB, action: 'ACTION3', toStateSignature: firmaA },
          ],
        }),
      });

      policy.decide(frame(gridA)); // visita A
      expect(policy.decide(frame(gridB)).action).toBe('ACTION4');
    });

    it('si TODAS las acciones ciclan, no filtra -- mejor una accion dudosa que ninguna', () => {
      const gridA = gridConMarca(1);
      const gridB = gridConMarca(2);
      const firmaA = firmaDe(gridA);
      const firmaB = firmaDe(gridB);

      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s14'),
        memorySeed: seed({
          transitions: ACCIONES.map((n) => ({
            fromStateSignature: firmaB,
            action: `ACTION${n}`,
            toStateSignature: firmaA,
          })),
        }),
      });

      policy.decide(frame(gridA));
      const decision = policy.decide(frame(gridB));
      expect(['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4']).toContain(decision.action);
    });
  });

  describe('degradacion sin memoria', () => {
    it('sin semilla se comporta como antes de BL.20861 (arranque frio, cero regresion)', () => {
      const policy = new IntelligentPolicy({ rng: createSeededRandom('s15') });
      expect(policy.seedSummary()).toEqual({ nonOpStates: 0, transitions: 0, planLength: 0 });
      expect(['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4']).toContain(
        policy.decide(frame(gridConMarca(1))).action,
      );
    });

    it('una semilla fria es equivalente a no tener semilla', () => {
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s16'),
        memorySeed: { activityId: 'g1', nonOps: [], plans: [], transitions: [], isCold: true },
      });
      expect(policy.seedSummary()).toEqual({ nonOpStates: 0, transitions: 0, planLength: 0 });
    });

    it('seedSummary reporta lo que la politica realmente sabe antes de la primera accion', () => {
      const policy = new IntelligentPolicy({
        rng: createSeededRandom('s17'),
        memorySeed: seed({
          nonOps: [
            { fromStateSignature: 'a', action: 'ACTION1' },
            { fromStateSignature: 'a', action: 'ACTION2' },
            { fromStateSignature: 'b', action: 'ACTION1' },
          ],
          transitions: [{ fromStateSignature: 'a', action: 'ACTION1', toStateSignature: 'b' }],
          plans: [{ actions: ['ACTION1', 'ACTION2'], validatedByRuns: 1 }],
        }),
      });
      // 2 firmas distintas con no-ops (no 3 entradas), 1 transicion, plan de 2.
      expect(policy.seedSummary()).toEqual({ nonOpStates: 2, transitions: 1, planLength: 2 });
    });
  });
});
