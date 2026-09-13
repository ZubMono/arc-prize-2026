/* [arc-agi-runner/__tests__/support/syntheticGridEnv] BL.20860 -- entorno SINTETICO con reglas
   CONOCIDAS (no es ARC real) para el test obligatorio de la wave 2 del epico BL.20858: probar
   que IntelligentPolicy resuelve el MISMO problema en MENOS acciones que baselineAgent (politica
   random uniforme). Grilla NxN con un marcador de color fijo; ACTION1..4 lo mueven 1 celda en
   una direccion (clip en el borde -- se vuelve no-op puntual si ya esta en el limite); ACTION5 es
   SIEMPRE no-op. WIN cuando el marcador llega exactamente a `target`. */

import type { ArcAction, ArcActionState, ArcFrameResponse } from '../../types';
import type { Grid } from '../../worldModel/grid';

export const SYNTHETIC_GRID_SIZE = 5;
export const SYNTHETIC_MARKER_COLOR = 5;

export interface GridPoint {
  x: number;
  y: number;
}

/** BL.21558 -- celdas del HUD sintetico: reproducen la patologia MEDIDA en los juegos publicos de
 *  ARC-AGI-3 (ar25-0c556536: 76 firmas unicas en 78 pasos). Son celdas de una fila extra que
 *  cambian en CADA paso pase lo que pase, incluso cuando la accion fue un no-op perfecto. */
export const SYNTHETIC_HUD_CELLS = 2;

export interface SyntheticEnvOptions {
  size?: number;
  /** Ancho de la grilla. Default: `size` (cuadrada, como en BL.20860). Existe para BL.21558: la
   *  barra de progreso necesita >= 16 celdas para ser una barra y no un par de celdas sueltas, y un
   *  tablero cuadrado de ese lado haria la sintesis del test cuatro veces mas cara sin aportar
   *  nada -- el ancho manda en la barra, el alto solo en el tablero. */
  width?: number;
  start: GridPoint;
  target: GridPoint;
  /** BL.21558 -- agrega una fila de HUD con un contador que avanza en cada paso. Con `false` (el
   *  default) el entorno es exactamente el de BL.20860. */
  hud?: boolean;
  /** BL.21558 -- desactiva el estado WIN: la partida no termina nunca. Reproduce el caso REAL
   *  medido (ar25, dc22, ka59 y cd82 agotaron el presupuesto sin ganar), que es donde importa que
   *  el modelo de mundo aprenda algo: un episodio que termina en 6 pasos no mide nada. */
  endless?: boolean;
  /** BL.21558 -- agrega una BARRA DE PROGRESO: una fila donde se enciende UNA celda nueva por paso.
   *  Es la forma REAL del ruido de ARC-AGI-3, medida sobre frames capturados de la API oficial
   *  (`__fixtures__/volatilityRealGames.json`): lf52 la tiene en la fila 0, ar25 en la columna 63,
   *  dc22 y ka59 en la fila 63. Ninguna celda de la barra cambia mas de una vez por vuelta, asi que
   *  el criterio por frecuencia del HUD no puede verla -- por eso los dos modos coexisten. */
  progressBar?: boolean;
}

/** Fila de HUD: dos contadores con periodos COPRIMOS (11 y 13, ambos dentro del rango de colores
 *  ARC 0-15). Asi la combinacion no se repite en 143 pasos -- mas que cualquier episodio de estos
 *  tests -- y cada frame es literalmente unico, igual que lo medido en juego real (94 firmas
 *  unicas en 94 pasos en lf52-271a04aa). Las dos celdas cambian en TODOS los pasos: eso, y no su
 *  valor, es lo que las vuelve volatiles. */
function buildHudRow(width: number, counter: number): number[] {
  const row = new Array(width).fill(0);
  row[0] = counter % 11;
  if (width > 1) row[1] = counter % 13;
  return row;
}

/** Barra de progreso: la celda `counter % width` toma un color nuevo en cada paso y las demas
 *  quedan como estaban. Al dar la vuelta cambia de color en vez de vaciarse -- es lo que hace la
 *  barra REAL (medido en lf52-271a04aa: 96 cambios en 96 transiciones sobre una barra de 64
 *  celdas, siempre de a UNA celda por paso, nunca un borrado en bloque). */
function buildProgressBarRow(width: number, counter: number): number[] {
  const row = new Array(width).fill(0);
  for (let i = 0; i < width; i++) {
    const vueltas = Math.floor((counter - i) / width);
    if (counter >= i && vueltas >= 0) row[i] = 1 + (vueltas % 3);
  }
  return row;
}

