/* [arc-agi-runner/__tests__/replayFrame.contract] BL.21557 -- guardia del mirror manual de los DOS
   contratos de escritura que este BL toca: `arcReplayFrames` (corpus nuevo) y los campos de senal
   densa agregados a `prometheusEvaluationRuns`.

   Lee los archivos privados COMO TEXTO, nunca los importa: importarlos crearia exactamente el
   acoplamiento de runtime que el aislamiento de licencia prohibe (ver CLAUDE.md). Fuera del
   monorepo los archivos no existen y los tests se saltean solos -- que es lo correcto: extraido
   standalone no hay con que divergir.

   POR QUE IMPORTA: un mirror que se desincroniza no rompe nada en tiempo de compilacion; escribe
   documentos con un campo que nadie lee, en silencio, hasta que alguien se pregunta por que el
   corpus esta incompleto. Es el mismo modo de falla que motivo este BL. */

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/** Sube hasta la raiz del monorepo buscando `relative`. `null` = proyecto extraido standalone. */
function findPrivateFile(relative: string): string | null {
  let dir = __dirname;
  for (let i = 0; i < 10; i++) {
    const candidate = path.join(dir, relative);
    if (existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

const REPLAY_TYPES = findPrivateFile(path.join('packages', 'api', 'arcReplayFrames', 'types.ts'));
const RUNS_TYPES = findPrivateFile(
  path.join('packages', 'api', 'prometheusEvaluationRuns', 'types.ts'),
);

/** Nombres de campo declarados dentro de `interface <name> { ... }`. Ignora comentarios. */
function interfaceFields(source: string, name: string): string[] {
  const start = source.indexOf(`interface ${name} {`);
  if (start === -1) return [];
  const body = source.slice(start, source.indexOf('\n}', start));
  const sinComentarios = body.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  return [...sinComentarios.matchAll(/^\s{2}([a-zA-Z_][a-zA-Z0-9_]*)\??:/gm)].map((m) => m[1]);
}

const CAMPOS_CORPUS = [
  'runId',
  'gameId',
  'modelId',
  'stepNum',
  'action',
  'x',
  'y',
  'availableActions',
  'gridWidth',
  'gridHeight',
  'diffRle',
  'changedCells',
  'levelsCompleted',
  'winLevels',
  'stateSignatureBefore',
  'stateSignatureAfter',
  'ts',
  'createdAt',
  'expiresAt',
];

describe('contrato del mirror con packages/api/arcReplayFrames (BL.21557)', () => {
  it.skipIf(REPLAY_TYPES === null)(
    'el schema privado declara exactamente los campos que escribe el runner',
    () => {
      const campos = interfaceFields(
        readFileSync(REPLAY_TYPES as string, 'utf8'),
        'ArcReplayFrame',
      );
      expect(
        campos.length,
        'no se pudo parsear ArcReplayFrame en el schema privado -- revisar el mirror a mano',
      ).toBeGreaterThan(0);
      for (const campo of CAMPOS_CORPUS) {
        expect(campos, `el schema privado ya no declara "${campo}"`).toContain(campo);
      }
    },
  );

  it.skipIf(REPLAY_TYPES === null)('el schema privado NO reimplementa el codec RLE', () => {
    const source = readFileSync(REPLAY_TYPES as string, 'utf8');
    // El codec tiene UNA fuente (replayRleDiff.ts). Dos implementaciones del mismo formato es
    // exactamente como se corrompe un corpus en silencio.
    expect(source).not.toMatch(/function\s+(encode|decode)GridDiff/);
    expect(source).toContain('replayRleDiff.ts');
  });
});

describe('contrato de senal densa con prometheusEvaluationRuns (BL.21557)', () => {
  it.skipIf(RUNS_TYPES === null)('el step privado acepta levelsCompleted y winLevels', () => {
    const campos = interfaceFields(
      readFileSync(RUNS_TYPES as string, 'utf8'),
      'PrometheusEvaluationStep',
    );
    expect(campos).toContain('levelsCompleted');
    expect(campos).toContain('winLevels');
  });

  it.skipIf(RUNS_TYPES === null)(
    'el result privado acepta maxLevelReached y winLevels (metrica de seleccion offline)',
    () => {
      const campos = interfaceFields(
        readFileSync(RUNS_TYPES as string, 'utf8'),
        'PrometheusEvaluationResult',
      );
      expect(campos).toContain('maxLevelReached');
      expect(campos).toContain('winLevels');
    },
  );
});
