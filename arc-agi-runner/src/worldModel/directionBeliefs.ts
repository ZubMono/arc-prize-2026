/* [arc-agi-runner/worldModel/directionBeliefs] BL.21590 -- CREENCIA de mapeo de direcciones
   sembrada por el prior (directionPriors.ts, indexado por CONJUNTO de acciones disponibles, jamas
   por game_id) y VALIDADA EN PARTIDA dentro de corridas monotonas. Espejo EXACTO de
   arc-agi3-kaggle-agent/arc_agent/direction_beliefs.py: los tests homonimos sobre la misma
   grabacion real (bl21590.realGames.effect.test.ts / test_bl21590_real_games.py) afirman los
   MISMOS numeros -- si un puerto cambia el criterio y el otro no, uno de los dos se pone en rojo.

   TRES RESULTADOS POR PULSACION, NUNCA DOS: `confirma` (se movio como predecia el prior),
   `refuta` (se movio en otra direccion) e `inconcluso` (NO se movio: pared, pantalla de titulo o
   mecanica no direccional -- tratarlo como refutacion produce remapeo espurio).

   TODA FIJACION EXIGE UNA CORRIDA MONOTONA: PASOS_DE_CORRIDA_MONOTONA traslaciones del MISMO
   signo en pulsaciones CONSECUTIVAS de la MISMA accion. La medicion de los 25 juegos dejo escrito
   que el round-robin FABRICA mapeos invertidos (ambiguedad objeto/hueco de BL.21561: un juego dio
   ACTION4->izquierda 20 veces contra 6) y que el protocolo guionado -- misma accion N veces,
   posicion absoluta monotona -- lo desarma. Las macro-acciones de BL.21559 ya repiten la accion
   mientras mueva: la corrida sale gratis. Una pulsacion sin movimiento en el medio PAUSA la
   corrida (la posicion absoluta no retrocedio); otra accion, u otro signo, la cortan.

   ACTION5/ACTION7 NO TIENEN PRIOR POSIBLE (medido): entran como INCOGNITA UNIFORME sobre firmas
   de mecanica {inerte, toggle, disparo, cambioDeEscena, desconocido}. */
import { DIRECTION_PRIORS } from './directionPriors';
import {
  EVENTO_DESCONOCIDA,
  EVENTO_OTRA,
  EVENTO_SIN_CAMBIO,
  EVENTO_TRASLACION,
  EVENTOS_NOMBRADOS,
  PosteriorDeMapeo,
  type EventoObservado,
} from './mechanicsPosterior';
import { TIPO_SIN_NOMBRAR } from './mechanicsSignature';
import { TIPO_SIN_MEDICION, type Mecanica } from './objectMechanics';
import type { ContextoDePared } from './wallPerception';

export const RESULTADO_CONFIRMA = 'confirma';
export const RESULTADO_REFUTA = 'refuta';
export const RESULTADO_INCONCLUSO = 'inconcluso';
export type ResultadoDeObservacion =
  | typeof RESULTADO_CONFIRMA
  | typeof RESULTADO_REFUTA
  | typeof RESULTADO_INCONCLUSO;

export const ESTADO_SIN_PRIOR = 'sinPrior';
export const ESTADO_SEMBRADA = 'sembrada';
export const ESTADO_CONFIRMADA = 'confirmada';
export const ESTADO_REMAPEADA = 'remapeada';
export const ESTADO_OBSERVADA = 'observada';
export const ESTADO_SIN_EVIDENCIA = 'sinEvidencia';

/** Pulsaciones CONSECUTIVAS de la misma accion con traslacion del MISMO signo que fijan una
 *  creencia (confirmar, remapear o adoptar). 2 = el minimo que constituye corrida monotona: la
 *  pulsacion aislada es exactamente lo que la ambiguedad objeto/hueco invierte de forma
 *  sistematica. Espejo de PASOS_DE_CORRIDA_MONOTONA en direction_beliefs.py. */
