/* [arc-agi-runner/__tests__/activityMemorySeed.contract] BL.20861 -- guardia del UNICO lugar donde
   este proyecto espeja LOGICA (no solo un shape) del monorepo privado: los umbrales de filtrado de
   la semilla de memoria.

   Lee packages/api/prometheusActivityMemory/seed.ts COMO TEXTO. No lo importa: importarlo crearia
   exactamente el acoplamiento de runtime que el aislamiento de licencia prohibe (ver CLAUDE.md).
   Leer un
   archivo en un test no acopla nada -- si el proyecto se extrae standalone el archivo no existe y
   el test se saltea solo, que es el comportamiento correcto: fuera del monorepo no hay con que
   divergir. */

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

import { SEED_MIN_CONFIDENCE, SEED_MIN_NONOP_CONFIRMATIONS } from '../activityMemorySeed';

/* Ruta del archivo privado RESUELTA subiendo hasta la raiz del monorepo, no hardcodeada con
   `../../../..`: ese literal se rompe con cualquier movida de carpeta y ademas los gates del repo lo
   prohiben (y su solucion estandar -- un alias a packages/ -- es exactamente lo que el aislamiento
   de licencia de este proyecto no permite). Fuera del monorepo el ascenso no encuentra nada y
   devuelve
   null, que es justo el caso "proyecto extraido standalone". */
const PRIVATE_SEED_RELATIVE = path.join('packages', 'api', 'prometheusActivityMemory', 'seed.ts');

function findPrivateSeedFile(): string | null {
  let dir = __dirname;
  for (let i = 0; i < 10; i++) {
    const candidate = path.join(dir, PRIVATE_SEED_RELATIVE);
    if (existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

const PRIVATE_SEED_FILE = findPrivateSeedFile();

/** Extrae `export const NOMBRE = <numero>;` del fuente privado. `null` si no aparece -- se trata
 *  como falla explicita, no como "coinciden": una constante renombrada del otro lado es
 *  exactamente el drift que este test existe para detectar. */
function readNumericConstant(source: string, name: string): number | null {
  const match = new RegExp(`export const ${name}\\s*=\\s*([0-9.]+)\\s*;`).exec(source);
  if (match === null) return null;
  return Number(match[1]);
}

describe('contrato de umbrales con el seed.ts privado de prometheusActivityMemory', () => {
  const disponible = PRIVATE_SEED_FILE !== null;

  it.skipIf(!disponible)('SEED_MIN_CONFIDENCE no divergio del lado privado', () => {
    const source = readFileSync(PRIVATE_SEED_FILE as string, 'utf8');
    const privado = readNumericConstant(source, 'SEED_MIN_CONFIDENCE');
    expect(
      privado,
      'SEED_MIN_CONFIDENCE ya no existe en el seed.ts privado -- actualizar el espejo de ' +
        'projects/arc-agi-runner/src/activityMemorySeed.ts',
    ).not.toBeNull();
    expect(SEED_MIN_CONFIDENCE).toBe(privado);
  });

  it.skipIf(!disponible)('SEED_MIN_NONOP_CONFIRMATIONS no divergio del lado privado', () => {
    const source = readFileSync(PRIVATE_SEED_FILE as string, 'utf8');
    const privado = readNumericConstant(source, 'SEED_MIN_NONOP_CONFIRMATIONS');
    expect(
      privado,
      'SEED_MIN_NONOP_CONFIRMATIONS ya no existe en el seed.ts privado -- actualizar el espejo de ' +
        'projects/arc-agi-runner/src/activityMemorySeed.ts',
    ).not.toBeNull();
    expect(SEED_MIN_NONOP_CONFIRMATIONS).toBe(privado);
  });

  it('el espejo NO importa packages/* (aislamiento de licencia)', () => {
    const espejo = readFileSync(path.resolve(__dirname, '../activityMemorySeed.ts'), 'utf8');
    expect(espejo).not.toMatch(/from\s+['"].*packages\//);
    expect(espejo).not.toMatch(/require\(['"].*packages\//);
  });
});
