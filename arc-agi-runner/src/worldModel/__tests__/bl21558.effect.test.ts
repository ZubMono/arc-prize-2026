/* [arc-agi-runner/worldModel/bl21558.effect.test] BL.21558 -- TESTS DE EFECTO, no de humo.

   Leccion explicita de BL.21500, que este archivo existe para no repetir: aquel fix "pasaba los
   tests" y tuvo efecto CERO sobre 400 selecciones reales, porque los tests verificaban que la
   funcion no explotara en vez de verificar que la accion volviera a elegirse. Aca cada `it` mide
   una MAGNITUD OBSERVABLE del comportamiento -- cuantos no-ops se detectan, cuantas firmas se
   repiten, cuantas veces sale elegida una accion -- y compara contra lo que daba el codigo viejo
   sobre EXACTAMENTE la misma trayectoria.

   El entorno es `SyntheticGridEnv` con `hud: true`: una fila extra con dos contadores que avanzan
   en CADA paso pase lo que pase. Reproduce la patologia medida en `prometheusEvaluationRuns`
   (ar25-0c556536 = 76 firmas unicas / 78 pasos; lf52-271a04aa = 94/94; dc22-fdcac232 = 128/129;
   ka59 = 100/101) sin depender de la API de ARC ni de Mongo. */
import { describe, expect, it } from 'vitest';

import { SyntheticGridEnv } from '../../__tests__/support/syntheticGridEnv';
import { createSeededRandom } from '../../prng';
import type { ArcAction, ArcFrameResponse } from '../../types';
import { selectExploratoryAction } from '../activeLearning';
import type { Grid } from '../grid';
import { IntelligentPolicy } from '../intelligentPolicy';
import { computeStateSignature, extractGrid, isNoOpTransition } from '../stateSignature';
import { synthesizeProgram } from '../synthesis';
import { TransitionMemory } from '../transitionMemory';

const PASOS = 80;

interface PasoObservado {
  action: string;
  pre: Grid;
  post: Grid;
  availableActions: number[];
}

/** Juega un episodio completo con la politica real y devuelve la trayectoria cruda. La MISMA
 *  trayectoria se mide despues con mascara y sin mascara: si se compararan dos corridas distintas,
 *  la diferencia podria venir del azar y no del fix. */
function jugarEpisodio(seed: string): {
  pasos: PasoObservado[];
  policy: IntelligentPolicy;
  posiciones: Set<string>;
} {
  const env = new SyntheticGridEnv({
    start: { x: 2, y: 2 },
    target: { x: 4, y: 4 },
    hud: true,
    endless: true,
  });
  const policy = new IntelligentPolicy({ rng: createSeededRandom(seed), actionBudget: PASOS });
  const pasos: PasoObservado[] = [];
  const posiciones = new Set<string>();

  let frame: ArcFrameResponse = env.reset();
  for (let i = 0; i < PASOS; i++) {
    const pre = extractGrid(frame)!;
    const availableActions = [...frame.available_actions];
    const decision = policy.decide(frame);
    frame = env.step(decision.action as ArcAction);
    pasos.push({ action: decision.action, pre, post: extractGrid(frame)!, availableActions });
    const { x, y } = env.markerPosition;
    posiciones.add(`${x},${y}`);
  }
  return { pasos, policy, posiciones };
}

/** BL.21561 -- techo EXPLICITO para los cuatro tests que juegan un episodio entero (80 pasos con
 *  sintesis DSL en cada uno). El `testTimeout: 30_000` global de vitest.config.ts los dejaba a
 *  centimetros: medidos en este host, 22-28s en reposo, asi que bajo la carga de 7 agentes
 *  paralelos se pasaban y ponian rojo el gate de push de CUALQUIERA que estuviera aterrizando otro
 *  BL -- que es exactamente el fallo que el comentario de vitest.config.ts describe. El episodio no
 *  se abarata sin dejar de medir lo que mide (la mascara necesita decenas de pasos para converger),
 *  asi que lo correcto es declarar que estos cuatro son caros, no bajar la evidencia. */