export const PASOS_DE_CORRIDA_MONOTONA = 2;

export type Direccion = readonly [number, number];

/** Forma canonica del conjunto de acciones disponibles -- la UNICA clave del prior. */
export function claveDeConjunto(availableActions: Iterable<number>): string {
  return [...new Set([...availableActions].map((n) => Math.trunc(n)))]
    .sort((a, b) => a - b)
    .join(',');
}

function signo(valor: number): number {
  return valor > 0 ? 1 : valor < 0 ? -1 : 0;
}

/** Signo (dy,dx) de la traslacion de una mecanica, o null si el paso no es una traslacion util.
 *  Se descartan las DIAGONALES: ninguna flecha de un D-pad mueve en diagonal, y las dos medidas
 *  eran basura (un salto espurio y un cambio de escena de ACTION5). */
export function direccionDeTraslacion(mecanica: Mecanica | null): Direccion | null {
  if (mecanica === null || mecanica.tipo !== 'traslacion') return null;
  const t = mecanica.traslacionPrincipal;
  if (t === null) return null;
  const dy = signo(t.dy);
  const dx = signo(t.dx);
  if (dy !== 0 && dx !== 0) return null;
  if (dy === 0 && dx === 0) return null;
  return [dy, dx];
}

interface CreenciaDeDireccion {
  accion: string;
  direccion: Direccion | null;
  origen: 'prior' | 'observacion';
  estado: string;
  confirmaciones: number;
  refutaciones: number;
  inconclusos: number;
  /** (dy,dx) CRUDO de la ultima traslacion: el prior fija la direccion, jamas la magnitud. */
  magnitud: Direccion | null;
  corridaDireccion: Direccion | null;
  corridaPasos: number;
}

function igual(a: Direccion | null, b: Direccion | null): boolean {
  return a !== null && b !== null && a[0] === b[0] && a[1] === b[1];
}

/** BL.21593 -- clasifica para el posterior un paso SIN traslacion util: `sinCambio` lleva el
 *  contexto de pared (la descomposicion del fallo); una mecanica visible no direccional es
 *  `otra`; lo que el detector no supo nombrar (incluida una traslacion diagonal) es
 *  `desconocida` y alimenta la masa reservada. Espejo de `_evento_sin_traslacion` (Python). */
function eventoSinTraslacion(
  mecanica: Mecanica | null,
  pared: Record<string, ContextoDePared> | null,
): EventoObservado {
  // BL.21741 -- "no lo medi" NO es "no paso nada" (ver `TIPO_SIN_MEDICION`). Va a la masa
  // reservada `desconocida`, que es lo que "no se" significa en el posterior. Sin esta guarda,
  // `formaIncompatible` (que sale con celdasCambiadas === 0 SIN haber contado nada) caia en la
  // rama de abajo y alimentaba la evidencia de que el boton es inerte: la inferencia OPUESTA.
  if (mecanica !== null && mecanica.tipo === TIPO_SIN_MEDICION) {
    return { tipo: EVENTO_DESCONOCIDA };
  }
  // BL.21741 (correccion) -- `sobreElTope` tampoco es `desconocida`: el detector no miro los
  // CLUSTERS pero conto las celdas, y ese conteo es exacto y enorme. Decir "desconocida" lo
  // mandaria a `L_DETECTOR_DESCONOCIDA`, una verosimilitud calibrada para "mire y no supe". Un
  // cambio de miles de celdas es una mecanica visible y NO puede ser una traslacion (un cluster de
  // mas de 2 * MAX_TAMANO_OBJETO celdas jamas cabe en `R U (R+d)`), o sea exactamente `otra` --
  // la misma lectura que hace `IncognitaDeMecanica` mandandolo a `cambioDeEscena`.
  if (mecanica !== null && mecanica.tipo === 'sobreElTope') {
    return { tipo: EVENTO_OTRA };
  }
  if (mecanica === null || mecanica.tipo === 'sinCambio' || mecanica.celdasCambiadas === 0) {
    return { tipo: EVENTO_SIN_CAMBIO, pared };
  }
  // BL.21853 -- antes los tres caian juntos en `EVENTO_OTRA` y el posterior no podia separar un
  // boton que recolorea de uno que borra objetos. La lista es la constante que define los simbolos,
  // no un literal repetido: tipo de cluster y tipo de evento comparten string.
  if ((EVENTOS_NOMBRADOS as readonly string[]).includes(mecanica.tipo)) {
    return { tipo: mecanica.tipo };
  }
  // BL.21853 -- "mire, NOMBRE cada parte y el conjunto es una MEZCLA" no es "no supe que paso":
  // `detectarMecanica` devuelve `desconocida` en los dos casos (el tipo global colapsa en cuanto
  // los clusters difieren) y los dos alimentaban la masa reservada. Una mezcla de mecanicas
  // nombradas es una mecanica VISIBLE no direccional -- `otra` -- y es la poblacion viva que le
  // queda a ese simbolo sobre las 7.258 transiciones del corpus.
  if (
    mecanica.tipo === TIPO_SIN_NOMBRAR &&
    mecanica.clusters.length > 0 &&
    mecanica.clusters.every((c) => c.tipo !== TIPO_SIN_NOMBRAR)
  ) {
    return { tipo: EVENTO_OTRA };
  }
  return { tipo: EVENTO_DESCONOCIDA };
}

