/* [arc-agi-runner/worldModel/bl21558.progressBar.effect.test] BL.21558 -- la cadena completa del
   modelo de mundo (memoria -> tracker -> sintesis) contra la forma REAL del ruido de ARC-AGI-3.

   `bl21558.effect.test.ts` simula el ruido como un HUD que cambia en cada paso, y con esa forma
   alcanzaba el criterio por frecuencia. Los frames REALES capturados para este BL
   (`__fixtures__/volatilityRealGames.json`) mostraron otra cosa: una BARRA donde se enciende UNA
   celda nueva por paso, con cada celda cambiando una sola vez por vuelta.

   Archivo aparte y no un `describe` mas del otro: los dos son episodios completos con sintesis y
   vitest paraleliza por ARCHIVO, asi que juntos empujaban la suite por encima del presupuesto de 30s
   del gate de push (GATE-01+02-SELECTIVE). */
import { describe, expect, it } from 'vitest';

import { SyntheticGridEnv } from '../../__tests__/support/syntheticGridEnv';
import type { ArcAction, ArcFrameResponse } from '../../types';
import type { Grid } from '../grid';
import { computeStateSignature, extractGrid, isNoOpTransition } from '../stateSignature';
import { TransitionMemory } from '../transitionMemory';

const ALTO = 2;
const ANCHO = 20;
/** El tablero, dos filas de aire (ver `syntheticGridEnv`) y recien ahi la barra. */
const FILA_BARRA = ALTO + 2;
/** Suficientes para que la barra se declare (>= SWEEP_MIN_TRANSITIONS) y para que la accion inerte
 *  acumule las 3 observaciones que pide `isKnownNoOp`. Mas pasos no agregan evidencia y si costo:
 *  cada observacion dispara una sintesis. */
const PASOS = 30;
const ACCIONES: ArcAction[] = ['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4', 'ACTION5'];

interface PasoObservado {
  pre: Grid;
  post: Grid;
  availableActions: number[];
}

/** Round-robin y no la politica: lo que se prueba es la cadena memoria -> tracker -> sintesis
 *  contra la forma real del ruido, y el round-robin garantiza que TODAS las acciones (incluida la
 *  inerte) aporten evidencia. La integracion con la politica la cubre `bl21558.effect.test.ts`, que
 *  recorre exactamente el mismo camino. */
function jugarConBarra(): { pasos: PasoObservado[]; memory: TransitionMemory } {
  const env = new SyntheticGridEnv({
    size: ALTO,
    width: ANCHO,
    start: { x: 2, y: 1 },
    target: { x: 4, y: 1 },
    progressBar: true,
    endless: true,
  });
  const memory = new TransitionMemory();
  const pasos: PasoObservado[] = [];
  let frame: ArcFrameResponse = env.reset();
  for (let i = 0; i < PASOS; i++) {
    const pre = extractGrid(frame) as Grid;
    const availableActions = [...frame.available_actions];
    const accion = ACCIONES[i % ACCIONES.length];
    frame = env.step(accion);
    const post = extractGrid(frame) as Grid;
    memory.recordObservation(accion, pre, post);
    pasos.push({ pre, post, availableActions });
  }
  return { pasos, memory };
}

describe('BL.21558 -- barra de progreso: la forma REAL del ruido de ARC-AGI-3', () => {
  it('el modelo de mundo aprende la barra y vuelve a detectar no-ops y firmas repetidas', () => {
    const { pasos, memory } = jugarConBarra();
    const mask = memory.getVolatilityMask();
    expect(mask).not.toBeNull();

    // Exactamente la fila de la barra, ni una celda del tablero.
    expect((mask as boolean[][])[FILA_BARRA].filter(Boolean).length).toBe(ANCHO);
    for (let y = 0; y < ALTO; y++) {
      expect((mask as boolean[][])[y].some(Boolean), `fila de tablero ${y} enmascarada`).toBe(
        false,
      );
    }

    const noOpsSinMascara = pasos.filter((p) => isNoOpTransition(p.pre, p.post, null)).length;
    const noOpsConMascara = pasos.filter((p) => isNoOpTransition(p.pre, p.post, mask)).length;
    const firmasSinMascara = new Set(
      pasos.map((p) => computeStateSignature(p.post, p.availableActions, null)),
    );
    const firmasConMascara = new Set(
      pasos.map((p) => computeStateSignature(p.post, p.availableActions, mask)),
    );

    // eslint-disable-next-line no-console -- magnitud medida del fix
    console.log(
      `[BL.21558][barra] no-ops ${noOpsSinMascara} -> ${noOpsConMascara}, ` +
        `firmas unicas ${firmasSinMascara.size} -> ${firmasConMascara.size} en ${PASOS} pasos`,
    );

    // La barra avanza pase lo que pase: sin mascara, cero no-ops y una firma nueva por paso --
    // calcado de lf52-271a04aa (0 no-ops y 92 firmas unicas en 92 pasos reales).
    expect(noOpsSinMascara).toBe(0);
    expect(firmasSinMascara.size).toBe(PASOS);
    expect(noOpsConMascara).toBeGreaterThan(3);
    expect(firmasConMascara.size).toBeLessThan(PASOS / 2);

    /* La consecuencia que importa: el modelo de mundo concluye que la accion inerte es la IDENTIDAD
       y la marca como no-op conocido. Con la barra dentro de la comparacion eso era imposible --
       ninguna hipotesis puede explicar el avance de la barra, asi que la accion se quedaba sin
       programa para siempre y el agente seguia gastandole acciones. */
    expect(memory.getVolatileCellCount()).toBe(ANCHO);
    expect(memory.getTransition('ACTION5')?.program).toEqual([]);
    expect(memory.isKnownNoOp('ACTION5')).toBe(true);
  });
});
