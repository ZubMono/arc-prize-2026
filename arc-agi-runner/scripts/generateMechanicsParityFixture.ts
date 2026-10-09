/* [arc-agi-runner/scripts/generateMechanicsParityFixture] BL.21741 (correccion) -- genera el
   FIXTURE DORADO de paridad de la PERCEPCION objeto-centrica:
   src/worldModel/__fixtures__/mechanicsParity.json.

   POR QUE EXISTE, con el defecto medido delante. `objectMechanics.ts` (este motor, el que juega
   contra la API oficial cada hora via `scripts/cron/arc-live-game-run.cjs`) y
   `arc-agi3-kaggle-agent/arc_agent/world_model/object_mechanics.py` (el que viaja a Kaggle) son dos
   implementaciones a mano del MISMO contrato. BL.21741 arreglo el puerto Python -- tope 4096, tipos
   propios para los dos silencios, firma compuesta -- y el motor TypeScript quedo en 2048 y
   "desconocida". Medido sobre el corpus persistido: el mismo par de grillas daba 7 firmas distintas
   del lado Python y UNA SOLA ("desconocida" 14 de 14) del lado TypeScript. Ninguna de las dos
   suites se puso roja: 566 tests TS y 1033 Python en verde con los dos motores diciendo cosas
   distintas. El fixture del DSL (`dslParity.json`) no lo cubria porque su alcance es
   `primitiveOps.ts`, no la percepcion.

   QUE ARBITRA. (1) las CONSTANTES del contrato -- el tope, los cubos, los tipos de "no mire" --,
   que es donde vivio la divergencia; (2) el resultado de `detectarMecanica` + `firmaDeMecanica` +
   `conteoDeTiposDeCluster` + `esFirmaDeSilencio` caso por caso.

   El esperado se CALCULA con el motor canonico y nunca se escribe a mano: si fueran literales
   habria TRES fuentes de verdad. A lo sumo el fixture puede quedar VIEJO, y de eso se encarga
   `scripts/safeguards/check-dsl-parity.cjs` (GATE-DSL-PARITY) comparando el `sourceHash`.

   Correr: cd projects/arc-agi-runner && npx tsx scripts/generateMechanicsParityFixture.ts */

import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import { todosLosCasos, type CasoDeMecanica } from './mechanicsParityCases';
import type { Grid, VolatilityMask } from '../src/worldModel/grid';
import {
  conteoDeTiposDeCluster,
  CORTES_DE_CUBO,
  esFirmaDeSilencio,
  firmaDeMecanica,
  PREFIJO_DE_FIRMA_COMPUESTA,
  TIPO_SIN_NOMBRAR,
} from '../src/worldModel/mechanicsSignature';
import { MAX_CELDAS_DE_OBJETO_ENTERO, MAX_PARES_DE_OBJETO } from '../src/worldModel/objectGeometry';
import {
  detectarMecanica,
  MAX_AREA_CAJA_DE_CAMBIOS,
  MAX_CELDAS_CAMBIADAS,
  MAX_TAMANO_OBJETO,
  MIN_EVIDENCIA_DE_OBJETO,
  TIPOS_DE_MECANICA,
  TIPOS_DE_NO_MIRE,
  TIPO_SIN_MEDICION,
} from '../src/worldModel/objectMechanics';
// BL.21853 -- los topes de la via de OBJETO ENTERO. Van al contrato por la misma razon que los
// otros cuatro: si un puerto los cambia y el otro no, las dos suites siguen verdes y los dos
// motores clasifican distinto el mismo frame (exactamente lo que paso con MAX_CELDAS_CAMBIADAS).

const RUTA_FIXTURE = resolve(__dirname, '../src/worldModel/__fixtures__/mechanicsParity.json');

/** Fuentes canonicas cuyo cambio invalida el fixture. Rutas relativas a projects/arc-agi-runner/.
 *  Es la LISTA UNICA: el gate la lee del propio fixture en vez de tener su copia. */
const FUENTES_CANONICAS = [
  'src/worldModel/grid.ts',
  'src/worldModel/objectGeometry.ts',
  'src/worldModel/objectMechanics.ts',
  'src/worldModel/mechanicsSignature.ts',
];

/** Igual que en el fixture del DSL: 8x8 alcanza y un diff de git con grillas grandes es ilegible.
 *  El tope se ejercita con `opciones.maxCeldasCambiadas`, no agrandando la grilla. */
const LADO_MAXIMO_DE_ENTRADA = 8;

function fallar(mensaje: string): never {
  throw new Error(`[generateMechanicsParityFixture] ${mensaje}`);
}

function esAscii(texto: string): boolean {
  return /^[\x20-\x7e]*$/.test(texto);
}

