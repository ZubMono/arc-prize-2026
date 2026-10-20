/* [arc-agi-runner/worldModel/mechanicsMemory] BL.21561 -- memoria de mecanicas POR ACCION y por
   EPISODIO, construida sobre `detectarMecanica` (objectMechanics.ts).

   POR ACCION acumula la firma de mecanica observada como distribucion Beta -- alpha son las veces
   que la accion volvio a hacer LO MISMO, beta las veces que hizo otra cosa. Nunca un booleano: en
   ARC-AGI-3 una accion de movimiento choca contra la pared cada tantos pasos y ahi no mueve nada;
   con verificacion de cero tolerancia esa unica observacion mataba la regla correcta (que es
   exactamente lo que rompia `verifyProgram`, ver synthesis.ts).

   POR EPISODIO implementa los dos detectores que no son de transicion:
   4. MARCO/HUD: las celdas que no cambiaron NUNCA. Su complemento -- el bbox de lo que si cambio
      alguna vez -- es la ARENA: todo lo de afuera es decorado y no deberia entrar en ninguna
      decision.
   5. CONTADOR: un color cuya cantidad de celdas se mueve siempre en el mismo sentido es puntaje o
      vidas -- senal densa de progreso, a diferencia del score del juego que solo cambia al ganar
      un nivel. */

import { isVolatileCell, type BoundingBox, type Grid, type VolatilityMask } from './grid';
import { firmaDeMecanica } from './mechanicsSignature';
import { detectarMecanica, type Mecanica, type Traslacion } from './objectMechanics';
// BL.21741 (correccion): la capa de VOCABULARIO vive en su propio modulo -- detectar y nombrar son
// dos responsabilidades, y objectMechanics.ts cruzaba el limite de 500 lineas del repo.

/** Observaciones minimas de una accion antes de afirmar que su mecanica es conocida. 2 y no 1:
 *  una sola coincidencia no distingue una regla de una casualidad, y en ARC-AGI-3 hay acciones
 *  (el click) que hacen cosas distintas segun donde caen. */
export const MIN_OBSERVACIONES_DE_MECANICA = 2;

/** Fraccion minima de observaciones que tienen que coincidir con la firma dominante para
 *  considerar que la accion TIENE una mecanica. 0.6 deja pasar la regla de movimiento que falla
 *  contra la pared un tercio de las veces, y no la que acierta la mitad. */
export const MIN_COBERTURA_DE_MECANICA = 0.6;

/** Cambios minimos de la cuenta de un color para llamarlo contador. Con menos, cualquier objeto
 *  que aparece y se queda quieto pasaria por marcador. */
export const MIN_CAMBIOS_DE_CONTADOR = 3;

export interface HipotesisDeMecanica {
  action: string;
  /** Firma dominante -- `sinCambio`, `traslacion:dy,dx`, `recoloreo:a>b`, ... */
  firma: string;
  /** Traslacion asociada a la firma dominante (`null` si la firma no es una traslacion). */
  traslacion: Traslacion | null;
  alpha: number;
  beta: number;
  observaciones: number;
  /** alpha-1 sobre observaciones: fraccion de las veces que la accion hizo lo mismo. */
  cobertura: number;
}

export interface ContadorDeColor {
  color: number;
  direccion: 'sube' | 'baja';
  cambios: number;
  delta: number;
}

interface RegistroDeAccion {
  conteoPorFirma: Map<string, number>;
  ultimaTraslacionPorFirma: Map<string, Traslacion>;
  observaciones: number;
}

export class MechanicsMemory {
  private readonly porAccion = new Map<string, RegistroDeAccion>();
  /** `true` en las celdas que cambiaron alguna vez -- el complemento es el marco estatico. */
  private cambioAlgunaVez: Uint8Array | null = null;
  private alto = 0;
  private ancho = 0;
  private observacionesTotales = 0;
  /** Cuenta de celdas por color en el ultimo frame observado. */
  private conteoAnterior: Map<number, number> | null = null;
  private readonly contadores = new Map<
    number,
    { direccion: 'sube' | 'baja' | null; cambios: number; delta: number; roto: boolean }
  >();

