/* [arc-agi-runner/replayWindowIngest] BL.21695 paso 1 -- traduce las VENTANAS DE SUBIDA DE NIVEL
   que captura el harness local offline (projects/arc-agi3-kaggle-agent/scripts/captura_de_niveles.py)
   a documentos de `arcReplayFrames`, el mismo contrato que escribe `replayFrameStore.ts`.

   POR QUE EXISTE. El corpus tenia 2.456 frames en produccion y CERO con `levelsCompleted > 0`: ni
   un solo ejemplo de como se ve GANAR. Las subidas de nivel observadas (ft09, g50t, lp85, m0r0,
   sc25, vc33) pasaron en el harness LOCAL, que es Python stdlib puro, sin red y sin Mongo por
   diseno (el notebook de Kaggle no tiene ninguna de las dos). Asi que la captura sale de ahi como
   JSONL y el puente a Mongo vive de este lado, que es donde ya viven el codec y el contrato.

   DOS DECISIONES QUE NO SON OBVIAS:

   1. EL PRIMER FRAME DE CADA VENTANA LLEVA EL RLE COMPLETO, no un diff. Una ventana es un TROZO de
      partida: no hay cadena de diffs desde el paso 0 que reconstruir, asi que el primer frame tiene
      que ser auto-suficiente o la ventana entera seria indecodificable. Los demas frames si son
      diffs contra el frame anterior DE LA MISMA VENTANA. `stepNum` conserva el indice real dentro
      de la partida, con huecos entre ventanas: el hueco es informacion honesta ("aca no se
      capturo"), y rellenarlo con pasos falsos corromperia el corpus.

   2. LOS FRAMES DE ESTA PUERTA NACEN RETENIDOS, CON LA MARCA PUESTA (BL.21749, revision
      adversarial). Historia corta de las tres versiones, porque las dos primeras estaban mal por
      motivos opuestos:
        (a) al principio la ingesta OMITIA `expiresAt`. El TTL no los alcanzaba -- bien -- pero
            quedaban SIN MARCA, o sea indistinguibles de documentos a los que les falta la fecha
            por descuido, y por lo tanto a merced del primer backfill de `expiresAt`. Eso es
            exactamente lo que se midio en produccion el 2026-08-18: 277 frames sin fecha y sin
            marca.
        (b) despues se les puso `expiresAt` a 30 dias "como al resto del corpus", delegando la
            retencion a que un operador corriera el script. Eso empeoro el flanco: esta puerta
            ingesta VENTANAS DE SUBIDA DE NIVEL, los unicos frames del corpus con
            `levelsCompleted > 0`, y pasaban a caducar solos salvo que alguien se acordara a tiempo.
        (c) ahora: nacen SIN `expiresAt` y CON `retenidoPor`/`retenidoEn`
            (`MOTIVO_RETENCION_VENTANA_DE_NIVEL`, en `politicaDeRetencion.ts`). Es fail-safe Y
            auditable: no hay ventana entre "existe" y "esta protegido", y cualquiera que lea el
            documento sabe por que no caduca.
      No es una excepcion caprichosa a la politica de 30 dias de BL.21557: esa politica rige para
      el corpus VOLUMINOSO que produce jugar (hasta 500 docs por partida, regenerables re-jugando).
      Esta puerta es manual, de bajo volumen (277 documentos en total) y trae capturas que costaron
      8.650 acciones en el harness offline.
      Los documentos ya escritos NO se tocan: la escritura manda `expiresAt` y las marcas por
      `$setOnInsert` (`operacionDeUpsertDeFrame`), asi que re-ingestar una ventana ya cargada nunca
      le devuelve fecha de purga ni le pisa el motivo a un documento retenido. */

import { MOTIVO_RETENCION_VENTANA_DE_NIVEL, marcasDeRetencion } from './politicaDeRetencion';
import { encodeGridDiff } from './replayRleDiff';
import type { ArcReplayFrame } from './types';
import type { Grid } from './worldModel/grid';