/** Mapeo accion -> direccion del episodio. UNA instancia por partida. */
export class CreenciaDeDirecciones {
  private readonly canonico = new Map<string, Direccion>(
    Object.entries(DIRECTION_PRIORS.mapeoCanonico).map(([a, v]) => [a, [v[0], v[1]] as const]),
  );
  private readonly creencias = new Map<string, CreenciaDeDireccion>();
  private readonly sembradas: string[] = [];
  private sembrada = false;
  private claveConjunto = '';
  private accionPrevia: string | null = null;
  observaciones = 0;
  /** BL.21593 -- el posterior jerarquico {arquetipo} x {boton -> mecanica} corre en paralelo a
   *  la maquina de estados: recibe CADA observacion (con su contexto de pared) y es quien decide
   *  `resuelta` cuando concentra. La maquina de BL.21590 conserva el REMAPEO (corrida monotona)
   *  y la auditoria (confirmada/remapeada/...). */
  readonly posterior = new PosteriorDeMapeo();

  /** Siembra el SUBCONJUNTO de flechas presentes (se midio un D-pad parcial: asumir que las
   *  cuatro vienen juntas es falso). Idempotente: solo la primera siembra cuenta. */
  sembrar(availableActions: Iterable<number>): number {
    if (this.sembrada) return 0;
    this.sembrada = true;
    const acciones = [...availableActions];
    this.claveConjunto = claveDeConjunto(acciones);
    this.posterior.sembrar(acciones); // BL.21593: mismo conjunto, misma unica siembra
    const disponibles = new Set(acciones.map((n) => `ACTION${n}`));
    let cuantas = 0;
    for (const accion of [...this.canonico.keys()].sort()) {
      if (!disponibles.has(accion)) continue;
      this.creencias.set(accion, {
        accion,
        direccion: this.canonico.get(accion) ?? null,
        origen: 'prior',
        estado: ESTADO_SEMBRADA,
        confirmaciones: 0,
        refutaciones: 0,
        inconclusos: 0,
        magnitud: null,
        corridaDireccion: null,
        corridaPasos: 0,
      });
      this.sembradas.push(accion);
      cuantas += 1;
    }
    return cuantas;
  }

  get claveDelConjunto(): string {
    return this.claveConjunto;
  }

