/* [arc-agi-runner/worldModel/mechanicsPosterior] BL.21593 -- INFERENCIA BAYESIANA EXACTA sobre el
   mapeo boton -> mecanica, con un latente JERARQUICO enumerable y una verosimilitud que EXPLICA
   el fallo. Espejo EXACTO de arc-agi3-kaggle-agent/arc_agent/mechanics_posterior.py: los tests
   homonimos pinnean los MISMOS numeros y las operaciones flotantes se hacen en el MISMO orden.

   EL MODELO, en dos capas y sin EM ni aproximaciones (todo cabe en un diccionario):
   1. ARQUETIPO del juego -- latente de la capa alta, con prior observable en el PRIMER frame:
      P(arquetipo | conjunto de acciones disponibles) sale de `conjuntosMedidos` (25 juegos
      publicos, BL.21590): `mueveCanonico` (11/17 con flechas), `flechasSinMapeo` (6/17),
      `mixto` (masa de Laplace) y `sinFlechas` (sin ACTION1..4 no hay mapeo que inferir).
   2. MECANICA por boton -- P(boton -> mecanica | arquetipo): condicional PARAMETRICA (jamas por
      game_id) derivada de `juegosQueConfirmanPorAccion`. Soporte: 4 direcciones + `inerte` +
      `otra` (mecanica visible no direccional) + `desconocida` (masa RESERVADA).

   Botones condicionalmente independientes dado el arquetipo: P(a|datos) proporcional a
   P(a) * prod_b sum_m P(m|a,b) * L(b,m). El acople por arquetipo es el punto: tres flechas
   muertas suben P(flechasSinMapeo) y la cuarta llega casi resuelta.

   LA PIEZA CENTRAL -- la verosimilitud del fallo se DESCOMPONE:
       P(no se movio | boton = direccion d) = P(pared en d | grilla) + P(desconocido)
   `P(pared | grilla)` es OBSERVABLE (wallPerception.ts). Fallo con pared adyacente en la
   direccion de la hipotesis = explicado, NO mueve el posterior; sin pared SI lo mueve; pared
   inobservable aporta poco pero no cero. El "inconcluso" de BL.21590 deja de ser rama cableada.

   MASA RESERVADA `desconocida`: verosimilitud agnostica + piso que nunca baja; si acumula, se
   REGISTRA (resumen -> reasoning persistido) como senal de vocabulario incompleto. NADA de crear
   categorias online: decision de alcance del BL. */

import { DIRECTION_PRIORS } from './directionPriors';
import { DIRECCIONES, PARED_DESCONOCIDA, type ContextoDePared } from './wallPerception';

export const MECANICA_INERTE = 'inerte';
export const MECANICA_OTRA = 'otra';
export const MECANICA_DESCONOCIDA = 'desconocida';

/* BL.21853 -- los tres simbolos que antes compartian el cajon `otra`; son tipos que
   `objectMechanics.clasificarCluster` ya emitia. Medido sobre 7.258 transiciones: recoloreo 1.539
   (25 juegos), desaparicion 248 (9), aparicion 78 (8).
   ALCANCE (revision de BL.21853, RFM-08): la FRECUENCIA los justifica, el EFECTO no. Se emiten
   (1.267/199/12) pero ningun consumidor actua sobre CUAL gano; aislados BAJAN el acierto
   (130 -> 124) y en el paquete aportan +1 sobre 182 pares. */
export const MECANICA_RECOLOREO = 'recoloreo';
export const MECANICA_APARICION = 'aparicion';
export const MECANICA_DESAPARICION = 'desaparicion';

/** Las visibles y NO direccionales con nombre; `MECANICA_OTRA` es el residual, no su sinonimo. */
export const MECANICAS_NOMBRADAS = [
  MECANICA_RECOLOREO,
  MECANICA_APARICION,
  MECANICA_DESAPARICION,
] as const;

