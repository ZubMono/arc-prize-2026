/* [arc-agi-runner] BL.21798 -- la SEMILLA declarada de la partida sobrevive el viaje completo:
   JSONL -> `arcReplayFrames` -> export -> ventana reconstruida.

   POR QUE ESTE CONTRATO. El veredicto de BL.21794 ("de CERO a UNO tipos de objetivo sostenidos por
   mas de un juego") depende, medido, de tres ventanas de dos corridas concretas: quitando esas dos
   corridas del mismo corpus el gate vuelve a CERO. Y desde el corpus NO habia forma de saber cuales
   de las 33 ventanas se podian volver a producir, porque lo unico que viaja es el `runId`, que
   lleva el LOTE -- y el lote dejo de sembrar la partida en el commit e7f70322d1. O sea que la
   receta de reproduccion publicada regeneraba OTRO corpus y nadie podia detectarlo mirando el dato.

   La semilla es de la PARTIDA y el corpus se persiste FRAME a FRAME, asi que viaja por frame y el
   export la levanta de vuelta al nivel de la ventana. Se prueba en los dos sentidos y, sobre todo,
   se prueba que la AUSENCIA se conserva: rellenarla con el lote o con un default haria pasar por
   reproducible una ventana que no lo es, que es exactamente el defecto que este BL cierra. */

import { describe, expect, it } from 'vitest';

import { ventanasDeCorpus } from '../replayWindowExport';
import type { DocumentoDeCorpus } from '../replayWindowExport';
import { documentosDeVentana } from '../replayWindowIngest';
import type { FrameDeVentana, VentanaDeNivel } from '../replayWindowIngest';

const TS = new Date('2026-08-19T16:00:00.000Z');

function grilla(valor: number): number[][] {
  return Array.from({ length: 4 }, () => Array.from({ length: 4 }, () => valor));
}

function frame(paso: number, valor: number, parcial: Partial<FrameDeVentana> = {}): FrameDeVentana {
  return {
    paso,
    accion: 'ACTION6',
    accionesDisponibles: [6],
    grilla: grilla(valor),
    nivelesCompletados: 0,
    nivelesParaGanar: 3,
    estado: 'NOT_FINISHED',
    reinicioCompleto: false,
    ...parcial,
  };
}

function ventana(parcial: Partial<VentanaDeNivel> = {}): VentanaDeNivel {
  const frames = [frame(10, 1), frame(11, 2), frame(12, 3, { nivelesCompletados: 1 })];
  return {
    juego: 'lp85',
    corrida: 'harness-local:lp85:20260819T163029Z-fondo30',
    modelo: 'harness-local',
    pasoDelEvento: 12,
    nivelPrevio: 0,
    nivelNuevo: 1,
    framesAntes: 2,
    framesDespues: 0,
    frames,
    ...parcial,
  };
}

function comoCorpus(v: VentanaDeNivel): DocumentoDeCorpus[] {
  return documentosDeVentana(v, TS) as unknown as DocumentoDeCorpus[];
}

describe('BL.21798 -- la semilla declarada viaja al corpus', () => {
  it('la ingesta la escribe en TODOS los frames de la ventana', () => {
    const docs = documentosDeVentana(ventana({ semilla: 'bl21794-f1' }), TS);
    expect(docs.map((d) => d.semilla)).toEqual(['bl21794-f1', 'bl21794-f1', 'bl21794-f1']);
  });

  it('el export la devuelve al nivel de la ventana', () => {
    const [reconstruida] = ventanasDeCorpus(comoCorpus(ventana({ semilla: 'bl21794-f1' })));
    expect(reconstruida.semilla).toBe('bl21794-f1');
  });

  it('sin semilla declarada el campo NO existe: la ausencia es el dato', () => {
    const docs = documentosDeVentana(ventana(), TS);
    for (const doc of docs) expect('semilla' in doc).toBe(false);
    const [reconstruida] = ventanasDeCorpus(docs as unknown as DocumentoDeCorpus[]);
    expect(reconstruida.semilla).toBeUndefined();
    // Y en particular NO se rellena con el runId ni con el lote, que es la tentacion obvia y la que
    // haria pasar por regenerable una partida que nadie puede volver a producir.
    expect(reconstruida.corrida).toContain('20260819T163029Z');
  });

  it('una semilla vacia se trata como ausente y no como una semilla mas', () => {
    const docs = documentosDeVentana(ventana({ semilla: '' }), TS);
    expect(docs.every((d) => !('semilla' in d))).toBe(true);
  });

  it('si solo algunos frames de la corrida la traen, la ventana igual la recupera', () => {
    // Caso real del corpus mezclado: una corrida re-ingestada por partes, o docs viejos conviviendo
    // con nuevos. La ventana tiene UNA semilla; que un frame no la traiga no la borra.
    const docs = comoCorpus(ventana({ semilla: 'bl21794-f1' }));
    delete docs[docs.length - 1].semilla;
    const [reconstruida] = ventanasDeCorpus(docs);
    expect(reconstruida.semilla).toBe('bl21794-f1');
  });
});
