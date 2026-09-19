/* [arc-agi-runner] BL.21794 -- la CLASE de cada frame, decidida en la captura, sobrevive el viaje
   completo: JSONL -> `arcReplayFrames` -> export -> JSONL.

   POR QUE ESTE CONTRATO. La clasificacion de los frames de una maniobra (`informativo` | `inerte` |
   `enAnimacion`) decide cuantos frames REALES sostienen cada veredicto del vocabulario de
   objetivos: medido sobre las 14 ventanas del corpus, de 100 frames de contexto 55 son
   informativos, 27 inertes y 18 una animacion en loop -- casi la mitad de lo que un informe podria
   contar como evidencia no sostiene nada. Hasta este BL esa contabilidad se RECONSTRUIA en cada
   corrida del informe y el corpus no decia nada sobre sus propios frames.

   Si el puente perdiera el campo en cualquiera de los dos sentidos, el corpus volveria a quedar
   mudo y nadie se enteraria: la ventana exportada seguiria siendo valida y el informe seguiria
   pudiendo reconstruir la clasificacion. Por eso el campo se prueba en los DOS sentidos y, sobre
   todo, se prueba que la AUSENCIA se conserva como ausencia -- un `''` por default haria
   indistinguible "capturado antes de BL.21794" de "clasificado como nada", y esa distincion es la
   que permite al informe no presentar una reconstruccion como dato del corpus. */

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

function ventana(frames: FrameDeVentana[], pasoDelEvento: number): VentanaDeNivel {
  return {
    juego: 'ft09',
    corrida: 'harness-local:ft09:20260819T160000Z-fondo30',
    modelo: 'harness-local',
    pasoDelEvento,
    nivelPrevio: 0,
    nivelNuevo: 1,
    framesAntes: frames.filter((f) => f.paso < pasoDelEvento).length,
    framesDespues: frames.filter((f) => f.paso > pasoDelEvento).length,
    frames,
  };
}

/** Los docs que produce la ingesta, en la forma que el exportador lee de Mongo. */
function comoCorpus(v: VentanaDeNivel): DocumentoDeCorpus[] {
  return documentosDeVentana(v, TS) as unknown as DocumentoDeCorpus[];
}

describe('BL.21794 -- la clase de paso viaja al corpus', () => {
  const capturada = ventana(
    [
      frame(10, 1, { claseDePaso: 'sinPrevio' }),
      frame(11, 1, { claseDePaso: 'inerte', firmaDelPaso: 'sinCambio' }),
      frame(12, 2, { claseDePaso: 'informativo', firmaDelPaso: 'recoloreo:1>2' }),
      frame(13, 3, { claseDePaso: 'elEvento', nivelesCompletados: 1 }),
      frame(14, 3, { claseDePaso: 'posteriorAlEvento' }),
    ],
    13,
  );

  it('la ingesta guarda la clase y la firma de cada frame', () => {
    const docs = documentosDeVentana(capturada, TS);
    expect(docs.map((d) => d.claseDePaso)).toEqual([
      'sinPrevio',
      'inerte',
      'informativo',
      'elEvento',
      'posteriorAlEvento',
    ]);
    expect(docs[1].firmaDelPaso).toBe('sinCambio');
    expect(docs[2].firmaDelPaso).toBe('recoloreo:1>2');
  });

  it('el export la devuelve intacta: la ventana reconstruida es la que se capturo', () => {
    const [reconstruida] = ventanasDeCorpus(comoCorpus(capturada));
    expect(reconstruida.frames.map((f) => f.claseDePaso)).toEqual([
      'sinPrevio',
      'inerte',
      'informativo',
      'elEvento',
      'posteriorAlEvento',
    ]);
    expect(reconstruida.frames[2].firmaDelPaso).toBe('recoloreo:1>2');
  });

  it('una captura SIN clasificar no inventa una clase: la ausencia se conserva', () => {
    // Las 14 ventanas que ya estan en produccion se capturaron antes de BL.21794. Si el puente les
    // pusiera un default, el informe no podria separar "clasificacion del corpus" de
    // "clasificacion reconstruida", que es justo el numero que este BL agrega al informe.
    const vieja = ventana(
      [frame(10, 1), frame(11, 2), frame(12, 3, { nivelesCompletados: 1 })],
      12,
    );
    const docs = documentosDeVentana(vieja, TS);
    for (const doc of docs) {
      expect(doc.claseDePaso).toBeUndefined();
      expect('claseDePaso' in doc).toBe(false);
    }
    const [reconstruida] = ventanasDeCorpus(docs as unknown as DocumentoDeCorpus[]);
    for (const f of reconstruida.frames) expect(f.claseDePaso).toBeUndefined();
  });

  it('una clase vacia se trata como ausente y no como una clase mas', () => {
    const conVacio = ventana(
      [frame(10, 1, { claseDePaso: '' }), frame(11, 2, { nivelesCompletados: 1 })],
      11,
    );
    const docs = documentosDeVentana(conVacio, TS);
    expect(docs.every((d) => !('claseDePaso' in d))).toBe(true);
  });
});
