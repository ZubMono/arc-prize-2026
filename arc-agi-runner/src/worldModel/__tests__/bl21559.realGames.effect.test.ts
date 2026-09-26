/* [arc-agi-runner/worldModel/bl21559.realGames.effect.test] BL.21559 -- TEST DE EFECTO sobre las
   PARTIDAS REALES, no de humo.

   LA LECCION QUE ESTE ARCHIVO EXISTE PARA NO REPETIR (ya paso dos veces: BL.21500 y el primer
   intento de BL.21558): un cambio que "pasa los tests" y tiene efecto CERO sobre dato real. Aca
   cada `it` mide una MAGNITUD sobre las cuatro partidas grabadas contra la API oficial
   (`__fixtures__/volatilityRealGames.json`, generado por scripts/generateVolatilityRealFixture.ts).

   QUE ES EXACTAMENTE LO QUE SE MIDE -- Y QUE NO. Es una evaluacion EN SOMBRA (off-policy): sobre la
   trayectoria grabada se reconstruye el modelo de mundo REAL (mascara de volatilidad, no-ops y
   sintesis alimentados con las acciones que REALMENTE se ejecutaron y las grillas que REALMENTE
   devolvio la API) y, en cada paso, se le pregunta a la regla de seleccion que accion elegiria en
   ese estado. Lo que se compara es la REGLA, con el mismo conocimiento del mundo en las dos ramas.
   Lo que NO se puede medir asi es que habria contestado el juego a una accion distinta de la
   grabada: no hay simulador de ARC-AGI-3, y esa parte se mide en el otro archivo
   (bl21559.displacement.effect.test.ts), donde el entorno SI responde.

   El lado "codigo viejo" tiene ademas una referencia que no es reconstruccion de nada: la
   distribucion GRABADA, o sea lo que la politica anterior hizo de verdad contra la API. Ahi esta la
   patologia en crudo -- rachas de a lo sumo 2 pasos iguales en 83, 100 y 128 pasos.

   La orquestacion de estas tres piezas (memoria + macro + novedad) esta escrita aca a mano y no via
   `IntelligentPolicy` a proposito: la politica atribuiria la transicion grabada a la accion que
   ELLA eligio, que es otra, y envenenaria el modelo de mundo con pares (accion, efecto) que nunca
   ocurrieron. Las tres piezas que se ejercitan -- `selectExploratoryAction`, `MacroCommitment` y
   `StateNoveltyTracker` -- son las de produccion, sin copias. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { createSeededRandom } from '../../prng';
import { RECONSIDERATION_PER_STEP_EPSILON, selectExploratoryAction } from '../activeLearning';
import { gridsEqualMasked, type Grid, type VolatilityMask } from '../grid';
import { MACRO_MAX_STEPS, MacroCommitment } from '../macroCommitment';
import { StateNoveltyTracker } from '../stateNovelty';
import { computeStateSignature } from '../stateSignature';
import { TransitionMemory } from '../transitionMemory';

interface PasoGrabado {
  accion: string;
  accionesDisponibles: number[];
  diff: number[];
}

interface JuegoGrabado {
  gameId: string;
  alto: number;
  ancho: number;
  base: number[][];
  pasos: PasoGrabado[];
}

const FIXTURE = resolve(__dirname, '../__fixtures__/volatilityRealGames.json');
const juegos = (JSON.parse(readFileSync(FIXTURE, 'utf8')) as { juegos: JuegoGrabado[] }).juegos;

function reconstruir(juego: JuegoGrabado): Grid[] {
  const grillas: Grid[] = [juego.base.map((fila) => [...fila])];
  for (const paso of juego.pasos) {
    const siguiente = grillas[grillas.length - 1].map((fila) => [...fila]);
    for (let i = 0; i < paso.diff.length; i += 3) {
      siguiente[paso.diff[i]][paso.diff[i + 1]] = paso.diff[i + 2];
    }
    grillas.push(siguiente);
  }
  return grillas;
}

interface EstadisticaDeSecuencia {
  conteo: Map<string, number>;
  /** Pasos que repiten la accion del paso anterior -- la magnitud del COMPROMISO. */
  repeticiones: number;
  /** Racha maxima de la misma accion seguida. */
  rachaMaxima: number;
}

