/* [arc-agi-runner/replayWindowExport] BL.21728 -- reconstruye las VENTANAS DE SUBIDA DE NIVEL a
   partir de lo que quedo PERSISTIDO en `arcReplayFrames`. Es la operacion inversa exacta de
   `replayWindowIngest.ts`.

   POR QUE EXISTE (defecto MEDIDO, BL.21728 defecto 2). El informe de BL.21695 se corria sobre los
   `.jsonl` sueltos de `runtime_reports/ventanas/`, un directorio intermedio que nadie versiona y
   que el propio barrido sigue llenando mientras el informe ya corrio. Resultado medido: el informe
   publico "12 eventos = 7 transiciones sobre 5 juegos" cuando el corpus efectivamente persistido
   eran 14 eventos / 8 transiciones / 6 juegos -- omitia g50t ENTERO, uno de los tres juegos que
   sostenian un candidato del vocabulario. Un archivo intermedio que puede quedar viejo no es una
   fuente: la fuente es la coleccion.

   COMO SE RECONSTRUYE. Los docs de una corrida se ordenan por `stepNum` y se parten en BLOQUES
   CONTIGUOS: el diff RLE de un paso se codifica contra el paso ANTERIOR de la misma ventana, asi
   que la cadena solo es decodificable dentro de un tramo de pasos consecutivos. El primer doc de
   cada bloque lleva el RLE COMPLETO (`replayWindowIngest` lo codifica con `previa = null`), asi que
   arrancar la cadena en el borde del bloque es correcto por construccion, no por suerte.

   Los eventos se re-derivan del propio corpus (`levelsCompleted` que SUBE respecto del doc
   anterior), igual que `pasos_de_subida_de_nivel` del lado Python: no hay una lista de eventos
   guardada aparte que pueda desincronizarse. */

import { decodeGridDiff } from './replayRleDiff';
import type { FrameDeVentana, VentanaDeNivel } from './replayWindowIngest';
import type { Grid } from './worldModel/grid';

/** Frames a cada lado del evento. Mismo valor que `VENTANA_POR_DEFECTO` del capturador: la ventana
 *  reconstruida tiene que ser la MISMA que se capturo, o el informe mediria otra cosa. */
export const VENTANA_POR_DEFECTO = 10;

/** Un documento de `arcReplayFrames` con lo minimo que hace falta para reconstruir la ventana.
 *  Estructural y no un import de `ArcReplayFrame` para que los tests puedan armar docs a mano. */
export interface DocumentoDeCorpus {
  runId: string;
  gameId: string;
  modelId?: string;
  stepNum: number;
  action: string;
  x?: number;
  y?: number;
  availableActions?: number[];
  gridWidth: number;
  gridHeight: number;
  diffRle: Uint8Array;
  levelsCompleted: number;
  winLevels?: number;
  /** BL.21794 -- clase de la transicion decidida en la CAPTURA. Opcional: los frames anteriores a
   *  ese BL no la tienen y el export los devuelve sin el campo, que es lo que permite al informe
   *  contar cuantos frames del corpus vienen clasificados de origen. */
  claseDePaso?: string;
  firmaDelPaso?: string;
  /** BL.21798 -- semilla declarada de la partida. Ausente en los frames anteriores a ese BL, y la
   *  ausencia se reporta como "no declarada": es lo que dice si la ventana se puede regenerar. */
  semilla?: string;
}

/** Un doc del corpus ya decodificado a grilla. */
interface FrameDecodificado {
  doc: DocumentoDeCorpus;
  grilla: Grid;
}

/** Bloques de `stepNum` CONSECUTIVOS. Un hueco corta el bloque: despues de un hueco la cadena de
 *  diffs se decodificaria contra la grilla equivocada y saldria una ventana sintacticamente valida
 *  y semanticamente basura -- exactamente el modo de falla que este BL viene a cerrar. */
