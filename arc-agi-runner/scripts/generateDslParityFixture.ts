/* [arc-agi-runner/scripts/generateDslParityFixture] BL.20860 -- genera el FIXTURE DORADO de
   paridad del DSL: src/worldModel/__fixtures__/dslParity.json.

   POR QUE existe: `projects/arc-agi3-kaggle-agent` porta este mismo DSL a Python (stdlib pura,
   sin red, notebook de Kaggle). Dos implementaciones del mismo lenguaje en dos runtimes distintos
   son dos fuentes de verdad, y la unica forma de que no drifteen sin acoplarlas es un contrato
   EJECUTABLE: entradas + salidas exactas producidas por el lado canonico. Este script es el
   productor de ese contrato; `src/worldModel/__tests__/dslParity.test.ts` (lado TS) y la suite
   pytest equivalente (lado Python) son los dos consumidores.

   POR QUE el esperado se calcula y no se escribe: si los `expected` fueran literales a mano
   habria TRES fuentes de verdad (TS, Python y el fixture) y el fixture podria estar mal sin que
   nadie se entere. Calculandolo con `applyProgram` el fixture no puede contradecir al TypeScript;
   a lo sumo puede quedar VIEJO, y de eso se encarga el test del lado TS, que falla si el motor
   cambio y nadie regenero.

   Correr: cd projects/arc-agi-runner && npx tsx scripts/generateDslParityFixture.ts */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import { todosLosCasos, type CasoParidad } from './dslParityCases';
import { gridsEqual, type Grid } from '../src/worldModel/grid';
import {
  applyProgram,
  DSL_PRIMITIVE_NAMES,
  type PrimitiveContext,
  type Program,
} from '../src/worldModel/primitiveOps';

const RUTA_FIXTURE = resolve(__dirname, '../src/worldModel/__fixtures__/dslParity.json');

/** Los grids se mantienen chicos a proposito: el fixture se lee a ojo cuando un port falla, y una
 *  grilla de 30x30 en un diff de git es ilegible. 8x8 alcanza para todos los casos borde que
 *  importan (el mas grande que necesitamos es un bloque 3x3 dentro de un marco, o sea 5x5). */
const LADO_MAXIMO_DE_ENTRADA = 8;

/** Tres casos por primitivo es el piso para que un port no pueda "acertar por casualidad": uno
 *  feliz, uno de borde y uno degenerado. La lista de primitivos NO se declara aca -- viene de
 *  `DSL_PRIMITIVE_NAMES` (primitiveOps.ts), asi que agregar un primitivo al DSL hace fallar este
 *  chequeo hasta que tenga sus casos escritos. */
const COBERTURA_MINIMA_POR_PRIMITIVO = 3;

interface CasoSerializado {
  name: string;
  why: string;
  program: Program;
  pre: Grid;
  anchor?: Grid;
  expected: Grid;
}

interface FixtureParidad {
  version: number;
  generatedFrom: 'typescript';
  note: string;
  /** SHA-256 de las fuentes canonicas del DSL en el momento de generar. Lo consume
   *  `scripts/safeguards/check-dsl-parity.cjs`: si alguien toca el motor TypeScript y no regenera,
   *  los hashes dejan de coincidir y el gate bloquea el commit. Sin esto el fixture envejece en
   *  silencio y la "paridad verificada" pasa a ser paridad con una version vieja del motor. */
  sourceHash: string;
  /** Los archivos que entran en ese hash, para que el gate no tenga que adivinarlos. */
  sourceFiles: string[];
  cases: CasoSerializado[];
}

/** Fuentes canonicas cuyo cambio invalida el fixture. Rutas relativas a projects/arc-agi-runner/.
 *  Es la LISTA UNICA: el gate la lee del propio fixture en vez de tener su copia. */
const FUENTES_CANONICAS = [
  'src/worldModel/grid.ts',
  'src/worldModel/primitiveOps.ts',
];

function hashDeFuentes(): string {
  const { createHash } = require('node:crypto') as typeof import('node:crypto');
  const { readFileSync } = require('node:fs') as typeof import('node:fs');
  const h = createHash('sha256');
  for (const rel of FUENTES_CANONICAS) {
    h.update(rel);
    h.update('\0');
    h.update(readFileSync(resolve(__dirname, '..', rel), 'utf8'));
    h.update('\0');
  }
  return h.digest('hex');
}

