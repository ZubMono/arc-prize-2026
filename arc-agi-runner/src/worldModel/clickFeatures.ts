/* [arc-agi-runner/worldModel/clickFeatures] BL.21560 -- vector de features POR CELDA para decidir
   DONDE clickear (ACTION6), y su combinacion lineal con los pesos de `clickPriors.ts`.

   EL PROBLEMA, medido sobre el corpus real (`arcReplayFrames`, corrida ft09-0d8bbf25):
   346 clicks, 32 productivos (9,2%). La heuristica previa (`pickClickTarget`) elegia UNIFORMEMENTE
   entre el decil superior de celdas "borde de color" -- unos 410 candidatos de 4096, de los cuales
   solo ~36 son las esquinas de las fichas del tablero jugable. 36/410 = 8,8%: la tasa medida no era
   mala suerte, era exactamente lo que predice tirar al azar dentro de ese conjunto.

   POR QUE ESTAS FEATURES Y NO OTRAS. Todas salen de helpers que YA existen (`grid.ts` +
   `findComponents` de `primitiveOps.ts`): son la misma segmentacion que ve el modelo de mundo, no
   una vision paralela. Y ninguna mira coordenadas absolutas ni identificadores de partida -- un
   peso aprendido en un juego tiene que poder servir en otro, que es la unica razon para transportar
   pesos. La feature que mas separa en el corpus real es `componenteRodeadaDeFondo`: el mismo dibujo
   (una ficha 6x6 de color 9) aparece DOS veces en pantalla -- como panel decorativo rodeado por el
   fondo, y como ficha jugable rodeada por el marco del tablero. Clickear la primera no hace nada
   (62 clicks muertos medidos); clickear la segunda siempre funciona (32 de 32). Nada del color ni
   del tamano distingue una de la otra: lo hace el VECINDARIO de su componente.

   Los pesos NO se escriben a mano: los ajusta `arc-agi3-kaggle-agent/scripts/fit_click_priors.py`
   por regresion logistica contra el corpus real y los emite a `clickPriors.ts` (este puerto) y a
   `arc_agent/priors.py` (el puerto Python). */

import {
  detectBackgroundColor,
  foregroundBoundingBox,
  type BoundingBox,
  type Grid,
} from './grid';
import { findComponents } from './primitiveOps';

/** ORDEN CANONICO de las features -- es un CONTRATO con `clickPriors.ts` y con el puerto Python
 *  (`arc_agent/click_targeting.py`): los pesos son un array posicional, asi que reordenar esta
 *  lista sin regenerar los priors invierte silenciosamente el significado de cada peso. El primer
 *  elemento es el sesgo (siempre 1). */
export const CLICK_FEATURE_NAMES = [
  'sesgo',
  'bordeDeColor',
  'tamanoComponente',
  'esBordeDeComponente',
  'rarezaDeColor',
  'esColorDeFondo',
  'distanciaAlBboxDeForeground',
  'componenteRodeadaDeFondo',
  'enRegionQueCambio',
] as const;

export const CLICK_FEATURE_COUNT = CLICK_FEATURE_NAMES.length;

/** Normalizador de `tamanoComponente`. 256 celdas = 1/16 de un frame 64x64: por encima de eso la
 *  "componente" ya es una region de fondo o un panel entero, no un objeto clickeable. Satura en 1
 *  para que un fondo gigante no domine el producto punto por magnitud. */
const TAMANO_COMPONENTE_SATURACION = 256;

/** Radio del parche que se guarda como plantilla al detectar un click con efecto (3x3 = radio 1).
 *  Fuente unica: lo usan `clickMemory.ts` y su espejo Python. */
export const RADIO_PARCHE = 1;

/** Valor de una celda del parche que cae FUERA de la grilla. -1 no colisiona con ningun color ARC
 *  (0-15), asi que dos parches de borde solo matchean si el borde cae en el mismo lugar. */
export const PARCHE_FUERA_DE_GRILLA = -1;

export interface ClickFeatureBoardOptions {
  /** Rectangulo que cambio en la ULTIMA transicion observada, o `null` si no hubo/no se sabe.
   *  Alimenta la feature `enRegionQueCambio`: lo que se acaba de mover suele ser lo que responde. */
  regionCambiada?: BoundingBox | null;
}

/** Features ya calculadas para TODAS las celdas de una grilla. Se construye UNA vez por frame:
 *  segmentar en componentes es O(celdas) y hacerlo por candidato seria cuadratico. */