const TIMEOUT_EPISODIO_COMPLETO_MS = 180_000;

describe('BL.21558 (A) -- mascara de volatilidad: efecto medido sobre una partida completa', () => {
  it('resucita la deteccion de no-ops: 0 sin mascara, decenas con mascara', () => {
    const { pasos, policy } = jugarEpisodio('bl21558-noops');
    const mask = policy.volatilityMask();
    expect(mask).not.toBeNull();

    const sinMascara = pasos.filter((p) => isNoOpTransition(p.pre, p.post, null)).length;
    const conMascara = pasos.filter((p) => isNoOpTransition(p.pre, p.post, mask)).length;

    // eslint-disable-next-line no-console -- magnitud medida del fix, se quiere ver en el reporter
    console.log(
      `[BL.21558] no-ops detectados en ${PASOS} pasos -- sin mascara: ${sinMascara}, con mascara: ${conMascara}`,
    );

    // El contador del HUD avanza en TODOS los pasos: sin mascara ni un solo no-op es detectable,
    // exactamente lo medido en juego real (1 de 77 en ar25 pese al round-robin contra paredes).
    expect(sinMascara).toBe(0);
    // Con mascara aparecen los choques contra la pared y la accion inerte del entorno.
    expect(conMascara).toBeGreaterThan(10);
  }, TIMEOUT_EPISODIO_COMPLETO_MS);

  it('las firmas de estado vuelven a repetirse: 80 unicas sin mascara, <= posiciones reales con ella', () => {
    const { pasos, policy, posiciones } = jugarEpisodio('bl21558-firmas');
    const mask = policy.volatilityMask();

    const sinMascara = new Set(
      pasos.map((p) => computeStateSignature(p.post, p.availableActions, null)),
    );
    const conMascara = new Set(
      pasos.map((p) => computeStateSignature(p.post, p.availableActions, mask)),
    );

    // eslint-disable-next-line no-console -- magnitud medida del fix
    console.log(
      `[BL.21558] firmas unicas en ${PASOS} pasos -- sin mascara: ${sinMascara.size}, ` +
        `con mascara: ${conMascara.size} (posiciones distintas del marcador: ${posiciones.size})`,
    );

    // La patologia: una firma nueva por paso, igual que los 150/153 destilados de ar25.
    expect(sinMascara.size).toBe(PASOS);
    // Con mascara, la firma vuelve a describir el ESTADO: no puede haber mas firmas que estados
    // distintos del tablero, y por lo tanto la memoria por-estado vuelve a poder disparar.
    expect(conMascara.size).toBeLessThanOrEqual(posiciones.size);
    expect(conMascara.size).toBeLessThan(PASOS / 2);
  }, TIMEOUT_EPISODIO_COMPLETO_MS);

  it('resucita la sintesis de identidad: null sobre el par crudo, programa vacio sobre el enmascarado', () => {
    const { pasos } = jugarEpisodio('bl21558-sintesis');
    const inertes = pasos.filter((p) => p.action === 'ACTION5');
    expect(inertes.length).toBeGreaterThan(2);

    // Sobre el par CRUDO la sintesis no puede explicar nada: tendria que reproducir tambien el
    // contador del HUD, que ningun programa del DSL de tablero puede generar.
    const crudo = synthesizeProgram(
      inertes.slice(0, 3).map((p) => ({ pre: p.pre, post: p.post })),
      {},
      3,
    );
    expect(crudo).toBeNull();

    // El mismo flujo de observaciones a traves de TransitionMemory (que aprende la mascara y
    // sintetiza sobre el diff enmascarado) concluye la identidad y la puede afirmar como no-op.
    const memory = new TransitionMemory();
    for (const paso of pasos) memory.recordObservation(paso.action, paso.pre, paso.post);
    const inerte = memory.getTransition('ACTION5');
    expect(inerte?.program).toEqual([]);
    expect(memory.isKnownNoOp('ACTION5')).toBe(true);
    expect(memory.getVolatileCellCount()).toBe(2); // exactamente las dos celdas del contador
  }, TIMEOUT_EPISODIO_COMPLETO_MS);

  it('ninguna accion queda congelada: las 5 se siguen usando a lo largo del episodio', () => {
    const { pasos } = jugarEpisodio('bl21558-distribucion');
    const conteo = new Map<string, number>();
    for (const paso of pasos) conteo.set(paso.action, (conteo.get(paso.action) ?? 0) + 1);

    // eslint-disable-next-line no-console -- magnitud medida del fix
    console.log(
      `[BL.21558] acciones emitidas en ${PASOS} pasos: ${JSON.stringify([...conteo.entries()].sort())}`,
    );

    // El defecto que se arregla es exactamente este numero: en juego real ACTION6 aparecia 1 vez
    // en 78/101/129 pasos. Y al destrabar la sintesis aparece el riesgo simetrico -- la accion
    // cuya regla SI se confirma pasaria al grupo de "ya aprendida" y dejaria de usarse (medido:
    // 1 de 80 antes de repartir el turno de reconsideracion, ver activeLearning.ts).
    for (const accion of ['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4', 'ACTION5']) {
      expect(conteo.get(accion) ?? 0, `${accion} quedo congelada`).toBeGreaterThan(2);
    }
  }, TIMEOUT_EPISODIO_COMPLETO_MS);

  it('una hipotesis sintetizada ANTES de la mascara se rehace cuando la mascara aparece', () => {
    /* La mascara es una PREMISA de la hipotesis. Este test fija el escenario que rompio la primera
       version del fix: la accion inerte se observa antes de que haya evidencia para enmascarar, la
       sintesis encuentra un programa no trivial que "explica" el avance del contador, y ese
       programa la relega para siempre porque la accion no vuelve a observarse. */
    const memory = new TransitionMemory();
    const tablero = [
      [0, 0],
      [0, 5],
    ];
    const conHud = (c: number): Grid => [...tablero.map((f) => [...f]), [c % 11, c % 13]];

    // Observacion 1 de la accion inerte: el tablero no cambia, el HUD si. Sin mascara todavia.
    memory.recordObservation('INERTE', conHud(0), conHud(1));
    expect(memory.getVolatilityMask()).toBeNull();
    const hipotesisPrevia = memory.getTransition('INERTE')?.program;

    // Evidencia de otras acciones hasta que la mascara se forma. La accion inerte NO se vuelve a
    // observar en todo el tramo -- justo el caso que dejaba la hipotesis vieja congelada.
    for (let i = 1; i <= 12; i++) {
      memory.recordObservation(i % 2 === 0 ? 'OTRA_A' : 'OTRA_B', conHud(i), conHud(i + 1));
    }
    expect(memory.getVolatilityMask()).not.toBeNull();

    // Sin re-sintesis, `INERTE` seguiria con la hipotesis deducida bajo las premisas viejas.
    expect(memory.getTransition('INERTE')?.program).toEqual([]);
    expect(hipotesisPrevia).not.toEqual([]);
  });

  it('sin HUD la mascara no se activa y nada cambia respecto de BL.20860', () => {
    const env = new SyntheticGridEnv({ start: { x: 2, y: 2 }, target: { x: 4, y: 4 } });
    const policy = new IntelligentPolicy({
      rng: createSeededRandom('bl21558-sin-hud'),
      actionBudget: PASOS,
    });
    let frame = env.reset();
    for (let i = 0; i < 30 && frame.state !== 'WIN'; i++) {
      const decision = policy.decide(frame);
      frame = decision.action === 'RESET' ? env.reset() : env.step(decision.action as ArcAction);
    }
    expect(policy.volatilityMask()).toBeNull();
  });
});

