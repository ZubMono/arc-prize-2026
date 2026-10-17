/* [arc-agi-runner/scripts/dslParityCases/index] BL.20860 -- barrel de los casos del fixture dorado
   de paridad del DSL. El orden de concatenacion ES el orden del array `cases` en el JSON y se
   mantiene estable a proposito: un fixture regenerado tiene que producir un diff de git legible
   (solo las lineas que cambiaron de semantica), no un reordenamiento completo. Por eso los casos
   se declaran en archivos separados y se concatenan, en vez de agruparse por un sort en runtime. */

export type { CasoParidad } from './tipos';

import { casosColor } from './color';
import { casosComposicion } from './composicion';
import { casosEstructurales } from './estructurales';
import { casosGeometricos } from './geometricos';
import { casosObjetos } from './objetos';
import type { CasoParidad } from './tipos';

export const todosLosCasos: CasoParidad[] = [
  ...casosGeometricos,
  ...casosColor,
  ...casosEstructurales,
  ...casosObjetos,
  ...casosComposicion,
];
