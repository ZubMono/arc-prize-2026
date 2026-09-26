/* [arc-agi-runner/worldModel/clickMemory] BL.21560 -- memoria de clicks de UN episodio: que
   coordenadas ya se probaron en cada estado, cuales produjeron efecto, y que parche 3x3 rodeaba a
   las que funcionaron.

   TRES CAPAS, en el orden en que actuan sobre una decision:
     1. PRIOR (offline): puntaje lineal de las features de la celda (clickFeatures.ts) con los pesos
        de clickPriors.ts, ajustados por regresion logistica contra clicks REALES etiquetados con
        "el click cambio la grilla" -- etiqueta auto-supervisada que no exige haber ganado nunca.
     2. PLANTILLA (en vivo): al detectar un click CON efecto se guarda el parche 3x3 que lo rodeaba;
        toda celda con un parche parecido sube al frente. Es lo que convierte UN acierto en una
        politica -- en ft09 las nueve fichas del tablero comparten el parche de sus esquinas, asi que
        el primer acierto ilumina las ocho restantes.
     3. MEMORIA (en vivo): mapa (firma, x, y) -> {probado, produjo cambio}. La clave lleva la FIRMA
        del estado y no solo la coordenada: si el tablero cambio, la misma coordenada vuelve a ser
        informativa; si no cambio, repetirla es puro costo. Es exactamente la clave que el puerto
        Python documentaba como "la correcta, que hoy no existe" (policy.py, BL.21518).

   MEDIDO sobre el corpus real (`arcReplayFrames`, ft09-0d8bbf25): 346 clicks, 32 productivos
   (9,2%), 117 repeticiones de coordenada y 106 clicks sobre una coordenada que ya habia fallado. */

import { GRID_MAX_COORD } from '../types';
import {
  construirTableroDeFeatures,
  extraerParche,
  puntuarCelda,
  similitudDeParche,
} from './clickFeatures';
import { CLICK_PRIORS } from './clickPriors';
import { hashGrid, type BoundingBox, type Grid } from './grid';

/** Cuanto suma al logit que el parche de una celda se parezca a una plantilla aprendida. Grande a
 *  proposito: una plantilla es evidencia DE ESTA PARTIDA (algo que ya funciono aca) y tiene que
 *  pesar mas que cualquier prior aprendido en otras partidas -- los pesos ajustados no pasan de
 *  |2,3|. Sigue siendo finito, y la memoria de coordenadas probadas se aplica DESPUES, asi que una
 *  plantilla nunca ancla al agente en la misma celda: la ilumina una vez y pasa a la siguiente. */
export const BONO_POR_PLANTILLA = 6.0;

/** Penalizacion simetrica de una ANTI-PLANTILLA: un parche que ya fallo varias veces. Misma
 *  magnitud que el bono porque es la misma clase de evidencia, con el signo dado vuelta. */
export const PENALIZACION_POR_ANTI_PLANTILLA = 6.0;

/** Clicks muertos con el MISMO parche antes de descartar toda la clase.
 *
 *  POR QUE EXISTE, medido contra la API oficial. Sin esto el agente recorre las 4096 celdas en orden
 *  de prior y, si el prior apunta a una region grande e inerte, se la barre entera: en
 *  lp85-305b61c3 -- un juego que NO esta en el corpus de ajuste -- gasto 403 de 499 clicks en la
 *  cenefa decorativa del borde y acerto 0. Con anti-plantillas esa region entera se descarta a los
 *  dos fallos, porque todas sus celdas comparten el mismo parche. Es la mitad negativa de la misma
 *  idea que la plantilla: lo que importa no es la coordenada, es el TIPO DE LUGAR.
 *
 *  2 y no 1 por el mismo criterio que `SEED_MIN_NONOP_CONFIRMATIONS`: un solo frame identico puede
 *  ser ruido del entorno. Una plantilla POSITIVA sobre el mismo parche gana siempre. */
export const ANTI_PLANTILLA_MIN_FALLOS = 2;

export interface ObjetivoDeClick {
  /** Coordenada en celdas de la grilla. */
  x: number;
  y: number;
  /** Coordenada escalada al rango que espera la API (0..GRID_MAX_COORD). */
  xApi: number;
  yApi: number;
  /** Por que se eligio -- viaja al `reasoning` persistido del step. */
  motivo: string;
}

function claveDeCelda(firma: string, x: number, y: number): string {
  return `${firma}|${x},${y}`;
}