export function bloquesContiguos(docs: DocumentoDeCorpus[]): DocumentoDeCorpus[][] {
  const ordenados = [...docs].sort((a, b) => a.stepNum - b.stepNum);
  const bloques: DocumentoDeCorpus[][] = [];
  let actual: DocumentoDeCorpus[] = [];
  for (const doc of ordenados) {
    const previo = actual[actual.length - 1];
    if (previo !== undefined && doc.stepNum !== previo.stepNum + 1) {
      bloques.push(actual);
      actual = [];
    }
    actual.push(doc);
  }
  if (actual.length > 0) bloques.push(actual);
  return bloques;
}

/** El driver de Mongo devuelve los Buffer como `Binary`. Sin normalizar, `decodeGridDiff` recibe
 *  un array vacio y devuelve grillas de ceros: el corpus saldria legible y falso. Se falla ruidoso
 *  ante una forma no reconocida en vez de exportar basura. */
export function aBytes(valor: unknown): Uint8Array {
  if (valor instanceof Uint8Array) return valor;
  const interno = (valor as { buffer?: unknown } | null)?.buffer;
  if (interno instanceof Uint8Array) return interno;
  if (interno instanceof ArrayBuffer) return new Uint8Array(interno);
  throw new Error('[ventanas-export] diffRle en un formato no reconocido -- corpus ilegible.');
}

function decodificarBloque(bloque: DocumentoDeCorpus[]): FrameDecodificado[] {
  const frames: FrameDecodificado[] = [];
  let previa: Grid | null = null;
  for (const doc of bloque) {
    const grilla = decodeGridDiff(aBytes(doc.diffRle), previa, doc.gridWidth, doc.gridHeight);
    frames.push({ doc, grilla });
    previa = grilla;
  }
  return frames;
}

function aFrameDeVentana(frame: FrameDecodificado): FrameDeVentana {
  const { doc } = frame;
  const tieneClick = typeof doc.x === 'number' && typeof doc.y === 'number';
  return {
    paso: doc.stepNum,
    accion: doc.action,
    ...(tieneClick ? { x: doc.x, y: doc.y } : { x: null, y: null }),
    accionesDisponibles: [...(doc.availableActions ?? [])],
    grilla: frame.grilla,
    nivelesCompletados: doc.levelsCompleted,
    nivelesParaGanar: doc.winLevels ?? 0,
    estado: 'NOT_FINISHED',
    reinicioCompleto: false,
    ...(typeof doc.claseDePaso === 'string' ? { claseDePaso: doc.claseDePaso } : {}),
    ...(typeof doc.firmaDelPaso === 'string' ? { firmaDelPaso: doc.firmaDelPaso } : {}),
  };
}

/** Indices (dentro del bloque) donde `levelsCompleted` SUBIO respecto del frame anterior. Solo
 *  incrementos: tras un GAME_OVER el contador BAJA y esa bajada no es un evento. */
export function indicesDeSubida(frames: FrameDecodificado[]): number[] {
  const indices: number[] = [];
  for (let i = 1; i < frames.length; i++) {
    if (frames[i].doc.levelsCompleted > frames[i - 1].doc.levelsCompleted) indices.push(i);
  }
  return indices;
}

/** Resultado del CENSO: las subidas de nivel contadas DIRECTO sobre los documentos crudos. */
export interface CensoDeSubidas {
  eventos: number;
  transiciones: string[];
  /** Subidas de nivel cuyo documento ANTERIOR (stepNum - 1) no esta en la coleccion. No son un
   *  error de este script: son un agujero en lo persistido, y hasta esta correccion nadie lo
   *  miraba. `ventanasDeCorpus` no las puede reconstruir (no tiene el frame previo), asi que se
   *  cuentan aparte y NO entran en `eventos`. */
  subidasSinPredecesor: number;
}

/**
 * Cuenta las subidas de nivel SIN pasar por `ventanasDeCorpus`: agrupa por `runId`, ordena por
 * `stepNum` y compara `levelsCompleted` contra el documento del paso INMEDIATAMENTE anterior. No
 * decodifica RLE ni recorta ventanas -- es a proposito el camino mas corto posible, para que un
 * bug de reconstruccion no pueda estar en los dos lados a la vez.
 */