  /** Confianza (Laplace) de que el prior aplique en un juego de ESTE conjunto. Observabilidad,
   *  no decision. */
  confianzaDelConjunto(): number {
    const entrada = DIRECTION_PRIORS.conjuntosMedidos[this.claveConjunto];
    if (entrada !== undefined && entrada.juegos > 0) {
      return (entrada.confirman + 1) / (entrada.juegos + 2);
    }
    const conFlechas = DIRECTION_PRIORS.nJuegosConFlechas;
    return conFlechas ? (DIRECTION_PRIORS.nJuegosQueConfirman + 1) / (conFlechas + 2) : 0.5;
  }

  /** Clasifica el efecto observado de `accion` contra la creencia vigente y la actualiza.
   *  BL.21593 -- la MISMA observacion alimenta el posterior jerarquico, con `pared` como contexto
   *  observable del fallo (wallPerception.ts). */
  observar(
    accion: string,
    mecanica: Mecanica | null,
    pared: Record<string, ContextoDePared> | null = null,
  ): ResultadoDeObservacion {
    this.observaciones += 1;
    const observada = direccionDeTraslacion(mecanica);
    const mismaCorrida = accion === this.accionPrevia;
    this.accionPrevia = accion;

    let creencia = this.creencias.get(accion);
    if (creencia === undefined) {
      creencia = {
        accion,
        direccion: null,
        origen: 'observacion',
        estado: ESTADO_SIN_PRIOR,
        confirmaciones: 0,
        refutaciones: 0,
        inconclusos: 0,
        magnitud: null,
        corridaDireccion: null,
        corridaPasos: 0,
      };
      this.creencias.set(accion, creencia);
    }

    if (observada === null) {
      this.posterior.observar(accion, eventoSinTraslacion(mecanica, pared));
      creencia.inconclusos += 1;
      // Pared en el medio de la corrida: la posicion absoluta no retrocedio, la corrida se PAUSA.
      if (!mismaCorrida) {
        creencia.corridaDireccion = null;
        creencia.corridaPasos = 0;
      }
      return RESULTADO_INCONCLUSO;
    }

    const t = mecanica?.traslacionPrincipal ?? null;
    if (t !== null) creencia.magnitud = [t.dy, t.dx];

    if (mismaCorrida && igual(creencia.corridaDireccion, observada)) {
      creencia.corridaPasos += 1;
    } else {
      creencia.corridaDireccion = observada;
      creencia.corridaPasos = 1;
    }

    // BL.21593 -- la traslacion entra al posterior con su fiabilidad medida: dentro de una
    // corrida monotona el sensor es fiel; aislada, la ambiguedad objeto/hueco la vuelve
    // sospechosa y su verosimilitud lo refleja.
    this.posterior.observar(accion, {
      tipo: EVENTO_TRASLACION,
      signo: observada,
      enCorrida: creencia.corridaPasos >= PASOS_DE_CORRIDA_MONOTONA,
    });

    if (igual(creencia.direccion, observada)) {
      creencia.confirmaciones += 1;
      if (creencia.corridaPasos >= PASOS_DE_CORRIDA_MONOTONA) {
        if (creencia.origen === 'prior') {
          creencia.estado = ESTADO_CONFIRMADA;
        } else if (creencia.estado !== ESTADO_REMAPEADA) {
          // `remapeada` NO se pisa con `observada`: que el prior fue refutado es informacion
          // que la auditoria de la partida necesita conservar.
          creencia.estado = ESTADO_OBSERVADA;
        }
      }
      return RESULTADO_CONFIRMA;
    }

    // Contradiccion (o traslacion sin prediccion). Solo una corrida monotona remapea/adopta.
    const habiaPrediccion = creencia.direccion !== null;
    if (habiaPrediccion) creencia.refutaciones += 1;
    if (creencia.corridaPasos >= PASOS_DE_CORRIDA_MONOTONA) {
      creencia.direccion = observada;
      creencia.origen = 'observacion';
      creencia.estado = habiaPrediccion ? ESTADO_REMAPEADA : ESTADO_OBSERVADA;
      creencia.confirmaciones = 0;
    }
    return habiaPrediccion ? RESULTADO_REFUTA : RESULTADO_INCONCLUSO;
  }