function buildGrid(
  size: number,
  x: number,
  y: number,
  hud: boolean,
  counter: number,
  progressBar = false,
  width = size,
): Grid {
  const grid: Grid = Array.from({ length: size }, () => new Array(width).fill(0));
  grid[y][x] = SYNTHETIC_MARKER_COLOR;
  if (hud) grid.push(buildHudRow(width, counter));
  if (progressBar) {
    /* Dos filas de aire entre el tablero y la barra: en los cuatro juegos reales medidos la barra
       vive sobre un BORDE del frame, lejos del tablero. Pegarlas seria simular otro juego -- uno
       donde el criterio, a proposito, se abstiene de enmascarar (ver volatilityMask.ts). */
    grid.push(new Array(width).fill(0), new Array(width).fill(0));
    grid.push(buildProgressBarRow(width, counter));
  }
  return grid;
}

/** Entorno con estado mutable -- una instancia por corrida, mismo contrato de uso que un juego
 *  real: `reset()` antes de jugar, `step(action)` despues de cada decision. */
export class SyntheticGridEnv {
  private readonly size: number;
  private readonly width: number;
  private readonly target: GridPoint;
  private readonly start: GridPoint;
  private readonly hud: boolean;
  private readonly progressBar: boolean;
  private readonly endless: boolean;
  private x: number;
  private y: number;
  private started = false;
  /** Contador del HUD -- avanza en cada `step()`, gane o pierda el agente, y tambien cuando la
   *  accion no cambio absolutamente nada del tablero. */
  private counter = 0;

  constructor(opts: SyntheticEnvOptions) {
    this.size = opts.size ?? SYNTHETIC_GRID_SIZE;
    this.width = opts.width ?? this.size;
    this.target = opts.target;
    this.start = opts.start;
    this.hud = opts.hud ?? false;
    this.progressBar = opts.progressBar ?? false;
    this.endless = opts.endless ?? false;
    this.x = opts.start.x;
    this.y = opts.start.y;
  }

  private atGoal(): boolean {
    if (this.endless) return false;
    return this.x === this.target.x && this.y === this.target.y;
  }

  private currentState(): ArcActionState {
    if (!this.started) return 'NOT_STARTED';
    return this.atGoal() ? 'WIN' : 'NOT_FINISHED';
  }

  private frameFor(): ArcFrameResponse {
    const atGoal = this.atGoal();
    return {
      game_id: 'synthetic-env',
      guid: 'synthetic-guid',
      frame: [
        buildGrid(this.size, this.x, this.y, this.hud, this.counter, this.progressBar, this.width),
      ],
      state: this.currentState(),
      levels_completed: atGoal ? 1 : 0,
      win_levels: 1,
      available_actions: atGoal ? [] : [1, 2, 3, 4, 5],
    };
  }

  reset(): ArcFrameResponse {
    this.started = true;
    this.x = this.start.x;
    this.y = this.start.y;
    return this.frameFor();
  }

  step(action: ArcAction): ArcFrameResponse {
    if (!this.started) return this.reset();
    this.counter += 1;
    switch (action) {
      case 'ACTION1': // derecha
        this.x = Math.min(this.width - 1, this.x + 1);
        break;
      case 'ACTION2': // abajo
        this.y = Math.min(this.size - 1, this.y + 1);
        break;
      case 'ACTION3': // izquierda
        this.x = Math.max(0, this.x - 1);
        break;
      case 'ACTION4': // arriba
        this.y = Math.max(0, this.y - 1);
        break;
      default: // ACTION5 (y cualquier otra) -- siempre no-op
        break;
    }
    return this.frameFor();
  }

  /** Grilla del objetivo -- para inyectar como `goalGrid` de IntelligentPolicy. Con HUD no tiene
   *  sentido usarla (el contador la vuelve inalcanzable por definicion), y por eso los tests de
   *  BL.21558 corren en modo exploracion, igual que la partida real contra la API de ARC. */
  get targetGrid(): Grid {
    return buildGrid(
      this.size,
      this.target.x,
      this.target.y,
      this.hud,
      this.counter,
      this.progressBar,
      this.width,
    );
  }

  /** Posicion actual del marcador -- los tests de efecto la usan para saber cuando DOS frames
   *  distintos corresponden en realidad al mismo estado del tablero. */
  get markerPosition(): GridPoint {
    return { x: this.x, y: this.y };
  }
}
