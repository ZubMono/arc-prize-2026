/* [arc-agi-runner/scripts/generateVolatilityRealFixture] BL.21558 -- graba partidas REALES contra
   la API oficial de ARC-AGI-3 y emite src/worldModel/__fixtures__/volatilityRealGames.json.

   POR QUE existe. La primera version de la mascara de volatilidad de este BL pasaba todos sus tests
   sinteticos y enmascaraba CERO celdas contra frames reales: el ruido de ARC-AGI-3 no es un digito
   que parpadea (lo que simulaba el entorno sintetico) sino una BARRA que avanza una celda por paso.
   El error no era detectable sin dato real, asi que el dato real entra al repositorio como fixture
   y los tests de efecto lo miden. Es la misma leccion que dejo BL.21500 -- un fix "verde" con
   efecto cero -- llevada al unico lugar donde no puede volver a pasar: la evidencia.

   QUE GRABA. Por juego: la grilla post-RESET completa y, por paso, la accion, las acciones
   disponibles y el DIFF de celdas contra el paso anterior. Diffs y no grillas: la partida completa
   en crudo son ~100 x 4096 numeros por juego; en diffs, los cuatro juegos entran en menos de lo que
   ocupa dslParity.json.

   El fixture es una GRABACION: no contiene ningun valor calculado por el motor, asi que no puede
   "confirmarse a si mismo". Las magnitudes esperadas viven en los tests
   (worldModel/__tests__/bl21558.realGames.effect.test.ts y el espejo Python
   tests/test_bl21558_real_games.py), que son los que fallan si el criterio deja de ver la barra.

   Correr (requiere ARC_API_KEY -- accion humana, ver CLAUDE.md del proyecto):
     cd projects/arc-agi-runner && npx tsx scripts/generateVolatilityRealFixture.ts
   Juegos por default: los cuatro medidos en el BL. Override: ARC_FIXTURE_GAME_IDS (CSV). */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

import { createArcApiClient } from '../src/arcApiClient';
import { createDeadLetterTracker } from '../src/deadLetterTracker';
import { runGame } from '../src/gameRunner';
import type { ArcAction, ArcFrameResponse } from '../src/types';
import { extractGrid } from '../src/worldModel/stateSignature';

const RUTA_FIXTURE = resolve(__dirname, '../src/worldModel/__fixtures__/volatilityRealGames.json');

/** Los cuatro juegos publicos con la patologia medida en `prometheusEvaluationRuns` (firmas unicas
 *  ~= pasos). Tienen la barra en bordes DISTINTOS del frame (fila 0, fila 63, columna 63), que es
 *  justo lo que hace falta para que el criterio no se pueda escribir mirando un solo caso. */
const JUEGOS_POR_DEFECTO = ['lf52-271a04aa', 'ar25-0c556536', 'ka59-38d34dbb', 'dc22-fdcac232'];

/** Tope de pasos grabados por juego. Las partidas medidas duran 80-130 pasos; el tope existe para
 *  que un juego que no termina nunca no infle el fixture sin aportar evidencia nueva. */
const PASOS_MAXIMOS = 130;

interface PasoGrabado {
  accion: string;
  accionesDisponibles: number[];
  /** Diff contra el paso anterior, aplanado: [y, x, valor, y, x, valor, ...]. */
  diff: number[];
}

interface JuegoGrabado {
  gameId: string;
  alto: number;
  ancho: number;
  /** Grilla completa del primer frame (post-RESET) -- el resto se reconstruye aplicando los diffs. */
  base: number[][];
  pasos: PasoGrabado[];
}

function diffEntre(pre: number[][], post: number[][]): number[] {
  const plano: number[] = [];
  for (let y = 0; y < post.length; y++) {
    for (let x = 0; x < post[y].length; x++) {
      if (pre[y]?.[x] !== post[y][x]) plano.push(y, x, post[y][x]);
    }
  }
  return plano;
}

async function grabarJuego(gameId: string, apiKey: string): Promise<JuegoGrabado | null> {
  const cliente = createArcApiClient({
    apiKey,
    baseUrl: process.env.ARC_API_BASE_URL ?? 'https://three.arcprize.org',
    stepTimeoutMs: 60_000,
  });
  const cardId = await cliente.openScorecard({ tags: ['bl21558-fixture'] });

  const frames: { accion: string; frame: ArcFrameResponse }[] = [];
  const clienteQueGraba = {
    async sendCommand(accion: ArcAction, body: Parameters<typeof cliente.sendCommand>[1]) {
      const frame = await cliente.sendCommand(accion, body);
      frames.push({ accion, frame });
      return frame;
    },
  };

  await runGame({
    client: clienteQueGraba,
    cardId,
    gameId,
    seed: `bl21558-fixture-${gameId}`,
    gameTimeoutMs: 20 * 60_000,
    deadLetter: createDeadLetterTracker(3),
    maxSteps: PASOS_MAXIMOS,
  });
  await cliente.closeScorecard(cardId);

  const grillas = frames.map((f) => extractGrid(f.frame));
  const base = grillas[0];
  if (base === null || base === undefined) {
    console.error(`[fixture] ${gameId}: el frame post-RESET no traia grilla, se omite`);
    return null;
  }

  const pasos: PasoGrabado[] = [];
  for (let i = 1; i < grillas.length; i++) {
    const pre = grillas[i - 1];
    const post = grillas[i];
    if (pre === null || post === null) continue;
    pasos.push({
      accion: frames[i].accion,
      accionesDisponibles: [...frames[i].frame.available_actions],
      diff: diffEntre(pre, post),
    });
  }

  return { gameId, alto: base.length, ancho: base[0]?.length ?? 0, base, pasos };
}

async function main(): Promise<void> {
  const apiKey = process.env.ARC_API_KEY?.trim();
  if (!apiKey) {
    throw new Error(
      '[fixture] ARC_API_KEY es obligatoria -- generar una en https://three.arcprize.org/api-keys ' +
        'y configurarla en .env/.env.<entorno> (accion humana, no generable en sesion).',
    );
  }
  const juegos = (process.env.ARC_FIXTURE_GAME_IDS?.split(',').map((g) => g.trim()) ?? []).filter(
    (g) => g.length > 0,
  );
  const objetivo = juegos.length > 0 ? juegos : JUEGOS_POR_DEFECTO;

  const grabados: JuegoGrabado[] = [];
  for (const gameId of objetivo) {
    const grabado = await grabarJuego(gameId, apiKey);
    if (grabado === null) continue;
    grabados.push(grabado);
    console.log(`[fixture] ${gameId}: ${grabado.pasos.length} paso(s) grabados`);
  }

  mkdirSync(dirname(RUTA_FIXTURE), { recursive: true });
  writeFileSync(
    RUTA_FIXTURE,
    `${JSON.stringify(
      {
        generadoPor: 'projects/arc-agi-runner/scripts/generateVolatilityRealFixture.ts',
        descripcion:
          'BL.21558 -- partidas REALES de ARC-AGI-3 grabadas en diffs. Evidencia de que la mascara ' +
          'de volatilidad ve la barra de progreso del juego. Grabacion pura: ningun valor calculado ' +
          'por el motor, las magnitudes esperadas viven en los tests.',
        juegos: grabados,
      },
      null,
      0,
    )}\n`,
  );
  console.log(`[fixture] escrito ${RUTA_FIXTURE} (${grabados.length} juego(s))`);
}

void main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
