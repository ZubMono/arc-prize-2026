/* [arc-agi-runner/prng] BL.20775 -- PRNG semillado (mulberry32) puro y deterministico. El baseline
   agent lo usa para elegir acciones; guardar el seed en replayMetadata.seed permite reproducir
   EXACTAMENTE la misma secuencia de decisiones del agente en un replay, aunque el estado interno
   del entorno ARC-AGI-3 no sea reproducible desde nuestro lado. */

/** Hash de un string a un entero de 32 bits (xmur3, variante simplificada) -- usado como semilla
 *  numerica interna del PRNG. */
function hashSeed(seed: string): number {
  let h = 1779033703 ^ seed.length;
  for (let i = 0; i < seed.length; i++) {
    h = Math.imul(h ^ seed.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return h >>> 0;
}

/** Genera un generador de numeros pseudoaleatorios deterministico en [0, 1) a partir de `seed`.
 *  Mismo seed -> misma secuencia siempre (mulberry32, rapido y suficientemente uniforme para
 *  elegir acciones de un agente baseline). */
export function createSeededRandom(seed: string): () => number {
  let state = hashSeed(seed);
  return function mulberry32(): number {
    state |= 0;
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Genera un seed nuevo, no deterministico -- para usar al arrancar una corrida real (el seed
 *  resultante SI se persiste, garantizando reproducibilidad hacia atras del replay). */
export function generateSeed(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
