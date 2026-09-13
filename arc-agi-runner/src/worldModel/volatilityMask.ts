/* [arc-agi-runner/worldModel/volatilityMask] BL.21558 -- aprende, DURANTE el episodio, que celdas
   del frame cambian sin relacion con la accion ejecutada (HUD, contador de pasos, barra de
   progreso) para que el resto del modelo de mundo pueda ignorarlas.

   EL PROBLEMA MEDIDO. En `prometheusEvaluationRuns`, los juegos publicos de ARC-AGI-3 producen un
   frame distinto en cada paso pase lo que pase: ar25-0c556536 = 76 firmas unicas / 78 pasos;
   lf52-271a04aa = 94/94; dc22-fdcac232 = 128/129; ka59 = 100/101. Con esas celdas dentro de la
   comparacion, `gridsEqual` no devuelve `true` nunca y se cae la cadena entera: casi ningun no-op
   detectado pese al round-robin contra paredes, `synthesizeProgram` obligada a explicar tambien el
   contador (imposible con un DSL de tablero) y ninguna firma de estado que vuelva a aparecer -- la
   memoria entre corridas solo podia disparar en el estado post-RESET.

   DOS FAMILIAS DE RUIDO, PORQUE EL DATO REAL MOSTRO DOS FORMAS DISTINTAS. La primera version de
   este modulo solo tenia la familia 1 y, medida contra frames REALES capturados de la API oficial,
   enmascaraba CERO celdas en los cuatro juegos citados arriba: el ruido de ARC-AGI-3 no es un
   digito que parpadea, es una BARRA que avanza.

   Familia 1 -- celda que cambia casi siempre, bajo TODAS las acciones (contador dibujado con
   sprites, animacion de fondo). Se exige `VOLATILITY_MIN_TRANSITIONS`,
   `VOLATILITY_MIN_DISTINCT_ACTIONS` y, para CADA accion, un ratio de cambio de esa celda
   >= `VOLATILITY_ENTRY_RATIO`. La exigencia POR ACCION es lo que protege el tablero: el marcador
   del jugador cambia bajo las acciones de movimiento pero NO bajo una accion inerte, asi que basta
   una accion que no lo mueva para que nunca entre.

   Familia 2 -- CONTADOR DE BARRIDO: una barra donde se enciende UNA celda nueva por paso. Medido
   sobre partidas reales completas capturadas para este BL (82-125 transiciones cada una):
     lf52-271a04aa  fila 0    (1x64) -- avanza en el 100% de los pasos, 1 celda por paso;
     ar25-0c556536  columna 63 (64x1) -- 78%;
     dc22-fdcac232  fila 63   (1x64) -- 51%;
     ka59-38d34dbb  fila 63   (1x64) -- 64%.
   La familia 1 NO puede verlas: cada celda de la barra cambia UNA sola vez en todo el episodio
   (ratio por celda ~0.01), aunque la barra cambie en cada paso. El criterio que si las ve mira la
   REGION: una componente conexa de >= `SWEEP_MIN_CELLS` celdas, con forma de LINEA de una celda de
   ancho, donde cada cambio ocurrio en SOLEDAD (ninguna otra celda cambio a distancia
   `SWEEP_ISOLATION_RADIUS`) y que registro cambios en >= `SWEEP_ENTRY_RATIO` de las transiciones,
   bajo >= 2 acciones distintas.

   POR QUE ESE CRITERIO NO SE COME EL TABLERO. Un objeto que se mueve cambia SIEMPRE 2 celdas a la
   vez y adyacentes (de donde sale y a donde llega): jamas pasa el filtro de soledad. Un tablero que
   responde cambia en bloques (mediana medida: 108 celdas por paso en ar25, 18 en ka59, 8-48 en
   dc22): tampoco. Y una region 2D de celdas que se encienden de a una -- el caso peligroso, tipo
   "simon dice" -- queda afuera por el requisito de forma de linea. Verificado contra las
   componentes REALES de los cuatro juegos: en los cuatro entra la barra y NINGUNA otra.

   POR QUE CONSERVADOR EN GENERAL. Enmascarar una celda del TABLERO es mucho peor que no enmascarar
   una del HUD: el agente se volveria ciego justo donde esta la señal, y no enmascarar es
   exactamente el comportamiento previo a este BL. De ahi los umbrales altos, las exigencias
   estructurales y el tope `VOLATILITY_MAX_FRACTION`: si "lo volatil" se comiera medio frame no es
   un HUD, es el juego -- y ahi la mascara se desactiva entera.

   HISTERESIS. Salir de la mascara pide un ratio mas bajo que entrar (`VOLATILITY_EXIT_RATIO`,
   `SWEEP_EXIT_RATIO`). Sin esa banda muerta, algo parado justo en el umbral entraria y saldria paso
   a paso y las firmas de estado volverian a ser irrepetibles -- el defecto que este modulo existe
   para arreglar. */

