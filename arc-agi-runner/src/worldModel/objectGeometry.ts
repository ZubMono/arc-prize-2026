/* [arc-agi-runner/worldModel/objectGeometry] BL.21561 -- geometria de objetos sobre una grilla:
   agrupacion de celdas cambiadas en clusters, bounding boxes y las dos mediciones que distinguen
   "aca se movio un OBJETO" de "aca se recorto un pedazo del fondo". Sin estado y sin dependencias
   fuera de grid.ts -- separado de objectMechanics.ts solo para respetar el limite de 500 lineas
   (misma responsabilidad conceptual: el analizador objeto-centrico). */

import { isVolatileCell } from './grid';
import type { BoundingBox, Grid, VolatilityMask } from './grid';

/** Radio del anillo de contexto con el que se estima el fondo LOCAL alrededor de un cluster. El
 *  fondo GLOBAL de la grilla no sirve: en dc22-fdcac232 el color mas frecuente del frame es la
 *  pared del marco (4) y el piso de la arena por el que se mueve el cursor es otro (2). */
export const RADIO_DE_FONDO_LOCAL = 2;

export type Celda = [number, number];

export function claveDeCelda(y: number, x: number): string {
  return `${y},${x}`;
}

/** Agrupa celdas en clusters 8-conexos. 8 y no 4 a proposito: un objeto que se mueve en diagonal
 *  deja la region que abandona y la que ocupa tocandose solo por la esquina, y son UN evento. */
export function agruparEnClusters(celdas: Celda[]): Celda[][] {
  const pendientes = new Set(celdas.map(([y, x]) => claveDeCelda(y, x)));
  const grupos: Celda[][] = [];
  for (const [y0, x0] of celdas) {
    if (!pendientes.has(claveDeCelda(y0, x0))) continue;
    pendientes.delete(claveDeCelda(y0, x0));
    const pila: Celda[] = [[y0, x0]];
    const grupo: Celda[] = [];
    while (pila.length > 0) {
      const [y, x] = pila.pop() as Celda;
      grupo.push([y, x]);
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          const k = claveDeCelda(y + dy, x + dx);
          if (pendientes.has(k)) {
            pendientes.delete(k);
            pila.push([y + dy, x + dx]);
          }
        }
      }
    }
    grupos.push(grupo);
  }
  return grupos;
}

export function cajaDeCeldas(celdas: Celda[]): BoundingBox {
  let minY = Infinity;
  let minX = Infinity;
  let maxY = -Infinity;
  let maxX = -Infinity;
  for (const [y, x] of celdas) {
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
  }
  return { minY, minX, maxY, maxX };
}

/** Fraccion de `caja` ocupada por componentes 4-conexas monocromas ENTERAMENTE contenidas en ella
 *  y de tamano <= `maxTamanoObjeto` -- la definicion operativa de "aca hay un objeto acotado".
 *  Un cursor da 1.0; un recorte del piso da 0, porque su componente se escapa de la caja. */
export function coberturaDeObjetos(grid: Grid, caja: BoundingBox, maxTamanoObjeto: number): number {
  const alto = grid.length;
  const ancho = grid[0]?.length ?? 0;
  const anchoCaja = caja.maxX - caja.minX + 1;
  const visto = new Uint8Array((caja.maxY - caja.minY + 1) * anchoCaja);
  const indice = (y: number, x: number): number => (y - caja.minY) * anchoCaja + (x - caja.minX);
  let cubiertas = 0;

  for (let y0 = caja.minY; y0 <= caja.maxY; y0++) {
    for (let x0 = caja.minX; x0 <= caja.maxX; x0++) {
      if (visto[indice(y0, x0)] === 1) continue;
      const color = grid[y0][x0];
      visto[indice(y0, x0)] = 1;
      const pila: Celda[] = [[y0, x0]];
      let tamano = 0;
      let seEscapa = false;
      while (pila.length > 0) {
        const [y, x] = pila.pop() as Celda;
        tamano++;
        const vecinas: Celda[] = [
          [y + 1, x],
          [y - 1, x],
          [y, x + 1],
          [y, x - 1],
        ];
        for (const [ny, nx] of vecinas) {
          if (ny < 0 || nx < 0 || ny >= alto || nx >= ancho) continue;
          if (grid[ny][nx] !== color) continue;
          if (ny < caja.minY || ny > caja.maxY || nx < caja.minX || nx > caja.maxX) {
            seEscapa = true;
            continue;
          }
          if (visto[indice(ny, nx)] === 1) continue;
          visto[indice(ny, nx)] = 1;
          pila.push([ny, nx]);
        }
      }
      if (!seEscapa && tamano <= maxTamanoObjeto) cubiertas += tamano;
    }
  }
  return cubiertas / ((caja.maxY - caja.minY + 1) * anchoCaja);
}