export class ClickMemory {
  /** `${firma}|${x},${y}` -> el click produjo cambio. */
  private readonly probadas = new Map<string, boolean>();
  private readonly plantillas: number[][] = [];
  /** Parches que ya fallaron `ANTI_PLANTILLA_MIN_FALLOS` veces, serializados. */
  private readonly antiPlantillas = new Set<string>();
  /** Fallos acumulados por parche -- el contador que lleva a ser anti-plantilla. */
  private readonly fallosPorParche = new Map<string, number>();
  /** Valores centrales presentes entre plantillas y anti-plantillas -- rechazo rapido: una celda
   *  cuyo color no es el centro de NINGUNA no puede parecerse a ninguna con un umbral alto. */
  private readonly centrosDePlantilla = new Set<number>();
  private readonly pesos: readonly number[];
  private readonly umbralSimilitud: number;

  /* Cache de UNA entrada. En ARC-AGI-3 la mayoria de los clicks no cambian nada, asi que la MISMA
     grilla se puntua muchos pasos seguidos (medido: 33 grillas distintas en 346 pasos de ft09).
     Sin esto, cada decision re-segmenta el frame entero para nada. */
  private claveCache: string | null = null;
  private puntajesCache: Float64Array = new Float64Array(0);
  private ordenCache: Int32Array = new Int32Array(0);
  private anchoCache = 0;

  constructor(opts: { pesos?: readonly number[]; umbralSimilitud?: number } = {}) {
    this.pesos = opts.pesos ?? CLICK_PRIORS.pesosClick;
    this.umbralSimilitud =
      opts.umbralSimilitud ?? CLICK_PRIORS.umbralesDetectores.similitudDeParcheMinima;
  }

  get plantillasAprendidas(): number {
    return this.plantillas.length;
  }

  get antiPlantillasAprendidas(): number {
    return this.antiPlantillas.size;
  }

  get coordenadasProbadas(): number {
    return this.probadas.size;
  }

  /** Atribuye el resultado del click anterior. `gridPrevia` es la grilla SOBRE LA QUE se clickeo: el
   *  parche de la plantilla tiene que describir lo que se veia al decidir, no lo que quedo despues
   *  (que ya cambio justamente por el click). */
  registrarResultado(
    firma: string,
    x: number,
    y: number,
    huboCambio: boolean,
    gridPrevia: Grid | null,
  ): void {
    this.probadas.set(claveDeCelda(firma, x, y), huboCambio);
    if (gridPrevia === null) return;
    const parche = extraerParche(gridPrevia, x, y);
    const serializado = parche.join(',');

    if (!huboCambio) {
      const fallos = (this.fallosPorParche.get(serializado) ?? 0) + 1;
      this.fallosPorParche.set(serializado, fallos);
      if (fallos >= ANTI_PLANTILLA_MIN_FALLOS && !this.antiPlantillas.has(serializado)) {
        this.antiPlantillas.add(serializado);
        this.centrosDePlantilla.add(parche[(parche.length - 1) / 2]);
        this.claveCache = null; // la anti-plantilla nueva cambia los puntajes
      }
      return;
    }

    if (this.plantillas.some((p) => p.join(',') === serializado)) return;
    this.plantillas.push(parche);
    this.centrosDePlantilla.add(parche[(parche.length - 1) / 2]);
    /* Evidencia de efecto real desmiente cualquier marca de "aca no pasa nada" sobre ese parche. */
    this.antiPlantillas.delete(serializado);
    this.fallosPorParche.delete(serializado);
    this.claveCache = null; // la plantilla nueva cambia los puntajes
  }

  /** Ajuste del puntaje por evidencia DE ESTA PARTIDA: +bono si el parche de la celda coincide con
   *  uno que ya funciono, -penalizacion si coincide con uno que ya fallo varias veces. La positiva
   *  gana: haber visto un efecto real le gana a no haber visto nada. */
  private bonoDePlantilla(grid: Grid, x: number, y: number): number {
    if (this.centrosDePlantilla.size === 0 || !this.centrosDePlantilla.has(grid[y][x])) return 0;
    const parche = extraerParche(grid, x, y);
    for (const plantilla of this.plantillas) {
      if (similitudDeParche(parche, plantilla) >= this.umbralSimilitud) return BONO_POR_PLANTILLA;
    }
    const serializado = parche.join(',');
    /* Umbral 1 (el caso real) se resuelve por lookup directo; por debajo hace falta comparar. */
    if (this.antiPlantillas.has(serializado)) return -PENALIZACION_POR_ANTI_PLANTILLA;
    if (this.umbralSimilitud < 1) {
      for (const anti of this.antiPlantillas) {
        const otro = anti.split(',').map(Number);
        if (similitudDeParche(parche, otro) >= this.umbralSimilitud) {
          return -PENALIZACION_POR_ANTI_PLANTILLA;
        }
      }
    }
    return 0;
  }

