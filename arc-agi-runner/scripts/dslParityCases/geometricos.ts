/* [arc-agi-runner/scripts/dslParityCases/geometricos] BL.20860 -- casos de paridad de los
   primitivos que mueven celdas sin tocar colores: translate, reflect, rotate.

   `translate` concentra la mayor densidad de casos de todo el fixture porque es el primitivo con
   el modo de falla de port MAS probable: TypeScript resuelve `grid[sy][sx]` con sy/sx negativos
   como `undefined` y el codigo lo BLOQUEA con un guard explicito (`sy >= 0 && sx >= 0`), mientras
   que Python indexa negativo SIN error y devuelve la fila/columna OPUESTA. Un port que copie la
   formula `sx = x - dx` y omita el guard no explota: produce una grilla que envuelve por el borde
   y pasa desapercibida hasta que la sintesis de programas aprende una transicion falsa. Por eso
   varios `pre` tienen valores distintivos justo en la ultima fila/columna: si el port envuelve,
   esos valores aparecen en el borde opuesto y el diff es inmediato y legible. */

import type { CasoParidad } from './tipos';

export const casosGeometricos: CasoParidad[] = [
  // ─── translate ─────────────────────────────────────────────────────────────
  {
    name: 'translate_dx_positivo_rellena_con_fondo_detectado',
    why: 'Caso base: el hueco que deja el desplazamiento se rellena con el fondo DETECTADO (el color mas frecuente), no con cero fijo.',
    program: [{ name: 'translate', params: { dx: 1, dy: 0 } }],
    pre: [
      [0, 0, 0],
      [0, 5, 0],
      [0, 0, 0],
    ],
  },
  {
    name: 'translate_dx_positivo_no_envuelve_por_la_columna_final',
    why: 'TRAMPA DE PORT: con dx=1 la columna 0 pide sx=-1. TS lo corta con el guard y pone fondo; Python indexaria grid[y][-1] y traeria la ULTIMA columna (9,8,7). El esperado no contiene 9/8/7 en ningun lado.',
    program: [{ name: 'translate', params: { dx: 1, dy: 0 } }],
    pre: [
      [0, 4, 9],
      [0, 0, 8],
      [0, 0, 7],
    ],
  },
  {
    name: 'translate_dy_positivo_no_envuelve_por_la_fila_final',
    why: 'TRAMPA DE PORT, eje Y: con dy=1 la fila 0 pide sy=-1. Python traeria la ULTIMA fila ([0,0,4]) en vez de fondo.',
    program: [{ name: 'translate', params: { dx: 0, dy: 1 } }],
    pre: [
      [1, 2, 3],
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 4],
    ],
  },
  {
    name: 'translate_dx_negativo_desborda_por_la_derecha',
    why: 'Con dx negativo el indice se pasa por ARRIBA (sx >= w). Ahi Python tira IndexError en vez de envolver, asi que la falla es ruidosa -- pero el guard tiene que existir igual.',
    program: [{ name: 'translate', params: { dx: -2, dy: 0 } }],
    pre: [
      [1, 2, 3, 4],
      [5, 0, 0, 0],
    ],
  },
  {
    name: 'translate_dx_y_dy_negativos_a_la_vez',
    why: 'Desplazamiento diagonal hacia arriba-izquierda: ejercita los dos guards de borde superior en la misma pasada.',
    program: [{ name: 'translate', params: { dx: -1, dy: -1 } }],
    pre: [
      [0, 0, 0, 0],
      [0, 6, 6, 0],
      [0, 6, 0, 0],
      [0, 0, 0, 0],
    ],
  },
  {
    name: 'translate_desplazamiento_mayor_que_la_grilla',
    why: 'Cuando el desplazamiento supera el ancho, NINGUNA celda origen es valida: la salida es fondo puro. Un port con modulo implicito devolveria la grilla intacta.',
    program: [{ name: 'translate', params: { dx: 5, dy: 0 } }],
    pre: [
      [2, 2, 0],
      [0, 3, 0],
      [0, 0, 0],
    ],
  },
  {
    name: 'translate_empate_de_fondo_gana_el_color_de_menor_indice',
    why: 'detectBackgroundColor desempata por color MENOR (3 y 5 aparecen 3 veces cada uno -> gana 3). El relleno del translate es el unico observable de ese desempate.',
    program: [{ name: 'translate', params: { dx: 0, dy: 1 } }],
    pre: [
      [3, 3],
      [5, 5],
      [3, 5],
    ],
  },
  {
    name: 'translate_grilla_1x1_rellena_con_su_unico_color',
    why: 'Grilla minima: el unico color ES el fondo, asi que desplazar no cambia nada visible. Bloquea que el port no asuma fondo=0.',
    program: [{ name: 'translate', params: { dx: 1, dy: 0 } }],
    pre: [[7]],
  },
  {
    name: 'translate_grilla_vacia_no_explota',
    why: 'Grilla vacia: h=0 y w=0, los loops no corren y la salida es vacia. Un port que calcule w como len(grid[0]) revienta con IndexError antes de llegar aca.',
    program: [{ name: 'translate', params: { dx: 1, dy: 1 } }],
    pre: [],
  },
  {
    name: 'translate_cero_es_identidad',
    why: 'dx=0,dy=0 debe ser identidad exacta, incluso sobre una grilla sin fondo dominante claro.',
    program: [{ name: 'translate', params: { dx: 0, dy: 0 } }],
    pre: [
      [1, 2],
      [3, 4],
    ],
  },

  // ─── reflect ───────────────────────────────────────────────────────────────
  {
    name: 'reflect_horizontal_invierte_columnas',
    why: "'horizontal' es espejo IZQUIERDA-DERECHA (invierte cada fila). El nombre del eje se presta a leerlo al reves.",
    program: [{ name: 'reflect', params: { axis: 'horizontal' } }],
    pre: [
      [1, 2, 3],
      [4, 5, 6],
      [7, 8, 9],
    ],
  },
  {
    name: 'reflect_vertical_invierte_filas',
    why: "'vertical' es espejo ARRIBA-ABAJO (invierte el orden de las filas), no el de las columnas.",
    program: [{ name: 'reflect', params: { axis: 'vertical' } }],
    pre: [
      [1, 2, 3],
      [4, 5, 6],
      [7, 8, 9],
    ],
  },
  {
    name: 'reflect_horizontal_no_cuadrada_2x4',
    why: 'Grilla no cuadrada: reflejar horizontal conserva las dimensiones. Un port que transponga por error cambia la forma.',
    program: [{ name: 'reflect', params: { axis: 'horizontal' } }],
    pre: [
      [1, 2, 3, 4],
      [5, 6, 7, 8],
    ],
  },
  {
    name: 'reflect_vertical_no_cuadrada_4x2',
    why: 'Complemento del anterior con la forma traspuesta, para que un port que confunda los ejes falle en uno de los dos si o si.',
    program: [{ name: 'reflect', params: { axis: 'vertical' } }],
    pre: [
      [1, 2],
      [3, 4],
      [5, 6],
      [7, 8],
    ],
  },
  {
    name: 'reflect_horizontal_fila_unica',
    why: 'Una sola fila: el reflejo horizontal es el unico que hace algo. Verifica que no se copie la referencia de la fila (el TS hace slice antes de reverse).',
    program: [{ name: 'reflect', params: { axis: 'horizontal' } }],
    pre: [[1, 2, 3, 4]],
  },
  {
    name: 'reflect_horizontal_1x1_es_identidad',
    why: 'Grilla minima: cualquier reflejo es identidad.',
    program: [{ name: 'reflect', params: { axis: 'horizontal' } }],
    pre: [[6]],
  },
  {
    name: 'reflect_vertical_grilla_vacia',
    why: 'Grilla vacia: reflejar nada devuelve nada, sin excepciones.',
    program: [{ name: 'reflect', params: { axis: 'vertical' } }],
    pre: [],
  },

  // ─── rotate ────────────────────────────────────────────────────────────────
  {
    name: 'rotate_1_cuarto_horario_no_cuadrada',
    why: 'Un cuarto de giro HORARIO sobre 2x3 devuelve 3x2: la fila superior pasa a ser la columna derecha. Antihorario da la traspuesta espejada, y el diff canta.',
    program: [{ name: 'rotate', params: { quarterTurns: 1 } }],
    pre: [
      [1, 2, 3],
      [4, 5, 6],
    ],
  },
  {
    name: 'rotate_2_cuartos_conserva_dimensiones',
    why: '180 grados sobre la MISMA grilla del caso anterior: conserva 2x3 y equivale a reflejar en los dos ejes.',
    program: [{ name: 'rotate', params: { quarterTurns: 2 } }],
    pre: [
      [1, 2, 3],
      [4, 5, 6],
    ],
  },
  {
    name: 'rotate_3_cuartos_es_el_inverso_de_1',
    why: 'Tres cuartos sobre la MISMA grilla: mismas dimensiones que rotate 1 pero contenido invertido. Los tres casos comparten `pre` justamente para que la comparacion entre ellos sea directa.',
    program: [{ name: 'rotate', params: { quarterTurns: 3 } }],
    pre: [
      [1, 2, 3],
      [4, 5, 6],
    ],
  },
  {
    name: 'rotate_1_convierte_fila_en_columna',
    why: 'De 1x4 a 4x1: el caso mas sensible al orden de los indices en el port (out[x][h-1-y] = grid[y][x]).',
    program: [{ name: 'rotate', params: { quarterTurns: 1 } }],
    pre: [[1, 2, 3, 4]],
  },
  {
    name: 'rotate_1_grilla_1x1_es_identidad',
    why: 'Grilla minima: rotar no cambia nada, pero el port tiene que construir la salida con las dimensiones intercambiadas igual.',
    program: [{ name: 'rotate', params: { quarterTurns: 1 } }],
    pre: [[8]],
  },
  {
    name: 'rotate_2_grilla_vacia',
    why: 'Grilla vacia con DOS giros encadenados: verifica que el resultado intermedio vacio siga siendo rotable.',
    program: [{ name: 'rotate', params: { quarterTurns: 2 } }],
    pre: [],
  },
  {
    name: 'rotate_1_asimetrica_3x3',
    why: 'Grilla 3x3 sin ninguna simetria: cualquier confusion de eje u orientacion produce un diff, cosa que una grilla simetrica ocultaria.',
    program: [{ name: 'rotate', params: { quarterTurns: 1 } }],
    pre: [
      [1, 0, 0],
      [2, 3, 0],
      [4, 5, 6],
    ],
  },
];
