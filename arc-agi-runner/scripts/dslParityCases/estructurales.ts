/* [arc-agi-runner/scripts/dslParityCases/estructurales] BL.20860 -- casos de paridad de los
   primitivos que cambian la FORMA de la grilla o la combinan con otra: cropToBBox, overlay,
   replicate.

   Puntos finos que estos casos bloquean:

   - `cropToBBox` recibe el fondo por PARAMETRO y no lo detecta. Es deliberado: el generador de
     candidatos prueba varios fondos posibles, asi que el primitivo tiene que obedecer el que le
     pasan aunque no sea el color mas frecuente. Sobre una grilla uniforme no hay foreground y el
     bbox es null -> no-op (nunca una grilla vacia, que es el error natural de un port que
     inicialice el bbox en 0,0).

   - `overlay` es el UNICO primitivo con estado externo: la grilla ancla del contexto (por diseno,
     el primer frame del episodio). Sin ancla degrada a identidad. Los casos con ancla la traen en
     el campo opcional `anchor` del fixture; el port debe pasarla como anchorGrid del contexto. El
     acceso es `anchor[y]?.[x] ?? cell`, con DOS niveles de tolerancia: si el ancla es mas chica
     que la grilla, las celdas sin cobertura quedan como estaban. En Python eso es un IndexError
     (o, peor, un indice negativo que envuelve) si el port no replica los opcionales.

   - `replicate` es aritmetica de modulo pura: `grid[y % h][x % w]`. Con timesX=0 la salida NO es
     una grilla vacia sino h filas VACIAS -- una forma degenerada que es facil de perder en el
     port y que aguas abajo cambia el hash de estado. Con timesY=0 si es vacia. Ojo: los loops
     nunca corren cuando h o w son 0, asi que el modulo nunca divide por cero; un port que
     precalcule `x % w` fuera del loop se comeria un ZeroDivisionError. */

import type { CasoParidad } from './tipos';

