/* [arc-agi-runner/scripts/dslParityCases/composicion] BL.20860 -- casos de paridad de programas de
   2 y 3 pasos.

   Componer no es solo "correr los primitivos en orden": hay dos propiedades del pipeline que
   ningun caso de un solo paso puede detectar y que estos casos existen para bloquear.

   PRIMERA: el fondo se re-detecta en CADA paso, sobre la grilla intermedia, nunca sobre la
   entrada original. Un port que calcule el fondo una vez al principio (una optimizacion que
   parece obvia) pasa todos los casos unitarios y falla solo aca. El caso
   `recolor_cambia_el_fondo_del_translate_siguiente` esta construido para que el recolor de en
   medio invierta el desempate de frecuencia y el translate posterior rellene con OTRO color.

   SEGUNDA: el contexto (la grilla ancla de overlay) es del PROGRAMA, no del paso: no se recalcula
   ni se reemplaza por la grilla intermedia. `overlay_despues_de_translate` lo fija.

   Ademas hay dos invariantes algebraicas (doble reflejo, cuatro cuartos de giro) que valen como
   red de seguridad barata: si el port las rompe, el error esta en la orientacion y no en el
   encadenado. */

import type { CasoParidad } from './tipos';

export const casosComposicion: CasoParidad[] = [
  {
    name: 'composicion_programa_vacio_es_identidad',
    why: 'Un programa sin pasos devuelve un CLON de la entrada. Es el caso base del reduce y el unico donde el resultado no pasa por ningun primitivo.',
    program: [],
    pre: [
      [1, 2],
      [3, 4],
    ],
  },
  {
    name: 'composicion_rotate1_luego_reflect_horizontal',
    why: 'Dos pasos que cambian la forma: 2x3 -> 3x2 y el reflejo opera sobre la grilla YA rotada. Invertir el orden da otro resultado.',
    program: [
      { name: 'rotate', params: { quarterTurns: 1 } },
      { name: 'reflect', params: { axis: 'horizontal' } },
    ],
    pre: [
      [1, 2, 3],
      [4, 5, 6],
    ],
  },
  {
    name: 'composicion_translate_negativo_luego_recolor',
    why: 'El recolor final incluye el color de fondo, asi que tine tambien las celdas que el translate acaba de rellenar: el segundo paso ve el resultado del primero, no la entrada.',
    program: [
      { name: 'translate', params: { dx: -1, dy: 0 } },
      { name: 'recolor', params: { mapping: { 7: 2, 0: 3 } } },
    ],
    pre: [
      [0, 0, 0],
      [0, 7, 0],
      [0, 0, 0],
    ],
  },
  {
    name: 'composicion_recolor_cambia_el_fondo_del_translate_siguiente',
    why: 'CASO CLAVE DEL FIXTURE: antes del recolor el fondo es 1 (empate 1/4 resuelto por color menor); despues del recolor 1->7 el empate pasa a ser 4/7 y el fondo es 4. El relleno del translate delata cual de los dos se uso. Un port que detecte el fondo una sola vez falla solo aca.',
    program: [
      { name: 'recolor', params: { mapping: { 1: 7 } } },
      { name: 'translate', params: { dx: 1, dy: 0 } },
    ],
    pre: [
      [1, 1, 4],
      [1, 4, 4],
    ],
  },
  {
    name: 'composicion_cropToBBox_luego_replicate',
    why: 'El replicate tesela la grilla RECORTADA (2x2), no la original (4x4): las dimensiones intermedias son parte del contrato.',
    program: [
      { name: 'cropToBBox', params: { backgroundColor: 0 } },
      { name: 'replicate', params: { timesX: 2, timesY: 1 } },
    ],
    pre: [
      [0, 0, 0, 0],
      [0, 1, 2, 0],
      [0, 3, 4, 0],
      [0, 0, 0, 0],
    ],
  },
  {
    name: 'composicion_objectExtract_luego_rotate2',
    why: 'El objeto en L se extrae con su relleno de fondo y recien despues se gira: el 180 tiene que caer sobre la grilla 2x2, no sobre la 4x4.',
    program: [
      { name: 'objectExtract', params: {} },
      { name: 'rotate', params: { quarterTurns: 2 } },
    ],
    pre: [
      [0, 0, 0, 0],
      [0, 8, 0, 0],
      [0, 8, 8, 0],
      [0, 0, 0, 0],
    ],
  },
  {
    name: 'composicion_overlay_despues_de_translate_usa_el_ancla_del_contexto',
    why: 'El ancla NO se actualiza entre pasos: el overlay ve la grilla ya desplazada como "actual" pero sigue usando el ancla original del contexto. La celda 5 sobrevive en su posicion nueva y todo el resto viene del ancla.',
    program: [
      { name: 'translate', params: { dx: 1, dy: 0 } },
      { name: 'overlay', params: {} },
    ],
    pre: [
      [0, 0, 0],
      [0, 5, 0],
      [0, 0, 0],
    ],
    anchor: [
      [1, 2, 3],
      [4, 5, 6],
      [7, 8, 9],
    ],
  },
  {
    name: 'composicion_doble_reflejo_vertical_es_identidad',
    why: 'Invariante algebraica barata: reflejar dos veces por el mismo eje devuelve la entrada exacta. Si falla, el bug es de orientacion y no de encadenado.',
    program: [
      { name: 'reflect', params: { axis: 'vertical' } },
      { name: 'reflect', params: { axis: 'vertical' } },
    ],
    pre: [
      [1, 2],
      [3, 4],
      [5, 6],
    ],
  },
  {
    name: 'composicion3_rotate_translate_recolor',
    why: 'Tres pasos de familias distintas (forma, posicion, color) sobre una grilla asimetrica: cualquier permutacion del orden produce un resultado distinto.',
    program: [
      { name: 'rotate', params: { quarterTurns: 2 } },
      { name: 'translate', params: { dx: 0, dy: 1 } },
      { name: 'recolor', params: { mapping: { 3: 5, 2: 6 } } },
    ],
    pre: [
      [0, 0, 1],
      [0, 2, 0],
      [3, 0, 0],
    ],
  },
  {
    name: 'composicion3_reflect_floodFill_conditionalRecolor',
    why: 'El floodFill usa coordenadas ABSOLUTAS sobre la grilla ya reflejada: apunta a (3,0), que solo tiene color 1 despues del espejo. Un port que reflejara despues pintaria la region equivocada.',
    program: [
      { name: 'reflect', params: { axis: 'horizontal' } },
      { name: 'floodFill', params: { x: 3, y: 0, to: 5 } },
      { name: 'conditionalRecolor', params: { from: 5, to: 9, predicate: 'border' } },
    ],
    pre: [
      [1, 1, 0, 0],
      [1, 1, 0, 0],
      [0, 0, 0, 0],
      [0, 0, 0, 2],
    ],
  },
  {
    name: 'composicion3_cropToBBox_replicate_reflect',
    why: 'Cadena que encoge, agranda y espeja: cada paso cambia las dimensiones o el orden, asi que un off-by-one en cualquiera de los tres se propaga hasta el final.',
    program: [
      { name: 'cropToBBox', params: { backgroundColor: 0 } },
      { name: 'replicate', params: { timesX: 2, timesY: 1 } },
      { name: 'reflect', params: { axis: 'horizontal' } },
    ],
    pre: [
      [0, 0, 0, 0],
      [0, 1, 2, 0],
      [0, 0, 3, 0],
      [0, 0, 0, 0],
    ],
  },
  {
    name: 'composicion3_objectExtract_replicate_rotate',
    why: 'El fondo que objectExtract mete en el hueco de la L se tesela y despues se gira: verifica que ese relleno sea parte del objeto extraido y no un artefacto descartable.',
    program: [
      { name: 'objectExtract', params: {} },
      { name: 'replicate', params: { timesX: 1, timesY: 2 } },
      { name: 'rotate', params: { quarterTurns: 1 } },
    ],
    pre: [
      [0, 0, 0, 0],
      [0, 8, 0, 0],
      [0, 8, 8, 0],
      [0, 0, 0, 0],
    ],
  },
  {
    name: 'composicion3_cuatro_cuartos_de_giro_es_identidad',
    why: 'Segunda invariante algebraica: 1+1+2 cuartos = 360 grados sobre una grilla no cuadrada, que ademas obliga a que las dimensiones vuelvan a 2x3 pasando por 3x2.',
    program: [
      { name: 'rotate', params: { quarterTurns: 1 } },
      { name: 'rotate', params: { quarterTurns: 1 } },
      { name: 'rotate', params: { quarterTurns: 2 } },
    ],
    pre: [
      [1, 2, 3],
      [4, 5, 6],
    ],
  },
];
