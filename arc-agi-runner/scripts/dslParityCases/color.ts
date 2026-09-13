/* [arc-agi-runner/scripts/dslParityCases/color] BL.20860 -- casos de paridad de los primitivos que
   cambian colores sin mover celdas: recolor, floodFill, conditionalRecolor.

   Tres trampas de port viven aca:

   1) `recolor` usa `mapping[cell] ?? cell`: el `??` es NULLISH, no falsy. Mapear un color a 0 es
      legitimo (0 es un color valido de ARC, tipicamente el fondo). Un port que escriba
      `mapping.get(c) or c` rompe exactamente ese caso. Ademas, al serializar a JSON las claves
      numericas del mapping se vuelven STRINGS: JS las re-coacciona sola al indexar, Python NO --
      el port tiene que convertir las claves a int al cargar.

   2) `floodFill` valida las coordenadas ANTES de leer la celda origen. Con x=-1 TS entra al guard;
      Python, sin guard, leeria la ultima columna y pintaria una region que no corresponde.

   3) `conditionalRecolor` chequea el borde de la grilla ANTES de mirar los 4 vecinos. Ese orden no
      es cosmetico: es lo que garantiza que el acceso a los vecinos nunca se salga de rango. Un
      port que invierta las dos condiciones lee vecinos con indice -1 y, en Python, envuelve.

   La region de floodFill se recorre con una pila (DFS), pero el resultado es un CONJUNTO de
   celdas: el orden de recorrido no es observable, asi que el port puede usar la travesia que
   quiera mientras respete la conectividad 4. */

import type { CasoParidad } from './tipos';