/** Un frame capturado, tal cual lo emite `captura_de_niveles.py` (claves camelCase). */
export interface FrameDeVentana {
  paso: number;
  accion: string;
  x?: number | null;
  y?: number | null;
  accionesDisponibles: number[];
  grilla: number[][];
  nivelesCompletados: number;
  nivelesParaGanar: number;
  estado: string;
  reinicioCompleto: boolean;
  /** BL.21794 -- clase de la transicion que produjo este frame, decidida EN LA CAPTURA por
   *  `clasificar_pasos` (agente offline): `informativo` | `inerte` | `enAnimacion` dentro de la
   *  maniobra, `sinPrevio` | `elEvento` | `posteriorAlEvento` fuera de ella. Ausente en las
   *  capturas anteriores a ese BL, y la ausencia se declara: el informe distingue "clasificacion
   *  del corpus" de "clasificacion reconstruida". */
  claseDePaso?: string;
  /** BL.21794 -- firma de mecanica de esa misma transicion. Vacia fuera de la maniobra. */
  firmaDelPaso?: string;
}

/** Los frames alrededor de UN incremento de `levels_completed`. */
export interface VentanaDeNivel {
  juego: string;
  corrida: string;
  modelo: string;
  /** BL.21798 -- semilla declarada de la partida. Ausente si la captura no la declaro. */
  semilla?: string;
  pasoDelEvento: number;
  nivelPrevio: number;
  nivelNuevo: number;
  framesAntes: number;
  framesDespues: number;
  frames: FrameDeVentana[];
}

function esGrillaUtil(valor: unknown): valor is number[][] {
  return (
    Array.isArray(valor) &&
    valor.length > 0 &&
    Array.isArray(valor[0]) &&
    (valor[0] as unknown[]).length > 0
  );
}

/** Valida la forma minima de una ventana. Se rechaza en bloque y no se "arregla": una ventana a la
 *  que le falta el frame del evento o las grillas no describe nada, y meterla igual al corpus
 *  produciria evidencia falsa sobre como se ve ganar -- el error mas caro posible en este BL. */
export function esVentanaValida(valor: unknown): valor is VentanaDeNivel {
  if (typeof valor !== 'object' || valor === null) return false;
  const v = valor as Partial<VentanaDeNivel>;
  if (typeof v.juego !== 'string' || v.juego.length === 0) return false;
  if (typeof v.corrida !== 'string' || v.corrida.length === 0) return false;
  if (typeof v.pasoDelEvento !== 'number') return false;
  if (!Array.isArray(v.frames) || v.frames.length === 0) return false;
  if (!v.frames.every((f) => typeof f?.paso === 'number' && esGrillaUtil(f?.grilla))) return false;
  return v.frames.some((f) => f.paso === v.pasoDelEvento);
}

/** Parsea el JSONL de ventanas. Las lineas invalidas se REPORTAN y se descartan, nunca se
 *  interpretan a medias: el llamador recibe el conteo para poder decidir si el archivo sirve. */
export function parsearVentanas(texto: string): {
  ventanas: VentanaDeNivel[];
  descartadas: number;
} {
  const ventanas: VentanaDeNivel[] = [];
  let descartadas = 0;
  for (const linea of texto.split('\n')) {
    if (linea.trim().length === 0) continue;
    let crudo: unknown;
    try {
      crudo = JSON.parse(linea);
    } catch {
      descartadas++;
      continue;
    }
    if (esVentanaValida(crudo)) ventanas.push(crudo);
    else descartadas++;
  }
  return { ventanas, descartadas };
}

function accionesValidas(valor: unknown): number[] {
  if (!Array.isArray(valor)) return [];
  return valor.filter((n): n is number => typeof n === 'number' && Number.isFinite(n));
}

/** Convierte una ventana en los documentos de `arcReplayFrames` que la representan.
 *  `ts` marca el instante de INGESTA: el harness local no emite reloj de partida, y fechar un frame
 *  con una hora inventada seria peor que fecharlo con la real de captura. SIN `expiresAt` y CON las
 *  marcas de retencion: ver la decision 2 del encabezado. */