import type { Grid, VolatilityMask } from './grid';

/** Transiciones minimas antes de afirmar nada. Por debajo de esto cualquier ratio es ruido. */
export const VOLATILITY_MIN_TRANSITIONS = 6;

/** Acciones distintas minimas. Con una sola accion observada, "cambia siempre" y "esta accion la
 *  cambia siempre" son indistinguibles -- y confundirlas enmascararia el efecto que hay que
 *  aprender. */
export const VOLATILITY_MIN_DISTINCT_ACTIONS = 2;

/** Fraccion de transiciones DE CADA ACCION en las que la celda debe cambiar para entrar. Alto a
 *  proposito (ver "POR QUE CONSERVADOR"), pero no 1.0: un digito dibujado con sprites comparte
 *  pixeles entre glifos consecutivos (8 -> 9), asi que algunas de sus celdas no cambian en TODOS
 *  los pasos y con 1.0 el contador quedaria a medio enmascarar. */
export const VOLATILITY_ENTRY_RATIO = 0.85;

/** Fraccion por debajo de la cual una celda ya enmascarada vuelve a contar. Ver "HISTERESIS". */
export const VOLATILITY_EXIT_RATIO = 0.6;

/** Si el conjunto volatil superara esta fraccion del frame, la mascara se desactiva por completo.
 *  Un frame que muta en mas de la mitad de sus celdas pase lo que pase no tiene HUD ruidoso: no es
 *  observable con este modelo, y enmascararlo dejaria al agente decidiendo sobre casi nada. */
export const VOLATILITY_MAX_FRACTION = 0.5;

/** Celdas minimas de una barra de progreso. Las cuatro medidas en juego real tienen 64 (un borde
 *  entero del frame); el piso esta bien por debajo para tolerar barras mas cortas, pero lo
 *  suficientemente alto como para que un par de celdas sueltas del tablero que se encienden de a
 *  una nunca alcancen a formar una. */
export const SWEEP_MIN_CELLS = 16;

/** Transiciones minimas para evaluar la familia 2. Mas exigente que la familia 1 porque el
 *  estadistico se calcula sobre la REGION: con pocas transiciones, cualquier region chica de
 *  celdas encendidas de a una pasaria el ratio por casualidad. */
export const SWEEP_MIN_TRANSITIONS = 12;

/** Fraccion de las transiciones del episodio en las que la barra tiene que haber avanzado para
 *  entrar. Medido: 1.00 (lf52), 0.78 (ar25), 0.64 (ka59), 0.51 (dc22) -- el piso 0.4 entra por
 *  debajo del peor caso real sin llegar a la mitad, que seria "cambia tanto como el tablero". */
export const SWEEP_ENTRY_RATIO = 0.4;

/** Ratio por debajo del cual una barra ya enmascarada vuelve a contar. Ver "HISTERESIS". */
export const SWEEP_EXIT_RATIO = 0.25;

/** Radio (Chebyshev) dentro del cual NO puede haber otra celda cambiando en la misma transicion
 *  para considerar que el cambio ocurrio en soledad. 2 y no 1: un objeto que se mueve dos celdas de
 *  golpe dejaria dos cambios separados por una celda intermedia, y eso no es una barra. */
export const SWEEP_ISOLATION_RADIUS = 2;