function contextoDe(caso: CasoParidad): PrimitiveContext {
  return caso.anchor ? { anchorGrid: caso.anchor } : {};
}

function dimensionesDe(grid: Grid): { alto: number; ancho: number } {
  return { alto: grid.length, ancho: grid.reduce((max, fila) => Math.max(max, fila.length), 0) };
}

function esAscii(texto: string): boolean {
  return /^[\x20-\x7e]*$/.test(texto);
}

function fallar(mensaje: string): never {
  throw new Error(`[generateDslParityFixture] ${mensaje}`);
}

/** Validaciones sobre la DECLARACION de los casos (antes de ejecutar nada). Fallan duro: un
 *  fixture a medias es peor que no tenerlo, porque el lado Python lo daria por bueno. */
function validarDeclaracion(casos: CasoParidad[]): void {
  const vistos = new Set<string>();
  for (const caso of casos) {
    if (vistos.has(caso.name)) fallar(`nombre de caso duplicado: "${caso.name}"`);
    vistos.add(caso.name);

    // Los nombres arrancan con el nombre camelCase del primitivo (floodFill_, cropToBBox_, ...)
    // para que ordenar el fixture alfabeticamente agrupe por primitivo. El resto es snake_case.
    // Lo que se exige es que sean identificadores validos en TS y en Python a la vez: sin tildes,
    // sin espacios y sin guiones, porque del otro lado terminan como nombres de test parametrizado.
    if (!/^[a-z][A-Za-z0-9_]*$/.test(caso.name)) {
      fallar(
        `el nombre "${caso.name}" debe ser un identificador ASCII (arrancar en minuscula y usar ` +
          `solo letras, digitos y guion bajo): del otro lado nombra un test parametrizado`,
      );
    }
    // El JSON es un artefacto COMPARTIDO con un codigo Python que por estilo del repo no lleva
    // tildes; si el `why` las trajera, cualquier copia al lado Python las arrastraria.
    if (!esAscii(caso.why)) fallar(`el campo "why" de "${caso.name}" tiene caracteres no ASCII`);
    if (caso.why.trim().length === 0) fallar(`el caso "${caso.name}" no explica por que existe`);

    for (const [etiqueta, grid] of [
      ['pre', caso.pre],
      ...(caso.anchor ? ([['anchor', caso.anchor]] as Array<[string, Grid]>) : []),
    ] as Array<[string, Grid]>) {
      const { alto, ancho } = dimensionesDe(grid);
      if (alto > LADO_MAXIMO_DE_ENTRADA || ancho > LADO_MAXIMO_DE_ENTRADA) {
        fallar(
          `la grilla "${etiqueta}" de "${caso.name}" es ${alto}x${ancho}, supera el limite de ` +
            `${LADO_MAXIMO_DE_ENTRADA}x${LADO_MAXIMO_DE_ENTRADA} (el fixture tiene que ser legible a ojo)`,
        );
      }
      for (const fila of grid) {
        for (const celda of fila) {
          if (!Number.isInteger(celda) || celda < 0 || celda > 15) {
            fallar(`la grilla "${etiqueta}" de "${caso.name}" tiene un color invalido: ${celda}`);
          }
        }
      }
    }

    // `anchor` solo tiene sentido si el programa usa overlay: si no, es ruido que confunde al port.
    const usaOverlay = caso.program.some((paso) => paso.name === 'overlay');
    if (caso.anchor && !usaOverlay) {
      fallar(`el caso "${caso.name}" trae "anchor" pero su programa no usa overlay`);
    }
  }
}

/** Cobertura: minimo 3 casos por primitivo, contando cualquier programa donde el primitivo
 *  aparezca (los de composicion suman). Es el requisito que hace del fixture un contrato y no una
 *  muestra: sin este chequeo, agregar un primitivo al DSL y olvidarse de sus casos pasaria
 *  desapercibido hasta que el port lo implemente mal en produccion. */
