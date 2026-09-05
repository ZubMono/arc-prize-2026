/* [arc-agi-runner/vitest.config] Configuracion Vitest propia (NO importa ../../vitest.shared) --
   BL.20775: aislamiento critico, el proyecto debe poder extraerse del monorepo sin arrastrar
   tooling compartido (se abre bajo licencia de dominio publico si se compite por el ARC Prize --
   MIT-0/CC0, ver BL.21045). Valores REIMPLEMENTADOS a
   mano del shared config -- misma razon por la que `src/mongoClient.ts` reimplementa el singleton
   con maxPoolSize en vez de importarlo: hay una frontera de licencia de por medio. */
import os from 'os';
import { defineConfig } from 'vitest/config';

/** Forks maximos CONSCIENTES DE LA CARGA REAL (equivalente local de `loadAwareMaxForks` del shared
 *  config -- GD-flaky-vitest).
 *
 *  BL.21029 (incidente 2026-08-10): antes esto era `maxForks: 2` hardcodeado, con un comentario que
 *  afirmaba conservar el anti-oversubscription del shared config. No lo conservaba: un numero fijo
 *  es justamente lo que el shared config dejo de usar. En un EC2 compartido por varias sesiones a
 *  load alto, 2 forks sobre-suscriben, los workers mueren por timeout y el gate se pone rojo aunque
 *  el algoritmo este intacto.
 *
 *  Es la MITAD del remedio, y por si sola no alcanzaba: menos forks reduce la contencion que este
 *  proceso AGREGA, pero no la que le imponen los otros ~7 agentes del host. Por eso convive con el
 *  `testTimeout` de abajo y con tests que se afirman en unidades de presupuesto, no en milisegundos.
 *
 *  `os.loadavg()` devuelve [0,0,0] en Windows -> se degrada al cap por cores (comportamiento previo). */
function loadAwareMaxForks(cores = os.cpus().length, load1 = os.loadavg()[0] || 0): number {
  const byCores = Math.max(1, Math.floor((cores - 2) / 2));
  const freeCores = Math.max(1, Math.floor(cores - load1));
  return Math.max(1, Math.min(byCores, Math.ceil(freeCores / 2)));
}

export default defineConfig({
  esbuild: {
    target: 'es2022',
  },
  test: {
    pool: 'forks',
    maxForks: loadAwareMaxForks(),
    minForks: 1,
    globals: true,
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/__tests__/**/*.test.ts'],
    reporters: ['verbose'],
    /* BL.21029 -- el default de 5s es un umbral de RELOJ, y esta suite corre dentro del gate de
       push del monorepo, en paralelo con hasta 7 agentes. Medido con load average 35: tests que
       tardan 200-700ms en una maquina ociosa tardaban 8-25s y timeouteaban, con lo que un test
       verde le costaba el ciclo de push completo (~40 min) a cualquier tercero que estuviera
       aterrizando otro BL. Los tests de presupuesto ya se abarataron para no depender de esto; el
       margen existe para que la CONTENCION nunca vuelva a leerse como regresion (misma leccion que
       BL.20994 en GATE-NODE-TESTS). Sigue siendo un techo: un test colgado de verdad falla igual. */
    testTimeout: 30_000,
  },
});