/** Orden FIJO: las sumas flotantes se hacen en este orden en los dos puertos (paridad exacta). */
export const MECANICAS = [
  'arriba',
  'abajo',
  'izquierda',
  'derecha',
  MECANICA_INERTE,
  MECANICA_RECOLOREO,
  MECANICA_APARICION,
  MECANICA_DESAPARICION,
  MECANICA_OTRA,
  MECANICA_DESCONOCIDA,
] as const;

/** Reparto de la masa "visible y no direccional" que antes se llevaba entera `otra`: los EVENTOS
 *  que el pipeline emite sobre el corpus (BL.21853, 7.258 transiciones), Laplace +1. OJO CON EL
 *  DENOMINADOR -- aca estuvo MAL una vez: contar las familias ANTES del cambio deja el residual en
 *  0 y los 270 pasos que SI salen `otra` sin donde concentrar (134 botones direccionales vs 140). */
export const CONTEO_VISIBLE_MEDIDO: Readonly<Record<string, number>> = {
  [MECANICA_RECOLOREO]: 1267,
  [MECANICA_APARICION]: 12,
  [MECANICA_DESAPARICION]: 199,
  [MECANICA_OTRA]: 270,
};

export const REPARTO_VISIBLE: Readonly<Record<string, number>> = (() => {
  const claves = Object.keys(CONTEO_VISIBLE_MEDIDO);
  const total = claves.reduce((acc, k) => acc + CONTEO_VISIBLE_MEDIDO[k], 0) + claves.length;
  const salida: Record<string, number> = {};
  for (const k of claves) salida[k] = (CONTEO_VISIBLE_MEDIDO[k] + 1) / total; // @proto-safe: claves del modulo
  return salida;
})();

export const ARQUETIPO_MUEVE = 'mueveCanonico';
export const ARQUETIPO_SIN_MAPEO = 'flechasSinMapeo';
export const ARQUETIPO_MIXTO = 'mixto';
export const ARQUETIPO_SIN_FLECHAS = 'sinFlechas';
export const ARQUETIPOS = [
  ARQUETIPO_MUEVE,
  ARQUETIPO_SIN_MAPEO,
  ARQUETIPO_MIXTO,
  ARQUETIPO_SIN_FLECHAS,
] as const;

export const BOTONES_DE_FLECHA = ['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4'] as const;

/** Piso de la masa reservada `desconocida`: NUNCA baja de aca. */
export const PISO_DESCONOCIDO = 0.02;

/** Un boton esta RESUELTO cuando una mecanica concentra este posterior. Derivado: lo supera UNA
 *  corrida monotona de confirmacion y no lo alcanza el prior solo (pinneado en tests). */
export const UMBRAL_RESOLUCION = 0.85;

export const UMBRAL_VOCABULARIO_INCOMPLETO = 0.35;
export const MIN_OBSERVACIONES_VOCABULARIO = 4;

/** Verosimilitudes de traslacion: DENTRO de una corrida monotona el sensor es fiel (0 remapeos
 *  espurios medidos); AISLADA es sospechosa -- la ambiguedad objeto/hueco invierte el signo de
 *  forma sistematica (medido: 20 lecturas invertidas contra 6 en un juego). */
export const L_TRASLACION_FIEL = 0.9;
export const L_TRASLACION_CONTRARIA_FIEL = 0.01;
export const L_TRASLACION_AISLADA = 0.65;
export const L_TRASLACION_CONTRARIA_AISLADA = 0.35;
export const L_TRASLACION_ORTOGONAL = 0.02;
export const L_TRASLACION_SI_INERTE = 0.01;
export const L_TRASLACION_SI_OTRA = 0.05;
export const L_TRASLACION_AGNOSTICA = 0.125;

/** P(pared | contexto observado). Ni 1.0 ni 0.0: la percepcion de pared es un detector. */
export const P_PARED: Readonly<Record<string, number>> = {
  presente: 0.95,
  ausente: 0.05,
  desconocida: 0.5,
};

/** P(desconocido) del fallo: "un fallo inexplicable aporta poco pero no cero" -- este es el poco. */
export const PISO_FALLO_INEXPLICADO = 0.05;