  /** Registra el efecto de `action` y devuelve la mecanica detectada (para logs y tests). */
  observe(action: string, pre: Grid, post: Grid, mask: VolatilityMask | null = null): Mecanica {
    const mecanica = detectarMecanica(pre, post, mask);
    const firma = firmaDeMecanica(mecanica);

    const registro = this.porAccion.get(action) ?? {
      conteoPorFirma: new Map<string, number>(),
      ultimaTraslacionPorFirma: new Map<string, Traslacion>(),
      observaciones: 0,
    };
    registro.observaciones += 1;
    registro.conteoPorFirma.set(firma, (registro.conteoPorFirma.get(firma) ?? 0) + 1);
    if (mecanica.traslacionPrincipal !== null) {
      registro.ultimaTraslacionPorFirma.set(firma, mecanica.traslacionPrincipal);
    }
    this.porAccion.set(action, registro);

    this.registrarCeldasCambiadas(pre, post, mask);
    this.registrarContadores(post, mask);
    this.observacionesTotales += 1;
    return mecanica;
  }

  /** Hipotesis vigente de `action`: la firma mas observada, con su Beta. `undefined` si la accion
   *  nunca se observo. */
  getHypothesis(action: string): HipotesisDeMecanica | undefined {
    const registro = this.porAccion.get(action);
    if (registro === undefined) return undefined;
    /* Desempate por firma (orden lexicografico) y no por orden de insercion: dos firmas empatadas
       tienen que resolver igual en el motor TS y en el puerto Python, que no comparten el orden
       de iteracion de sus mapas. */
    const ordenadas = [...registro.conteoPorFirma.entries()].sort(
      (a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0),
    );
    const [firma, aciertos] = ordenadas[0];
    const fallos = registro.observaciones - aciertos;
    return {
      action,
      firma,
      traslacion: registro.ultimaTraslacionPorFirma.get(firma) ?? null,
      alpha: 1 + aciertos,
      beta: 1 + fallos,
      observaciones: registro.observaciones,
      cobertura: aciertos / registro.observaciones,
    };
  }

  /** Direccion de movimiento CONFIRMADA de `action` -- `null` si la accion no mueve nada, si aun
   *  no hay evidencia suficiente o si la mecanica dominante no es una traslacion. Es el mapeo
   *  ACTION1..5 -> direccion que el DSL global nunca pudo dar. */
  getDirection(action: string): { dy: number; dx: number } | null {
    const h = this.getHypothesis(action);
    if (h === undefined || h.traslacion === null) return null;
    if (!h.firma.startsWith('traslacion:')) return null;
    if (h.observaciones < MIN_OBSERVACIONES_DE_MECANICA) return null;
    if (h.cobertura < MIN_COBERTURA_DE_MECANICA) return null;
    return { dy: h.traslacion.dy, dx: h.traslacion.dx };
  }

  /** Acciones con direccion de movimiento confirmada, en orden de registro. */
  getMovementActions(): string[] {
    return [...this.porAccion.keys()].filter((a) => this.getDirection(a) !== null);
  }

  /** Acciones con mecanica dominante `sinCambio` y evidencia suficiente -- no-op observacional,
   *  sin pasar por la sintesis DSL. */
  isInertAction(action: string): boolean {
    const h = this.getHypothesis(action);
    if (h === undefined) return false;
    return (
      h.firma === 'sinCambio' &&
      h.observaciones >= MIN_OBSERVACIONES_DE_MECANICA &&
      h.cobertura >= MIN_COBERTURA_DE_MECANICA
    );
  }

  /** DETECTOR 4 -- caja de lo que cambio alguna vez: la ARENA. Todo lo de afuera es marco/HUD
   *  estatico. `null` mientras no se observo ningun cambio. */
  getActiveBoundingBox(): BoundingBox | null {
    if (this.cambioAlgunaVez === null) return null;
    let minY = Infinity;
    let minX = Infinity;
    let maxY = -Infinity;
    let maxX = -Infinity;
    for (let y = 0; y < this.alto; y++) {
      for (let x = 0; x < this.ancho; x++) {
        if (this.cambioAlgunaVez[y * this.ancho + x] === 1) {
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
        }
      }
    }
    if (maxY < minY) return null;
    return { minY, minX, maxY, maxX };
  }