/** Color mas frecuente de `grid` en el anillo que rodea a `caja`, IGNORANDO las celdas de
 *  `excluidas` (las que cambiaron: son el evento, no el contexto). Empate: el color de menor
 *  indice, para determinismo bit a bit entre el motor TS y el puerto Python. */
export function fondoLocal(grid: Grid, excluidas: Celda[], caja: BoundingBox): number {
  const fuera = new Set(excluidas.map(([y, x]) => claveDeCelda(y, x)));
  const conteo = new Map<number, number>();
  const desdeY = Math.max(0, caja.minY - RADIO_DE_FONDO_LOCAL);
  const hastaY = Math.min(grid.length - 1, caja.maxY + RADIO_DE_FONDO_LOCAL);
  for (let y = desdeY; y <= hastaY; y++) {
    const desdeX = Math.max(0, caja.minX - RADIO_DE_FONDO_LOCAL);
    const hastaX = Math.min(grid[y].length - 1, caja.maxX + RADIO_DE_FONDO_LOCAL);
    for (let x = desdeX; x <= hastaX; x++) {
      if (fuera.has(claveDeCelda(y, x))) continue;
      conteo.set(grid[y][x], (conteo.get(grid[y][x]) ?? 0) + 1);
    }
  }
  let fondo = -1;
  let mejor = -1;
  for (const [color, n] of [...conteo.entries()].sort((a, b) => a[0] - b[0])) {
    if (n > mejor) {
      fondo = color;
      mejor = n;
    }
  }
  return fondo;
}

/* ── BL.21853 -- objeto ENTERO: la via que ve al multicelda que se va lejos ─────────────────── */

/** Tope de celdas de un OBJETO (no del area de su caja). Es la diferencia que hace a esta via: el
 *  analisis por cluster acota el AREA DE LA CAJA (`MAX_TAMANO_OBJETO`, 256) y un objeto de 153
 *  celdas repartido en una caja de 17x17=289 ya no entra, aunque el objeto sea chico. Medido sobre
 *  las 7.258 transiciones de `arcReplayFrames` (BL.21853): los objetos que esta via recupera miden
 *  53 y 153 celdas, o sea que 256 celdas los cubre a los dos. */
export const MAX_CELDAS_DE_OBJETO_ENTERO = 256;

/** Tope de pares (objeto de pre, objeto de post) con la MISMA forma que se prueban antes de
 *  rendirse. Guarda de costo para el tablero embaldosado: una grilla con 40 fichas identicas da
 *  1.600 pares y ninguno explica el cambio. */
export const MAX_PARES_DE_OBJETO = 64;

/** Componentes 4-conexas de celdas distintas de `fondo` que contienen alguna celda de `semillas`.
 *  Color-AGNOSTICO puertas adentro: un avatar de dos colores es UN objeto, no dos.
 *  NO es la misma nocion de objeto que `coberturaDeObjetos`: aquella exige MONOCROMIA y se ata a
 *  una caja; esta no hace ninguna de las dos cosas. Son dos definiciones distintas de "objeto"
 *  conviviendo en el arbol -- enumerado a proposito en vez de decir que se reusa una sola:
 *  BL.21853 lo afirmo de mas y la revision lo midio.
 *  Descarta la componente que supera `maxCeldas` celdas -- eso ya no es un objeto, es el tablero
 *  -- y la descarta ENTERA: al pasarse el tope sigue recorriendola solo para marcarla como vista,
 *  porque cortar el recorrido dejaba el resto sin visitar y una semilla posterior lo volvia a
 *  floodear y emitia un PEDAZO de esa misma componente como si fuera un objeto. Medido (BL.21853,
 *  revision): corredor 4-conexo de 304 celdas con tope 256, semillas en los dos extremos ->
 *  devolvia un "objeto" de 47 celdas; con una sola semilla devolvia []. O sea que la salida
 *  dependia de QUE celdas cambiaron y no solo de la grilla.
 *  Orden DETERMINISTA (el de `semillas`, que llega en barrido por filas): los dos puertos tienen
 *  que elegir el mismo candidato cuando hay varios. */