export const L_SIN_CAMBIO_SI_INERTE = 0.95;
export const L_SIN_CAMBIO_SI_OTRA = 0.3;
export const L_SIN_CAMBIO_AGNOSTICA = 0.5;

/** L(evento `otra` | mecanica). BL.21853 cambio DOS numeros por la misma razon: `otra` ya no
 *  significa lo que significaba. Antes era una mecanica visible LIMPIA y por eso `direccion` valia
 *  0.02; esos casos tienen simbolo propio ahora y lo que queda es una MEZCLA de nombradas, que no
 *  dice nada de la direccion: pasa a 0.05, el agnostico de `L_DETECTOR_DESCONOCIDA`. MEDIDO sobre
 *  7.258 transiciones: con 0.02 el vocabulario ampliado acierta 144 botones direccionales de 204
 *  (el detector solo acierta 150); con 0.05 sube a 151. `nombrada` es la fila nueva. */
const L_OTRA_MECANICA: Readonly<Record<string, number>> = {
  direccion: 0.05,
  inerte: 0.02,
  nombrada: 0.15,
  otra: 0.6,
  desconocida: 0.3,
};
const L_DETECTOR_DESCONOCIDA: Readonly<Record<string, number>> = {
  direccion: 0.05,
  inerte: 0.03,
  nombrada: 0.15,
  otra: 0.2,
  desconocida: 0.4,
};

/** BL.21853 -- L(evento de una mecanica NOMBRADA | mecanica del boton). `propia` conserva el 0.6
 *  que tenia `otra` -> `otra`; `hermana` baja a 0.05. ALCANCE HONESTO: barrido 0.05..0.60 sobre las
 *  7.258 transiciones dio SIEMPRE lo mismo -- sobre ESTE corpus el valor no decide nada. */
const L_MECANICA_NOMBRADA: Readonly<Record<string, number>> = {
  direccion: 0.02,
  inerte: 0.02,
  propia: 0.6,
  hermana: 0.05,
  residual: 0.1,
  desconocida: 0.3,
};

export const EVENTO_TRASLACION = 'traslacion';
export const EVENTO_SIN_CAMBIO = 'sinCambio';
export const EVENTO_OTRA = 'otra';
export const EVENTO_DESCONOCIDA = 'desconocida';

/** BL.21853 -- un evento por mecanica nombrada; MISMO string que la mecanica, un solo alfabeto. */
export const EVENTO_RECOLOREO = MECANICA_RECOLOREO;
export const EVENTO_APARICION = MECANICA_APARICION;
export const EVENTO_DESAPARICION = MECANICA_DESAPARICION;

/** Tipos de evento que nombran una mecanica visible. FUENTE UNICA para los dos consumidores. */
export const EVENTOS_NOMBRADOS = [EVENTO_RECOLOREO, EVENTO_APARICION, EVENTO_DESAPARICION] as const;

/** Observacion de UN paso de UN boton, ya clasificada por la percepcion (BL.21561) y con el
 *  contexto de pared observado en la grilla. `pared` (nombre de direccion -> contexto) en null
 *  equivale a todo desconocida (avatar aun no visto). */
export interface EventoObservado {
  tipo: string;
  signo?: readonly [number, number] | null;
  enCorrida?: boolean;
  pared?: Record<string, ContextoDePared> | null;
}

type Distribucion = Record<string, number>;

/** P(arquetipo | conjunto de acciones), con Laplace sobre los juegos medidos de ESE conjunto.
 *  Un conjunto con flechas nunca visto cae en la tasa base de los 17 juegos con flechas. Sin
 *  flechas no hay mapeo que inferir: `sinFlechas` se lleva todo. */