describe('BL.21558 (B) -- identidad != regla confirmada: la accion no-op vuelve al ciclo', () => {
  /* Reconstruccion EXACTA del escenario medido: ninguna accion llega nunca a confirmar un
     programa (todas quedan en `program === null`, rango 0) salvo la que tuvo un no-op en su PRIMERA
     observacion, que con el codigo viejo pasaba a rango 1 y quedaba ultima en el sort para siempre.
     Verificado en datos reales: ACTION6 aparece EXACTAMENTE 1 vez en ar25 (78 pasos), ka59 (101),
     dc22 (129) y cd82 (101) -- incluida una corrida posterior a BL.21500. */
  function memoriaDelEscenarioMedido(): TransitionMemory {
    const memory = new TransitionMemory();
    // ACTION1..ACTION5: pares sin explicacion consistente -> program null (rango 0). Dos
    // observaciones cada una, para que ACTION6 sea ademas la MENOS observada.
    for (const accion of ['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4', 'ACTION5']) {
      memory.recordObservation(accion, [[1, 1]], [[9, 8]]);
      memory.recordObservation(accion, [[2, 2]], [[3, 7]]);
      expect(memory.getTransition(accion)?.program).toBeNull();
    }
    // ACTION6 (el click): su primera observacion cae sobre una celda vacia y no cambia nada.
    memory.recordObservation('ACTION6', [[0, 0]], [[0, 0]]);
    expect(memory.getTransition('ACTION6')?.program).toEqual([]); // identidad, NO null
    return memory;
  }

  it('la accion con identidad en su primera observacion es la SIGUIENTE elegida, no la ultima', () => {
    const memory = memoriaDelEscenarioMedido();
    const disponibles = ['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4', 'ACTION5', 'ACTION6'];
    const rng = createSeededRandom('bl21558-primera-eleccion');

    // Rango 0 para todas (ninguna tiene regla NO trivial) y ACTION6 es la menos observada -> el
    // sort la pone primera SIEMPRE. Con el codigo viejo su rango era 1 y salia ultima siempre.
    let veces = 0;
    for (let i = 0; i < 200; i++) {
      if (selectExploratoryAction(disponibles, memory, rng) === 'ACTION6') veces++;
    }
    // eslint-disable-next-line no-console -- magnitud medida del fix
    console.log(`[BL.21558] ACTION6 elegida ${veces}/200 veces (codigo viejo: 0/200)`);
    expect(veces).toBe(200);
  });

  it('con las observaciones empatadas sigue siendo elegible -- no queda relegada por ser identidad', () => {
    const memory = new TransitionMemory();
    memory.recordObservation('ACTION1', [[1, 1]], [[9, 8]]); // program null, 1 observacion
    memory.recordObservation('ACTION6', [[0, 0]], [[0, 0]]); // identidad, 1 observacion
    const rng = createSeededRandom('bl21558-empate');

    let veces = 0;
    for (let i = 0; i < 400; i++) {
      if (selectExploratoryAction(['ACTION1', 'ACTION6'], memory, rng) === 'ACTION6') veces++;
    }
    // Empatan en rango y en observaciones: el barajado reproducible reparte ~50/50. Lo que se
    // afirma es que NO esta relegada -- con el codigo viejo este numero era exactamente 0.
    expect(veces).toBeGreaterThan(120);
    expect(veces).toBeLessThan(280);
  });

  it('el filtro de no-ops SIGUE existiendo: con 3 observaciones la accion se excluye igual', () => {
    // El fix no desactiva la exclusion de no-ops confirmados (eso seria cambiar un extremo por el
    // otro): solo deja de disparar con UNA observacion.
    const memory = new TransitionMemory();
    memory.recordObservation('ACTION1', [[1, 1]], [[9, 8]]);
    for (let i = 0; i < 3; i++) memory.recordObservation('ACTION6', [[0, 0]], [[0, 0]]);
    expect(memory.isKnownNoOp('ACTION6')).toBe(true);

    const rng = createSeededRandom('bl21558-filtro-vive');
    let veces = 0;
    for (let i = 0; i < 400; i++) {
      if (selectExploratoryAction(['ACTION1', 'ACTION6'], memory, rng) === 'ACTION6') veces++;
    }
    expect(veces).toBeLessThan(400 * 0.2); // solo el epsilon de reexploracion de BL.21500
  });
});