  /** La sonda/libro agoto sus intentos sin ver una sola traslacion: el prior queda como mejor
   *  hipotesis pero deja de gastarse presupuesto en confirmarlo. */
  declararSinEvidencia(accion: string): void {
    const creencia = this.creencias.get(accion);
    if (creencia !== undefined && creencia.estado === ESTADO_SEMBRADA) {
      creencia.estado = ESTADO_SIN_EVIDENCIA;
    }
  }

  direccionDe(accion: string): Direccion | null {
    return this.creencias.get(accion)?.direccion ?? null;
  }

  magnitudDe(accion: string): Direccion | null {
    return this.creencias.get(accion)?.magnitud ?? null;
  }

  estadoDe(accion: string): string {
    return this.creencias.get(accion)?.estado ?? ESTADO_SIN_PRIOR;
  }

  refutacionesDe(accion: string): number {
    return this.creencias.get(accion)?.refutaciones ?? 0;
  }

  /** BL.21593 -- ademas de los estados terminales de BL.21590, resuelve el POSTERIOR cuando
   *  concentra: deja de gastar presupuesto en una flecha muerta a la que el arquetipo ya condeno
   *  con la evidencia de sus hermanas, sin esperar los intentos espaciados del libro. */
  resuelta(accion: string): boolean {
    if (
      [ESTADO_CONFIRMADA, ESTADO_REMAPEADA, ESTADO_OBSERVADA, ESTADO_SIN_EVIDENCIA].includes(
        this.estadoDe(accion),
      )
    ) {
      return true;
    }
    return this.posterior.resuelta(accion);
  }

  accionesSembradas(): string[] {
    return [...this.sembradas];
  }

  mapeo(): Record<string, Direccion> {
    const resultado: Record<string, Direccion> = {};
    for (const [a, c] of [...this.creencias.entries()].sort(([x], [y]) => x.localeCompare(y))) {
      if (c.direccion !== null) resultado[a] = c.direccion; // @proto-safe: claves ACTION1..7 propias
    }
    return resultado;
  }

  resumen(): string {
    if (this.creencias.size === 0) {
      return 'sin creencia de direcciones (el juego no habilita flechas)';
    }
    return [...this.creencias.entries()]
      .sort(([x], [y]) => x.localeCompare(y))
      .map(([a, c]) =>
        c.direccion !== null
          ? `${a}=${c.direccion[0]},${c.direccion[1]}:${c.estado}`
          : `${a}=?:${c.estado}`,
      )
      .join(' ');
  }
}

// ── ACTION5/ACTION7: incognita uniforme sobre firmas de mecanica ─────────────────────────────

export const FIRMA_INERTE = 'inerte';
export const FIRMA_TOGGLE = 'toggle';
export const FIRMA_DISPARO = 'disparo';
export const FIRMA_CAMBIO_DE_ESCENA = 'cambioDeEscena';
export const FIRMA_DESCONOCIDA = 'desconocido';

export const FIRMAS_DE_MECANICA = [
  FIRMA_INERTE,
  FIRMA_TOGGLE,
  FIRMA_DISPARO,
  FIRMA_CAMBIO_DE_ESCENA,
  FIRMA_DESCONOCIDA,
] as const;
export type FirmaDeMecanica = (typeof FIRMAS_DE_MECANICA)[number];

export const ACCIONES_DE_INCOGNITA = ['ACTION5', 'ACTION7'] as const;

/** Medido: el cambio de escena movia 180-190 celdas por pulsacion; el recoloreo tipo disparo,
 *  30-60. 100 parte esa distancia sin rozar ninguno de los dos lados. */
export const CELDAS_DE_CAMBIO_DE_ESCENA = 100;

/** Evidencia sobre la mecanica de UNA accion sin prior. Posterior UNIFORME con cero
 *  observaciones (Laplace +1): "no sabemos", jamas "no hace nada". */