function estadisticas(secuencia: string[]): EstadisticaDeSecuencia {
  const conteo = new Map<string, number>();
  for (const accion of secuencia) conteo.set(accion, (conteo.get(accion) ?? 0) + 1);
  let repeticiones = 0;
  let racha = 1;
  let rachaMaxima = 1;
  for (let i = 1; i < secuencia.length; i++) {
    if (secuencia[i] === secuencia[i - 1]) {
      repeticiones++;
      racha++;
      if (racha > rachaMaxima) rachaMaxima = racha;
    } else {
      racha = 1;
    }
  }
  return { conteo, repeticiones, rachaMaxima };
}

interface Medicion {
  pasos: number;
  grabada: EstadisticaDeSecuencia;
  vieja: EstadisticaDeSecuencia;
  nueva: EstadisticaDeSecuencia;
  /** Firmas unicas con la mascara VIVA reconstruida como era ANTES de este BL: solo celdas que ya
   *  se habian visto cambiar. Ver `mascaraPrevia`. */
  firmasMascaraPrevia: number;
  /** Firmas unicas con la mascara viva de HOY (la barra se cierra apenas se la reconoce). */
  firmasMascaraEstable: number;
  /** Pasos en los que quedaba al menos una accion nunca probada desde esa firma -- mide si el
   *  criterio de novedad tiene sobre que discriminar en dato real. */
  pasosConSenalDeNovedad: number;
}

/** Reconstruye la mascara PREVIA a este BL a partir de la vigente: la extension de BL.21559 solo
 *  agrega celdas de la linea de la barra que TODAVIA no se vieron cambiar, asi que intersecar la
 *  mascara de hoy con "esta celda ya cambio alguna vez" devuelve el conjunto que enmascaraba el
 *  codigo anterior. Es la unica forma de medir el antes y el despues sobre la MISMA trayectoria sin
 *  mantener dos implementaciones de la mascara. */
function mascaraPrevia(
  mask: VolatilityMask | null,
  cambioAlgunaVez: boolean[][],
): VolatilityMask | null {
  if (mask === null) return null;
  return mask.map((fila, y) =>
    fila.map((esVolatil, x) => esVolatil && cambioAlgunaVez[y]?.[x] === true),
  );
}

function medir(juego: JuegoGrabado): Medicion {
  const grillas = reconstruir(juego);
  const memoria = new TransitionMemory({});
  const novedad = new StateNoveltyTracker();
  const macro = new MacroCommitment();
  const rngViejo = createSeededRandom(`bl21559-viejo-${juego.gameId}`);
  const rngNuevo = createSeededRandom(`bl21559-nuevo-${juego.gameId}`);

  const viejas: string[] = [];
  const nuevas: string[] = [];
  const firmasPrevias = new Set<string>();
  const firmasEstables = new Set<string>();
  const cambioAlgunaVez: boolean[][] = Array.from({ length: juego.alto }, () =>
    new Array<boolean>(juego.ancho).fill(false),
  );

  let firmaAnterior: string | null = null;
  let versionAnterior = 0;
  let huboCambioAnterior = false;
  let ultimaNueva: string | null = null;
  let pasosConSenalDeNovedad = 0;

  for (let i = 0; i < juego.pasos.length; i++) {
    const paso = juego.pasos[i];
    const disponibles = paso.accionesDisponibles.map((n) => `ACTION${n}`);
    const mask = memoria.getVolatilityMask();
    const version = memoria.getVolatilityVersion();
    const firma = String(computeStateSignature(grillas[i], paso.accionesDisponibles, mask));

    /* La version entra en la clave porque dos firmas calculadas con mascaras distintas son hashes
       de DOS definiciones de estado: contarlas juntas inventaria repeticiones. */
    firmasEstables.add(`${version}:${firma}`);
    firmasPrevias.add(
      `${version}:${computeStateSignature(
        grillas[i],
        paso.accionesDisponibles,
        mascaraPrevia(mask, cambioAlgunaVez),
      )}`,
    );

    if (firmaAnterior !== null && i > 0 && version === versionAnterior) {
      novedad.registrarTransicion(firmaAnterior, juego.pasos[i - 1].accion, firma);
    }
    novedad.registrarVisita(firma);
    if (novedad.hayAccionSinProbar(firma, disponibles)) pasosConSenalDeNovedad++;

    // Regla ANTERIOR a este BL: sin novedad y sin compromiso -- la misma funcion, sin opciones.
    viejas.push(selectExploratoryAction(disponibles, memoria, rngViejo));

    // Regla NUEVA: turno de reconsideracion por paso -> macro -> seleccion con novedad.
    const turnoDeReconsideracion = rngNuevo() < RECONSIDERATION_PER_STEP_EPSILON;
    if (turnoDeReconsideracion) macro.cancelar();
    let nueva = macro.continuar({
      accionAnterior: ultimaNueva,
      huboCambioEnmascarado: huboCambioAnterior,
      disponibles,
    });
    if (nueva === null) {
      nueva = selectExploratoryAction(disponibles, memoria, rngNuevo, {
        novelty: { tracker: novedad, signature: firma },
        turnoDeReconsideracion,
      });
      macro.iniciar(nueva);
    }
    nuevas.push(nueva);
    ultimaNueva = nueva;

    huboCambioAnterior = !gridsEqualMasked(grillas[i], grillas[i + 1], mask);
    for (let k = 0; k < paso.diff.length; k += 3) {
      cambioAlgunaVez[paso.diff[k]][paso.diff[k + 1]] = true;
    }
    memoria.recordObservation(paso.accion, grillas[i], grillas[i + 1]);
    firmaAnterior = firma;
    versionAnterior = version;
  }

  return {
    pasos: juego.pasos.length,
    grabada: estadisticas(juego.pasos.map((p) => p.accion)),
    vieja: estadisticas(viejas),
    nueva: estadisticas(nuevas),
    firmasMascaraPrevia: firmasPrevias.size,
    firmasMascaraEstable: firmasEstables.size,
    pasosConSenalDeNovedad,
  };
}