function hashDeFuentes(): string {
  const h = createHash('sha256');
  for (const rel of FUENTES_CANONICAS) {
    h.update(rel);
    h.update('\0');
    h.update(readFileSync(resolve(__dirname, '..', rel), 'utf8'));
    h.update('\0');
  }
  return h.digest('hex');
}

function validarDeclaracion(casos: CasoDeMecanica[]): void {
  const vistos = new Set<string>();
  for (const caso of casos) {
    if (vistos.has(caso.name)) fallar(`nombre de caso duplicado: "${caso.name}"`);
    vistos.add(caso.name);
    if (!/^[a-z][A-Za-z0-9_]*$/.test(caso.name)) {
      fallar(`el nombre "${caso.name}" tiene que ser un identificador ASCII`);
    }
    if (!esAscii(caso.why) || caso.why.trim().length === 0) {
      fallar(`el caso "${caso.name}" no explica en ASCII por que existe`);
    }
    for (const [etiqueta, grid] of [
      ['pre', caso.pre],
      ['post', caso.post],
    ] as Array<[string, Grid]>) {
      const alto = grid.length;
      const ancho = grid.reduce((max, fila) => Math.max(max, fila.length), 0);
      if (alto > LADO_MAXIMO_DE_ENTRADA || ancho > LADO_MAXIMO_DE_ENTRADA) {
        fallar(`la grilla "${etiqueta}" de "${caso.name}" es ${alto}x${ancho} y el tope es 8x8`);
      }
      for (const fila of grid) {
        for (const celda of fila) {
          if (!Number.isInteger(celda) || celda < 0 || celda > 15) {
            fallar(`color invalido en "${caso.name}": ${celda}`);
          }
        }
      }
    }
    if (caso.mask && caso.mask.length !== caso.pre.length) {
      fallar(`la mascara de "${caso.name}" no tiene el alto de la grilla`);
    }
  }
}

/** COBERTURA: un caso por cada tipo que el motor puede devolver, y ademas las dos formas de firma
 *  compuesta (informativa y de silencio). Sin este chequeo, agregar un tipo al motor y olvidarse
 *  del caso pasaria desapercibido hasta que el port lo implemente distinto -- que es exactamente lo
 *  que paso con `sobreElTope` y `formaIncompatible`. */
function validarCobertura(resultados: Array<{ tipo: string; firma: string }>): void {
  const tipos = new Set(resultados.map((r) => r.tipo));
  const faltantes = TIPOS_DE_MECANICA.filter((t) => !tipos.has(t));
  if (faltantes.length > 0) {
    fallar(`sin caso para el/los tipo(s): ${faltantes.join(', ')}`);
  }
  const compuestas = resultados.filter((r) => r.firma.startsWith(PREFIJO_DE_FIRMA_COMPUESTA));
  if (!compuestas.some((r) => esFirmaDeSilencio(r.firma))) {
    fallar('falta un caso de firma COMPUESTA de silencio (todos los componentes "desconocida")');
  }
  if (!compuestas.some((r) => !esFirmaDeSilencio(r.firma))) {
    fallar('falta un caso de firma COMPUESTA informativa (al menos un tipo nombrado)');
  }
}

function esperadoDe(caso: CasoDeMecanica): Record<string, unknown> {
  const mask = (caso.mask ?? null) as VolatilityMask | null;
  const preOriginal = JSON.stringify(caso.pre);
  const mecanica = detectarMecanica(caso.pre, caso.post, mask, caso.opciones ?? {});
  const repetida = detectarMecanica(caso.pre, caso.post, mask, caso.opciones ?? {});
  const firma = firmaDeMecanica(mecanica);
  if (firma !== firmaDeMecanica(repetida)) {
    fallar(`el caso "${caso.name}" no es deterministico`);
  }
  if (JSON.stringify(caso.pre) !== preOriginal) {
    fallar(`el caso "${caso.name}" muto su grilla de entrada (detectarMecanica debe ser puro)`);
  }
  const t = mecanica.traslacionPrincipal;
  return {
    tipo: mecanica.tipo,
    celdasCambiadas: mecanica.celdasCambiadas,
    firma,
    esFirmaDeSilencio: esFirmaDeSilencio(firma),
    conteoDeTiposDeCluster: conteoDeTiposDeCluster(mecanica),
    // Solo el signo y el tamano: `cobertura`/`relleno` son flotantes y su paridad ya la arbitra el
    // hecho de que la traslacion se haya ELEGIDO (los dos puertos ordenan las candidatas igual).
    traslacionPrincipal: t === null ? null : { dy: t.dy, dx: t.dx, alto: t.alto, ancho: t.ancho },
    cambioDeColorPrincipal: mecanica.cambioDeColorPrincipal,
  };
}

