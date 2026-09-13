/* [arc-agi-runner] BL.21728 -- contrato del camino de VUELTA: de `arcReplayFrames` a las ventanas
   de subida de nivel.

   Lo que se protege: que el informe de objetivos pueda leer EXACTAMENTE lo que se persistio, y no
   un directorio intermedio que quedo viejo. El defecto medido de BL.21695 fue publicar "12 eventos
   = 7 transiciones sobre 5 juegos" cuando el corpus persistido eran 14 / 8 / 6.

   Las dos trampas que estos tests fijan:
   - IDA Y VUELTA: ingestar una ventana y volver a exportarla tiene que devolver las MISMAS grillas.
     Si la cadena de diffs se decodifica contra la grilla equivocada, el export sale sintacticamente
     valido y semanticamente basura.
   - HUECOS: dos ventanas de la MISMA corrida separadas por un hueco de `stepNum` son dos cadenas
     independientes. Decodificarlas como una sola produciria grillas falsas desde el hueco en
     adelante. */

import { describe, expect, it } from 'vitest';

import { bloquesContiguos, censoDeSubidas, ventanasDeCorpus } from '../replayWindowExport';
import type { DocumentoDeCorpus } from '../replayWindowExport';
import { documentosDeVentanas } from '../replayWindowIngest';
import type { FrameDeVentana, VentanaDeNivel } from '../replayWindowIngest';

const TS = new Date('2026-08-18T18:42:50.257Z');