export function objetosQueTocan(
  grid: Grid,
  fondo: number,
  semillas: Celda[],
  maxCeldas: number,
): Celda[][] {
  const alto = grid.length;
  const ancho = grid[0]?.length ?? 0;
  const visto = new Set<string>();
  const salida: Celda[][] = [];
  for (const [sy, sx] of semillas) {
    if (visto.has(claveDeCelda(sy, sx)) || grid[sy][sx] === fondo) continue;
    const pila: Celda[] = [[sy, sx]];
    visto.add(claveDeCelda(sy, sx));
    const celdas: Celda[] = [];
    let excedido = false;
    while (pila.length > 0) {
      const [y, x] = pila.pop() as Celda;
      if (!excedido) {
        // Al pasarse el tope se sigue recorriendo SOLO para dejar la componente entera en `visto`.
        // Sin esto, el remanente no visitado quedaba disponible para una semilla posterior y salia
        // como objeto propio.
        celdas.push([y, x]);
        if (celdas.length > maxCeldas) {
          excedido = true;
          celdas.length = 0;
        }
      }
      const vecinas: Celda[] = [
        [y + 1, x],
        [y - 1, x],
        [y, x + 1],
        [y, x - 1],
      ];
      for (const [ny, nx] of vecinas) {
        if (ny < 0 || nx < 0 || ny >= alto || nx >= ancho) continue;
        if (visto.has(claveDeCelda(ny, nx)) || grid[ny][nx] === fondo) continue;
        visto.add(claveDeCelda(ny, nx));
        pila.push([ny, nx]);
      }
    }
    if (!excedido) {
      celdas.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      salida.push(celdas);
    }
  }
  return salida;
}

/** Forma del objeto normalizada a su esquina superior izquierda, con el color de cada celda (como
 *  clave canonica ordenada), y esa esquina. Dos objetos con la misma clave son el MISMO objeto en
 *  otra posicion. */
export function formaConColor(celdas: Celda[], grid: Grid): { clave: string; esquina: Celda } {
  let my = Infinity;
  let mx = Infinity;
  for (const [y, x] of celdas) {
    if (y < my) my = y;
    if (x < mx) mx = x;
  }
  const partes = celdas.map(([y, x]) => `${y - my},${x - mx},${grid[y][x]}`).sort();
  return { clave: partes.join(';'), esquina: [my, mx] };
}

/** RECONSTRUYE `post` a partir de `pre` moviendo `objeto` por (dy,dx) y exige que quede EXACTO.
 *  Es lo que separa esta via de un match de formas: en un tablero embaldosado hay decenas de
 *  objetos con la misma forma y "alguno coincide desplazado" no dice nada. Aca se pide (a) que TODA
 *  celda cambiada este en el origen o en el destino y (b) que el destino tenga el contenido del
 *  objeto y el origen desalojado tenga el fondo. La diferencia entre los dos criterios esta MEDIDA
 *  sobre el corpus: 564 transiciones con el criterio flojo contra 146 con este. */
function objetoExplicaElCambio(
  pre: Grid,
  post: Grid,
  cambios: Set<string>,
  fondo: number,
  objeto: Celda[],
  dy: number,
  dx: number,
  mask: VolatilityMask | null,
): boolean {
  const alto = pre.length;
  const ancho = pre[0].length;
  const destino = new Map<string, number>();
  for (const [y, x] of objeto) {
    const ny = y + dy;
    const nx = x + dx;
    if (ny < 0 || nx < 0 || ny >= alto || nx >= ancho) return false;
    destino.set(claveDeCelda(ny, nx), pre[y][x]);
  }
  const tocadas = new Map<string, Celda>();
  for (const [y, x] of objeto) tocadas.set(claveDeCelda(y, x), [y, x]);
  for (const [y, x] of objeto) tocadas.set(claveDeCelda(y + dy, x + dx), [y + dy, x + dx]);
  for (const clave of cambios) if (!tocadas.has(clave)) return false;
  for (const [clave, [y, x]] of tocadas) {
    if (isVolatileCell(mask, y, x)) continue;
    const esperado = destino.has(clave) ? (destino.get(clave) as number) : fondo;
    if (post[y][x] !== esperado) return false;
  }
  return true;
}

