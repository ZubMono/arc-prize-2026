/* [arc-agi-runner/worldModel/mechanicsParity.test] BL.21741 (correccion) -- corre el FIXTURE
   DORADO de paridad de la PERCEPCION (`__fixtures__/mechanicsParity.json`) contra este motor.

   POR QUE existe si el fixture LO GENERA el mismo motor: para que no quede STALE. El defecto que lo
   motiva es medido y no hipotetico -- BL.21741 arreglo `object_mechanics.py` (tope 4096, tipos
   propios para los dos silencios, firma compuesta) y ESTE archivo quedo en 2048 y "desconocida"
   durante todo el BL; sobre el mismo corpus persistido un puerto daba 7 firmas distintas y el otro
   una sola, y las dos suites seguian verdes. Con este test, cambiar el motor sin regenerar el
   fixture es un build rojo del lado que hizo el cambio.

   Este archivo NO tiene expectativas escritas a mano: todo lo que afirma sale del fixture. Un caso
   que parezca mal se arregla en `scripts/mechanicsParityCases.ts` y se regenera. */
import { describe, expect, it } from 'vitest';

import fixtureJson from '../__fixtures__/mechanicsParity.json';
import type { Grid, VolatilityMask } from '../grid';
import {
  conteoDeTiposDeCluster,
  CORTES_DE_CUBO,
  esFirmaDeSilencio,
  firmaDeMecanica,
  PREFIJO_DE_FIRMA_COMPUESTA,
  TIPO_SIN_NOMBRAR,
} from '../mechanicsSignature';
import { MAX_CELDAS_DE_OBJETO_ENTERO, MAX_PARES_DE_OBJETO } from '../objectGeometry';
import {
  detectarMecanica,
  MAX_AREA_CAJA_DE_CAMBIOS,
  MAX_CELDAS_CAMBIADAS,
  MAX_TAMANO_OBJETO,
  MIN_EVIDENCIA_DE_OBJETO,
  TIPOS_DE_MECANICA,
  TIPOS_DE_NO_MIRE,
  TIPO_SIN_MEDICION,
  type OpcionesDeMecanica,
} from '../objectMechanics';

interface EsperadoDeMecanica {
  tipo: string;
  celdasCambiadas: number;
  firma: string;
  esFirmaDeSilencio: boolean;
  conteoDeTiposDeCluster: Record<string, number>;
  traslacionPrincipal: { dy: number; dx: number; alto: number; ancho: number } | null;
  cambioDeColorPrincipal: { desde: number; hasta: number; celdas: number } | null;
}

interface CasoDeMecanicaFixture {
  name: string;
  why: string;
  pre: Grid;
  post: Grid;
  mask?: boolean[][];
  opciones?: OpcionesDeMecanica;
  expected: EsperadoDeMecanica;
}

interface FixtureDeMecanicas {
  version: number;
  generatedFrom: string;
  note: string;
  constantes: Record<string, unknown>;
  cases: CasoDeMecanicaFixture[];
}

/* Cast deliberado: el JSON tiene un unico escritor (el generador), que valida la forma antes de
   escribir. Tiparlo a mano seria una tercera declaracion del mismo shape. */
const fixture = fixtureJson as unknown as FixtureDeMecanicas;

describe('fixture de paridad de la percepcion -- metadatos', () => {
  it('declara version 1 y origen typescript', () => {
    expect(fixture.version).toBe(1);
    expect(fixture.generatedFrom).toBe('typescript');
    expect(fixture.note.length).toBeGreaterThan(0);
  });

  it('cubre TODOS los tipos que el motor puede devolver', () => {
    const tipos = new Set(fixture.cases.map((c) => c.expected.tipo));
    for (const tipo of TIPOS_DE_MECANICA) expect(tipos).toContain(tipo);
  });

  it('cubre las dos formas de firma compuesta: la informativa y la de SILENCIO', () => {
    const compuestas = fixture.cases
      .map((c) => c.expected.firma)
      .filter((f) => f.startsWith(PREFIJO_DE_FIRMA_COMPUESTA));
    expect(compuestas.some((f) => esFirmaDeSilencio(f))).toBe(true);
    expect(compuestas.some((f) => !esFirmaDeSilencio(f))).toBe(true);
  });
});

describe('las CONSTANTES del contrato no quedaron stale', () => {
  // Es la mitad del fixture que habria atajado la divergencia real: el tope valia 4096 de un lado
  // y 2048 del otro, y ningun caso de comportamiento con grillas chicas lo habria mostrado.
  it('el fixture declara las constantes VIGENTES del motor', () => {
    expect(fixture.constantes).toEqual({
      MAX_CELDAS_CAMBIADAS,
      MAX_AREA_CAJA_DE_CAMBIOS,
      MAX_TAMANO_OBJETO,
      MIN_EVIDENCIA_DE_OBJETO,
      MAX_CELDAS_DE_OBJETO_ENTERO,
      MAX_PARES_DE_OBJETO,
      CORTES_DE_CUBO: [...CORTES_DE_CUBO],
      TIPOS_DE_MECANICA: [...TIPOS_DE_MECANICA],
      TIPOS_DE_NO_MIRE: [...TIPOS_DE_NO_MIRE],
      TIPO_SIN_MEDICION,
      TIPO_SIN_NOMBRAR,
      PREFIJO_DE_FIRMA_COMPUESTA,
    });
  });
});

describe('el motor reproduce el fixture caso por caso', () => {
  for (const caso of fixture.cases) {
    it(`${caso.name}: ${caso.why}`, () => {
      const mask = (caso.mask ?? null) as VolatilityMask | null;
      const mecanica = detectarMecanica(caso.pre, caso.post, mask, caso.opciones ?? {});
      const firma = firmaDeMecanica(mecanica);
      expect(mecanica.tipo).toBe(caso.expected.tipo);
      expect(mecanica.celdasCambiadas).toBe(caso.expected.celdasCambiadas);
      expect(firma).toBe(caso.expected.firma);
      expect(esFirmaDeSilencio(firma)).toBe(caso.expected.esFirmaDeSilencio);
      expect(conteoDeTiposDeCluster(mecanica)).toEqual(caso.expected.conteoDeTiposDeCluster);
      const t = mecanica.traslacionPrincipal;
      expect(t === null ? null : { dy: t.dy, dx: t.dx, alto: t.alto, ancho: t.ancho }).toEqual(
        caso.expected.traslacionPrincipal,
      );
      expect(mecanica.cambioDeColorPrincipal).toEqual(caso.expected.cambioDeColorPrincipal);
    });
  }
});