/** Fraccion de los cambios de la REGION que tuvieron que ocurrir en soledad. Se mide sobre la
 *  region entera y no celda por celda: si un cambio del tablero pasa cerca de la barra, la celda
 *  afectada no puede quedar descalificada para siempre -- la barra se partiria en pedazos
 *  demasiado cortos y dejaria de reconocerse. No es 1.0 por lo mismo. */
export const SWEEP_MIN_ISOLATION_RATIO = 0.9;

interface ContadoresDeAccion {
  /** Transiciones observadas de esta accion. */
  transiciones: number;
  /** `cambios[y][x]` -- en cuantas de ellas cambio esa celda. */
  cambios: number[][];
}

function ensureRows(matriz: number[][], height: number, width: number): void {
  while (matriz.length < height) matriz.push([]);
  for (const row of matriz) {
    while (row.length < width) row.push(0);
  }
}

function ensureBoolRows(matriz: boolean[][], height: number, width: number): void {
  while (matriz.length < height) matriz.push([]);
  for (const row of matriz) {
    while (row.length < width) row.push(false);
  }
}

/** Acumula evidencia transicion a transicion y expone la mascara vigente. UNA instancia por
 *  episodio: la volatilidad es una propiedad del juego EN CURSO, no del agente. */
export class VolatilityTracker {
  private readonly porAccion = new Map<string, ContadoresDeAccion>();
  private volatile: boolean[][] = [];
  /** Familia 1 y familia 2 se guardan por separado: comparten el tope y la version, pero cada una
   *  tiene su propia histeresis y mezclarlas haria que una celda que entro por barrido saliera por
   *  el umbral de frecuencia (y al reves). */
  private volatilPorFrecuencia: boolean[][] = [];
  private volatilPorBarrido: boolean[][] = [];
  /** `cambiosTotales[y][x]` -- transiciones en las que la celda cambio, sumando todas las acciones.
   *  `cambiosAislados[y][x]` -- cuantas de esas ocurrieron sin ninguna otra celda cambiando cerca. */
  private cambiosTotales: number[][] = [];
  private cambiosAislados: number[][] = [];
  private height = 0;
  private width = 0;
  private transiciones = 0;
  private volatileCount = 0;
  private desactivadaPorTope = false;
  private versionActual = 0;

  /** Registra una transicion observada `pre -> post` bajo `action`. Idempotente respecto de las
   *  grillas: no las muta ni las retiene. */
  observe(action: string, pre: Grid, post: Grid): void {
    const height = Math.max(pre.length, post.length);
    const width = Math.max(
      pre.reduce((max, row) => Math.max(max, row.length), 0),
      post.reduce((max, row) => Math.max(max, row.length), 0),
    );
    if (height === 0 || width === 0) return;

    this.crecerHasta(height, width);
    this.transiciones += 1;

    const contadores = this.contadoresDe(action);
    contadores.transiciones += 1;
    ensureRows(contadores.cambios, this.height, this.width);

    const cambiadas: number[] = [];
    for (let y = 0; y < this.height; y++) {
      const filaPre = pre[y];
      const filaPost = post[y];
      for (let x = 0; x < this.width; x++) {
        /* Celda ausente en un lado: se compara contra el centinela -1 (mismo criterio que
           cellDiffCount en grid.ts), asi que aparecer/desaparecer cuenta como cambio. */
        const valorPre = filaPre?.[x] ?? -1;
        const valorPost = filaPost?.[x] ?? -1;
        if (valorPre !== valorPost) {
          contadores.cambios[y][x] += 1;
          this.cambiosTotales[y][x] += 1;
          cambiadas.push(y * this.width + x);
        }
      }
    }

    this.registrarSoledad(cambiadas);
    this.recomputar();
  }

  /** Mascara vigente, o `null` si todavia no hay evidencia suficiente (o si se desactivo por el
   *  tope de fraccion). `null` significa "compara todo", el comportamiento previo a este BL. */
  get mask(): VolatilityMask | null {
    if (this.volatileCount === 0 || this.desactivadaPorTope) return null;
    return this.volatile;
  }

  /** Cambia cada vez que el conjunto de celdas volatiles cambia. Los consumidores que cachean algo
   *  derivado de la mascara (firmas de estado, por ejemplo) comparan esta version para saber que
   *  lo cacheado dejo de ser comparable. */
  get version(): number {
    return this.versionActual;
  }