function construirNota(cantidad: number): string {
  return [
    'Fixture DORADO de paridad de la PERCEPCION objeto-centrica: el contrato ejecutable entre el',
    'motor canonico TypeScript (projects/arc-agi-runner/src/worldModel/objectMechanics.ts +',
    'mechanicsSignature.ts, el que juega contra la API oficial) y su puerto Python',
    '(projects/arc-agi3-kaggle-agent/arc_agent/world_model/, el que viaja al notebook de Kaggle).',
    'EL DEFECTO QUE LO MOTIVA (BL.21741, medido): el arreglo de percepcion se aplico solo al puerto',
    'Python y el motor TypeScript quedo con MAX_CELDAS_CAMBIADAS=2048 y "desconocida" para los dos',
    'silencios; sobre el mismo corpus persistido de subidas de nivel un puerto daba 7 firmas',
    'distintas y el otro 1, y NINGUNA de las dos suites se puso roja. "constantes" es tan contrato',
    'como "cases": ahi vivio la divergencia. Cada caso declara pre/post (y mask/opciones si hacen',
    `falta); "expected" es la salida EXACTA del motor TypeScript, CALCULADA por el generador. Un`,
    `port es correcto si y solo si reproduce "expected" en los ${cantidad} casos y las constantes.`,
    'REGENERAR: cd projects/arc-agi-runner && npx tsx scripts/generateMechanicsParityFixture.ts.',
    'Los casos se declaran en scripts/mechanicsParityCases.ts; este JSON es generado y cualquier',
    'edicion manual la pisa la proxima regeneracion. TRAMPAS DE PORT que cubre: (1) el TOPE de',
    'celdas y su tipo propio `sobreElTope` -- "no mire porque cambio demasiado" no es "mire y no',
    'supe"; (2) `formaIncompatible` con celdasCambiadas 0, que NO puede leerse como `sinCambio`',
    'aguas abajo (alimentaria la evidencia de que el boton es inerte, la inferencia opuesta); (3) la',
    'firma COMPUESTA, su orden alfabetico de tipos y sus cubos por orden de magnitud; (4) la',
    'compuesta de SILENCIO (todos los componentes "desconocida"), que tiene el prefijo compuesta: y',
    'no nombra nada -- distinguirla es lo que `esFirmaDeSilencio` arbitra; (5) la mascara de',
    'volatilidad aplicada ANTES de contar cambios.',
  ].join(' ');
}

function main(): void {
  const casos = todosLosCasos;
  if (casos.length === 0) fallar('no hay casos declarados');
  validarDeclaracion(casos);

  const serializados = casos.map((caso) => ({
    name: caso.name,
    why: caso.why,
    pre: caso.pre,
    post: caso.post,
    ...(caso.mask ? { mask: caso.mask } : {}),
    ...(caso.opciones ? { opciones: caso.opciones } : {}),
    expected: esperadoDe(caso),
  }));
  validarCobertura(
    serializados.map((c) => ({
      tipo: String(c.expected.tipo),
      firma: String(c.expected.firma),
    })),
  );

  const fixture = {
    version: 1,
    generatedFrom: 'typescript' as const,
    note: construirNota(serializados.length),
    sourceHash: hashDeFuentes(),
    sourceFiles: FUENTES_CANONICAS,
    constantes: {
      MAX_CELDAS_CAMBIADAS,
      MAX_AREA_CAJA_DE_CAMBIOS,
      MAX_TAMANO_OBJETO,
      MIN_EVIDENCIA_DE_OBJETO,
      MAX_CELDAS_DE_OBJETO_ENTERO,
      MAX_PARES_DE_OBJETO,
      CORTES_DE_CUBO: [...CORTES_DE_CUBO],
      TIPOS_DE_MECANICA: [...TIPOS_DE_MECANICA],
      TIPOS_DE_NO_MIRE: [...TIPOS_DE_NO_MIRE],
      TIPO_SIN_MEDICION,
      TIPO_SIN_NOMBRAR,
      PREFIJO_DE_FIRMA_COMPUESTA,
    },
    cases: serializados,
  };

  if (!esAscii(fixture.note)) fallar('la nota del fixture tiene caracteres no ASCII');

  mkdirSync(dirname(RUTA_FIXTURE), { recursive: true });
  writeFileSync(RUTA_FIXTURE, `${JSON.stringify(fixture, null, 2)}\n`, 'utf8');
  process.stdout.write(
    `[generateMechanicsParityFixture] ${serializados.length} casos -> ${RUTA_FIXTURE}\n`,
  );
}

main();