function grilla(base: number, marca?: { y: number; x: number; color: number }): number[][] {
  const salida = Array.from({ length: 4 }, () => Array.from({ length: 4 }, () => base));
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

/** Una ventana de 5 frames con el evento en el medio: el nivel sube en `pasoDelEvento`. */
function ventana(
  juego: string,
  corrida: string,
  desde: number,
  nivelNuevo: number,
): VentanaDeNivel {
  const pasoDelEvento = desde + 2;
  const frames = [0, 1, 2, 3, 4].map((i) =>
    frame(desde + i, grilla(0, { y: 1, x: i % 4, color: 3 + i }), {
      nivelesCompletados: desde + i >= pasoDelEvento ? nivelNuevo : nivelNuevo - 1,
      ...(i === 2 ? { accion: 'ACTION6', x: 7, y: 9 } : {}),
    }),
  );
  return {
    juego,
    corrida,
    modelo: 'harness-local',
    pasoDelEvento,
    nivelPrevio: nivelNuevo - 1,
    nivelNuevo,
    framesAntes: 2,
    framesDespues: 2,
    frames,
  };
}

/** Los documentos crudos de `arcReplayFrames` que produce un conjunto de ventanas. */
function documentosDeCorpus(ventanas: VentanaDeNivel[]): DocumentoDeCorpus[] {
  const { docs } = documentosDeVentanas(ventanas, TS);
  return docs.map((d) => ({
    runId: d.runId,
    gameId: d.gameId,
    modelId: d.modelId,
    stepNum: d.stepNum,
    action: d.action,
    ...(d.x !== undefined ? { x: d.x, y: d.y } : {}),
    availableActions: d.availableActions,
    gridWidth: d.gridWidth,
    gridHeight: d.gridHeight,
    diffRle: d.diffRle,
    levelsCompleted: d.levelsCompleted,
    winLevels: d.winLevels,
  }));
}

/** Recorre el camino real: ventana -> documentos de `arcReplayFrames` -> ventana. */
function idaYVuelta(ventanas: VentanaDeNivel[], antes = 10, despues = 10): VentanaDeNivel[] {
  return ventanasDeCorpus(documentosDeCorpus(ventanas), { antes, despues });
}

describe('replayWindowExport', () => {
  it('devuelve las MISMAS grillas que se ingestaron', () => {
    const original = ventana('ft09', 'harness-local:ft09:t1', 100, 1);
    const [recuperada] = idaYVuelta([original]);

    expect(recuperada.juego).toBe('ft09');
    expect(recuperada.corrida).toBe('harness-local:ft09:t1');
    expect(recuperada.pasoDelEvento).toBe(original.pasoDelEvento);
    expect(recuperada.nivelPrevio).toBe(0);
    expect(recuperada.nivelNuevo).toBe(1);
    expect(recuperada.frames.map((f) => f.paso)).toEqual(original.frames.map((f) => f.paso));
    expect(recuperada.frames.map((f) => f.grilla)).toEqual(original.frames.map((f) => f.grilla));
  });

  it('conserva la coordenada del click del evento', () => {
    const [recuperada] = idaYVuelta([ventana('vc33', 'harness-local:vc33:t1', 50, 1)]);
    const delEvento = recuperada.frames.find((f) => f.paso === recuperada.pasoDelEvento);
    expect(delEvento?.accion).toBe('ACTION6');
    expect([delEvento?.x, delEvento?.y]).toEqual([7, 9]);
  });

  it('parte una corrida en bloques donde hay un hueco de stepNum', () => {
    const doc = (stepNum: number): DocumentoDeCorpus => ({
      runId: 'r',
      gameId: 'g',
      stepNum,
      action: 'ACTION1',
      gridWidth: 4,
      gridHeight: 4,
      diffRle: new Uint8Array([16, 16]),
      levelsCompleted: 0,
    });
    const bloques = bloquesContiguos([doc(10), doc(11), doc(12), doc(80), doc(81)]);
    expect(bloques.map((b) => b.map((d) => d.stepNum))).toEqual([
      [10, 11, 12],
      [80, 81],
    ]);
  });

  it('reconstruye DOS ventanas separadas de la misma corrida sin mezclar sus cadenas', () => {
    const corrida = 'harness-local:lp85:t';
    const primera = ventana('lp85', corrida, 57, 1);
    const segunda = ventana('lp85', corrida, 172, 2);
    const recuperadas = idaYVuelta([primera, segunda]);

    expect(recuperadas).toHaveLength(2);
    expect(recuperadas.map((v) => v.nivelNuevo)).toEqual([1, 2]);
    // La clave: las grillas de la SEGUNDA ventana no se decodificaron contra la primera.
    expect(recuperadas[1].frames.map((f) => f.grilla)).toEqual(segunda.frames.map((f) => f.grilla));
  });

  it('reconstruye DOS eventos solapados de un mismo bloque contiguo', () => {
    // vc33 medido: 25 documentos CONTIGUOS (pasos 1..25) que contienen DOS subidas de nivel. Al
    // solaparse, la ingesta deduplica por {runId, stepNum} y el corpus deja de decir donde
    // empezaba cada ventana: los eventos se re-derivan de `levelsCompleted`, que es la unica
    // fuente que sobrevive al upsert.
    const niveles = [0, 0, 1, 1, 1, 2, 2, 2];
    const docs: DocumentoDeCorpus[] = niveles.map((nivel, i) => ({
      runId: 'harness-local:vc33:t',
      gameId: 'vc33',
      stepNum: i + 1,
      action: 'ACTION6',
      gridWidth: 4,
      gridHeight: 4,
      // RLE completo de una grilla 4x4 uniforme: decodifica igual sin grilla previa.
      diffRle: new Uint8Array([16, nivel]),
      levelsCompleted: nivel,
    }));
    const recuperadas = ventanasDeCorpus(docs);
    expect(recuperadas.map((v) => v.pasoDelEvento)).toEqual([3, 6]);
    expect(recuperadas.map((v) => v.nivelNuevo)).toEqual([1, 2]);
    // framesAntes REALES: el primer evento tiene 2 frames antes, el segundo tiene 5.
    expect(recuperadas.map((v) => v.framesAntes)).toEqual([2, 5]);
  });

  it('reporta framesAntes REALES cuando la ventana esta truncada en el borde del bloque', () => {
    // El caso vc33 nivel 1: el evento cae en el paso 3 y solo hay 2 frames antes. El informe usa
    // este numero para no darle a una ventana de 2 frames el mismo peso que a una de 10.
    const [recuperada] = idaYVuelta([ventana('vc33', 'harness-local:vc33:t', 1, 1)]);
    expect(recuperada.framesAntes).toBe(2);
    expect(recuperada.framesDespues).toBe(2);
  });

  it('no inventa un evento donde el contador de niveles BAJA', () => {
    // Tras un GAME_OVER + RESET el contador vuelve a 0: esa bajada no es una subida de nivel.
    const docs: DocumentoDeCorpus[] = [2, 2, 0].map((nivel, i) => ({
      runId: 'r',
      gameId: 'g',
      stepNum: i,
      action: 'RESET',
      gridWidth: 4,
      gridHeight: 4,
      diffRle: new Uint8Array([16, 16]),
      levelsCompleted: nivel,
    }));
    expect(ventanasDeCorpus(docs)).toHaveLength(0);
  });
});

/* ─── EL CENSO: el segundo camino para contar la misma muestra (correccion de BL.21728) ───────────
   El sha256 del manifiesto ata el INFORME al export y nunca el export a la COLECCION: un export a
   medias con su manifiesto recalculado pasa todos los chequeos del lector. `censoDeSubidas` cuenta
   las subidas de nivel DIRECTO sobre los documentos, sin decodificar RLE ni recortar ventanas, y
   `exportarVentanasDeNivel` FALLA si las dos cuentas no coinciden. Estos tests fijan que las dos
   cuenten lo mismo y que el censo vea lo que la reconstruccion no puede ver. */
describe('censoDeSubidas -- el segundo camino', () => {
  it('cuenta lo MISMO que la reconstruccion de ventanas, sin pasar por ella', () => {
    const ventanas = [
      ventana('ft09', 'harness-local:ft09:a', 10, 1),
      ventana('lp85', 'harness-local:lp85:b', 40, 1),
      ventana('lp85', 'harness-local:lp85:b', 80, 2),
    ];
    const docs = documentosDeCorpus(ventanas);
    const censo = censoDeSubidas(docs);
    const reconstruidas = ventanasDeCorpus(docs);

    expect(censo.eventos).toBe(reconstruidas.length);
    expect(censo.transiciones).toEqual(
      [...new Set(reconstruidas.map((v) => `${v.juego}:nivel${v.nivelNuevo}`))].sort(),
    );
    expect(censo.subidasSinPredecesor).toBe(0);
  });

  it('un export a medias se detecta: faltan documentos y las dos cuentas dejan de coincidir', () => {
    const ventanas = [
      ventana('ft09', 'harness-local:ft09:a', 10, 1),
      ventana('g50t', 'harness-local:g50t:b', 40, 1),
    ];
    const docs = documentosDeCorpus(ventanas);
    // La forma EXACTA del defecto original: g50t desaparece del export.
    const aMedias = docs.filter((d) => d.gameId !== 'g50t');

    expect(censoDeSubidas(docs).eventos).toBe(2);
    expect(ventanasDeCorpus(aMedias).length).toBe(1);
    expect(censoDeSubidas(docs).eventos).not.toBe(ventanasDeCorpus(aMedias).length);
  });

  it('una subida sin el frame previo persistido se cuenta APARTE, no como evento', () => {
    /* `ventanasDeCorpus` no puede reconstruirla (no tiene el par pre/post) y hasta esta correccion
       desaparecia en silencio. Contarla como evento haria fallar el cruce por un agujero del dato,
       no por un bug; no contarla en ningun lado la vuelve invisible. */
    const docs = documentosDeCorpus([ventana('vc33', 'harness-local:vc33:a', 10, 1)]);
    const sinPredecesor = docs.filter((d) => d.stepNum !== 11);

    const censo = censoDeSubidas(sinPredecesor);
    expect(censo.eventos).toBe(0);
    expect(censo.subidasSinPredecesor).toBe(1);
    expect(ventanasDeCorpus(sinPredecesor).length).toBe(0);
  });
});