export function priorDeArquetipos(claveConjunto: string): Distribucion {
  const numeros = new Set(
    claveConjunto
      .split(',')
      .filter((n) => n.trim() !== '')
      .map((n) => Math.trunc(Number(n))),
  );
  const hayFlechas = [1, 2, 3, 4].some((n) => numeros.has(n));
  if (!hayFlechas) {
    const salida: Distribucion = {};
    for (const a of ARQUETIPOS) salida[a] = a === ARQUETIPO_SIN_FLECHAS ? 1.0 : 0.0; // @proto-safe: tupla const ARQUETIPOS
    return salida;
  }
  const entrada = DIRECTION_PRIORS.conjuntosMedidos[claveConjunto];
  let juegos: number;
  let confirman: number;
  let sinMovimiento: number;
  if (entrada !== undefined && entrada.juegos > 0) {
    juegos = entrada.juegos;
    confirman = entrada.confirman;
    sinMovimiento = entrada.sinMovimiento;
  } else {
    juegos = DIRECTION_PRIORS.nJuegosConFlechas;
    confirman = DIRECTION_PRIORS.nJuegosQueConfirman;
    sinMovimiento = DIRECTION_PRIORS.nJuegosSinMovimientoObservable;
  }
  const total = juegos + 3;
  return {
    [ARQUETIPO_MUEVE]: (confirman + 1) / total,
    [ARQUETIPO_SIN_MAPEO]: (sinMovimiento + 1) / total,
    [ARQUETIPO_MIXTO]: (juegos - confirman - sinMovimiento + 1) / total,
    [ARQUETIPO_SIN_FLECHAS]: 0.0,
  };
}

/** Clampa `desconocida` al piso reservado y renormaliza el resto: la masa nunca baja de ahi. */
function conPiso(distribucion: Distribucion): Distribucion {
  const actual = distribucion[MECANICA_DESCONOCIDA];
  if (actual >= PISO_DESCONOCIDO) return distribucion;
  const resto = 1.0 - actual;
  const escala = resto > 0 ? (1.0 - PISO_DESCONOCIDO) / resto : 0.0;
  const salida: Distribucion = {};
  for (const [m, v] of Object.entries(distribucion)) salida[m] = v * escala; // @proto-safe: claves = MECANICAS del modulo
  salida[MECANICA_DESCONOCIDA] = PISO_DESCONOCIDO; // @proto-safe: constante del modulo
  return salida;
}

/** P(mecanica | arquetipo, boton) -- parametrica, derivada de la medicion de 25 juegos.
 *  `mueveCanonico`: la masa canonica sale de `juegosQueConfirmanPorAccion` (una flecha individual
 *  puede seguir muerta: se midio medio D-pad inerte); el resto segun los modos de fallo medidos.
 *  `flechasSinMapeo`: inerte domina. `mixto`: difusa a proposito -- el arquetipo de lo no medido. */
export function condicionalDeMecanicas(arquetipo: string, boton: string): Distribucion {
  const canonicaCruda = DIRECTION_PRIORS.mapeoCanonico[boton];
  const canonica: readonly [number, number] | null =
    canonicaCruda === undefined ? null : [canonicaCruda[0], canonicaCruda[1]];

  /* `visible` es la masa de "visible y no direccional" ENTERA -- la que antes se llevaba `otra`
     sola; BL.21853 la reparte con `REPARTO_VISIBLE`. El total no cambia. */
  const repartir = (
    masaCanonica: number,
    inerte: number,
    visible: number,
    desconocida: number,
  ): Distribucion => {
    const otrasDirecciones = 1.0 - masaCanonica - inerte - visible - desconocida;
    const porDireccion = otrasDirecciones / 3.0;
    const d: Distribucion = {};
    for (const m of MECANICAS) {
      if (m in DIRECCIONES) {
        const vector = DIRECCIONES[m];
        const esCanonica =
          canonica !== null && vector[0] === canonica[0] && vector[1] === canonica[1];
        d[m] = esCanonica ? masaCanonica : porDireccion; // @proto-safe: m itera la tupla const MECANICAS
      } else if (m === MECANICA_INERTE) {
        d[m] = inerte; // @proto-safe: m itera la tupla const MECANICAS
      } else if (m in REPARTO_VISIBLE) {
        d[m] = visible * REPARTO_VISIBLE[m]; // @proto-safe: m itera la tupla const MECANICAS
      } else {
        d[m] = desconocida; // @proto-safe: m itera la tupla const MECANICAS
      }
    }
    return conPiso(d);
  };

  if (arquetipo === ARQUETIPO_MUEVE) {
    const confirmanBoton = DIRECTION_PRIORS.juegosQueConfirmanPorAccion[boton] ?? 0;
    const confirmanTotal = DIRECTION_PRIORS.nJuegosQueConfirman;
    const base = confirmanTotal ? (confirmanBoton + 1) / (confirmanTotal + 2) : 0.75;
    const resto = 1.0 - base;
    return repartir(base, resto * 0.55, resto * 0.2, resto * 0.1);
  }
  if (arquetipo === ARQUETIPO_SIN_MAPEO) return repartir(0.0125, 0.6, 0.25, 0.1);
  // `mixto` y (por completitud) `sinFlechas`: difusas. Bajo `sinFlechas` no hay botones de
  // flecha sembrados, asi que su condicional jamas pesa en la practica.
  return repartir(0.3, 0.25, 0.2, 0.1);
}