/* Una sola pasada por las cuatro partidas: reconstruir el modelo de mundo real cuesta ~16s (la
   sintesis corre sobre grillas de 64x64) y repetirlo por cada `it` haria de este archivo el cuello
   del presupuesto de suite. */
const mediciones = new Map<string, Medicion>(juegos.map((j) => [j.gameId, medir(j)]));

/** Juegos donde la GRABACION muestra el ciclado perfecto que este BL viene a romper. lf52 queda
 *  afuera de esa afirmacion puntual: su grabacion es posterior y ya trae rachas largas. */
const CON_CICLADO_GRABADO = ['ar25-0c556536', 'ka59-38d34dbb', 'dc22-fdcac232'];

describe('BL.21559 -- macro-acciones y novedad medidas sobre partidas REALES de ARC-AGI-3', () => {
  it('la GRABACION de produccion confirma el defecto: ciclado perfecto, rachas de 2', () => {
    for (const gameId of CON_CICLADO_GRABADO) {
      const m = mediciones.get(gameId) as Medicion;
      // eslint-disable-next-line no-console -- magnitud medida sobre dato real de produccion
      console.log(
        `[BL.21559][${gameId}] GRABADO en produccion: ${JSON.stringify([...m.grabada.conteo].sort())} ` +
          `| racha maxima ${m.grabada.rachaMaxima} | repeticiones ${m.grabada.repeticiones}/${m.pasos}`,
      );
      // Nunca dos macro-acciones: a lo sumo dos pasos iguales seguidos en toda la partida.
      expect(
        m.grabada.rachaMaxima,
        `${gameId}: la grabacion no muestra ciclado`,
      ).toBeLessThanOrEqual(2);
      // Y practicamente ninguna repeticion: 2/83, 4/100, 7/128 sobre la grabacion vigente.
      expect(m.grabada.repeticiones / m.pasos).toBeLessThan(0.1);
    }
  });

  it('la regla nueva se COMPROMETE: las repeticiones se multiplican sobre las mismas trayectorias', () => {
    let pasos = 0;
    let vieja = 0;
    let nueva = 0;
    for (const m of mediciones.values()) {
      pasos += m.pasos;
      vieja += m.vieja.repeticiones;
      nueva += m.nueva.repeticiones;
    }
    // eslint-disable-next-line no-console -- magnitud agregada sobre las 4 partidas reales
    console.log(
      `[BL.21559][agregado] ${pasos} pasos reales -- pasos que repiten la accion anterior: ` +
        `regla vieja ${vieja}, regla nueva ${nueva}`,
    );
    expect(nueva).toBeGreaterThan(vieja * 2);
    // Mas de la mitad de los pasos del episodio pasan a ser continuacion de una macro.
    expect(nueva / pasos).toBeGreaterThan(0.5);
  });

  it('la mascara viva se estabiliza y las firmas VUELVEN A REPETIRSE durante la partida', () => {
    for (const [gameId, m] of mediciones) {
      // eslint-disable-next-line no-console -- magnitud medida sobre dato real
      console.log(
        `[BL.21559][${gameId}] firmas unicas con mascara VIVA en ${m.pasos} pasos -- ` +
          `antes de este BL: ${m.firmasMascaraPrevia}, ahora: ${m.firmasMascaraEstable}`,
      );
      /* El efecto que BL.21558 media era RETROSPECTIVO (mascara final aplicada a toda la
         trayectoria). Durante la partida la mascara crecia una celda por paso y la firma cambiaba
         igual: 78/83, 95/100, 123/128 -- practicamente lo mismo que sin mascara. */
      expect(m.firmasMascaraPrevia).toBeGreaterThan(m.pasos * 0.65);
      expect(m.firmasMascaraEstable).toBeLessThan(m.firmasMascaraPrevia * 0.6);
    }
  });

  it('la novedad tiene senal real: casi siempre queda una accion sin probar desde el estado', () => {
    for (const [gameId, m] of mediciones) {
      const fraccion = m.pasosConSenalDeNovedad / m.pasos;
      // eslint-disable-next-line no-console -- magnitud medida sobre dato real
      console.log(
        `[BL.21559][${gameId}] pasos con al menos una accion nunca probada desde esa firma: ` +
          `${m.pasosConSenalDeNovedad}/${m.pasos}`,
      );
      /* Si esto fuera ~0, el desempate por novedad no discriminaria nada y el fix seria de papel.
         lf52 es el caso de SOBRE-COLAPSO documentado (el agente no movio el tablero en toda la
         partida, todas las firmas colapsan) y aun ahi queda senal en el 45% de los pasos. */
      expect(fraccion, `${gameId} sin senal de novedad`).toBeGreaterThan(0.4);
    }
  });

  it('el compromiso llega a macros largas, no a repeticiones sueltas', () => {
    for (const [gameId, m] of mediciones) {
      // eslint-disable-next-line no-console -- magnitud medida sobre dato real
      console.log(
        `[BL.21559][${gameId}] racha maxima -- grabada ${m.grabada.rachaMaxima}, ` +
          `regla vieja ${m.vieja.rachaMaxima}, regla nueva ${m.nueva.rachaMaxima}`,
      );
      // Una macro completa son MACRO_MAX_STEPS pasos; se exige llegar al menos a una.
      expect(m.nueva.rachaMaxima, `${gameId}: la macro nunca llego al tope`).toBeGreaterThanOrEqual(
        MACRO_MAX_STEPS,
      );
    }
  });

  it('ninguna accion disponible queda congelada -- no se pierde lo que gano BL.21558', () => {
    /* El riesgo simetrico del compromiso: con macros hay ~8 veces menos SELECCIONES por episodio,
       asi que el turno de reconsideracion de los grupos relegados (no-ops conocidos y acciones con
       regla confirmada) se dispara 8 veces menos. Medido antes de sortearlo por PASO: ACTION6 caia
       a 0 apariciones en ka59 y ACTION7 a 0 en ar25 -- exactamente la relegacion que BL.21558
       arreglo. Se mide en AGREGADO porque cuantas veces sale una accion depende del juego. */
    let viejas = 0;
    let nuevas = 0;
    for (const m of mediciones.values()) {
      viejas += m.vieja.conteo.get('ACTION6') ?? 0;
      nuevas += m.nueva.conteo.get('ACTION6') ?? 0;
    }
    // eslint-disable-next-line no-console -- magnitud medida sobre dato real
    console.log(
      `[BL.21559][agregado] ACTION6 (el click) en las 4 partidas -- regla vieja: ${viejas}, regla nueva: ${nuevas}`,
    );
    /* Medido: 40 -> 54. El umbral es holgado a proposito -- lo que este test tiene que atrapar es
       el COLAPSO por division del presupuesto (que daba ~0), no una variacion de seed. */
    expect(nuevas).toBeGreaterThan(viejas * 0.5);
  });
});