  volatileCellCount(): number {
    return this.desactivadaPorTope ? 0 : this.volatileCount;
  }

  observedTransitions(): number {
    return this.transiciones;
  }

  private contadoresDe(action: string): ContadoresDeAccion {
    const existente = this.porAccion.get(action);
    if (existente !== undefined) return existente;
    const nuevo: ContadoresDeAccion = { transiciones: 0, cambios: [] };
    ensureRows(nuevo.cambios, this.height, this.width);
    this.porAccion.set(action, nuevo);
    return nuevo;
  }

  private crecerHasta(height: number, width: number): void {
    if (height <= this.height && width <= this.width) return;
    this.height = Math.max(this.height, height);
    this.width = Math.max(this.width, width);
    ensureBoolRows(this.volatile, this.height, this.width);
    ensureBoolRows(this.volatilPorFrecuencia, this.height, this.width);
    ensureBoolRows(this.volatilPorBarrido, this.height, this.width);
    ensureRows(this.cambiosTotales, this.height, this.width);
    ensureRows(this.cambiosAislados, this.height, this.width);
    for (const contadores of this.porAccion.values()) {
      ensureRows(contadores.cambios, this.height, this.width);
    }
  }

  /** Marca cuales de los cambios de ESTA transicion ocurrieron sin compania alrededor. Es la unica
   *  parte del criterio de barrido que no se puede recalcular despues: depende de que cambio JUNTO
   *  con que, y eso se pierde en cuanto se acumulan los contadores. */
  private registrarSoledad(cambiadas: number[]): void {
    if (cambiadas.length === 0) return;
    const enDiff = new Set(cambiadas);
    for (const indice of cambiadas) {
      const y = Math.floor(indice / this.width);
      const x = indice % this.width;
      let solo = true;
      for (let dy = -SWEEP_ISOLATION_RADIUS; dy <= SWEEP_ISOLATION_RADIUS && solo; dy++) {
        for (let dx = -SWEEP_ISOLATION_RADIUS; dx <= SWEEP_ISOLATION_RADIUS; dx++) {
          if (dy === 0 && dx === 0) continue;
          const ny = y + dy;
          const nx = x + dx;
          if (ny < 0 || nx < 0 || ny >= this.height || nx >= this.width) continue;
          if (enDiff.has(ny * this.width + nx)) {
            solo = false;
            break;
          }
        }
      }
      if (solo) this.cambiosAislados[y][x] += 1;
    }
  }

  /** Reevalua las dos familias contra los contadores acumulados y publica la union. O(celdas x
   *  acciones) por transicion -- ~4K x 8 en un frame ARC de 64x64, despreciable frente a una
   *  llamada HTTP. */
  private recomputar(): void {
    const cambioFrecuencia = this.recomputarPorFrecuencia();
    const cambioBarrido = this.recomputarPorBarrido();
    if (!cambioFrecuencia && !cambioBarrido) return;

    let volatiles = 0;
    for (let y = 0; y < this.height; y++) {
      for (let x = 0; x < this.width; x++) {
        const esVolatil = this.volatilPorFrecuencia[y][x] || this.volatilPorBarrido[y][x];
        this.volatile[y][x] = esVolatil;
        if (esVolatil) volatiles++;
      }
    }

    this.volatileCount = volatiles;
    const tope = this.height * this.width * VOLATILITY_MAX_FRACTION;
    this.desactivadaPorTope = volatiles > tope;
    this.versionActual += 1;
  }

  /** Familia 1: celdas que cambian casi siempre bajo TODAS las acciones. */
  private recomputarPorFrecuencia(): boolean {
    const acciones = [...this.porAccion.values()];
    if (this.transiciones < VOLATILITY_MIN_TRANSITIONS) return false;
    if (acciones.length < VOLATILITY_MIN_DISTINCT_ACTIONS) return false;

    let cambio = false;
    for (let y = 0; y < this.height; y++) {
      for (let x = 0; x < this.width; x++) {
        const eraVolatil = this.volatilPorFrecuencia[y][x];
        const umbral = eraVolatil ? VOLATILITY_EXIT_RATIO : VOLATILITY_ENTRY_RATIO;
        const esVolatil = acciones.every(
          (contadores) =>
            contadores.transiciones === 0 ||
            contadores.cambios[y][x] >= contadores.transiciones * umbral,
        );
        if (esVolatil !== eraVolatil) {
          this.volatilPorFrecuencia[y][x] = esVolatil;
          cambio = true;
        }
      }
    }
    return cambio;
  }