function validarCobertura(casos: CasoParidad[]): Map<string, number> {
  const conteo = new Map<string, number>();
  for (const nombre of DSL_PRIMITIVE_NAMES) conteo.set(nombre, 0);
  for (const caso of casos) {
    const usados = new Set(caso.program.map((paso) => paso.name));
    for (const nombre of usados) conteo.set(nombre, (conteo.get(nombre) ?? 0) + 1);
  }
  const faltantes = [...conteo.entries()].filter(
    ([, cantidad]) => cantidad < COBERTURA_MINIMA_POR_PRIMITIVO,
  );
  if (faltantes.length > 0) {
    fallar(
      `cobertura insuficiente (minimo ${COBERTURA_MINIMA_POR_PRIMITIVO} casos por primitivo): ` +
        faltantes.map(([nombre, cantidad]) => `${nombre}=${cantidad}`).join(', '),
    );
  }
  return conteo;
}

/** Ejecuta el caso y verifica tres propiedades que el port tambien debe cumplir y que conviene
 *  descubrir aca y no en Python: (a) el motor no lanza, (b) es deterministico, (c) NO muta la
 *  entrada (si mutara, `pre` en el JSON no seria la entrada real del caso y el fixture mentiria). */
function ejecutarCaso(caso: CasoParidad): Grid {
  const ctx = contextoDe(caso);
  const preOriginal = JSON.stringify(caso.pre);
  const anchorOriginal = JSON.stringify(caso.anchor ?? null);

  const salida = applyProgram(caso.program, caso.pre, ctx);
  const salidaRepetida = applyProgram(caso.program, caso.pre, ctx);

  if (!gridsEqual(salida, salidaRepetida)) {
    fallar(`el caso "${caso.name}" no es deterministico: dos corridas dieron resultados distintos`);
  }
  if (JSON.stringify(caso.pre) !== preOriginal) {
    fallar(`el caso "${caso.name}" muto su grilla de entrada (applyProgram debe ser puro)`);
  }
  if (JSON.stringify(caso.anchor ?? null) !== anchorOriginal) {
    fallar(`el caso "${caso.name}" muto su grilla ancla (applyProgram debe ser puro)`);
  }
  return salida;
}

/** Vuelve a ejecutar el caso a partir del JSON YA serializado y deserializado. No es paranoia
 *  gratuita: `recolor.mapping` tiene claves numericas que JSON convierte en cadenas, y JavaScript
 *  las re-coacciona sola al indexar. Esta pasada confirma que lo que se guarda en disco -- que es
 *  lo unico que ve el port -- sigue produciendo el mismo resultado que los objetos en memoria. */
function validarRoundTripJson(fixture: FixtureParidad): void {
  const releido = JSON.parse(JSON.stringify(fixture)) as FixtureParidad;
  for (const caso of releido.cases) {
    const ctx: PrimitiveContext = caso.anchor ? { anchorGrid: caso.anchor } : {};
    const salida = applyProgram(caso.program, caso.pre, ctx);
    if (!gridsEqual(salida, caso.expected)) {
      fallar(
        `el caso "${caso.name}" no sobrevive el round-trip por JSON: el programa deserializado ` +
          `produce otra salida (sospechar de claves numericas convertidas a cadena)`,
      );
    }
  }
  if (!esAscii(releido.note)) fallar('el campo "note" del fixture tiene caracteres no ASCII');
}