export interface ClickFeatureBoard {
  readonly ancho: number;
  readonly alto: number;
  readonly colorDeFondo: number;
  /** Vector de features de (x,y), en el orden de `CLICK_FEATURE_NAMES`. */
  features(x: number, y: number): number[];
  /** Tamano de la componente 4-conexa de (x,y); 0 si la celda es del color de fondo. */
  tamanoDeComponente(x: number, y: number): number;
}

function bboxContiene(bbox: BoundingBox, x: number, y: number): boolean {
  return x >= bbox.minX && x <= bbox.maxX && y >= bbox.minY && y <= bbox.maxY;
}

/** Distancia Chebyshev de (x,y) al rectangulo, 0 si esta adentro. */
function distanciaAlBBox(bbox: BoundingBox, x: number, y: number): number {
  const dx = Math.max(bbox.minX - x, 0, x - bbox.maxX);
  const dy = Math.max(bbox.minY - y, 0, y - bbox.maxY);
  return Math.max(dx, dy);
}

export function construirTableroDeFeatures(
  grid: Grid,
  opts: ClickFeatureBoardOptions = {},
): ClickFeatureBoard {
  const alto = grid.length;
  const ancho = alto > 0 ? (grid[0]?.length ?? 0) : 0;
  const total = ancho * alto;
  const colorDeFondo = detectBackgroundColor(grid);
  const fgBBox = foregroundBoundingBox(grid, colorDeFondo);
  const regionCambiada = opts.regionCambiada ?? null;

  /* Conteo global de colores -- alimenta `rarezaDeColor`. */
  const conteoDeColor = new Map<number, number>();
  for (let y = 0; y < alto; y++) {
    const fila = grid[y];
    for (let x = 0; x < ancho; x++) {
      const c = fila[x];
      conteoDeColor.set(c, (conteoDeColor.get(c) ?? 0) + 1);
    }
  }

  /* Segmentacion en componentes 4-conexas -- la MISMA que usa el DSL (objectExtract). */
  const etiqueta = new Int32Array(total).fill(-1);
  const componentes = findComponents(grid, colorDeFondo);
  const tamanos = new Int32Array(componentes.length);
  for (let i = 0; i < componentes.length; i++) {
    tamanos[i] = componentes[i].length;
    for (const [cx, cy] of componentes[i]) etiqueta[cy * ancho + cx] = i;
  }

  /* Fraccion del CONTORNO de cada componente que toca el color de fondo. Es lo que separa un panel
     decorativo (flotando sobre el fondo) de una ficha dentro de un tablero (rodeada por el marco). */
  const rodeadaDeFondo = new Float64Array(componentes.length);
  for (let i = 0; i < componentes.length; i++) {
    let contorno = 0;
    let contornoDeFondo = 0;
    for (const [cx, cy] of componentes[i]) {
      const vecinos: Array<[number, number]> = [
        [cx - 1, cy],
        [cx + 1, cy],
        [cx, cy - 1],
        [cx, cy + 1],
      ];
      for (const [vx, vy] of vecinos) {
        const dentro = vx >= 0 && vy >= 0 && vx < ancho && vy < alto;
        if (dentro && etiqueta[vy * ancho + vx] === i) continue;
        contorno++;
        if (dentro && grid[vy][vx] === colorDeFondo) contornoDeFondo++;
      }
    }
    rodeadaDeFondo[i] = contorno > 0 ? contornoDeFondo / contorno : 0;
  }

  const maxDistancia = Math.max(ancho, alto, 1);

  return {
    ancho,
    alto,
    colorDeFondo,
    tamanoDeComponente(x: number, y: number): number {
      if (x < 0 || y < 0 || x >= ancho || y >= alto) return 0;
      const id = etiqueta[y * ancho + x];
      return id < 0 ? 0 : tamanos[id];
    },
    features(x: number, y: number): number[] {
      if (x < 0 || y < 0 || x >= ancho || y >= alto) {
        return new Array<number>(CLICK_FEATURE_COUNT).fill(0);
      }
      const valor = grid[y][x];
      const id = etiqueta[y * ancho + x];

      let bordeDeColor = 0;
      if (x > 0 && grid[y][x - 1] !== valor) bordeDeColor++;
      if (x < ancho - 1 && grid[y][x + 1] !== valor) bordeDeColor++;
      if (y > 0 && grid[y - 1][x] !== valor) bordeDeColor++;
      if (y < alto - 1 && grid[y + 1][x] !== valor) bordeDeColor++;

      const tamano = id < 0 ? 0 : tamanos[id];
      /* Borde de la COMPONENTE, no de la grilla: una celda cuya componente se corta contra el
         limite del frame tambien cuenta (el vecino inexistente no pertenece a la componente). */
      const esBorde =
        id >= 0 &&
        (x === 0 ||
          y === 0 ||
          x === ancho - 1 ||
          y === alto - 1 ||
          etiqueta[y * ancho + (x - 1)] !== id ||
          etiqueta[y * ancho + (x + 1)] !== id ||
          etiqueta[(y - 1) * ancho + x] !== id ||
          etiqueta[(y + 1) * ancho + x] !== id);

      const conteo = conteoDeColor.get(valor) ?? 0;
      const rareza = total > 0 ? 1 - conteo / total : 0;

      return [
        1,
        bordeDeColor / 4,
        Math.min(1, tamano / TAMANO_COMPONENTE_SATURACION),
        esBorde ? 1 : 0,
        rareza,
        valor === colorDeFondo ? 1 : 0,
        fgBBox === null ? 1 : distanciaAlBBox(fgBBox, x, y) / maxDistancia,
        id < 0 ? 0 : rodeadaDeFondo[id],
        regionCambiada !== null && bboxContiene(regionCambiada, x, y) ? 1 : 0,
      ];
    },
  };
}

