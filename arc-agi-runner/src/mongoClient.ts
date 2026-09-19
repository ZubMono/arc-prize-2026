/* [arc-agi-runner/mongoClient] BL.20775 -- factory de MongoClient AUTO-CONTENIDA: NO importa
   packages/mongo (aislamiento critico -- este proyecto debe poder extraerse del monorepo si se
   gana el ARC Prize, sin arrastrar el core privado). Reimplementa el mismo patron de singleton +
   maxPoolSize obligatorio (regla del repo, packages/mongo::getMongoClient) de forma independiente. */

import { MongoClient } from 'mongodb';

const DEFAULT_MAX_POOL_SIZE = 3;

const singletons = new Map<string, Promise<MongoClient>>();

/** Devuelve el MongoClient singleton para `uri` (uno por proceso), creandolo si no existe.
 *  SIEMPRE pasa maxPoolSize a MongoClient.connect (default 3 -- proceso batch de baja
 *  concurrencia, un runner que juega juegos secuencialmente). */
export async function getArcRunnerMongoClient(
  uri: string,
  opts?: { maxPoolSize?: number },
): Promise<MongoClient> {
  const existing = singletons.get(uri);
  if (existing) return existing;

  const maxPoolSize = opts?.maxPoolSize ?? DEFAULT_MAX_POOL_SIZE;
  const promise = MongoClient.connect(uri, {
    maxPoolSize,
    minPoolSize: 0,
    serverSelectionTimeoutMS: 10_000,
    connectTimeoutMS: 10_000,
  });
  promise.catch(() => {
    // Conexion fallida: no dejar un singleton envenenado -- el proximo intento reconecta.
    singletons.delete(uri);
  });
  singletons.set(uri, promise);
  return promise;
}

/** Cierra y elimina el singleton para `uri`. Llamar SOLO en shutdown (crashGuard/cierre normal). */
export async function closeArcRunnerMongoClient(uri: string): Promise<void> {
  const existing = singletons.get(uri);
  if (!existing) return;
  singletons.delete(uri);
  const client = await existing.catch(() => null);
  await client?.close().catch(() => {});
}

/** Solo para tests: limpia el registry singleton entre casos. */
export function _resetArcRunnerMongoSingletons(): void {
  singletons.clear();
}
