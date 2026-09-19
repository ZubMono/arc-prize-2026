/* [arc-agi-runner] BL.21695 paso 1 -- contrato del puente entre la captura del harness local
   offline y `arcReplayFrames`.

   Lo que se protege: que una ventana capturada se pueda VOLVER A LEER. Si el primer frame de la
   ventana no lleva el RLE completo, o si la cadena de diffs se rompe, el corpus queda
   sintacticamente valido y semanticamente basura -- exactamente el modo de falla que ya se pago en
   BL.21560 (un fixture de clicks lleno de grillas de ceros). Aca se decodifica de vuelta y se
   compara contra las grillas originales. */

import { describe, expect, it } from 'vitest';

import { MOTIVO_RETENCION_VENTANA_DE_NIVEL } from '../politicaDeRetencion';
import { operacionDeUpsertDeFrame } from '../replayFrameStore';
import { decodeGridDiff } from '../replayRleDiff';
import {
  documentosDeVentana,
  documentosDeVentanas,
  esVentanaValida,
  parsearVentanas,
} from '../replayWindowIngest';
import type { FrameDeVentana, VentanaDeNivel } from '../replayWindowIngest';
import type { Grid } from '../worldModel/grid';

const TS = new Date('2026-08-18T18:00:00.000Z');

function grilla(valor: number, marca?: { y: number; x: number; color: number }): number[][] {
  const salida = Array.from({ length: 4 }, () => Array.from({ length: 4 }, () => valor));
  if (marca) salida[marca.y][marca.x] = marca.color;
  return salida;
}

function frame(paso: number, g: number[][], parcial: Partial<FrameDeVentana> = {}): FrameDeVentana {
  return {
    paso,
    accion: 'ACTION1',
    accionesDisponibles: [1, 2, 3, 4],
    grilla: g,
    nivelesCompletados: 0,
    nivelesParaGanar: 3,
    estado: 'NOT_FINISHED',
    reinicioCompleto: false,
    ...parcial,
  };
}

function ventana(frames: FrameDeVentana[], pasoDelEvento: number): VentanaDeNivel {
  return {
    juego: 'ft09',
    corrida: 'harness-local:ft09:20260818T180000Z',
    modelo: 'harness-local',
    pasoDelEvento,
    nivelPrevio: 0,
    nivelNuevo: 1,
    framesAntes: frames.filter((f) => f.paso < pasoDelEvento).length,
    framesDespues: frames.filter((f) => f.paso > pasoDelEvento).length,
    frames,
  };
}

describe('documentosDeVentana', () => {
  it('reconstruye las grillas originales decodificando la cadena de diffs', () => {
    const grillas = [
      grilla(0, { y: 1, x: 1, color: 5 }),
      grilla(0, { y: 1, x: 2, color: 5 }),
      grilla(0, { y: 1, x: 3, color: 5 }),
    ];
    const docs = documentosDeVentana(
      ventana(
        [
          frame(40, grillas[0]),
          frame(41, grillas[1]),
          frame(42, grillas[2], { nivelesCompletados: 1 }),
        ],
        42,
      ),
      TS,
    );

    expect(docs).toHaveLength(3);
    let previa: Grid | null = null;
    docs.forEach((doc, i) => {
      const reconstruida = decodeGridDiff(doc.diffRle, previa, doc.gridWidth, doc.gridHeight);
      expect(reconstruida).toEqual(grillas[i]);
      previa = reconstruida;
    });
  });

  it('hace AUTO-SUFICIENTE al primer frame: se decodifica sin grilla previa', () => {
    const g = grilla(3, { y: 0, x: 0, color: 7 });
    const [primero] = documentosDeVentana(ventana([frame(10, g), frame(11, g)], 11), TS);
    expect(decodeGridDiff(primero.diffRle, null, primero.gridWidth, primero.gridHeight)).toEqual(g);
  });

  it('conserva stepNum real, niveles y coordenadas del click', () => {
    const docs = documentosDeVentana(
      ventana(
        [
          frame(858, grilla(0)),
          frame(859, grilla(0, { y: 2, x: 2, color: 9 }), {
            accion: 'ACTION6',
            x: 31,
            y: 12,
            nivelesCompletados: 2,
          }),
        ],
        859,
      ),
      TS,
    );
    expect(docs.map((d) => d.stepNum)).toEqual([858, 859]);
    expect(docs[1]).toMatchObject({ action: 'ACTION6', x: 31, y: 12, levelsCompleted: 2 });
    expect(docs[0].x).toBeUndefined();
  });

  it('los frames de una ventana de nivel NACEN RETENIDOS: sin expiresAt y CON la marca', () => {
    /* Revision adversarial de BL.21749. Esta puerta ingesta las ventanas de SUBIDA DE NIVEL: los
       unicos frames del corpus con levelsCompleted > 0. Ponerles expiresAt a 30 dias y delegar la
       retencion a que un operador corriera un script los dejaba caducando salvo que alguien se
       acordara a tiempo; omitir la fecha SIN marca (la version original) los dejaba indistinguibles
       de un descuido, a merced del primer backfill. Nacer retenidos es fail-safe Y auditable. */
    const docs = documentosDeVentana(ventana([frame(1, grilla(0)), frame(2, grilla(1))], 2), TS);
    expect(docs.length).toBeGreaterThan(0);
    for (const doc of docs) {
      expect(doc.expiresAt).toBeUndefined();
      expect(doc.retenidoPor).toBe(MOTIVO_RETENCION_VENTANA_DE_NIVEL);
      expect(doc.retenidoEn).toEqual(TS);
    }
  });
});