export class IncognitaDeMecanica {
  readonly conteos: Record<FirmaDeMecanica, number> = {
    inerte: 0,
    toggle: 0,
    disparo: 0,
    cambioDeEscena: 0,
    desconocido: 0,
  };
  private ultimoCambioDeColor: readonly [number, number] | null = null;

  observar(mecanica: Mecanica): FirmaDeMecanica {
    const firma = this.clasificar(mecanica);
    this.conteos[firma] += 1;
    return firma;
  }

  private clasificar(mecanica: Mecanica): FirmaDeMecanica {
    // BL.21741: "no lo medi" antes de "no paso nada" (ver `TIPO_SIN_MEDICION`). `sobreElTope` NO
    // entra aca a proposito: su conteo de celdas es exacto y cae solo en `cambioDeEscena`.
    if (mecanica.tipo === TIPO_SIN_MEDICION) {
      this.ultimoCambioDeColor = null;
      return FIRMA_DESCONOCIDA;
    }
    if (mecanica.tipo === 'sinCambio' || mecanica.celdasCambiadas === 0) {
      this.ultimoCambioDeColor = null;
      return FIRMA_INERTE;
    }
    if (mecanica.celdasCambiadas >= CELDAS_DE_CAMBIO_DE_ESCENA) {
      this.ultimoCambioDeColor = null;
      return FIRMA_CAMBIO_DE_ESCENA;
    }
    const cambio = mecanica.cambioDeColorPrincipal;
    if (cambio === null) {
      this.ultimoCambioDeColor = null;
      return FIRMA_DESCONOCIDA;
    }
    const par = [cambio.desde, cambio.hasta] as const;
    const previo = this.ultimoCambioDeColor;
    this.ultimoCambioDeColor = par;
    if (previo !== null && previo[0] === par[1] && previo[1] === par[0]) return FIRMA_TOGGLE;
    if (previo !== null && previo[0] === par[0] && previo[1] === par[1]) return FIRMA_DISPARO;
    return FIRMA_DESCONOCIDA;
  }

  posterior(): Record<FirmaDeMecanica, number> {
    const total =
      Object.values(this.conteos).reduce((a, b) => a + b, 0) + FIRMAS_DE_MECANICA.length;
    const resultado = {} as Record<FirmaDeMecanica, number>;
    for (const firma of FIRMAS_DE_MECANICA) {
      resultado[firma] = (this.conteos[firma] + 1) / total; // @proto-safe: tupla const del modulo
    }
    return resultado;
  }

  dominante(): FirmaDeMecanica | null {
    const maximo = Math.max(...Object.values(this.conteos));
    if (maximo === 0) return null;
    const ganadoras = FIRMAS_DE_MECANICA.filter((f) => this.conteos[f] === maximo); // @proto-safe: tupla const
    return ganadoras.length === 1 ? ganadoras[0] : null;
  }
}

/** Incognitas por accion. UNA instancia por partida; solo acumula para ACTION5/ACTION7. */
export class IncognitasDeMecanica {
  private readonly porAccion = new Map<string, IncognitaDeMecanica>();

  observar(accion: string, mecanica: Mecanica): FirmaDeMecanica | null {
    if (!(ACCIONES_DE_INCOGNITA as readonly string[]).includes(accion)) return null;
    let incognita = this.porAccion.get(accion);
    if (incognita === undefined) {
      incognita = new IncognitaDeMecanica();
      this.porAccion.set(accion, incognita);
    }
    return incognita.observar(mecanica);
  }

  conteosDe(accion: string): Record<FirmaDeMecanica, number> {
    return { ...(this.porAccion.get(accion) ?? new IncognitaDeMecanica()).conteos };
  }

  dominanteDe(accion: string): FirmaDeMecanica | null {
    return this.porAccion.get(accion)?.dominante() ?? null;
  }
}
