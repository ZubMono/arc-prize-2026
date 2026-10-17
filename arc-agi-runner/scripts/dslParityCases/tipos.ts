/* [arc-agi-runner/scripts/dslParityCases/tipos] BL.20860 -- tipo de un caso del fixture dorado de
   paridad TS<->Python del DSL. Los casos se declaran SIN `expected`: el valor esperado lo calcula
   el generador corriendo el motor TypeScript canonico (primitiveOps.ts). Declarar el esperado a
   mano seria una segunda fuente de verdad -- exactamente lo que este fixture existe para evitar.

   `program` esta tipado como `Program` (no como JSON suelto) a proposito: si alguien cambia la
   forma de un ProgramStep del DSL, la compilacion de los casos rompe ANTES de regenerar el
   fixture, en vez de generar silenciosamente un contrato distinto. */

import type { Grid } from '../../src/worldModel/grid';
import type { Program } from '../../src/worldModel/primitiveOps';

export interface CasoParidad {
  /** Identificador estable del caso. ASCII, snake_case, sin tildes: viaja al JSON y de ahi al
   *  lado Python, que por regla de estilo del repo no usa tildes en su fuente. */
  name: string;
  /** Que semantica bloquea este caso -- POR QUE existe, no que hace. Tambien ASCII. */
  why: string;
  program: Program;
  pre: Grid;
  /** Solo para 'overlay': la grilla ancla del PrimitiveContext. Ausente = contexto vacio, que es
   *  justamente la rama defensiva de overlay (degrada a identidad). */
  anchor?: Grid;
}
