/* [arc-agi-runner/arcMongoUrl.test] BL.21700 paso 1 -- precedencia de la URL de Mongo del ciclo ARC.

   Lo que se protege aca no es una funcion de tres lineas: es que el runner NO PUEDA volver a
   escribir en el cluster equivocado. El bug medido el 2026-08-18 fue exactamente eso -- leia
   `MONGO_URL`, que en cualquier invocacion manual viene de .env.development, y partio el corpus de
   ARC entre dos bases (2.757 frames en development contra 2.456 en produccion).

   El test de PARIDAD contra la fuente unica del monorepo vive del lado privado
   (`scripts/lib/__tests__/arcMongoUrl.test.cjs`): este proyecto es auto-contenido y no puede
   requerir `scripts/`. Lo que si vive aca es el PIN de la precedencia contra su literal, para que
   mover el orden de este lado ponga algo en rojo aunque el repo publico se lea solo. */
import { describe, expect, it } from 'vitest';

import {
  ARC_MONGO_URL_ENV_PRECEDENCE,
  mensajeSinUrlArc,
  resolverArcMongoUrl,
} from '../arcMongoUrl';

const DEV = 'mongodb://dev-cluster:27017/invierte';
const PROD = 'mongodb://prod-cluster:27017/invierte';
const DESCARTABLE = 'mongodb://descartable:27017/invierte';

describe('resolverArcMongoUrl', () => {
  it('con MONGO_URL=dev y PROMETHEUS_MONGO_URL=prod resuelve PROD (el bug de BL.21700)', () => {
    expect(resolverArcMongoUrl({ MONGO_URL: DEV, PROMETHEUS_MONGO_URL: PROD })).toBe(PROD);
  });

  it('ARC_RUNNER_MONGO_URL gana sobre PROMETHEUS_MONGO_URL (escape explicito)', () => {
    expect(
      resolverArcMongoUrl({
        ARC_RUNNER_MONGO_URL: DESCARTABLE,
        PROMETHEUS_MONGO_URL: PROD,
        MONGO_URL: DEV,
      }),
    ).toBe(DESCARTABLE);
  });

  it('con solo PROMETHEUS_MONGO_URL resuelve (antes esto lanzaba "MONGO_URL es obligatoria")', () => {
    expect(resolverArcMongoUrl({ PROMETHEUS_MONGO_URL: PROD })).toBe(PROD);
  });

  it('NUNCA cae a MONGO_URL: sin ninguna de las dos del ciclo devuelve vacio', () => {
    expect(resolverArcMongoUrl({ MONGO_URL: DEV })).toBe('');
    expect(resolverArcMongoUrl({})).toBe('');
  });

  it('ignora valores vacios o de puro espacio y sigue con la siguiente variable', () => {
    expect(resolverArcMongoUrl({ ARC_RUNNER_MONGO_URL: '   ', PROMETHEUS_MONGO_URL: PROD })).toBe(
      PROD,
    );
    expect(resolverArcMongoUrl({ ARC_RUNNER_MONGO_URL: '', PROMETHEUS_MONGO_URL: '  ' })).toBe('');
  });

  it('recorta espacios alrededor del valor (un .env con espacio final no rompe la conexion)', () => {
    expect(resolverArcMongoUrl({ PROMETHEUS_MONGO_URL: `  ${PROD}  ` })).toBe(PROD);
  });
});

describe('ARC_MONGO_URL_ENV_PRECEDENCE (pin anti-drift)', () => {
  /* Este pin es la mitad publica del guard de paridad. Si alguien reordena la precedencia, agrega
     MONGO_URL al final "por compatibilidad" o la saca, este test se pone rojo y obliga a mirar
     tambien scripts/lib/arcMongoUrl.cjs -- que es el otro lado del porte. */
  it('es exactamente ARC_RUNNER_MONGO_URL -> PROMETHEUS_MONGO_URL', () => {
    expect([...ARC_MONGO_URL_ENV_PRECEDENCE]).toEqual([
      'ARC_RUNNER_MONGO_URL',
      'PROMETHEUS_MONGO_URL',
    ]);
  });

  it('MONGO_URL no esta en la precedencia -- es la variable que apuntaba a DEV', () => {
    expect([...ARC_MONGO_URL_ENV_PRECEDENCE]).not.toContain('MONGO_URL');
  });
});

describe('mensajeSinUrlArc', () => {
  it('nombra las dos variables del ciclo y desaconseja MONGO_URL explicitamente', () => {
    const msg = mensajeSinUrlArc('contexto de prueba');
    expect(msg).toContain('ARC_RUNNER_MONGO_URL');
    expect(msg).toContain('PROMETHEUS_MONGO_URL');
    expect(msg).toContain('contexto de prueba');
    /* Que el mensaje diga por que NO se usa MONGO_URL es parte del arreglo: el reflejo de quien lo
       lee es exportar la que ya tiene a mano, que es justo la de development. */
    expect(msg).toMatch(/MONGO_URL NO se usa/);
  });
});