export const casosColor: CasoParidad[] = [
  // ─── recolor ───────────────────────────────────────────────────────────────
  {
    name: 'recolor_mapping_total',
    why: 'Caso base: todos los colores presentes estan en el mapping.',
    program: [{ name: 'recolor', params: { mapping: { 1: 4, 2: 5 } } }],
    pre: [
      [1, 2],
      [2, 1],
    ],
  },
  {
    name: 'recolor_mapping_parcial_deja_intactos_los_no_mapeados',
    why: 'Los colores ausentes del mapping quedan IGUAL (identidad), no en 0 ni en undefined.',
    program: [{ name: 'recolor', params: { mapping: { 3: 6 } } }],
    pre: [
      [3, 1, 3],
      [2, 3, 0],
    ],
  },
  {
    name: 'recolor_mapping_vacio_es_identidad',
    why: 'Mapping vacio = no-op. En JSON es un objeto {} y el port no debe confundirlo con null.',
    program: [{ name: 'recolor', params: { mapping: {} } }],
    pre: [
      [1, 2],
      [3, 4],
    ],
  },
  {
    name: 'recolor_destino_cero_no_es_falsy',
    why: 'TRAMPA DE PORT: mapear 3 -> 0 debe dar 0. TS usa ?? (nullish); un port con `or` devolveria 3 porque 0 es falsy.',
    program: [{ name: 'recolor', params: { mapping: { 3: 0 } } }],
    pre: [
      [3, 3, 1],
      [1, 3, 1],
    ],
  },
  {
    name: 'recolor_origen_cero_es_clave_valida',
    why: 'TRAMPA DE PORT: la clave 0 viaja al JSON como la cadena "0". Un port que la descarte por falsy (o que no convierta la clave a int) deja el fondo sin recolorear.',
    program: [{ name: 'recolor', params: { mapping: { 0: 8 } } }],
    pre: [
      [0, 1, 0],
      [1, 0, 1],
    ],
  },
  {
    name: 'recolor_clave_ausente_en_la_grilla_es_identidad',
    why: 'Un mapping que apunta a un color inexistente no debe alterar nada ni agregar colores nuevos.',
    program: [{ name: 'recolor', params: { mapping: { 9: 1 } } }],
    pre: [
      [2, 2],
      [2, 3],
    ],
  },
  {
    name: 'recolor_grilla_vacia',
    why: 'Grilla vacia: map sobre cero filas devuelve cero filas.',
    program: [{ name: 'recolor', params: { mapping: { 1: 2 } } }],
    pre: [],
  },

  // ─── floodFill ─────────────────────────────────────────────────────────────
  {
    name: 'floodFill_region_conexa_completa',
    why: 'Caso base: pinta el bloque conexo de 1 y NO toca el bloque de 2, aunque compartan la grilla.',
    program: [{ name: 'floodFill', params: { x: 0, y: 0, to: 7 } }],
    pre: [
      [1, 1, 0, 0],
      [1, 1, 0, 0],
      [0, 0, 2, 2],
      [0, 0, 2, 2],
    ],
  },
  {
    name: 'floodFill_conectividad_4_no_propaga_en_diagonal',
    why: 'Las diagonales NO conectan: arrancando del 3 central se pinta UNA sola celda, no las cinco. Un port con vecindad 8 pinta las cinco.',
    program: [{ name: 'floodFill', params: { x: 1, y: 1, to: 6 } }],
    pre: [
      [3, 0, 3],
      [0, 3, 0],
      [3, 0, 3],
    ],
  },
  {
    name: 'floodFill_pinta_la_region_de_fondo',
    why: 'El origen puede ser una celda de fondo: la region a pintar se define por el COLOR del origen, no por ser foreground.',
    program: [{ name: 'floodFill', params: { x: 0, y: 0, to: 4 } }],
    pre: [
      [0, 0, 0, 0],
      [0, 5, 5, 0],
      [0, 5, 0, 0],
      [0, 0, 0, 0],
    ],
  },
  {
    name: 'floodFill_destino_igual_al_origen_no_cambia_nada',
    why: 'Pintar del color que ya tiene es un no-op observable; sirve para detectar ports que se cuelguen en un ciclo por marcar visitados con el color destino en vez de con un set.',
    program: [{ name: 'floodFill', params: { x: 1, y: 1, to: 5 } }],
    pre: [
      [0, 0, 0],
      [0, 5, 5],
      [0, 5, 5],
    ],
  },
  {
    name: 'floodFill_coordenada_fuera_de_rango_es_no_op',
    why: 'x=5 en una grilla de ancho 3: el guard devuelve un clon sin cambios. Nunca lanza.',
    program: [{ name: 'floodFill', params: { x: 5, y: 0, to: 9 } }],
    pre: [
      [1, 1, 1],
      [1, 2, 1],
      [1, 1, 1],
    ],
  },
  {
    name: 'floodFill_coordenada_negativa_es_no_op',
    why: 'TRAMPA DE PORT: x=-1 debe ser no-op. Python leeria grid[0][-1] (la ultima columna, color 1) y pintaria todo el marco.',
    program: [{ name: 'floodFill', params: { x: -1, y: 0, to: 9 } }],
    pre: [
      [1, 1, 1],
      [1, 2, 1],
      [1, 1, 1],
    ],
  },
  {
    name: 'floodFill_grilla_1x1',
    why: 'Grilla minima con coordenada valida: la unica celda cambia.',
    program: [{ name: 'floodFill', params: { x: 0, y: 0, to: 9 } }],
    pre: [[4]],
  },
  {
    name: 'floodFill_grilla_vacia_es_no_op',
    why: 'Grilla vacia: el guard de rango corta antes de leer nada, aunque las coordenadas sean 0,0.',
    program: [{ name: 'floodFill', params: { x: 0, y: 0, to: 9 } }],
    pre: [],
  },

  // ─── conditionalRecolor ────────────────────────────────────────────────────
  {
    name: 'conditionalRecolor_all_recolorea_todas_las_celdas_del_origen',
    why: "Con predicate 'all' equivale a un recolor de un solo color, sin mirar vecinos.",
    program: [{ name: 'conditionalRecolor', params: { from: 3, to: 7, predicate: 'all' } }],
    pre: [
      [3, 0, 3],
      [0, 3, 0],
      [3, 3, 3],
    ],
  },
  {
    name: 'conditionalRecolor_border_incluye_borde_de_grilla_y_contacto_con_otro_color',
    why: "'border' es la union de dos condiciones distintas: tocar el borde de la grilla O tener un vecino de otro color. El bloque 3x3 centrado tiene su anillo recoloreado y su centro intacto.",
    program: [{ name: 'conditionalRecolor', params: { from: 3, to: 7, predicate: 'border' } }],
    pre: [
      [0, 0, 0, 0, 0],
      [0, 3, 3, 3, 0],
      [0, 3, 3, 3, 0],
      [0, 3, 3, 3, 0],
      [0, 0, 0, 0, 0],
    ],
  },
  {
    name: 'conditionalRecolor_interior_es_el_complemento_exacto_de_border',
    why: 'MISMA grilla que el caso anterior con el predicado opuesto: solo la celda central sobrevive al filtro. Los dos casos juntos prueban que la particion es exacta.',
    program: [{ name: 'conditionalRecolor', params: { from: 3, to: 7, predicate: 'interior' } }],
    pre: [
      [0, 0, 0, 0, 0],
      [0, 3, 3, 3, 0],
      [0, 3, 3, 3, 0],
      [0, 3, 3, 3, 0],
      [0, 0, 0, 0, 0],
    ],
  },
  {
    name: 'conditionalRecolor_border_en_1x1_todo_es_borde',
    why: 'En una grilla 1x1 la unica celda toca los cuatro bordes: el chequeo de borde de grilla dispara ANTES de mirar vecinos, que no existen.',
    program: [{ name: 'conditionalRecolor', params: { from: 3, to: 6, predicate: 'border' } }],
    pre: [[3]],
  },
  {
    name: 'conditionalRecolor_interior_en_1x1_no_cambia_nada',
    why: 'Complemento del anterior: no hay interior posible, asi que la salida es identica a la entrada.',
    program: [{ name: 'conditionalRecolor', params: { from: 3, to: 6, predicate: 'interior' } }],
    pre: [[3]],
  },
  {
    name: 'conditionalRecolor_origen_ausente_es_no_op',
    why: 'Si el color origen no esta en la grilla no se toca nada, sin importar el predicado.',
    program: [{ name: 'conditionalRecolor', params: { from: 9, to: 1, predicate: 'all' } }],
    pre: [
      [2, 2],
      [2, 2],
    ],
  },
  {
    name: 'conditionalRecolor_interior_en_uniforme_3x3_solo_el_centro',
    why: 'TRAMPA DE PORT, la mas fina del fixture: en una grilla uniforme 3x3 el interior es EXACTAMENTE la celda central; las otras ocho tocan el borde de la grilla. Un port que evalue los vecinos sin chequear primero el borde recolorea las nueve, porque en Python los vecinos con indice -1 de las celdas del borde envuelven y devuelven el mismo color.',
    program: [{ name: 'conditionalRecolor', params: { from: 5, to: 1, predicate: 'interior' } }],
    pre: [
      [5, 5, 5],
      [5, 5, 5],
      [5, 5, 5],
    ],
  },
  {
    name: 'conditionalRecolor_border_sobre_franja_no_cuadrada',
    why: 'Grilla 2x6: sin filas interiores, todo es borde. Verifica que el chequeo use w y h reales y no asuma cuadrada.',
    program: [{ name: 'conditionalRecolor', params: { from: 4, to: 2, predicate: 'border' } }],
    pre: [
      [4, 4, 4, 0, 4, 4],
      [4, 0, 4, 4, 4, 4],
    ],
  },
  {
    name: 'conditionalRecolor_grilla_vacia',
    why: 'Grilla vacia: no hay celdas que evaluar y la salida es vacia.',
    program: [{ name: 'conditionalRecolor', params: { from: 1, to: 2, predicate: 'all' } }],
    pre: [],
  },
];