/** L(evento | mecanica del boton). No depende del arquetipo dado la mecanica: se acumula una
 *  sola vez por boton y se comparte entre arquetipos. */
export function verosimilitud(evento: EventoObservado, mecanica: string): number {
  const signo = evento.signo ?? null;
  if (evento.tipo === EVENTO_TRASLACION && signo !== null) {
    if (mecanica in DIRECCIONES) {
      const d = DIRECCIONES[mecanica];
      if (signo[0] === d[0] && signo[1] === d[1]) {
        return evento.enCorrida === true ? L_TRASLACION_FIEL : L_TRASLACION_AISLADA;
      }
      if (signo[0] === -d[0] && signo[1] === -d[1]) {
        return evento.enCorrida === true
          ? L_TRASLACION_CONTRARIA_FIEL
          : L_TRASLACION_CONTRARIA_AISLADA;
      }
      return L_TRASLACION_ORTOGONAL;
    }
    if (mecanica === MECANICA_INERTE) return L_TRASLACION_SI_INERTE;
    if (mecanica in REPARTO_VISIBLE) return L_TRASLACION_SI_OTRA;
    return L_TRASLACION_AGNOSTICA;
  }
  if (evento.tipo === EVENTO_SIN_CAMBIO) {
    if (mecanica in DIRECCIONES) {
      const contexto = evento.pared?.[mecanica] ?? PARED_DESCONOCIDA;
      const pPared = P_PARED[contexto] ?? P_PARED[PARED_DESCONOCIDA];
      return pPared + (1.0 - pPared) * PISO_FALLO_INEXPLICADO;
    }
    if (mecanica === MECANICA_INERTE) return L_SIN_CAMBIO_SI_INERTE;
    if (mecanica in REPARTO_VISIBLE) return L_SIN_CAMBIO_SI_OTRA;
    return L_SIN_CAMBIO_AGNOSTICA;
  }
  if ((EVENTOS_NOMBRADOS as readonly string[]).includes(evento.tipo)) {
    /* BL.21853: la fila que se elige es lo unico que distingue `recoloreo` de `desaparicion`. */
    if (mecanica in DIRECCIONES) return L_MECANICA_NOMBRADA.direccion;
    if (mecanica === MECANICA_INERTE) return L_MECANICA_NOMBRADA.inerte;
    if (mecanica === MECANICA_DESCONOCIDA) return L_MECANICA_NOMBRADA.desconocida;
    if (mecanica === MECANICA_OTRA) return L_MECANICA_NOMBRADA.residual;
    return mecanica === evento.tipo ? L_MECANICA_NOMBRADA.propia : L_MECANICA_NOMBRADA.hermana;
  }
  const tabla = evento.tipo === EVENTO_OTRA ? L_OTRA_MECANICA : L_DETECTOR_DESCONOCIDA;
  if (mecanica in DIRECCIONES) return tabla.direccion;
  if ((MECANICAS_NOMBRADAS as readonly string[]).includes(mecanica)) return tabla.nombrada;
  return tabla[mecanica];
}