  /** DETECTOR 4 -- celdas que no cambiaron NUNCA en todo lo observado. */
  getStaticCellCount(): number {
    if (this.cambioAlgunaVez === null) return 0;
    let estaticas = 0;
    for (const marca of this.cambioAlgunaVez) if (marca === 0) estaticas++;
    return estaticas;
  }

  isStaticCell(y: number, x: number): boolean {
    if (this.cambioAlgunaVez === null) return true;
    if (y < 0 || x < 0 || y >= this.alto || x >= this.ancho) return true;
    return this.cambioAlgunaVez[y * this.ancho + x] === 0;
  }

  /** DETECTOR 5 -- colores cuya cantidad de celdas se movio SIEMPRE en el mismo sentido:
   *  puntaje/vidas. Ordenado por cantidad de cambios descendente. */
  getCounters(): ContadorDeColor[] {
    const salida: ContadorDeColor[] = [];
    for (const [color, c] of [...this.contadores.entries()].sort((a, b) => a[0] - b[0])) {
      if (c.roto || c.direccion === null) continue;
      if (c.cambios < MIN_CAMBIOS_DE_CONTADOR) continue;
      salida.push({ color, direccion: c.direccion, cambios: c.cambios, delta: c.delta });
    }
    return salida.sort((a, b) => b.cambios - a.cambios || a.color - b.color);
  }

  getObservationCount(): number {
    return this.observacionesTotales;
  }

  private registrarCeldasCambiadas(pre: Grid, post: Grid, mask: VolatilityMask | null): void {
    const alto = pre.length;
    const ancho = pre[0]?.length ?? 0;
    if (alto === 0 || ancho === 0) return;
    /* Un cambio de forma del frame reinicia el mapa: las coordenadas viejas ya no describen el
       mismo tablero, y mezclarlas produciria una arena inventada. */
    if (this.cambioAlgunaVez === null || this.alto !== alto || this.ancho !== ancho) {
      this.cambioAlgunaVez = new Uint8Array(alto * ancho);
      this.alto = alto;
      this.ancho = ancho;
    }
    for (let y = 0; y < alto; y++) {
      const fila = pre[y];
      const filaPost = post[y] ?? [];
      for (let x = 0; x < fila.length && x < ancho; x++) {
        if (fila[x] !== filaPost[x] && !isVolatileCell(mask, y, x)) {
          this.cambioAlgunaVez[y * ancho + x] = 1; // @proto-safe: Uint8Array indexado por entero acotado, sin claves de string
        }
      }
    }
  }

  private registrarContadores(post: Grid, mask: VolatilityMask | null): void {
    const conteo = new Map<number, number>();
    for (let y = 0; y < post.length; y++) {
      const fila = post[y];
      for (let x = 0; x < fila.length; x++) {
        if (isVolatileCell(mask, y, x)) continue;
        conteo.set(fila[x], (conteo.get(fila[x]) ?? 0) + 1);
      }
    }
    const anterior = this.conteoAnterior;
    this.conteoAnterior = conteo;
    if (anterior === null) return;

    const colores = new Set([...anterior.keys(), ...conteo.keys()]);
    for (const color of colores) {
      const antes = anterior.get(color) ?? 0;
      const ahora = conteo.get(color) ?? 0;
      if (antes === ahora) continue;
      const direccion: 'sube' | 'baja' = ahora > antes ? 'sube' : 'baja';
      const estado = this.contadores.get(color) ?? {
        direccion: null,
        cambios: 0,
        delta: 0,
        roto: false,
      };
      if (estado.direccion !== null && estado.direccion !== direccion) estado.roto = true;
      estado.direccion = estado.direccion ?? direccion;
      estado.cambios += 1;
      estado.delta += ahora - antes;
      this.contadores.set(color, estado);
    }
  }
}