function construirNota(cantidadDeCasos: number): string {
  return [
    'Fixture DORADO de paridad del DSL de transformaciones grilla-a-grilla: el contrato ejecutable',
    'entre el motor canonico TypeScript (projects/arc-agi-runner/src/worldModel/primitiveOps.ts) y',
    'cualquier port a otro lenguaje (hoy, el agente Python offline de',
    'projects/arc-agi3-kaggle-agent, stdlib pura y sin red). Cada caso declara un programa y una',
    `grilla de entrada; "expected" es la salida EXACTA del motor TypeScript, CALCULADA por el`,
    'generador, nunca escrita a mano (escribirla a mano crearia una tercera fuente de verdad que',
    'podria contradecir a las otras dos sin que nadie se entere). Un port es correcto si y solo si',
    `reproduce "expected" celda por celda, incluida la FORMA de la grilla, en los ${cantidadDeCasos}`,
    'casos. REGENERAR: cd projects/arc-agi-runner && npx tsx scripts/generateDslParityFixture.ts.',
    'Los casos se declaran en scripts/dslParityCases/*.ts; este JSON es generado y cualquier edicion',
    'manual la pisa la proxima regeneracion. El test src/worldModel/__tests__/dslParity.test.ts',
    'corre el fixture contra el TypeScript en cada CI: si alguien cambia el DSL y no regenera, el',
    'build del lado TS rompe antes de que el port se entere. CAMPOS: "name" identificador estable;',
    '"why" que semantica bloquea el caso (documentacion, no dato); "program" la secuencia de pasos;',
    '"pre" la grilla de entrada; "anchor" OPCIONAL, presente SOLO en casos de overlay, es la grilla',
    'ancla del PrimitiveContext (pasarla como anchorGrid; su ausencia significa contexto vacio, que',
    'es la rama defensiva de overlay: degrada a identidad); "expected" la salida. Todas las cadenas',
    'son ASCII a proposito, para que el lado Python (que por estilo del repo no usa tildes) pueda',
    'copiarlas sin transliterar. TRAMPAS DE PORT que este fixture cubre explicitamente: (1) indices',
    'negativos: TypeScript los corta con guards explicitos, Python indexa negativo SIN error y',
    'devuelve la fila/columna opuesta -- translate con dx/dy positivos pide sx/sy=-1 y floodFill',
    'acepta coordenadas negativas; (2) las claves numericas de recolor.mapping viajan en JSON como',
    'CADENAS: JavaScript las re-coacciona sola al indexar, Python no, hay que convertirlas a int al',
    'cargar; (3) mapear un color a 0 es legitimo: el TypeScript usa ?? (nullish), no "or", porque 0',
    'es un color valido de ARC; (4) el fondo se DETECTA por frecuencia con desempate por color',
    'MENOR, y se re-detecta en CADA paso sobre la grilla intermedia, nunca una sola vez sobre la',
    'entrada; (5) los desempates de objectExtract son contrato: mas celdas, luego menor minY, luego',
    'menor minX; (6) conectividad 4 (nunca 8) y componentes MONO-COLOR; (7) formas degeneradas:',
    'grilla vacia, filas vacias (replicate con timesX=0 devuelve h filas VACIAS, no una grilla',
    'vacia), 1x1 y no cuadradas; (8) los primitivos NUNCA lanzan: parametros invalidos degradan a',
    'no-op (clon sin cambios). ARITMETICA: primitiveOps.ts no usa division entera en ningun lado,',
    'asi que no hay riesgo de redondeo divergente; la unica operacion no trivial es el modulo de',
    'replicate, que siempre opera sobre indices NO negativos (por eso la diferencia de signo entre',
    'el % de JavaScript y el de Python no se manifiesta) y que nunca se evalua con h o w en cero',
    'porque los loops no iteran -- un port que precalcule el modulo fuera del loop se come un',
    'ZeroDivisionError donde el TypeScript simplemente no hace nada.',
  ].join(' ');
}

function main(): void {
  const casos = todosLosCasos;
  if (casos.length === 0) fallar('no hay casos declarados');

  validarDeclaracion(casos);
  const cobertura = validarCobertura(casos);

  const serializados: CasoSerializado[] = casos.map((caso) => ({
    name: caso.name,
    why: caso.why,
    program: caso.program,
    pre: caso.pre,
    ...(caso.anchor ? { anchor: caso.anchor } : {}),
    expected: ejecutarCaso(caso),
  }));

  const fixture: FixtureParidad = {
    version: 1,
    generatedFrom: 'typescript',
    note: construirNota(serializados.length),
    sourceHash: hashDeFuentes(),
    sourceFiles: FUENTES_CANONICAS,
    cases: serializados,
  };

  validarRoundTripJson(fixture);

  mkdirSync(dirname(RUTA_FIXTURE), { recursive: true });
  writeFileSync(RUTA_FIXTURE, `${JSON.stringify(fixture, null, 2)}\n`, 'utf8');

  const desglose = [...cobertura.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([nombre, cantidad]) => `  ${nombre.padEnd(20)} ${cantidad}`)
    .join('\n');
  process.stdout.write(
    `[generateDslParityFixture] ${serializados.length} casos -> ${RUTA_FIXTURE}\n` +
      `Casos por primitivo (los de composicion cuentan en cada primitivo que usan):\n${desglose}\n`,
  );
}

main();