/** Posterior conjunto {arquetipo} x {boton -> mecanica}, exacto por enumeracion. UNA instancia
 *  por partida; tabla chica (4 arquetipos x <=4 botones x 7 mecanicas), se recalcula al leer. */
export class PosteriorDeMapeo {
  private arquetipos: Distribucion = {};
  private readonly condicionales = new Map<string, Record<string, Distribucion>>();
  private readonly lambda = new Map<string, Distribucion>();
  private readonly observaciones = new Map<string, number>();
  private sembrado = false;

  constructor() {
    for (const a of ARQUETIPOS) this.arquetipos[a] = 0.0; // @proto-safe: tupla const ARQUETIPOS
  }

  /** Idempotente; devuelve cuantos botones de flecha quedaron bajo inferencia. */
  sembrar(availableActions: Iterable<number>): number {
    if (this.sembrado) return 0;
    this.sembrado = true;
    const numeros = [...new Set([...availableActions].map((n) => Math.trunc(n)))].sort(
      (a, b) => a - b,
    );
    const clave = numeros.join(',');
    this.arquetipos = priorDeArquetipos(clave);
    const presentes = new Set(numeros.map((n) => `ACTION${n}`));
    for (const boton of BOTONES_DE_FLECHA) {
      if (!presentes.has(boton)) continue;
      const lambda: Distribucion = {};
      for (const m of MECANICAS) lambda[m] = 1.0; // @proto-safe: tupla const MECANICAS
      this.lambda.set(boton, lambda);
      this.observaciones.set(boton, 0);
      const porArquetipo: Record<string, Distribucion> = {};
      for (const a of ARQUETIPOS) porArquetipo[a] = condicionalDeMecanicas(a, boton); // @proto-safe: claves = ARQUETIPOS del modulo
      this.condicionales.set(boton, porArquetipo);
    }
    return this.lambda.size;
  }

  get botones(): string[] {
    return BOTONES_DE_FLECHA.filter((b) => this.lambda.has(b));
  }

  observacionesDe(boton: string): number {
    return this.observaciones.get(boton) ?? 0;
  }

  observar(boton: string, evento: EventoObservado): void {
    const acumulado = this.lambda.get(boton);
    if (acumulado === undefined) return;
    let maximo = 0.0;
    for (const m of MECANICAS) {
      acumulado[m] *= verosimilitud(evento, m);
      if (acumulado[m] > maximo) maximo = acumulado[m];
    }
    // Renormalizacion por el maximo: evita underflow y se cancela en todos los cocientes del
    // posterior (misma operacion, mismo orden, en los dos puertos).
    if (maximo > 0.0) for (const m of MECANICAS) acumulado[m] /= maximo;
    this.observaciones.set(boton, (this.observaciones.get(boton) ?? 0) + 1);
  }

  posteriorDeArquetipo(): Distribucion {
    const pesos: Distribucion = {};
    for (const a of ARQUETIPOS) {
      let v = this.arquetipos[a] ?? 0.0;
      for (const b of this.botones) {
        const cond = (this.condicionales.get(b) as Record<string, Distribucion>)[a];
        const lambda = this.lambda.get(b) as Distribucion;
        let z = 0.0;
        for (const m of MECANICAS) z += cond[m] * lambda[m];
        v *= z;
      }
      pesos[a] = v; // @proto-safe: a itera la tupla const ARQUETIPOS
    }
    let total = 0.0;
    for (const a of ARQUETIPOS) total += pesos[a];
    const salida: Distribucion = {};
    for (const a of ARQUETIPOS)
      salida[a] = total <= 0.0 ? 1.0 / ARQUETIPOS.length : pesos[a] / total; // @proto-safe: tupla const ARQUETIPOS
    return salida;
  }

