/* [arc-agi-runner/scripts/measureReplayCorpusSize] BL.21557 -- mide el tamano BSON REAL del corpus
   de replay de una partida completa.

   POR QUE EXISTE: el requisito del corpus ("una partida de 500 pasos debe entrar en <1MB") no se
   puede verificar leyendo el codigo -- depende de cuanto cambia la pantalla por paso. Este script
   corre el runner REAL (misma IntelligentPolicy, mismo gameRunner, mismo codec RLE) contra un
   entorno sintetico de 64x64 con movimiento del orden de magnitud de un juego ARC-AGI-3, y pesa
   cada documento con el serializador BSON del driver -- no con una estimacion.

   Correr: `npx tsx scripts/measureReplayCorpusSize.ts`  (sin red, sin Mongo). */

import { BSON } from 'mongodb';

import { createDeadLetterTracker } from '../src/deadLetterTracker';
import { runGame } from '../src/gameRunner';
import { createReplayFrameStore } from '../src/replayFrameStore';
import type { ArcAction, ArcActionState, ArcFrameResponse, ArcReplayFrame } from '../src/types';
import type { Grid } from '../src/worldModel/grid';

const SIZE = 64;
const PASOS = 500;
/** Cada cuantos pasos el entorno cambia de "nivel": repinta la pantalla entera. Es el peor caso
 *  realista para un diff (todo cambia) y hay que incluirlo o la medicion seria optimista. */
const PASOS_POR_NIVEL = 60;

function fondoDeNivel(nivel: number): Grid {
  // Fondo con estructura (bandas horizontales), como una pantalla de ARC -- no ruido uniforme.
  return Array.from({ length: SIZE }, (_, y) =>
    new Array<number>(SIZE).fill((Math.floor(y / 8) + nivel) % 16),
  );
}

/** Entorno 64x64: un sprite de 3x3 que se mueve segun la accion + transicion de nivel periodica. */
class EntornoMedicion {
  private x = 30;
  private y = 30;
  private paso = 0;
  private nivel = 0;

  private grilla(): Grid {
    const grid = fondoDeNivel(this.nivel);
    for (let dy = 0; dy < 3; dy++) {
      for (let dx = 0; dx < 3; dx++) {
        const py = (this.y + dy) % SIZE;
        const px = (this.x + dx) % SIZE;
        grid[py][px] = 9;
      }
    }
    return grid;
  }

  private frame(state: ArcActionState): ArcFrameResponse {
    return {
      game_id: 'medicion-64x64',
      guid: 'guid-medicion',
      frame: [this.grilla()],
      state,
      levels_completed: this.nivel,
      win_levels: Math.ceil(PASOS / PASOS_POR_NIVEL),
      available_actions: [1, 2, 3, 4, 5, 6],
    };
  }

  reset(): ArcFrameResponse {
    this.x = 30;
    this.y = 30;
    this.paso = 0;
    this.nivel = 0;
    // NOT_FINISHED (no NOT_STARTED): es lo que devuelve la API real tras un RESET, y la politica
    // responde a NOT_STARTED con otro RESET -- devolverlo aca dejaria al agente reseteando en bucle
    // y la medicion mediria una partida que no existe.
    return this.frame('NOT_FINISHED');
  }

  step(action: ArcAction, x?: number, y?: number): ArcFrameResponse {
    this.paso++;
    if (action === 'ACTION1') this.y = (this.y + SIZE - 1) % SIZE;
    if (action === 'ACTION2') this.y = (this.y + 1) % SIZE;
    if (action === 'ACTION3') this.x = (this.x + SIZE - 1) % SIZE;
    if (action === 'ACTION4') this.x = (this.x + 1) % SIZE;
    if (action === 'ACTION6' && x !== undefined && y !== undefined) {
      this.x = x % SIZE;
      this.y = y % SIZE;
    }
    if (this.paso % PASOS_POR_NIVEL === 0) this.nivel++;
    return this.frame('NOT_FINISHED');
  }
}

async function main(): Promise<void> {
  const entorno = new EntornoMedicion();
  const tamanos: number[] = [];

  const store = createReplayFrameStore(
    {
      async bulkWrite(ops: unknown) {
        for (const op of ops as { updateOne: { update: { $set: ArcReplayFrame } } }[]) {
          tamanos.push(BSON.calculateObjectSize(op.updateOne.update.$set));
        }
        return { ok: 1 } as never;
      },
    },
    { runId: 'medicion:medicion-64x64:hoy', gameId: 'medicion-64x64', modelId: 'medicion' },
  );

  const resultado = await runGame({
    client: {
      async sendCommand(action, body) {
        return action === 'RESET' ? entorno.reset() : entorno.step(action, body.x, body.y);
      },
    },
    cardId: 'card-medicion',
    gameId: 'medicion-64x64',
    seed: 'medicion-determinista',
    gameTimeoutMs: 10 * 60_000,
    deadLetter: createDeadLetterTracker(3),
    maxSteps: PASOS,
    capture: store,
  });
  await store.flush();

  const total = tamanos.reduce((a, b) => a + b, 0);
  const stats = store.stats();
  const max = tamanos.length > 0 ? Math.max(...tamanos) : 0;

  console.warn(
    [
      `[medicion] pasos jugados: ${resultado.steps.length} (estado final ${resultado.finalState})`,
      `[medicion] nivel maximo alcanzado: ${resultado.levelProgress.maxLevelsCompleted} de ${resultado.levelProgress.winLevels}`,
      `[medicion] frames capturados: ${stats.framesCapturados} (escritos ${stats.framesEscritos}, presupuesto agotado: ${stats.presupuestoAgotado})`,
      `[medicion] BSON total de la partida: ${total} bytes (${(total / 1024).toFixed(1)} KB)`,
      `[medicion] BSON promedio por frame: ${(total / Math.max(1, tamanos.length)).toFixed(1)} bytes`,
      `[medicion] BSON del frame mas pesado (transicion de nivel): ${max} bytes`,
      `[medicion] presupuesto 1MB: ${total < 1_000_000 ? 'OK' : 'EXCEDIDO'} (${((total / 1_000_000) * 100).toFixed(1)}% usado)`,
    ].join('\n'),
  );
}

void main();
