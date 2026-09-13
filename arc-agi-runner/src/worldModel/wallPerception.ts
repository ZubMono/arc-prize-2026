/* [arc-agi-runner/worldModel/wallPerception] BL.21593 -- PERCEPCION del termino observable de la
   verosimilitud del fallo: `P(pared | grilla)`. La pared se VE -- este modulo la mira. Espejo
   EXACTO de arc-agi3-kaggle-agent/arc_agent/wall_perception.py.

   Dos piezas, ambas capa de percepcion (consumen grilla y mecanicas de BL.21561, jamas game_id):

   - `RastreadorDeAvatar`: el avatar es el ultimo objeto que se TRASLADO (el cursor que BL.21561
     ya detecta) y el PISO es el color que dejan las celdas que desaloja -- la misma evidencia
     `relleno` que el detector de traslaciones exige. Sin esto la pared no es evaluable.
   - `contextoDePared`: para cada direccion, mira la franja de celdas por delante de la caja del
     avatar; borde del tablero o cualquier celda que no sea piso = pared presente.

   El consumidor es la capa de creencia (mechanicsPosterior.ts): un fallo de movimiento con pared
   presente en la direccion de la hipotesis queda TOTALMENTE explicado y no mueve el posterior. */

import { DIRECTION_PRIORS } from './directionPriors';
import type { Grid } from './grid';
import type { Mecanica } from './objectMechanics';

const MECANICA_ARRIBA = 'arriba';
const MECANICA_ABAJO = 'abajo';
const MECANICA_IZQUIERDA = 'izquierda';
const MECANICA_DERECHA = 'derecha';

/** Signo (dy,dx) de cada mecanica direccional -- y crece hacia abajo, x hacia la derecha. Vive
 *  en la capa de percepcion porque el contexto de pared se evalua POR DIRECCION; la capa de
 *  creencia lo importa como parte del vocabulario. */
export const DIRECCIONES: Readonly<Record<string, readonly [number, number]>> = {
  [MECANICA_ARRIBA]: [-1, 0],
  [MECANICA_ABAJO]: [1, 0],
  [MECANICA_IZQUIERDA]: [0, -1],
  [MECANICA_DERECHA]: [0, 1],
};

export const PARED_PRESENTE = 'presente';
export const PARED_AUSENTE = 'ausente';
export const PARED_DESCONOCIDA = 'desconocida';
export type ContextoDePared =
  | typeof PARED_PRESENTE
  | typeof PARED_AUSENTE
  | typeof PARED_DESCONOCIDA;

/** Caja del avatar: [minY, minX, alto, ancho]. */
export type CajaDeAvatar = readonly [number, number, number, number];

/** Cuantas celdas por delante del avatar se inspeccionan buscando pared. Si la magnitud del paso
 *  del boton ya se midio, el camino que el paso necesita libre es exactamente esa; si no, la
 *  maxima magnitud medida en los 25 juegos (conservador: ante la duda, mas fallos quedan
 *  explicados por pared y el posterior se mueve menos -- el lado seguro del error). */
export function profundidadDeSondeo(magnitud: readonly [number, number] | null): number {
  if (magnitud !== null) return Math.max(1, Math.abs(magnitud[0]) + Math.abs(magnitud[1]));
  const magnitudes = DIRECTION_PRIORS.magnitudesDePasoMedidas;
  return magnitudes.length > 0 ? Math.max(...magnitudes) : 1;
}

/** `presente`/`ausente` por direccion, mirando la franja de `profundidad` celdas por delante de
 *  la caja del avatar: cualquier celda que no sea del color del piso (o el borde del tablero) es
 *  pared. Sin avatar o sin piso conocidos, todo es `desconocida` -- el fallo inexplicable que
 *  aporta poco pero no cero. */
export function contextoDePared(
  grilla: Grid | null,
  caja: CajaDeAvatar | null,
  piso: number | null,
  profundidad: number,
): Record<string, ContextoDePared> {
  const contexto: Record<string, ContextoDePared> = {};
  if (
    grilla === null ||
    caja === null ||
    piso === null ||
    grilla.length === 0 ||
    grilla[0].length === 0
  ) {
    // @proto-safe: claves = las 4 direcciones constantes del modulo
    for (const nombre of Object.keys(DIRECCIONES)) contexto[nombre] = PARED_DESCONOCIDA; // @proto-safe: 4 direcciones const
    return contexto;
  }
  const alto = grilla.length;
  const ancho = grilla[0].length;
  const [minY, minX, altoCaja, anchoCaja] = caja;
  for (const [nombre, [dy, dx]] of Object.entries(DIRECCIONES)) {
    let hayPared = false;
    for (let paso = 1; paso <= profundidad && !hayPared; paso++) {
      const celdas: Array<[number, number]> = [];
      if (dy !== 0) {
        const fila = dy < 0 ? minY - paso : minY + altoCaja - 1 + paso;
        for (let x = minX; x < minX + anchoCaja; x++) celdas.push([fila, x]);
      } else {
        const columna = dx < 0 ? minX - paso : minX + anchoCaja - 1 + paso;
        for (let y = minY; y < minY + altoCaja; y++) celdas.push([y, columna]);
      }
      for (const [y, x] of celdas) {
        if (y < 0 || x < 0 || y >= alto || x >= ancho || grilla[y][x] !== piso) {
          hayPared = true;
          break;
        }
      }
    }
    contexto[nombre] = hayPared ? PARED_PRESENTE : PARED_AUSENTE; // @proto-safe: claves = 4 direcciones del modulo
  }
  return contexto;
}

/** Posicion vigente del objeto controlado y el color del PISO que deja al moverse.
 *
 *  El avatar es el ultimo objeto que se traslado (el cursor de BL.21561); el piso se lee de las
 *  celdas que DESALOJO. Es la percepcion que vuelve observable a `P(pared | grilla)`. */
export class RastreadorDeAvatar {
  caja: CajaDeAvatar | null = null;
  piso: number | null = null;

  observar(mecanica: Mecanica | null, post: Grid | null): void {
    if (mecanica === null || mecanica.traslacionPrincipal === null || post === null) return;
    const t = mecanica.traslacionPrincipal;
    this.caja = [t.minY + t.dy, t.minX + t.dx, t.alto, t.ancho];
    const conteo = new Map<number, number>();
    for (let y = t.minY; y < t.minY + t.alto; y++) {
      for (let x = t.minX; x < t.minX + t.ancho; x++) {
        const enDestino =
          t.minY + t.dy <= y &&
          y < t.minY + t.dy + t.alto &&
          t.minX + t.dx <= x &&
          x < t.minX + t.dx + t.ancho;
        if (enDestino || y < 0 || x < 0 || y >= post.length || x >= post[0].length) continue;
        const color = post[y][x];
        conteo.set(color, (conteo.get(color) ?? 0) + 1);
      }
    }
    if (conteo.size > 0) {
      // Desempate por color menor: identico al puerto Python (max sobre colores ordenados).
      let mejor = -1;
      let mejorConteo = -1;
      for (const color of [...conteo.keys()].sort((a, b) => a - b)) {
        const c = conteo.get(color) as number;
        if (c > mejorConteo) {
          mejor = color;
          mejorConteo = c;
        }
      }
      this.piso = mejor;
    }
  }
}
