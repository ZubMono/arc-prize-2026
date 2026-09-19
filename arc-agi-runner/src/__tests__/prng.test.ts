/* [arc-agi-runner/prng.test] BL.20775 -- PRNG semillado deterministico para reproducibilidad de
   replay (replayMetadata.seed). */
import { describe, expect, it } from 'vitest';

import { createSeededRandom, generateSeed } from '../prng';

describe('createSeededRandom', () => {
  it('la misma semilla produce la misma secuencia', () => {
    const rngA = createSeededRandom('seed-fijo');
    const rngB = createSeededRandom('seed-fijo');
    const seqA = Array.from({ length: 10 }, () => rngA());
    const seqB = Array.from({ length: 10 }, () => rngB());
    expect(seqA).toEqual(seqB);
  });

  it('semillas distintas producen secuencias distintas', () => {
    const rngA = createSeededRandom('seed-1');
    const rngB = createSeededRandom('seed-2');
    expect(rngA()).not.toBe(rngB());
  });

  it('siempre devuelve valores en [0, 1)', () => {
    const rng = createSeededRandom('rango');
    for (let i = 0; i < 200; i++) {
      const v = rng();
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });
});

describe('generateSeed', () => {
  it('genera semillas distintas en llamadas sucesivas', () => {
    const seeds = new Set(Array.from({ length: 20 }, () => generateSeed()));
    expect(seeds.size).toBe(20);
  });

  it('genera un string no vacio', () => {
    expect(generateSeed().length).toBeGreaterThan(0);
  });
});