export function documentosDeVentana(ventana: VentanaDeNivel, ts: Date): ArcReplayFrame[] {
  const docs: ArcReplayFrame[] = [];
  let previa: Grid | null = null;
  for (const frame of ventana.frames) {
    const codificado = encodeGridDiff(previa, frame.grilla as Grid);
    if (codificado === null) continue;
    const tieneClick = typeof frame.x === 'number' && typeof frame.y === 'number';
    docs.push({
      runId: ventana.corrida,
      gameId: ventana.juego,
      modelId: ventana.modelo || 'harness-local',
      stepNum: frame.paso,
      action: frame.accion,
      ...(tieneClick ? { x: frame.x as number, y: frame.y as number } : {}),
      availableActions: accionesValidas(frame.accionesDisponibles),
      gridWidth: codificado.width,
      gridHeight: codificado.height,
      diffRle: codificado.rle,
      changedCells: codificado.changedCells,
      levelsCompleted: Math.max(0, Math.trunc(frame.nivelesCompletados ?? 0)),
      winLevels: Math.max(0, Math.trunc(frame.nivelesParaGanar ?? 0)),
      // BL.21794: solo si la captura la trae. Se omite el campo en vez de escribir un default --
      // un `''` haria indistinguible "capturado sin clasificar" de "clasificado como nada", y esa
      // distincion es justamente la que el informe necesita para no presentar una reconstruccion
      // como dato del corpus.
      ...(typeof frame.claseDePaso === 'string' && frame.claseDePaso.length > 0
        ? { claseDePaso: frame.claseDePaso }
        : {}),
      ...(typeof frame.firmaDelPaso === 'string' && frame.firmaDelPaso.length > 0
        ? { firmaDelPaso: frame.firmaDelPaso }
        : {}),
      // BL.21798: la semilla es de la PARTIDA, no del frame, pero viaja por frame porque el corpus
      // se persiste frame a frame y el export reconstruye la ventana desde ahi. Misma regla que
      // arriba: se omite si no vino, nunca se rellena con el lote.
      ...(typeof ventana.semilla === 'string' && ventana.semilla.length > 0
        ? { semilla: ventana.semilla }
        : {}),
      ts,
      createdAt: ts,
      ...marcasDeRetencion(MOTIVO_RETENCION_VENTANA_DE_NIVEL, ts),
    });
    previa = frame.grilla as Grid;
  }
  return docs;
}

/** Resumen de una ingesta -- lo que el operador necesita para saber si el corpus quedo bien. */
export interface ResumenDeIngesta {
  ventanas: number;
  documentos: number;
  documentosConNivel: number;
  juegos: string[];
}

/** Documentos de VARIAS ventanas + el resumen. Deduplica por {runId, stepNum} conservando el
 *  PRIMERO: dos ventanas de la misma partida pueden solaparse (dos subidas de nivel a menos de 20
 *  pasos, medido en sc25: 1298 y 1375 estan lejos, pero lp85 no garantiza nada), y el upsert de
 *  Mongo dejaria pasar el segundo pisando al primero con un diff calculado contra OTRA cadena. */
export function documentosDeVentanas(
  ventanas: VentanaDeNivel[],
  ts: Date,
): { docs: ArcReplayFrame[]; grupos: ArcReplayFrame[][]; resumen: ResumenDeIngesta } {
  const vistos = new Set<string>();
  const docs: ArcReplayFrame[] = [];
  // `grupos` es la MISMA lista, particionada por ventana. BL.21849: la ventana es la unidad atomica
  // de escritura porque su primer frame lleva el RLE completo y los demas son diffs contra el
  // anterior de la MISMA ventana -- una ventana sin su primer frame es INDECODIFICABLE. Escribir en
  // lotes planos de 25 documentos partia ventanas de 21 por la mitad.
  const grupos: ArcReplayFrame[][] = [];
  for (const ventana of ventanas) {
    const grupo: ArcReplayFrame[] = [];
    for (const doc of documentosDeVentana(ventana, ts)) {
      const clave = `${doc.runId}#${doc.stepNum}`;
      if (vistos.has(clave)) continue;
      vistos.add(clave);
      docs.push(doc);
      grupo.push(doc);
    }
    if (grupo.length > 0) grupos.push(grupo);
  }
  return {
    docs,
    grupos,
    resumen: {
      ventanas: ventanas.length,
      documentos: docs.length,
      documentosConNivel: docs.filter((d) => d.levelsCompleted > 0).length,
      juegos: [...new Set(ventanas.map((v) => v.juego))].sort(),
    },
  };
}