  /** Familia 2: barras de progreso / contadores de barrido. Ver el encabezado del archivo. */
  private recomputarPorBarrido(): boolean {
    if (this.transiciones < SWEEP_MIN_TRANSITIONS) return false;
    if (this.porAccion.size < VOLATILITY_MIN_DISTINCT_ACTIONS) return false;

    const nuevo: boolean[][] = Array.from({ length: this.height }, () =>
      new Array<boolean>(this.width).fill(false),
    );
    for (const celdas of this.componentesDeCambio()) {
      if (celdas.length < SWEEP_MIN_CELLS) continue;
      if (!esLinea(celdas, this.width)) continue;
      if (this.accionesQueTocaron(celdas) < VOLATILITY_MIN_DISTINCT_ACTIONS) continue;

      let cambios = 0;
      let aislados = 0;
      for (const indice of celdas) {
        const y = Math.floor(indice / this.width);
        const x = indice % this.width;
        cambios += this.cambiosTotales[y][x];
        aislados += this.cambiosAislados[y][x];
      }
      // Que los cambios ocurran de a UNO es lo que separa una barra de un objeto que se mueve (dos
      // celdas adyacentes por paso) o de un tablero que responde (bloques enteros).
      if (aislados < cambios * SWEEP_MIN_ISOLATION_RATIO) continue;

      const yaEnmascarada = celdas.some(
        (indice) => this.volatilPorBarrido[Math.floor(indice / this.width)][indice % this.width],
      );
      const umbral = yaEnmascarada ? SWEEP_EXIT_RATIO : SWEEP_ENTRY_RATIO;
      if (cambios < this.transiciones * umbral) continue;

      for (const indice of this.celdasDeLaBarra(celdas)) {
        nuevo[Math.floor(indice / this.width)][indice % this.width] = true;
      }
    }

    let cambio = false;
    for (let y = 0; y < this.height; y++) {
      for (let x = 0; x < this.width; x++) {
        if (nuevo[y][x] !== this.volatilPorBarrido[y][x]) {
          this.volatilPorBarrido[y][x] = nuevo[y][x];
          cambio = true;
        }
      }
    }
    return cambio;
  }