  /** P(mecanica | boton, datos), marginalizando el arquetipo. Con el piso aplicado: la masa
   *  `desconocida` nunca baja de PISO_DESCONOCIDO. */
  posteriorDe(boton: string): Distribucion | null {
    const lambda = this.lambda.get(boton);
    if (lambda === undefined) return null;
    const postA = this.posteriorDeArquetipo();
    const resultado: Distribucion = {};
    for (const m of MECANICAS) resultado[m] = 0.0; // @proto-safe: claves = tupla const MECANICAS del modulo
    for (const a of ARQUETIPOS) {
      const pa = postA[a];
      if (pa <= 0.0) continue;
      const cond = (this.condicionales.get(boton) as Record<string, Distribucion>)[a];
      let z = 0.0;
      for (const m of MECANICAS) z += cond[m] * lambda[m];
      if (z <= 0.0) continue;
      for (const m of MECANICAS) resultado[m] += (pa * cond[m] * lambda[m]) / z;
    }
    return conPiso(resultado);
  }

  mecanicaDominante(boton: string): [string, number] | null {
    const posterior = this.posteriorDe(boton);
    if (posterior === null) return null;
    let dominante: string = MECANICAS[0];
    for (const m of MECANICAS) if (posterior[m] > posterior[dominante]) dominante = m;
    return [dominante, posterior[dominante]];
  }

  direccionDe(boton: string): readonly [number, number] | null {
    const dominante = this.mecanicaDominante(boton);
    if (dominante === null || !(dominante[0] in DIRECCIONES)) return null;
    return DIRECCIONES[dominante[0]];
  }

  /** El posterior concentro: deja de valer la pena gastar presupuesto en este boton. Exige al
   *  menos una observacion -- el prior solo jamas resuelve (pinneado en tests de paridad). */
  resuelta(boton: string): boolean {
    if ((this.observaciones.get(boton) ?? 0) < 1) return false;
    const dominante = this.mecanicaDominante(boton);
    return dominante !== null && dominante[1] >= UMBRAL_RESOLUCION;
  }

  inerte(boton: string): boolean {
    const dominante = this.mecanicaDominante(boton);
    return (
      dominante !== null && dominante[0] === MECANICA_INERTE && dominante[1] >= UMBRAL_RESOLUCION
    );
  }

  /** Botones cuya masa `desconocida` acumulo por encima del umbral con evidencia suficiente: el
   *  vocabulario de mecanicas no explica lo observado. Se registra, no se inventa online. */
  senalDeVocabularioIncompleto(): Array<[string, number]> {
    const senal: Array<[string, number]> = [];
    for (const boton of this.botones) {
      if ((this.observaciones.get(boton) ?? 0) < MIN_OBSERVACIONES_VOCABULARIO) continue;
      const posterior = this.posteriorDe(boton);
      if (posterior !== null && posterior[MECANICA_DESCONOCIDA] >= UMBRAL_VOCABULARIO_INCOMPLETO) {
        senal.push([boton, posterior[MECANICA_DESCONOCIDA]]);
      }
    }
    return senal;
  }

  /** Linea legible para el reasoning persistido (la 'firma en el reporte' del BL: la senal de
   *  vocabulario incompleto viaja aca y queda registrada en el corpus de la partida). */
  resumen(): string {
    if (this.lambda.size === 0) return 'posterior sin botones de flecha';
    const postA = this.posteriorDeArquetipo();
    let arquetipo: string = ARQUETIPOS[0];
    for (const a of ARQUETIPOS) if (postA[a] > postA[arquetipo]) arquetipo = a;
    const partes = [`arquetipo=${arquetipo}:${postA[arquetipo].toFixed(2)}`];
    for (const boton of this.botones) {
      const dominante = this.mecanicaDominante(boton);
      if (dominante !== null) partes.push(`${boton}=${dominante[0]}:${dominante[1].toFixed(2)}`);
    }
    const vocabulario = this.senalDeVocabularioIncompleto();
    if (vocabulario.length > 0) {
      const detalle = vocabulario.map(([b, masa]) => `${b}:${masa.toFixed(2)}`).join(',');
      partes.push(`vocabularioIncompleto=${detalle}`);
    }
    return partes.join(' ');
  }
}
