/* [arc-agi-runner/worldModel/dslParity.test] BL.20860 -- corre el FIXTURE DORADO de paridad del
   DSL (`__fixtures__/dslParity.json`) contra el motor TypeScript canonico.

   POR QUE existe este test si el fixture LO GENERA el mismo motor: para que no quede STALE. El
   fixture es el contrato que consume el port Python de `projects/arc-agi3-kaggle-agent` (stdlib
   pura, notebook Kaggle sin red). Si alguien cambia la semantica de un primitivo y no corre
   `npx tsx scripts/generateDslParityFixture.ts`, el contrato queda describiendo un motor que ya
   no existe: el port seguiria verde contra un fixture viejo y la divergencia recien aparecerian
   jugando, donde nadie la puede debuggear. Este test convierte ese escenario en un build rojo del
   lado TypeScript, que es el lado que hizo el cambio y el unico que puede arreglarlo.

   Corolario de diseno: este archivo NO debe tener expectativas escritas a mano. Todo lo que
   afirma sale del fixture. Si un caso te parece mal, se arregla en `scripts/dslParityCases/*.ts`
   y se regenera -- nunca parcheando el JSON ni agregando un `expect` suelto aca. */
import { describe, expect, it } from 'vitest';

import fixtureJson from '../__fixtures__/dslParity.json';
import type { Grid } from '../grid';
import {
  applyProgram,
  DSL_PRIMITIVE_NAMES,
  type PrimitiveContext,
  type Program,
} from '../primitiveOps';

interface CasoParidadFixture {
  name: string;
  why: string;
  program: Program;
  pre: Grid;
  anchor?: Grid;
  expected: Grid;
}

interface FixtureParidad {
  version: number;
  generatedFrom: string;
  note: string;
  cases: CasoParidadFixture[];
}

/* El cast es seguro y deliberado: el JSON tiene un unico escritor (el generador), que valida la
   forma antes de escribir y ademas verifica el round-trip por JSON. Tipar el import a mano seria
   una tercera declaracion del mismo shape. */
const fixture = fixtureJson as unknown as FixtureParidad;

const COBERTURA_MINIMA_POR_PRIMITIVO = 3;

function contextoDe(caso: CasoParidadFixture): PrimitiveContext {
  return caso.anchor ? { anchorGrid: caso.anchor } : {};
}

describe('fixture de paridad del DSL -- metadatos', () => {
  it('declara version 1 y origen typescript', () => {
    expect(fixture.version).toBe(1);
    expect(fixture.generatedFrom).toBe('typescript');
    expect(fixture.note.length).toBeGreaterThan(0);
  });

  it('tiene casos y ninguno repite nombre', () => {
    expect(fixture.cases.length).toBeGreaterThan(0);
    const nombres = fixture.cases.map((caso) => caso.name);
    expect(new Set(nombres).size).toBe(nombres.length);
  });

  it('cubre cada primitivo del DSL con al menos 3 casos', () => {
    // La lista de primitivos viene de primitiveOps (fuente unica): si el DSL crece, este test
    // empieza a fallar por el primitivo nuevo hasta que alguien le escriba sus casos.
    const conteo = new Map<string, number>(DSL_PRIMITIVE_NAMES.map((nombre) => [nombre, 0]));
    for (const caso of fixture.cases) {
      for (const nombre of new Set(caso.program.map((paso) => paso.name))) {
        conteo.set(nombre, (conteo.get(nombre) ?? 0) + 1);
      }
    }
    const insuficientes = [...conteo.entries()].filter(
      ([, cantidad]) => cantidad < COBERTURA_MINIMA_POR_PRIMITIVO,
    );
    expect(insuficientes).toEqual([]);
  });

  it('solo trae grilla ancla en los casos que usan overlay', () => {
    // `anchor` es el unico dato de contexto del fixture. Si apareciera en un caso sin overlay, el
    // port podria concluir que hay que pasarlo en algun otro lado.
    const anchorSinOverlay = fixture.cases
      .filter((caso) => caso.anchor !== undefined)
      .filter((caso) => !caso.program.some((paso) => paso.name === 'overlay'))
      .map((caso) => caso.name);
    expect(anchorSinOverlay).toEqual([]);
  });

  it('documenta por que existe cada caso', () => {
    const sinExplicacion = fixture.cases
      .filter((caso) => !caso.why || caso.why.trim().length === 0)
      .map((caso) => caso.name);
    expect(sinExplicacion).toEqual([]);
  });
});

describe('fixture de paridad del DSL -- ejecucion', () => {
  // it.each por caso (y no un solo it con un for) para que el reporter nombre EXACTAMENTE que
  // caso divergio: cuando este test se rompe, el nombre del caso es la primera pista del bug.
  it.each(fixture.cases.map((caso) => [caso.name, caso] as const))(
    'applyProgram reproduce el esperado -- %s',
    (_nombre, caso) => {
      expect(applyProgram(caso.program, caso.pre, contextoDe(caso))).toEqual(caso.expected);
    },
  );

  it('applyProgram no muta la grilla de entrada en ningun caso', () => {
    // Pureza: el fixture guarda `pre` como la entrada del caso. Si applyProgram mutara, `pre` en
    // el JSON dejaria de ser la entrada real y el contrato mentiria de la forma mas dificil de
    // detectar (el lado TS seguiria verde consigo mismo).
    for (const caso of fixture.cases) {
      const preAntes = JSON.stringify(caso.pre);
      const anchorAntes = JSON.stringify(caso.anchor ?? null);
      applyProgram(caso.program, caso.pre, contextoDe(caso));
      expect(JSON.stringify(caso.pre), `caso ${caso.name} muto su pre`).toBe(preAntes);
      expect(JSON.stringify(caso.anchor ?? null), `caso ${caso.name} muto su ancla`).toBe(
        anchorAntes,
      );
    }
  });

  it('es deterministico -- dos corridas del mismo caso dan lo mismo', () => {
    for (const caso of fixture.cases) {
      const ctx = contextoDe(caso);
      expect(applyProgram(caso.program, caso.pre, ctx)).toEqual(
        applyProgram(caso.program, caso.pre, ctx),
      );
    }
  });
});