describe('documentosDeVentanas', () => {
  it('deduplica {runId, stepNum} entre ventanas solapadas de la misma partida', () => {
    const a = ventana([frame(10, grilla(0)), frame(11, grilla(1))], 11);
    const b = ventana([frame(11, grilla(1)), frame(12, grilla(2))], 12);
    const { docs, resumen } = documentosDeVentanas([a, b], TS);
    expect(docs.map((d) => d.stepNum)).toEqual([10, 11, 12]);
    expect(resumen.ventanas).toBe(2);
    expect(resumen.juegos).toEqual(['ft09']);
  });

  it('cuenta los documentos con levelsCompleted > 0 -- la metrica que faltaba en el corpus', () => {
    const v = ventana([frame(5, grilla(0)), frame(6, grilla(1), { nivelesCompletados: 1 })], 6);
    expect(documentosDeVentanas([v], TS).resumen.documentosConNivel).toBe(1);
  });

  it('BL.21849: agrupa por VENTANA y el primer doc de cada grupo lleva el RLE completo', () => {
    // La ventana es la unidad ATOMICA de escritura: sus frames son diffs encadenados contra el
    // anterior de la MISMA ventana, asi que una ventana sin su primer frame es INDECODIFICABLE.
    // El ingestor aplanaba todas las ventanas y cortaba cada 25 documentos, partiendo ventanas
    // de 21 por la mitad.
    const a = ventana([frame(10, grilla(0)), frame(11, grilla(1))], 11);
    const b = ventana([frame(30, grilla(2)), frame(31, grilla(3))], 31);
    const { docs, grupos } = documentosDeVentanas([a, b], TS);
    expect(grupos.length).toBe(2);
    expect(grupos.flat().length).toBe(docs.length);
    expect(grupos.map((g) => g.map((d) => d.stepNum))).toEqual([
      [10, 11],
      [30, 31],
    ]);
    // El primer frame de cada grupo es el que lleva la grilla entera (previa = null).
    for (const grupo of grupos) expect(grupo[0].changedCells).toBeGreaterThan(0);
  });

  it('BL.21849: la deduplicacion no deja grupos vacios (una ventana totalmente repetida desaparece)', () => {
    const a = ventana([frame(10, grilla(0)), frame(11, grilla(1))], 11);
    const { grupos } = documentosDeVentanas([a, a], TS);
    expect(grupos.length).toBe(1);
    expect(grupos.every((g) => g.length > 0)).toBe(true);
  });
});

describe('parsearVentanas', () => {
  it('descarta lineas invalidas y las reporta en vez de interpretarlas a medias', () => {
    const valida = JSON.stringify(ventana([frame(1, grilla(0)), frame(2, grilla(1))], 2));
    const texto = [valida, 'no es json', JSON.stringify({ juego: 'ft09' }), ''].join('\n');
    const { ventanas, descartadas } = parsearVentanas(texto);
    expect(ventanas).toHaveLength(1);
    expect(descartadas).toBe(2);
  });

  it('rechaza una ventana sin el frame del evento', () => {
    const sinEvento = ventana([frame(1, grilla(0)), frame(2, grilla(1))], 99);
    expect(esVentanaValida(sinEvento)).toBe(false);
  });

  it('rechaza una ventana con grillas vacias', () => {
    const vacia = ventana([frame(1, []), frame(2, [])], 2);
    expect(esVentanaValida(vacia)).toBe(false);
  });
});

describe('escritura del puente (BL.21749)', () => {
  type OperacionUpsert = {
    updateOne: {
      filter: Record<string, unknown>;
      update: { $set: Record<string, unknown>; $setOnInsert?: Record<string, unknown> };
      upsert: boolean;
    };
  };

  it('las marcas van por $setOnInsert: re-ingestar NO pisa la retencion de un frame existente', () => {
    const [doc] = documentosDeVentana(ventana([frame(1, grilla(0))], 1), TS);
    const op = operacionDeUpsertDeFrame(doc) as unknown as OperacionUpsert;

    expect(op.updateOne.filter).toEqual({ runId: doc.runId, stepNum: doc.stepNum });
    expect(op.updateOne.upsert).toBe(true);
    expect(op.updateOne.update.$setOnInsert?.retenidoPor).toBe(MOTIVO_RETENCION_VENTANA_DE_NIVEL);
    expect(op.updateOne.update.$setOnInsert?.retenidoEn).toEqual(TS);
    expect(op.updateOne.update.$set).not.toHaveProperty('retenidoPor');
    expect(
      'expiresAt' in op.updateOne.update.$set,
      'un $set de expiresAt le devolveria fecha de purga a los 5.490 frames retenidos a mano',
    ).toBe(false);
    // El resto del contrato sigue pisandose: la idempotencia por {runId, stepNum} no cambia.
    expect(op.updateOne.update.$set.levelsCompleted).toBe(doc.levelsCompleted);
  });

  it('un frame del sink online (con expiresAt) tambien lo manda por $setOnInsert', () => {
    const [doc] = documentosDeVentana(ventana([frame(1, grilla(0))], 1), TS);
    const online = { ...doc, retenidoPor: undefined, retenidoEn: undefined, expiresAt: TS };
    const op = operacionDeUpsertDeFrame(online) as unknown as OperacionUpsert;
    expect(op.updateOne.update.$setOnInsert?.expiresAt).toEqual(TS);
    expect(op.updateOne.update.$set).not.toHaveProperty('expiresAt');
  });
});
