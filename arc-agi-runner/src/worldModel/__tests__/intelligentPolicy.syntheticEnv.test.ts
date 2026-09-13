/* [arc-agi-runner/worldModel/intelligentPolicy.syntheticEnv.test] BL.20860 -- TEST OBLIGATORIO
   de la wave 2 del epico BL.20858: sobre un entorno SINTETICO con reglas CONOCIDAS (no ARC real,
   ver ../../__tests__/support/syntheticGridEnv.ts), IntelligentPolicy debe resolver el MISMO
   problema en MENOS acciones que baselineAgent (politica random uniforme, BL.20775). El scoring
   real de ARC-AGI-3 es min(acciones_humano/acciones_agente,1) AL CUADRADO -- penaliza
   cuadraticamente cada accion de mas, asi que este test mide justo la magnitud que ese scoring
   castiga: numero de acciones hasta resolver. */
import { describe, expect, it } from 'vitest';

import { SyntheticGridEnv } from '../../__tests__/support/syntheticGridEnv';
import { decideNextAction } from '../../baselineAgent';
import { createSeededRandom } from '../../prng';
import type { ArcAction } from '../../types';
import { IntelligentPolicy } from '../intelligentPolicy';

const MAX_STEPS = 400;
const SEEDS = ['seed-1', 'seed-2', 'seed-3', 'seed-4', 'seed-5', 'seed-6', 'seed-7', 'seed-8'];
const START = { x: 0, y: 0 };
const TARGET = { x: 3, y: 3 };

function runBaseline(seed: string): number {
  const env = new SyntheticGridEnv({ start: START, target: TARGET });
  const rng = createSeededRandom(seed);
  let frame = env.reset();
  let steps = 0;
  while (frame.state !== 'WIN' && steps < MAX_STEPS) {
    const decision = decideNextAction(frame, rng);
    frame = decision.action === 'RESET' ? env.reset() : env.step(decision.action as ArcAction);
    steps++;
  }
  return steps;
}

function runIntelligent(seed: string): number {
  const env = new SyntheticGridEnv({ start: START, target: TARGET });
  const policy = new IntelligentPolicy({
    rng: createSeededRandom(seed),
    goalGrid: env.targetGrid,
    actionBudget: MAX_STEPS,
  });
  let frame = env.reset();
  let steps = 0;
  while (frame.state !== 'WIN' && steps < MAX_STEPS) {
    const decision = policy.decide(frame);
    frame = decision.action === 'RESET' ? env.reset() : env.step(decision.action as ArcAction);
    steps++;
  }
  return steps;
}

describe('IntelligentPolicy vs baseline random -- entorno sintetico con reglas conocidas', () => {
  it('resuelve en MENOS acciones que la politica random en TODOS los seeds probados', () => {
    const baselineCounts = SEEDS.map(runBaseline);
    const intelligentCounts = SEEDS.map(runIntelligent);

    const baselineAvg = baselineCounts.reduce((a, b) => a + b, 0) / SEEDS.length;
    const intelligentAvg = intelligentCounts.reduce((a, b) => a + b, 0) / SEEDS.length;
    const improvementPct = ((baselineAvg - intelligentAvg) / baselineAvg) * 100;

    // eslint-disable-next-line no-console -- resultado numerico del benchmark obligatorio BL.20860
    console.log(
      `[BL.20860] baseline random por seed: ${JSON.stringify(baselineCounts)} (promedio ${baselineAvg.toFixed(1)} acciones)\n` +
        `[BL.20860] IntelligentPolicy por seed: ${JSON.stringify(intelligentCounts)} (promedio ${intelligentAvg.toFixed(1)} acciones)\n` +
        `[BL.20860] mejora promedio: ${improvementPct.toFixed(1)}% menos acciones`,
    );

    for (let i = 0; i < SEEDS.length; i++) {
      expect(intelligentCounts[i]).toBeLessThan(baselineCounts[i]);
    }
    // mejora sustancial, no marginal -- el modelo de mundo + planificacion deben dominar
    // claramente al ensayo y error, no solo empatar por casualidad de seed
    expect(intelligentAvg).toBeLessThan(baselineAvg * 0.5);
  });
});
