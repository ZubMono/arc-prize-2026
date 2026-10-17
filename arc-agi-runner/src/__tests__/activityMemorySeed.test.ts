/* [arc-agi-runner/__tests__/activityMemorySeed] BL.20861 -- filtrado de la semilla: que entra, que
   se descarta y en que orden. El criterio de fondo es asimetrico a proposito: NO sembrar cuesta
   una corrida ineficiente; sembrar basura cuesta que el agente evite lo que si funciona. */

import { describe, expect, it } from 'vitest';

import { buildSeedFromDoc, coldSeed, type ActivityMemoryDocLike } from '../activityMemorySeed';

function doc(overrides: Partial<ActivityMemoryDocLike> = {}): ActivityMemoryDocLike {
  return { activityId: 'juego-1', ...overrides };
}

describe('buildSeedFromDoc', () => {
  it('doc inexistente devuelve semilla fria en vez de lanzar (corrida 1 es el caso NORMAL)', () => {
    expect(buildSeedFromDoc(null, 'juego-x')).toEqual(coldSeed('juego-x'));
    expect(buildSeedFromDoc(null, 'juego-x').isCold).toBe(true);
  });

  it('un doc vacio tambien es arranque frio -- isCold refleja utilidad, no existencia', () => {
    expect(buildSeedFromDoc(doc(), 'juego-1').isCold).toBe(true);
  });

  // BL.21499 -- justamente PORQUE isCold refleja utilidad y no existencia, hace falta un segundo
  // campo para separar los dos casos. Sin el, "primera corrida" y "el destilador nunca proceso
  // esta actividad" se ven identicos desde afuera: eso fue lo que oculto una semana que el ciclo
  // de aprendizaje jamas corrio sobre ARC (7 partidas, todas reportadas como "en frio").
  it('BL.21499: distingue "nunca jugado" de "jugado pero sin memoria utilizable"', () => {
    const nuncaJugado = buildSeedFromDoc(null, 'juego-x');
    const jugadoSinMemoria = buildSeedFromDoc(doc(), 'juego-1');

    // Los dos son frios -- esa es justamente la ambiguedad que motivo el campo.
    expect(nuncaJugado.isCold).toBe(true);
    expect(jugadoSinMemoria.isCold).toBe(true);

    // Pero ahora son distinguibles.
    expect(nuncaJugado.sinDocumento).toBe(true);
    expect(jugadoSinMemoria.sinDocumento).toBe(false);
  });

  it('BL.21499: un doc CON contenido utilizable tampoco es "sin documento"', () => {
    const seed = buildSeedFromDoc(
      doc({ successfulPlans: [{ actions: ['ACTION1'], evaluationRefs: ['r1'] }] }),
      'juego-1',
    );
    expect(seed.isCold).toBe(false);
    expect(seed.sinDocumento).toBe(false);
  });

  it('descarta el no-op observado UNA sola vez (podria ser ruido del entorno)', () => {
    const seed = buildSeedFromDoc(
      doc({
        nonOpActions: [
          { fromStateSignature: 's1', action: 'ACTION1', confirmedCount: 1 },
          { fromStateSignature: 's1', action: 'ACTION2', confirmedCount: 2 },
        ],
      }),
      'juego-1',
    );
    expect(seed.nonOps).toEqual([{ fromStateSignature: 's1', action: 'ACTION2' }]);
  });

  it('descarta la transicion sin evidencia positiva neta (Beta(1,1) = 0.5 < 0.6)', () => {
    const seed = buildSeedFromDoc(
      doc({
        knownTransitions: [
          // 1 exito / 1 fracaso -> media 0.5, por debajo del umbral.
          {
            fromStateSignature: 's1',
            action: 'ACTION1',
            toStateSignature: 's2',
            confidence: { successes: 1, failures: 1 },
          },
          // 4 exitos / 0 fracasos -> media 5/6 = 0.83.
          {
            fromStateSignature: 's1',
            action: 'ACTION3',
            toStateSignature: 's4',
            confidence: { successes: 4, failures: 0 },
          },
        ],
      }),
      'juego-1',
    );
    expect(seed.transitions).toEqual([
      { fromStateSignature: 's1', action: 'ACTION3', toStateSignature: 's4' },
    ]);
  });

  it('ordena planes por largo ASC -- el score de ARC penaliza cada accion de mas cuadraticamente', () => {
    const seed = buildSeedFromDoc(
      doc({
        successfulPlans: [
          { actions: ['ACTION1', 'ACTION2', 'ACTION3'], evaluationRefs: [{ runId: 'r1' }] },
          { actions: ['ACTION5'], evaluationRefs: [{ runId: 'r2' }] },
          { actions: ['ACTION1', 'ACTION4'], evaluationRefs: [{ runId: 'r3' }] },
        ],
      }),
      'juego-1',
    );
    expect(seed.plans.map((p) => p.actions.length)).toEqual([1, 2, 3]);
  });

  it('a igual largo desempata el mas validado -- pero el largo manda por sobre las validaciones', () => {
    const seed = buildSeedFromDoc(
      doc({
        successfulPlans: [
          // Mas corto pero validado UNA vez: gana igual.
          { actions: ['ACTION9'], evaluationRefs: [{ runId: 'r1' }] },
          // Mas largo y validado 3 veces.
          {
            actions: ['ACTION1', 'ACTION2'],
            evaluationRefs: [{ runId: 'a' }, { runId: 'b' }, { runId: 'c' }],
          },
          { actions: ['ACTION7', 'ACTION8'], evaluationRefs: [{ runId: 'd' }] },
        ],
      }),
      'juego-1',
    );
    expect(seed.plans[0].actions).toEqual(['ACTION9']);
    // A igual largo (2), primero el de 3 validaciones.
    expect(seed.plans[1].validatedByRuns).toBe(3);
    expect(seed.plans[2].validatedByRuns).toBe(1);
  });

  it('descarta el plan vacio -- sembrarlo haria creer que hay conocimiento donde no lo hay', () => {
    const seed = buildSeedFromDoc(
      doc({ successfulPlans: [{ actions: [], evaluationRefs: [{ runId: 'r1' }] }] }),
      'juego-1',
    );
    expect(seed.plans).toEqual([]);
    expect(seed.isCold).toBe(true);
  });

  it('tolera arrays ausentes en el doc (schema viejo) sin lanzar', () => {
    expect(() => buildSeedFromDoc({ activityId: 'juego-1' }, 'juego-1')).not.toThrow();
  });

  it('usa el activityId del doc, no el pedido -- el doc es la fuente de verdad de su propia clave', () => {
    const seed = buildSeedFromDoc(doc({ activityId: 'real' }), 'pedido');
    expect(seed.activityId).toBe('real');
  });
});
