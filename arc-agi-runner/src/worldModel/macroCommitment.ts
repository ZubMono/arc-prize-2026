/* [arc-agi-runner/worldModel/macroCommitment] BL.21559 -- COMPROMISO CON LA ACCION ELEGIDA
   (macro-accion): una vez elegida una accion se la REPITE mientras siga produciendo cambio
   ENMASCARADO, hasta un tope de `MACRO_MAX_STEPS` pasos. Es lo que convierte "probar ACTION1" en
   "avanzar hasta chocar".

   EL DEFECTO QUE ARREGLA, medido en produccion contra la API oficial. Sin compromiso, la politica
   elegia de nuevo desde cero en cada paso y el desempate por menos-observada producia ciclado
   PERFECTO: ar25-0c556536 {A1:15, A2:16, A3:15, A4:16, A5:3, A6:3, A7:15} con racha maxima de 2
   pasos iguales en 83; ka59-38d34dbb {A1:24, A2:24, A3:23, A4:23, A6:6}, racha maxima 2 en 100;
   dc22-fdcac232 {A1:30, A2:29, A3:30, A4:30, A6:9}, racha maxima 2 en 128. En un juego de
   desplazamiento eso es lo peor que se puede hacer: arriba + abajo + izquierda + derecha se
   cancelan EXACTO y el agente termina el episodio donde empezo. Random puro tiene mas varianza.

   POR QUE EL CRITERIO DE CORTE ES EL CAMBIO ENMASCARADO Y NO UN LARGO FIJO. Repetir una accion que
   ya no hace nada es gastar presupuesto (el score de ARC-AGI-3 penaliza CUADRATICAMENTE cada accion
   de mas). "Dejo de cambiar el tablero" es exactamente la señal de choque contra una pared, de
   palanca ya bajada o de accion inerte, y solo es legible con la mascara de volatilidad de BL.21558
   -- sin ella la barra de progreso avanza en cada paso y TODO parece cambio, con lo cual la macro
   correria siempre hasta el tope. Antes de que la mascara se forme (las primeras ~16-31
   transiciones medidas en las cuatro partidas reales) eso es justamente lo que pasa, y sigue siendo
   mejor que rotar: 8 pasos en una direccion mueven al agente 8 celdas, la rotacion lo deja donde
   estaba.

   POR QUE HAY TOPE. La otra cara: una accion que cambia algo SIEMPRE (una animacion que la mascara
   todavia no reconocio) monopolizaria el episodio entero. El tope acota esa perdida a
   `MACRO_MAX_STEPS` pasos y garantiza que la exploracion vuelva a elegir.

   ESTADO ENTRE LLAMADAS. La macro vive en el objeto, no en el paso: `decide()` se llama una vez por
   accion contra la API y sin estado persistente no hay compromiso posible -- ese era, literalmente,
   el defecto. */

/** Tope de pasos consecutivos de una misma macro-accion.
 *
 *  8 es un compromiso medido: los episodios reales duran 83-128 pasos, asi que una macro completa
 *  gasta ~7-10% del presupuesto -- suficiente para cruzar un tablero tipico de ARC-AGI-3 de lado a
 *  lado, y lo bastante corto como para que un episodio pruebe del orden de una decena de macros y
 *  no se quede sin cubrir acciones. Subirlo mucho arriesga monopolizar el episodio con una sola
 *  accion; bajarlo a 2-3 devuelve el problema original, porque cuatro direcciones que se alternan
 *  cada 2 pasos siguen cancelandose. */
export const MACRO_MAX_STEPS = 8;

export interface ContextoDeContinuacion {
  /** Accion que la politica emitio en el paso anterior. Si no es la de la macro, algo se metio en
   *  el medio (un plan sembrado, un RESET) y la macro ya no describe lo que paso. */
  accionAnterior: string | null;
  /** La transicion anterior cambio el tablero IGNORANDO las celdas volatiles. */
  huboCambioEnmascarado: boolean;
  /** Acciones disponibles en el estado actual -- una macro nunca puede emitir una accion que el
   *  juego dejo de ofrecer. */
  disponibles: readonly string[];
}

export class MacroCommitment {
  private accion: string | null = null;
  private pasos = 0;

  /** Accion con la que hay compromiso vigente, o `null`. */
  get accionVigente(): string | null {
    return this.accion;
  }

  /** Pasos ya emitidos de la macro vigente (0 si no hay ninguna). */
  get pasosEmitidos(): number {
    return this.pasos;
  }

  /** Accion a repetir en este paso, o `null` si el compromiso termino (y entonces la politica
   *  vuelve a elegir). Cancela la macro en cuanto deja de cumplirse alguna condicion: nunca queda
   *  un compromiso "a medias" que reviva mas adelante con evidencia vieja. */
  continuar(ctx: ContextoDeContinuacion): string | null {
    const accion = this.accion;
    if (accion === null) return null;
    if (ctx.accionAnterior !== accion) {
      this.cancelar();
      return null;
    }
    if (!ctx.huboCambioEnmascarado) {
      this.cancelar();
      return null;
    }
    if (!ctx.disponibles.includes(accion)) {
      this.cancelar();
      return null;
    }
    if (this.pasos >= MACRO_MAX_STEPS) {
      this.cancelar();
      return null;
    }
    this.pasos += 1;
    return accion;
  }

  /** Abre un compromiso nuevo con `accion` -- el paso que se esta por emitir cuenta como el
   *  primero de la macro. */
  iniciar(accion: string): void {
    this.accion = accion;
    this.pasos = 1;
  }

  cancelar(): void {
    this.accion = null;
    this.pasos = 0;
  }
}