export function censoDeSubidas(docs: DocumentoDeCorpus[]): CensoDeSubidas {
  const porCorrida = new Map<string, DocumentoDeCorpus[]>();
  for (const doc of docs) {
    const lista = porCorrida.get(doc.runId);
    if (lista === undefined) porCorrida.set(doc.runId, [doc]);
    else lista.push(doc);
  }
  let eventos = 0;
  let subidasSinPredecesor = 0;
  const transiciones = new Set<string>();
  for (const deLaCorrida of porCorrida.values()) {
    const ordenados = [...deLaCorrida].sort((a, b) => a.stepNum - b.stepNum);
    for (let i = 1; i < ordenados.length; i++) {
      const previo = ordenados[i - 1];
      const actual = ordenados[i];
      if (actual.levelsCompleted <= previo.levelsCompleted) continue;
      if (actual.stepNum !== previo.stepNum + 1) {
        subidasSinPredecesor += 1;
        continue;
      }
      eventos += 1;
      transiciones.add(`${actual.gameId}:nivel${actual.levelsCompleted}`);
    }
  }
  return { eventos, transiciones: [...transiciones].sort(), subidasSinPredecesor };
}

/** Ventanas reconstruidas de TODOS los docs que se le pasen, agrupando por `runId`.
 *
 *  `framesAntes`/`framesDespues` se recalculan sobre los frames REALMENTE presentes, nunca sobre el
 *  ancho nominal: una ventana truncada en el borde de la partida (vc33 sube de nivel en el paso 3 y
 *  solo tiene 2 frames antes) tiene que decir 2, porque el informe usa ese numero para no darle a
 *  una ventana de 2 frames el mismo peso que a una de 10. */
export function ventanasDeCorpus(
  docs: DocumentoDeCorpus[],
  opciones: { antes?: number; despues?: number } = {},
): VentanaDeNivel[] {
  const antes = Math.max(0, opciones.antes ?? VENTANA_POR_DEFECTO);
  const despues = Math.max(0, opciones.despues ?? VENTANA_POR_DEFECTO);

  const porCorrida = new Map<string, DocumentoDeCorpus[]>();
  for (const doc of docs) {
    const lista = porCorrida.get(doc.runId);
    if (lista === undefined) porCorrida.set(doc.runId, [doc]);
    else lista.push(doc);
  }

  const ventanas: VentanaDeNivel[] = [];
  for (const [runId, deLaCorrida] of [...porCorrida.entries()].sort((a, b) =>
    a[0].localeCompare(b[0]),
  )) {
    for (const bloque of bloquesContiguos(deLaCorrida)) {
      const frames = decodificarBloque(bloque);
      for (const indice of indicesDeSubida(frames)) {
        const desde = Math.max(0, indice - antes);
        const hasta = Math.min(frames.length - 1, indice + despues);
        const recorte = frames.slice(desde, hasta + 1).map(aFrameDeVentana);
        const pasoDelEvento = frames[indice].doc.stepNum;
        ventanas.push({
          juego: frames[indice].doc.gameId,
          corrida: runId,
          modelo: frames[indice].doc.modelId ?? 'harness-local',
          // La semilla vive en los docs de la corrida; se toma la del frame del evento y, si ese no
          // la trae, la primera del bloque que la declare. Sin ninguna, la ventana sale SIN campo.
          ...(() => {
            const declarada =
              frames[indice].doc.semilla ?? bloque.find((d) => d.semilla !== undefined)?.semilla;
            return typeof declarada === 'string' && declarada.length > 0
              ? { semilla: declarada }
              : {};
          })(),
          pasoDelEvento,
          nivelPrevio: frames[indice - 1].doc.levelsCompleted,
          nivelNuevo: frames[indice].doc.levelsCompleted,
          framesAntes: recorte.filter((f) => f.paso < pasoDelEvento).length,
          framesDespues: recorte.filter((f) => f.paso > pasoDelEvento).length,
          frames: recorte,
        });
      }
    }
  }
  return ventanas;
}
