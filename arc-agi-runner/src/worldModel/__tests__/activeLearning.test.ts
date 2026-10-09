/* [arc-agi-runner/worldModel/activeLearning.test] BL.20860 -- seleccion de la proxima accion a
   PROBAR maximizando informacion sobre reglas aun no confirmadas del modelo de mundo. Idea de
   "menos visitado primero" + exclusion de no-ops conocidos tomada de
   arc-agi3-kaggle-agent/arc_agent/policy.py::rank_candidates (BL.20783), reencuadrada como
   active learning (prioriza incertidumbre del modelo, no solo frecuencia de visita). */
import { describe, expect, it } from 'vitest';

import { createSeededRandom } from '../../prng';
import { selectExploratoryAction } from '../activeLearning';
import { TransitionMemory } from '../transitionMemory';

describe('selectExploratoryAction', () => {
  it('prioriza acciones SIN programa confirmado sobre acciones ya confirmadas', () => {
    const memory = new TransitionMemory();
    memory.recordObservation('ACTION1', [[1]], [[9]]); // confirma recolor 1->9
    const rng = createSeededRandom('s1');
    const choice = selectExploratoryAction(['ACTION1', 'ACTION2'], memory, rng);
    expect(choice).toBe('ACTION2'); // ACTION2 nunca se probo -- maxima incertidumbre
  });

  // BL.21500: hacen falta 3 observaciones (MIN_OBSERVATIONS_FOR_NOOP), no 2. Cambio deliberado:
  // antes bastaba UNA para retirar la accion de la exploracion para siempre.
  it('excluye no-ops conocidos salvo que sean la unica opcion disponible', () => {
    const memory = new TransitionMemory();
    memory.recordObservation('ACTION1', [[1]], [[1]]);
    memory.recordObservation('ACTION1', [[2]], [[2]]);
    memory.recordObservation('ACTION1', [[3]], [[3]]); // 3ra observacion -> recien aca es no-op
    const rng = createSeededRandom('s2');
    const choice = selectExploratoryAction(['ACTION1', 'ACTION2'], memory, rng);
    expect(choice).toBe('ACTION2');
  });

  it('si TODAS son no-ops conocidos, igual devuelve una (nunca se queda sin candidatos)', () => {
    const memory = new TransitionMemory();
    memory.recordObservation('ACTION1', [[1]], [[1]]);
    memory.recordObservation('ACTION1', [[2]], [[2]]);
    memory.recordObservation('ACTION1', [[3]], [[3]]);
    const rng = createSeededRandom('s3');
    const choice = selectExploratoryAction(['ACTION1'], memory, rng);
    expect(choice).toBe('ACTION1');
  });

  it('entre acciones igualmente inciertas, prefiere la menos observada', () => {
    const memory = new TransitionMemory();
    // ACTION1 se probo una vez sin llegar a confirmar programa (par ambiguo/contradictorio)
    memory.recordObservation('ACTION1', [[1, 1]], [[9, 8]]); // sin mapping consistente -> program null
    const rng = createSeededRandom('s4');
    const choice = selectExploratoryAction(['ACTION1', 'ACTION2'], memory, rng);
    expect(choice).toBe('ACTION2'); // ACTION2 con 0 observaciones vs ACTION1 con 1
  });

  it('es deterministico dado el mismo seed', () => {
    const memory = new TransitionMemory();
    const rngA = createSeededRandom('determinismo');
    const rngB = createSeededRandom('determinismo');
    const seqA = Array.from({ length: 10 }, () =>
      selectExploratoryAction(['ACTION1', 'ACTION2', 'ACTION3'], memory, rngA),
    );
    const seqB = Array.from({ length: 10 }, () =>
      selectExploratoryAction(['ACTION1', 'ACTION2', 'ACTION3'], memory, rngB),
    );
    expect(seqA).toEqual(seqB);
  });

  // ── BL.21500 — el lockout de ACTION6 ───────────────────────────────────────────────────────
  // Regresion del defecto medido en juego real (ar25-0c556536, 2026-08-16): ACTION6 (el click)
  // se probo UNA vez en el paso 2, la sintesis concluyo identidad con esa unica observacion, y
  // la accion quedo excluida los 76 pasos restantes de la partida.

  it('BL.21500: una accion observada UNA sola vez como no-op SIGUE siendo elegible', () => {
    const memory = new TransitionMemory();
    // ACTION6 (click) sobre una celda vacia: no cambia nada. Una sola observacion.
    memory.recordObservation('ACTION6', [[0]], [[0]]);

    // Con el codigo viejo isKnownNoOp ya daba true aca y ACTION6 quedaba fuera para siempre.
    expect(memory.isKnownNoOp('ACTION6')).toBe(false);

    // Y sigue en el conjunto de candidatos: sobre muchas decisiones tiene que salir elegida.
    // Se mide asi y no con una sola llamada a proposito: ACTION6 y ACTION1 empatan en rango de
    // incertidumbre y en observaciones, con lo cual una unica decision la define el barajado y
    // el test seria una moneda al aire.
    memory.recordObservation('ACTION1', [[1]], [[9]]); // confirma programa (no es no-op)
    const rng = createSeededRandom('bl21500-una-obs');
    const elegidas = new Set(
      Array.from({ length: 50 }, () =>
        selectExploratoryAction(['ACTION6', 'ACTION1'], memory, rng),
      ),
    );
    expect(elegidas.has('ACTION6')).toBe(true);
  });

  it('BL.21500: tras 3 observaciones no-op si se la excluye (el filtro sigue existiendo)', () => {
    const memory = new TransitionMemory();
    memory.recordObservation('ACTION6', [[0]], [[0]]);
    expect(memory.isKnownNoOp('ACTION6')).toBe(false);
    memory.recordObservation('ACTION6', [[0]], [[0]]);
    expect(memory.isKnownNoOp('ACTION6')).toBe(false);
    memory.recordObservation('ACTION6', [[0]], [[0]]);
    expect(memory.isKnownNoOp('ACTION6')).toBe(true); // recien con la 3ra
  });

  it('BL.21500: el descarte NO es absorbente -- el epsilon reconsidera los no-ops', () => {
    const memory = new TransitionMemory();
    for (let i = 0; i < 3; i++) memory.recordObservation('ACTION6', [[0]], [[0]]);
    expect(memory.isKnownNoOp('ACTION6')).toBe(true);
    memory.recordObservation('ACTION1', [[1]], [[9]]); // confirmada, no no-op

    // Sobre muchas decisiones, ACTION6 tiene que volver a aparecer alguna vez. Sin el epsilon
    // (codigo viejo) el conteo seria exactamente 0, porque una accion excluida nunca se vuelve
    // a observar y por lo tanto nunca puede salir del conjunto de no-ops.
    const rng = createSeededRandom('bl21500-epsilon');
    let vecesACTION6 = 0;
    for (let i = 0; i < 400; i++) {
      if (selectExploratoryAction(['ACTION6', 'ACTION1'], memory, rng) === 'ACTION6')
        vecesACTION6++;
    }
    expect(vecesACTION6).toBeGreaterThan(0);
    // Pero sigue siendo la excepcion, no la regla: el filtro no quedo desactivado de hecho.
    expect(vecesACTION6).toBeLessThan(400 * 0.2);
  });

  it('lanza si no hay ninguna accion disponible -- invariante del llamador', () => {
    const memory = new TransitionMemory();
    const rng = createSeededRandom('s5');
    expect(() => selectExploratoryAction([], memory, rng)).toThrow();
  });
});
