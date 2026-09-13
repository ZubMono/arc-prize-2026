/* [arc-agi-runner/arcMongoUrl] BL.21700 paso 1 -- resolucion de la URL de Mongo del ciclo ARC.

   POR QUE EXISTE ESTE ARCHIVO Y NO UN import: el runner es AUTO-CONTENIDO (no importa `packages/*`
   ni `scripts/*` -- ver CLAUDE.md, "Aislamiento critico": el proyecto se publica bajo MIT-0 en
   github.com/ZubMono/arc-prize-2026 y no puede arrastrar el core privado). La fuente unica del
   monorepo vive en `scripts/lib/arcMongoUrl.cjs`; esto es un PORTE deliberado de su precedencia,
   del mismo tipo que el mirror de tipos de `types.ts`.

   UN PORTE SIN GUARDIA ES EL MISMO BUG QUE ESTE ARCHIVO VIENE A ARREGLAR, asi que la divergencia
   esta atada por un test de PARIDAD que corre del lado privado --
   `scripts/lib/__tests__/arcMongoUrl.test.cjs` compara las DOS implementaciones sobre la misma
   matriz de entornos y se pone rojo si alguien mueve la precedencia de un solo lado. Del lado
   publico, `__tests__/arcMongoUrl.test.ts` fija la precedencia contra su literal, asi que tampoco
   se puede mover aca sin que algo se ponga rojo.

   QUE ESTABA ROTO (medido el 2026-08-18, BL.21700): `config.ts` leia UNICAMENTE `MONGO_URL`. Con
   `MONGO_URL` apuntando a DEV (lo normal al invocar el runner a mano, que hereda .env.development)
   el runner escribia el corpus en DEV mientras el cron, el destilador y los lectores miraban PROD.
   Peor: con solo `PROMETHEUS_MONGO_URL` seteada el runner LANZABA "MONGO_URL es obligatoria" -- no
   podia apuntarse a produccion por ninguna via canonica. 2.757 frames de `arcReplayFrames`
   quedaron partidos en el cluster equivocado por esto.

   PRECEDENCIA (identica a la del monorepo):
     1. ARC_RUNNER_MONGO_URL -- escape explicito: apunta TODO el ciclo a otra base (util para
        correr contra una descartable) sin tocar codigo. Si esta, manda.
     2. PROMETHEUS_MONGO_URL -- el default: las corridas viven junto al resto de la telemetria de
        Prometheus, que es donde los consumidores ya miran.

   `MONGO_URL` NO participa a proposito: es exactamente la variable que apunta a DEV en el entorno
   heredado y la que causo el corpus partido. */

/** Variables consultadas, EN ORDEN. Es la definicion de la precedencia: `resolverArcMongoUrl`
 *  itera esta lista y no conoce ningun nombre de variable fuera de ella, de modo que un cambio de
 *  precedencia obliga a cambiar esta constante (y a poner rojos los tests de paridad). */
export const ARC_MONGO_URL_ENV_PRECEDENCE = [
  'ARC_RUNNER_MONGO_URL',
  'PROMETHEUS_MONGO_URL',
] as const;

/** URL que DEBEN usar el runner y sus scripts auxiliares. Devuelve '' (nunca undefined) cuando no
 *  hay ninguna: el llamador hace fail-closed con un mensaje propio, que es mas util que un throw
 *  generico desde aca. */
export function resolverArcMongoUrl(env: NodeJS.ProcessEnv = process.env): string {
  for (const variable of ARC_MONGO_URL_ENV_PRECEDENCE) {
    const valor = (env[variable] ?? '').trim();
    if (valor) return valor;
  }
  return '';
}

/** Mensaje unico del fail-closed. Vive aca (y no duplicado en cada llamador) para que el operador
 *  lea SIEMPRE las mismas dos variables, y para que nadie lo "arregle" sugiriendo MONGO_URL. */
export function mensajeSinUrlArc(contexto: string): string {
  return (
    `[arc-agi-runner] falta la URL de Mongo del ciclo ARC (${contexto}). Definir ` +
    `${ARC_MONGO_URL_ENV_PRECEDENCE.join(' o ')} -- en ese orden de precedencia. ` +
    'MONGO_URL NO se usa a proposito: apunta al cluster de desarrollo y escribir ahi parte el ' +
    'corpus entre dos bases (BL.21700).'
  );
}