/** (dy, dx, celdas del objeto) si UN objeto entero se movio y eso explica TODO el cambio.
 *
 *  POR QUE HACE FALTA (BL.21853, medido sobre 7.258 transiciones reales). El analisis por cluster
 *  de `objectMechanics` despeja la caja `R` del bbox del cluster, o sea que solo ve al objeto que
 *  se mueve MENOS que su propio ancho; y acota `R` por AREA (256), que un objeto grande desborda
 *  aunque tenga pocas celdas. Un objeto que salta lejos deja dos clusters disjuntos y ninguno se
 *  explica solo. Resultado medido: 146 transiciones (2,01% del corpus) que hoy caen en
 *  `desconocida` son traslaciones rigidas CARDINALES de objetos de 53 y 153 celdas.
 *
 *  ALCANCE DE ESE 146, que la revision midio y el enunciado original no decia: las 146 salen de
 *  DOS juegos de los 27 con transiciones (re86-8af5384d 77, cn04-2fe56bfb 69). Es el mismo
 *  criterio con el que el BL descarto `rotacion` por venir de un solo juego, asi que lo honesto es
 *  "medido en dos escenas", no "confirmado sobre el corpus". Se conserva porque es la unica
 *  informacion NUEVA del paquete y porque su criterio de aceptacion es una reconstruccion exacta;
 *  no hay evidencia de que generalice a los otros 25 juegos.
 *
 *  NO reemplaza al analisis por cluster: `objectMechanics` la llama SOLO cuando ese analisis y su
 *  respaldo fusionado no dieron NINGUNA traslacion (`if (conTraslacion.length === 0)`). Esa guarda
 *  no dice "la transicion no estaba explicada": un paso cuyo tipo global es `recoloreo`/
 *  `aparicion`/`desaparicion` entra igual y estructuralmente puede cambiar de respuesta. Lo medido
 *  es mas chico que eso -- sobre las 7.258 transiciones del corpus las 146 salen las 146 de
 *  `desconocida` -- y es lo unico que se afirma. La version anterior de esta linea decia "ninguna
 *  transicion que hoy se explica cambia de respuesta", que es una propiedad universal que el
 *  codigo no sostiene (RFM-07, corregido en la revision de BL.21853). */
export function traslacionDeObjetoEntero(
  pre: Grid,
  post: Grid,
  cambios: Celda[],
  fondo: number,
  mask: VolatilityMask | null = null,
  maxCeldas: number = MAX_CELDAS_DE_OBJETO_ENTERO,
  maxPares: number = MAX_PARES_DE_OBJETO,
): { dy: number; dx: number; objeto: Celda[] } | null {
  if (cambios.length === 0) return null;
  const conjunto = new Set(cambios.map(([y, x]) => claveDeCelda(y, x)));
  const objetosPre = objetosQueTocan(pre, fondo, cambios, maxCeldas);
  if (objetosPre.length === 0) return null;
  const objetosPost = objetosQueTocan(post, fondo, cambios, maxCeldas);
  if (objetosPost.length === 0) return null;

  const indice = new Map<string, Celda[]>();
  for (const celdas of objetosPost) {
    const { clave, esquina } = formaConColor(celdas, post);
    const lista = indice.get(clave);
    if (lista === undefined) indice.set(clave, [esquina]);
    else lista.push(esquina);
  }

  const aceptadas: { dy: number; dx: number; objeto: Celda[] }[] = [];
  let pares = 0;
  for (const celdas of objetosPre) {
    const { clave, esquina } = formaConColor(celdas, pre);
    for (const destino of indice.get(clave) ?? []) {
      const dy = destino[0] - esquina[0];
      const dx = destino[1] - esquina[1];
      if (dy === 0 && dx === 0) continue;
      pares++;
      if (pares > maxPares) return null;
      if (objetoExplicaElCambio(pre, post, conjunto, fondo, celdas, dy, dx, mask)) {
        aceptadas.push({ dy, dx, objeto: celdas });
      }
    }
  }
  if (aceptadas.length === 0) return null;
  aceptadas.sort(
    (a, b) =>
      Math.abs(a.dy) + Math.abs(a.dx) - (Math.abs(b.dy) + Math.abs(b.dx)) ||
      a.dy - b.dy ||
      a.dx - b.dx ||
      b.objeto.length - a.objeto.length,
  );
  return aceptadas[0];
}