  /** Componentes conexas (8-conectividad) de TODAS las celdas que cambiaron alguna vez. Agrupar por
   *  region y no por celda es lo que sostiene el criterio cuando el tablero roza la barra: una
   *  interferencia puntual no puede sacar celdas del medio y partirla en pedazos irreconocibles.
   *  El precio -- que una barra PEGADA al tablero forme una sola componente y ya no parezca una
   *  linea -- es el lado correcto del error: no enmascarar nada es el comportamiento previo. */
  private componentesDeCambio(): number[][] {
    const candidata: boolean[][] = Array.from({ length: this.height }, () =>
      new Array<boolean>(this.width).fill(false),
    );
    for (let y = 0; y < this.height; y++) {
      for (let x = 0; x < this.width; x++) {
        candidata[y][x] = this.cambiosTotales[y][x] > 0;
      }
    }

    const visitada: boolean[][] = Array.from({ length: this.height }, () =>
      new Array<boolean>(this.width).fill(false),
    );
    const componentes: number[][] = [];
    for (let y0 = 0; y0 < this.height; y0++) {
      for (let x0 = 0; x0 < this.width; x0++) {
        if (!candidata[y0][x0] || visitada[y0][x0]) continue;
        const celdas: number[] = [];
        const pila: [number, number][] = [[y0, x0]];
        visitada[y0][x0] = true;
        while (pila.length > 0) {
          const [y, x] = pila.pop() as [number, number];
          celdas.push(y * this.width + x);
          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              const ny = y + dy;
              const nx = x + dx;
              if (ny < 0 || nx < 0 || ny >= this.height || nx >= this.width) continue;
              if (!candidata[ny][nx] || visitada[ny][nx]) continue;
              visitada[ny][nx] = true;
              pila.push([ny, nx]);
            }
          }
        }
        componentes.push(celdas);
      }
    }
    return componentes;
  }

  /** BL.21559 -- celdas que hay que enmascarar por una barra YA reconocida.
   *
   *  EL PROBLEMA QUE RESUELVE, medido en vivo. La componente crece de a UNA celda por paso (esa es
   *  la definicion de barra de barrido), asi que enmascarar solo lo ya observado hace que el
   *  conjunto volatil -- y por lo tanto la VERSION de la mascara y toda firma calculada con ella --
   *  cambie en cada paso durante ~48 pasos, hasta que la barra completa su primera vuelta. Medido
   *  reproduciendo las cuatro partidas reales con la mascara VIVA (no la final): 50 versiones
   *  distintas de mascara por partida y firmas unicas 78/83 en ar25, 95/100 en ka59, 123/128 en
   *  dc22 -- practicamente lo mismo que SIN mascara. La mejora que BL.21558 midio (78 -> 19, 95 ->
   *  9, 123 -> 9) era RETROSPECTIVA, con la mascara final aplicada a toda la trayectoria; durante la
   *  partida no existia. Sin firmas que se repitan, "estado nuevo" no significa nada y la novedad
   *  por conteo de BL.21559 no tiene sobre que contar.
   *
   *  LA REGLA. Si la barra vive sobre un BORDE del frame se enmascara la linea ENTERA desde el
   *  momento en que se la reconoce, no solo las celdas que ya se encendieron. Las celdas que faltan
   *  son las que la barra va a encender en los proximos pasos: adelantarse es lo que vuelve la
   *  mascara ESTABLE. Las cuatro barras medidas contra la API oficial estan justo ahi -- lf52 fila
   *  0, ar25 columna 63, ka59 y dc22 fila 63 -- y ocupan el borde completo, asi que sobre dato real
   *  la extension no agrega NI UNA celda que la barra no vaya a ocupar igual.
   *
   *  POR QUE SOLO EN EL BORDE. Extender una linea interior barreria una fila o columna entera del
   *  TABLERO por si acaso, que es el error que este modulo mas evita (ver "POR QUE CONSERVADOR").
   *  Una barra que no este en un borde conserva el comportamiento previo: se enmascara de a una
   *  celda, mas lento pero nunca de mas. */
  private celdasDeLaBarra(celdas: number[]): number[] {
    const primeraY = Math.floor(celdas[0] / this.width);
    const primeraX = celdas[0] % this.width;
    const esHorizontal = celdas.every((indice) => Math.floor(indice / this.width) === primeraY);
    if (esHorizontal && (primeraY === 0 || primeraY === this.height - 1)) {
      return Array.from({ length: this.width }, (_, x) => primeraY * this.width + x);
    }
    const esVertical = celdas.every((indice) => indice % this.width === primeraX);
    if (esVertical && (primeraX === 0 || primeraX === this.width - 1)) {
      return Array.from({ length: this.height }, (_, y) => y * this.width + primeraX);
    }
    return celdas;
  }

  /** Cuantas acciones distintas provocaron al menos un cambio dentro de la componente. */
  private accionesQueTocaron(celdas: number[]): number {
    let acciones = 0;
    for (const contadores of this.porAccion.values()) {
      const toco = celdas.some(
        (indice) => contadores.cambios[Math.floor(indice / this.width)][indice % this.width] > 0,
      );
      if (toco) acciones++;
    }
    return acciones;
  }
}

/** `true` si la componente es una linea de UNA celda de ancho (fila o columna). Es la forma de una
 *  barra de progreso y NO la de una region del tablero que se enciende de a una celda -- el falso
 *  positivo mas peligroso, porque dejaria al agente ciego justo donde esta la señal. */
function esLinea(celdas: number[], width: number): boolean {
  let minY = Infinity;
  let maxY = -Infinity;
  let minX = Infinity;
  let maxX = -Infinity;
  for (const indice of celdas) {
    const y = Math.floor(indice / width);
    const x = indice % width;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
  }
  return minY === maxY || minX === maxX;
}