  /** Puntaje (logit + bono de plantilla) de cada celda, row-major. Puro: depende solo de la grilla,
   *  la region que cambio y las plantillas vigentes -- por eso se cachea. */
  puntajesPorCelda(grid: Grid, regionCambiada: BoundingBox | null = null): Float64Array {
    const region =
      regionCambiada === null
        ? 'x'
        : `${regionCambiada.minX},${regionCambiada.minY},${regionCambiada.maxX},${regionCambiada.maxY}`;
    const clave = `${hashGrid(grid)}|${region}|${this.plantillas.length}|${this.antiPlantillas.size}`;
    if (this.claveCache === clave) return this.puntajesCache;

    const tablero = construirTableroDeFeatures(grid, { regionCambiada });
    const puntajes = new Float64Array(tablero.ancho * tablero.alto);
    for (let y = 0; y < tablero.alto; y++) {
      for (let x = 0; x < tablero.ancho; x++) {
        puntajes[y * tablero.ancho + x] =
          puntuarCelda(tablero.features(x, y), this.pesos) + this.bonoDePlantilla(grid, x, y);
      }
    }
    const orden = Int32Array.from(puntajes.keys()).sort((a, b) => puntajes[b] - puntajes[a]);

    this.claveCache = clave;
    this.puntajesCache = puntajes;
    this.ordenCache = orden;
    this.anchoCache = tablero.ancho;
    return puntajes;
  }

  /** Coordenada a clickear: la celda NO PROBADA en este estado con mayor puntaje. Si todas se
   *  probaron, se prefiere una que YA produjo cambio (un boton que funciono vuelve a funcionar)
   *  antes que una muerta.
   *
   *  Recorre las celdas en orden de puntaje DESCENDENTE (precalculado junto con los puntajes), asi
   *  que el costo por decision es proporcional a cuantas celdas ya se probaron en este estado, no a
   *  las 4096 del frame.
   *
   *  Consume EXACTAMENTE un numero del `rng`, igual que la heuristica que reemplaza: la
   *  reproducibilidad de una partida dado su seed depende de que la secuencia del rng no varie con
   *  el contenido de la memoria. */
  elegirObjetivo(
    grid: Grid | null,
    firma: string | null,
    rng: () => number,
    regionCambiada: BoundingBox | null = null,
  ): ObjetivoDeClick {
    if (grid === null || grid.length === 0 || (grid[0]?.length ?? 0) === 0) {
      const x = Math.floor(rng() * (GRID_MAX_COORD + 1));
      const y = Math.floor(rng() * (GRID_MAX_COORD + 1));
      return {
        x,
        y,
        xApi: x,
        yApi: y,
        motivo: 'sin grilla observable -- coordenada al azar en el rango estandar',
      };
    }

    const alto = grid.length;
    const ancho = grid[0].length;
    const claveFirma = firma ?? 'sin-firma';
    const puntajes = this.puntajesPorCelda(grid, regionCambiada);
    const orden = this.ordenCache;
    const sorteo = rng();

    const empatadas: number[] = [];
    for (let k = 0; k < orden.length; k++) {
      const i = orden[k];
      if (this.probadas.has(claveDeCelda(claveFirma, i % ancho, Math.floor(i / ancho)))) continue;
      if (empatadas.length > 0 && puntajes[i] !== puntajes[empatadas[0]]) break;
      empatadas.push(i);
    }
    let motivo =
      empatadas.length > 0
        ? `celda no probada de mayor prioridad en este estado (${empatadas.length} empatada(s), ` +
          `${this.plantillas.length} plantilla(s) y ${this.antiPlantillas.size} anti-plantilla(s))`
        : '';
    if (empatadas.length === 0) {
      for (const productiva of [true, false]) {
        for (let k = 0; k < orden.length && empatadas.length === 0; k++) {
          const i = orden[k];
          if (
            this.probadas.get(claveDeCelda(claveFirma, i % ancho, Math.floor(i / ancho))) ===
            productiva
          ) {
            empatadas.push(i);
            motivo = productiva
              ? 'todas las celdas probadas en este estado -- se repite la que ya produjo cambio'
              : 'todas las celdas probadas y ninguna produjo cambio -- se reintenta la mejor';
          }
        }
        if (empatadas.length > 0) break;
      }
    }

    const elegida = empatadas[Math.floor(sorteo * empatadas.length) % empatadas.length] ?? 0;
    const x = elegida % ancho;
    const y = Math.floor(elegida / ancho);
    const escalaX = ancho > 1 ? GRID_MAX_COORD / (ancho - 1) : 0;
    const escalaY = alto > 1 ? GRID_MAX_COORD / (alto - 1) : 0;
    return {
      x,
      y,
      xApi: Math.min(GRID_MAX_COORD, Math.round(x * escalaX)),
      yApi: Math.min(GRID_MAX_COORD, Math.round(y * escalaY)),
      motivo,
    };
  }
}
