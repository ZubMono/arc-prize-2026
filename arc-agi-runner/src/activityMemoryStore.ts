/* [arc-agi-runner/activityMemoryStore] BL.20861 -- lectura de la memoria que persiste ENTRE
   corridas, desde la coleccion `prometheusActivityMemory`. Solo LECTURA: la escritura (destilar la
   corrida en memoria) vive del lado privado (packages/api/prometheusActivityMemory/distill.ts),
   que corre despues, fuera de este proceso. Esa asimetria es deliberada -- el runner es el
   consumidor de conocimiento, no su curador, y asi no necesita el lock optimista ni la politica de
   eviccion del lado privado. */

import type { Collection } from 'mongodb';

import {
  buildSeedFromDoc,
  coldSeed,
  type ActivityMemoryDocLike,
  type ActivityMemorySeed,
} from './activityMemorySeed';

export interface ActivityMemoryStore {
  /** Semilla para arrancar la corrida de esta actividad. NUNCA lanza: una actividad nunca jugada
   *  devuelve semilla fria, y un fallo de lectura tambien -- la corrida debe poder jugarse aunque
   *  la memoria no este disponible (degradacion a la politica de arranque frio, que es
   *  exactamente el comportamiento previo a BL.20861). */
  loadSeed(activityId: string): Promise<ActivityMemorySeed>;
}

export function createActivityMemoryStore(
  collection: Collection<ActivityMemoryDocLike>,
  onWarn: (message: string) => void = () => {},
): ActivityMemoryStore {
  return {
    async loadSeed(activityId: string): Promise<ActivityMemorySeed> {
      try {
        const doc = await collection.findOne({ activityId });
        return buildSeedFromDoc(doc, activityId);
      } catch (err) {
        onWarn(
          `No se pudo leer la memoria de la actividad ${activityId} ` +
            `(${err instanceof Error ? err.message : String(err)}) -- se arranca en frio.`,
        );
        return coldSeed(activityId);
      }
    },
  };
}