export const casosEstructurales: CasoParidad[] = [
  // ─── cropToBBox ────────────────────────────────────────────────────────────
  {
    name: 'cropToBBox_recorta_al_contenido',
    why: 'Caso base: recorta el marco de fondo y deja solo el bloque de foreground.',
    program: [{ name: 'cropToBBox', params: { backgroundColor: 0 } }],
    pre: [
      [0, 0, 0, 0, 0],
      [0, 4, 4, 0, 0],
      [0, 4, 4, 0, 0],
      [0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0],
    ],
  },
  {
    name: 'cropToBBox_grilla_uniforme_sin_foreground_es_no_op',
    why: 'Sin ninguna celda distinta del fondo el bbox es null y se devuelve la grilla ENTERA sin cambios. Un port que inicialice minX/minY en 0 devolveria una grilla de 1x1 o vacia.',
    program: [{ name: 'cropToBBox', params: { backgroundColor: 0 } }],
    pre: [
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ],
  },
  {
    name: 'cropToBBox_fondo_distinto_de_cero',
    why: 'El fondo es 5, no 0: el recorte deja el bloque central de 0 y 7. Bloquea que el port hardcodee 0 como fondo, que es el valor tipico pero no el unico.',
    program: [{ name: 'cropToBBox', params: { backgroundColor: 5 } }],
    pre: [
      [5, 5, 5, 5],
      [5, 0, 7, 5],
      [5, 7, 0, 5],
      [5, 5, 5, 5],
    ],
  },
  {
    name: 'cropToBBox_usa_el_fondo_del_parametro_no_el_detectado',
    why: 'MISMA grilla que el caso anterior pero pasando 7 como fondo. El fondo DETECTADO seria 5 (12 de 16 celdas); el primitivo tiene que obedecer el parametro igual, y con fondo 7 casi todo es foreground, asi que el bbox cubre la grilla entera y no recorta nada. Un port que detecte el fondo por su cuenta devuelve el 2x2 del centro y el diff es inmediato. El parametro existe justamente porque el generador de candidatos prueba varios fondos posibles.',
    program: [{ name: 'cropToBBox', params: { backgroundColor: 7 } }],
    pre: [
      [5, 5, 5, 5],
      [5, 0, 7, 5],
      [5, 7, 0, 5],
      [5, 5, 5, 5],
    ],
  },
  {
    name: 'cropToBBox_no_cuadrada_recorta_los_dos_ejes',
    why: 'Grilla 3x6 con contenido descentrado: el recorte tiene que ajustar ancho y alto de forma independiente.',
    program: [{ name: 'cropToBBox', params: { backgroundColor: 0 } }],
    pre: [
      [0, 0, 0, 0, 0, 0],
      [0, 0, 7, 7, 0, 0],
      [0, 0, 0, 7, 0, 0],
    ],
  },
  {
    name: 'cropToBBox_una_sola_celda_de_foreground',
    why: 'Una unica celda distinta del fondo produce una grilla 1x1: los limites del bbox son inclusivos en los dos extremos.',
    program: [{ name: 'cropToBBox', params: { backgroundColor: 0 } }],
    pre: [
      [0, 0, 0],
      [0, 0, 0],
      [0, 2, 0],
    ],
  },
  {
    name: 'cropToBBox_grilla_vacia_es_no_op',
    why: 'Grilla vacia: no hay foreground, el bbox es null y el clon vacio sale sin excepciones.',
    program: [{ name: 'cropToBBox', params: { backgroundColor: 0 } }],
    pre: [],
  },

  // ─── overlay ───────────────────────────────────────────────────────────────
  {
    name: 'overlay_sin_ancla_es_identidad',
    why: 'RAMA DEFENSIVA: sin anchorGrid en el contexto overlay no puede hacer nada y devuelve un clon. Este caso NO trae campo `anchor` a proposito.',
    program: [{ name: 'overlay', params: {} }],
    pre: [
      [0, 0, 0],
      [0, 5, 0],
      [0, 0, 0],
    ],
  },
  {
    name: 'overlay_con_ancla_rellena_solo_el_fondo',
    why: 'Caso base: las celdas de foreground de la grilla actual MANDAN; solo las de fondo toman el valor del ancla.',
    program: [{ name: 'overlay', params: {} }],
    pre: [
      [0, 0, 0],
      [0, 5, 0],
      [0, 0, 0],
    ],
    anchor: [
      [1, 2, 3],
      [4, 9, 6],
      [7, 8, 9],
    ],
  },
  {
    name: 'overlay_ancla_mas_chica_deja_intactas_las_celdas_sin_cobertura',
    why: 'TRAMPA DE PORT: el ancla 2x2 no cubre la grilla 3x3. TS resuelve anchor[y]?.[x] a undefined y cae al valor original; Python tira IndexError (fila 2) o envuelve.',
    program: [{ name: 'overlay', params: {} }],
    pre: [
      [0, 0, 0],
      [0, 5, 0],
      [0, 0, 0],
    ],
    anchor: [
      [1, 2],
      [3, 4],
    ],
  },
  {
    name: 'overlay_ancla_mas_grande_usa_solo_la_region_coincidente',
    why: 'El tamano de la SALIDA lo fija la grilla actual, no el ancla: las filas y columnas sobrantes del ancla se ignoran.',
    program: [{ name: 'overlay', params: {} }],
    pre: [
      [0, 6],
      [0, 0],
    ],
    anchor: [
      [1, 2, 3, 4],
      [5, 6, 7, 8],
      [9, 1, 2, 3],
      [4, 5, 6, 7],
    ],
  },
  {
    name: 'overlay_grilla_uniforme_toma_el_ancla_entera',
    why: 'Si toda la grilla es fondo, el resultado ES el ancla. Extremo util para detectar la polaridad invertida (un port que pise el foreground en vez del fondo).',
    program: [{ name: 'overlay', params: {} }],
    pre: [
      [0, 0],
      [0, 0],
    ],
    anchor: [
      [1, 2],
      [3, 4],
    ],
  },

  // ─── replicate ─────────────────────────────────────────────────────────────
  {
    name: 'replicate_2x1_tesela_horizontal',
    why: 'Caso base: duplica en X y deja Y igual. El ancho se multiplica, el alto no.',
    program: [{ name: 'replicate', params: { timesX: 2, timesY: 1 } }],
    pre: [
      [1, 2],
      [3, 4],
    ],
  },
  {
    name: 'replicate_1x2_tesela_vertical',
    why: 'Complemento del anterior sobre una grilla no cuadrada 1x3: verifica que no se confundan los ejes.',
    program: [{ name: 'replicate', params: { timesX: 1, timesY: 2 } }],
    pre: [[1, 2, 3]],
  },
  {
    name: 'replicate_1x1_es_identidad',
    why: 'Factor 1 en los dos ejes debe devolver una copia exacta.',
    program: [{ name: 'replicate', params: { timesX: 1, timesY: 1 } }],
    pre: [
      [1, 2, 3],
      [4, 5, 6],
    ],
  },
  {
    name: 'replicate_2x2_sobre_1x1',
    why: 'Modulo sobre dimension 1: x % 1 y y % 1 son siempre 0. Grilla minima teselada a 2x2.',
    program: [{ name: 'replicate', params: { timesX: 2, timesY: 2 } }],
    pre: [[5]],
  },
  {
    name: 'replicate_3x1_sobre_no_cuadrada',
    why: 'Tres repeticiones horizontales de una grilla 2x2: el patron se repite exacto, sin espejar (un port que alterne la direccion produciria un espejo en la segunda copia).',
    program: [{ name: 'replicate', params: { timesX: 3, timesY: 1 } }],
    pre: [
      [1, 2],
      [3, 0],
    ],
  },
  {
    name: 'replicate_2x2_completo',
    why: 'Los dos ejes a la vez sobre una grilla asimetrica: bloquea el orden de los indices en la formula grid[y % h][x % w].',
    program: [{ name: 'replicate', params: { timesX: 2, timesY: 2 } }],
    pre: [
      [1, 2],
      [3, 4],
    ],
  },
  {
    name: 'replicate_timesX_cero_produce_filas_vacias',
    why: 'FORMA DEGENERADA: timesX=0 con timesY=1 no da una grilla vacia sino DOS filas vacias. La distincion importa porque aguas abajo cambia el hash de estado.',
    program: [{ name: 'replicate', params: { timesX: 0, timesY: 1 } }],
    pre: [
      [1, 2],
      [3, 4],
    ],
  },
  {
    name: 'replicate_timesY_cero_produce_grilla_vacia',
    why: 'Complemento del anterior: con timesY=0 no hay ninguna fila, ni siquiera vacia.',
    program: [{ name: 'replicate', params: { timesX: 2, timesY: 0 } }],
    pre: [
      [1, 2],
      [3, 4],
    ],
  },
  {
    name: 'replicate_grilla_vacia_no_divide_por_cero',
    why: 'Con h=0 el loop externo no corre, asi que el modulo nunca se evalua. Un port que calcule w o h fuera del loop y haga la division igual explota con ZeroDivisionError.',
    program: [{ name: 'replicate', params: { timesX: 2, timesY: 2 } }],
    pre: [],
  },
  {
    name: 'replicate_filas_vacias_se_multiplican_pero_siguen_vacias',
    why: 'Entrada degenerada (dos filas de ancho cero): salen cuatro filas vacias. Es la ida y vuelta del caso replicate_timesX_cero, y de nuevo el modulo por w=0 nunca se evalua.',
    program: [{ name: 'replicate', params: { timesX: 2, timesY: 2 } }],
    pre: [[], []],
  },
];