/** Producto punto features x pesos (logit). Pesos de largo distinto al vector se recortan/rellenan
 *  con 0: un `priors.ts` regenerado con una feature de mas nunca debe hacer crashear una partida,
 *  degrada a ignorar lo que no entiende. */
export function puntuarCelda(features: number[], pesos: readonly number[]): number {
  let acumulado = 0;
  const n = Math.min(features.length, pesos.length);
  for (let i = 0; i < n; i++) acumulado += features[i] * pesos[i];
  return acumulado;
}

/** Probabilidad logistica -- solo para reportar/umbralar; el ranking usa el logit directo. */
export function sigmoide(logit: number): number {
  if (logit >= 0) return 1 / (1 + Math.exp(-logit));
  const e = Math.exp(logit);
  return e / (1 + e);
}

/** Parche cuadrado de lado `2*RADIO_PARCHE+1` centrado en (x,y), aplanado en orden row-major.
 *  Las celdas fuera de la grilla valen `PARCHE_FUERA_DE_GRILLA`. */
export function extraerParche(grid: Grid, x: number, y: number): number[] {
  const alto = grid.length;
  const ancho = alto > 0 ? (grid[0]?.length ?? 0) : 0;
  const parche: number[] = [];
  for (let dy = -RADIO_PARCHE; dy <= RADIO_PARCHE; dy++) {
    for (let dx = -RADIO_PARCHE; dx <= RADIO_PARCHE; dx++) {
      const px = x + dx;
      const py = y + dy;
      const dentro = px >= 0 && py >= 0 && px < ancho && py < alto;
      parche.push(dentro ? grid[py][px] : PARCHE_FUERA_DE_GRILLA);
    }
  }
  return parche;
}

/** Similitud entre dos parches: fraccion de celdas iguales, en [0,1]. Largos distintos (imposible
 *  hoy, pero barato de blindar) comparan solo el prefijo comun. */
export function similitudDeParche(a: readonly number[], b: readonly number[]): number {
  const n = Math.min(a.length, b.length);
  if (n === 0) return 0;
  let iguales = 0;
  for (let i = 0; i < n; i++) if (a[i] === b[i]) iguales++;
  return iguales / n;
}

/** Rectangulo que cambio entre dos grillas, o `null` si no cambio nada (o si no son comparables).
 *  Alimenta la feature `enRegionQueCambio`. */
export function regionQueCambio(pre: Grid | null, post: Grid | null): BoundingBox | null {
  if (pre === null || post === null) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const alto = Math.min(pre.length, post.length);
  for (let y = 0; y < alto; y++) {
    const ancho = Math.min(pre[y]?.length ?? 0, post[y]?.length ?? 0);
    for (let x = 0; x < ancho; x++) {
      if (pre[y][x] === post[y][x]) continue;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }
  if (maxX < minX) return null;
  return { minX, minY, maxX, maxY };
}
