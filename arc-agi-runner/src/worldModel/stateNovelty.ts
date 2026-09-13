/* [arc-agi-runner/worldModel/stateNovelty] BL.21559 -- NOVEDAD POR CONTEO sobre la firma
   ENMASCARADA: cuenta visitas por estado y por par (estado, accion) para que el desempate de la
   exploracion prefiera "ir a un estado poco visitado" en vez de "repartir las acciones parejo".

   EL DEFECTO QUE REEMPLAZA, medido en produccion contra la API oficial. La distribucion de acciones
   por partida era ciclado PERFECTO: ar25-0c556536 {A1:15, A2:16, A3:15, A4:16, A5:3, A6:3, A7:15};
   ka59-38d34dbb {A1:24, A2:24, A3:23, A4:23, A6:6}; dc22-fdcac232 {A1:30, A2:29, A3:30, A4:30,
   A6:9} -- con rachas de a lo sumo 2 pasos iguales en 83, 100 y 128 pasos. Sale de que
   `uncertaintyRank` vale 0 para todas las acciones (en juego real casi ninguna llega a confirmar
   una regla) y el unico desempate que quedaba era `getObservationCount` ascendente, o sea rotacion
   estricta. En un juego de desplazamiento esa es la PEOR politica posible: arriba + abajo +
   izquierda + derecha se cancelan exacto y el episodio termina donde empezo.

   EL CRITERIO. Para cada accion candidata desde la firma actual:
     1. par (firma, accion) nunca probado -> maxima novedad, va primero;
     2. ya probado -> se ordena por VISITAS DEL ESTADO DESTINO (ascendente) y, a igualdad, por
        veces que se probo el par. Una accion que devuelve a un estado ya pisado mil veces pierde
        contra una que lleva a uno visto una sola vez.
   No es una tabla de valor ni un bandit: es conteo puro, del mismo orden de costo que el criterio
   que reemplaza (una lectura de Map por candidata).

   POR QUE SOBRE LA FIRMA ENMASCARADA Y NO SOBRE EL FRAME CRUDO. Sin la mascara de volatilidad
   (BL.21558) ninguna firma se repite jamas -- la barra de progreso avanza una celda por paso y
   vuelve unico a cada frame -- asi que TODO estado seria nuevo, TODA accion tendria destino
   desconocido y el criterio no discriminaria nada. Es la misma razon por la que este BL tuvo que
   estabilizar la mascara viva (ver `celdasDeLaBarra` en volatilityMask.ts): medido reproduciendo
   las cuatro partidas reales paso a paso, las firmas unicas eran 78/83, 95/100 y 123/128 -- con la
   mascara estable bajan a 33/83, 30/100 y 37/128, que es cuando "estado nuevo" recien significa
   algo.

   SOBRE-COLAPSO (limitacion conocida, no defecto). Si el agente no consigue cambiar NADA del
   tablero en todo el episodio, todas las firmas colapsan a una sola (medido en lf52-271a04aa: 3
   firmas enmascaradas en 92 pasos) y este criterio se queda sin señal: todos los destinos son el
   mismo estado con las mismas visitas y el desempate cae, correctamente, en "la menos probada desde
   aca". Ahi el que sostiene el comportamiento es el compromiso de macro-accion
   (macroCommitment.ts), no la novedad. */

/** Clave de un par (firma, accion). El separador `|` no puede aparecer en una firma (siempre es un
 *  entero sin signo serializado) ni en un nombre de accion (`ACTION1..7`, `RESET`). */
function clavePar(firma: string, accion: string): string {
  return `${firma}|${accion}`;
}

export class StateNoveltyTracker {
  private readonly visitasPorFirma = new Map<string, number>();
  private readonly intentosPorPar = new Map<string, number>();
  /** Ultimo destino observado de un par. Se guarda el ULTIMO y no todos porque el efecto de una
   *  accion en ARC-AGI-3 depende del estado global del juego: el destino de hace 40 pasos puede ya
   *  no valer, y el reciente es la mejor estimacion disponible sin inventar un modelo. */
  private readonly destinoPorPar = new Map<string, string>();

  /** Suma una visita al estado. Se llama UNA vez por paso, con la firma vigente. */
  registrarVisita(firma: string): void {
    this.visitasPorFirma.set(firma, (this.visitasPorFirma.get(firma) ?? 0) + 1);
  }

  /** Registra que `accion` llevo de `origen` a `destino`. El llamador NO debe invocarla cuando las
   *  dos firmas se calcularon con mascaras distintas: serian hashes de dos definiciones de
   *  "estado" y el destino guardado no describiria nada. */
  registrarTransicion(origen: string, accion: string, destino: string): void {
    const clave = clavePar(origen, accion);
    this.intentosPorPar.set(clave, (this.intentosPorPar.get(clave) ?? 0) + 1);
    this.destinoPorPar.set(clave, destino);
  }

  visitasDe(firma: string): number {
    return this.visitasPorFirma.get(firma) ?? 0;
  }

  intentosDe(firma: string, accion: string): number {
    return this.intentosPorPar.get(clavePar(firma, accion)) ?? 0;
  }

  /** Estados distintos vistos en el episodio -- solo observabilidad (logs y tests de efecto). */
  firmasDistintas(): number {
    return this.visitasPorFirma.size;
  }

  /** `true` si desde `firma` queda al menos una accion de `disponibles` sin probar -- la señal que
   *  el criterio necesita para poder discriminar. Solo observabilidad. */
  hayAccionSinProbar(firma: string, disponibles: readonly string[]): boolean {
    return disponibles.some((accion) => this.intentosDe(firma, accion) === 0);
  }

  /** Comparador de novedad entre dos acciones desde el MISMO estado. Negativo = `a` es mas novedosa
   *  (va primero). Devuelve 0 cuando no hay con que separarlas, y ahi decide el criterio siguiente
   *  del llamador -- nunca inventa un orden. */
  comparar(firma: string, a: string, b: string): number {
    const intentosA = this.intentosDe(firma, a);
    const intentosB = this.intentosDe(firma, b);
    // Nunca probada desde aca = maxima novedad. Empatan entre si a proposito: separarlas por
    // conteo global seria volver al round-robin que este modulo existe para romper.
    if (intentosA === 0 || intentosB === 0)
      return (intentosA === 0 ? 0 : 1) - (intentosB === 0 ? 0 : 1);

    const visitasDestinoA = this.visitasDelDestino(firma, a);
    const visitasDestinoB = this.visitasDelDestino(firma, b);
    if (visitasDestinoA !== visitasDestinoB) return visitasDestinoA - visitasDestinoB;
    return intentosA - intentosB;
  }

  /** Visitas del estado al que lleva `accion` desde `firma`. Destino desconocido (el par se probo
   *  en un paso donde la mascara cambio, ver `registrarTransicion`) cuenta como 0: sin evidencia se
   *  asume novedoso, que es el lado del error que hace explorar en vez de dejar de explorar. */
  private visitasDelDestino(firma: string, accion: string): number {
    const destino = this.destinoPorPar.get(clavePar(firma, accion));
    return destino === undefined ? 0 : this.visitasDe(destino);
  }
}
