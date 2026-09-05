/* [arc-agi-runner/scripts/dslParityCases/objetos] BL.20860 -- casos de paridad de objectExtract,
   el primitivo con mas semantica implicita del DSL y el que mas facil se porta "casi bien".

   Cuatro reglas que ningun test de una sola grilla revela y que estos casos fijan por separado:

   1) Un componente es MONO-COLOR y 4-conexo. Dos celdas vecinas de colores distintos son objetos
      DISTINTOS, no uno solo. floodRegion compara contra el color del origen, no contra "no es
      fondo".

   2) El fondo se DETECTA (color mas frecuente, desempate por color menor) y las celdas de fondo
      nunca forman componente. Corolario poco obvio: pedir explicitamente el color del fondo
      devuelve CERO componentes y por lo tanto un no-op, no la grilla entera.

   3) El desempate para elegir el objeto es total y deterministico, en este orden: mayor cantidad
      de celdas, luego menor minY, luego menor minX. Ese orden es contrato -- la sintesis de
      programas y la memoria de transiciones dependen de que dos corridas (y dos lenguajes) elijan
      el MISMO objeto. Hay un caso dedicado por cada nivel de desempate.

   4) El recorte se hace sobre el BBOX del objeto elegido, y las celdas del bbox que pertenecen a
      OTRO objeto (o al fondo) se rellenan con fondo. No se copia la region tal cual. */

import type { CasoParidad } from './tipos';

export const casosObjetos: CasoParidad[] = [
  {
    name: 'objectExtract_sin_color_elige_el_componente_mas_grande',
    why: 'Caso base sin filtro de color: gana el objeto con MAS celdas (el bloque de 2, con 4 celdas) sobre el de 3 con 2 celdas.',
    program: [{ name: 'objectExtract', params: {} }],
    pre: [
      [0, 0, 0, 0, 0],
      [0, 2, 2, 0, 0],
      [0, 2, 2, 0, 0],
      [0, 0, 0, 3, 0],
      [0, 0, 0, 3, 0],
    ],
  },
  {
    name: 'objectExtract_con_color_ignora_los_demas_objetos',
    why: 'MISMA grilla que el caso anterior pidiendo el color 3: el filtro se aplica ANTES del ranking, asi que gana un objeto que de otro modo perderia por tamano.',
    program: [{ name: 'objectExtract', params: { color: 3 } }],
    pre: [
      [0, 0, 0, 0, 0],
      [0, 2, 2, 0, 0],
      [0, 2, 2, 0, 0],
      [0, 0, 0, 3, 0],
      [0, 0, 0, 3, 0],
    ],
  },
  {
    name: 'objectExtract_empate_de_tamano_gana_el_de_menor_minY',
    why: 'DESEMPATE NIVEL 2: dos objetos de 2 celdas; gana el que empieza mas arriba (el 4, en y=0). Un port que no ordene por minY puede devolver el 5 segun el orden de enumeracion.',
    program: [{ name: 'objectExtract', params: {} }],
    pre: [
      [0, 4, 0, 0],
      [0, 4, 0, 0],
      [0, 0, 0, 0],
      [0, 0, 5, 0],
      [0, 0, 5, 0],
    ],
  },
  {
    name: 'objectExtract_empate_de_tamano_y_de_minY_gana_el_de_menor_minX',
    why: 'DESEMPATE NIVEL 3: dos objetos de 2 celdas que arrancan en la MISMA fila; decide la columna. Es el ultimo criterio, y sin el la eleccion quedaria a merced del orden del sort.',
    program: [{ name: 'objectExtract', params: {} }],
    pre: [
      [6, 0, 0, 7],
      [6, 0, 0, 7],
    ],
  },
  {
    name: 'objectExtract_rellena_con_fondo_lo_que_no_pertenece_al_objeto',
    why: 'Objeto en L: el bbox es 2x2 pero el objeto tiene 3 celdas. La celda restante sale con el color de FONDO, no con lo que hubiera en la grilla original.',
    program: [{ name: 'objectExtract', params: {} }],
    pre: [
      [0, 0, 0, 0],
      [0, 8, 0, 0],
      [0, 8, 8, 0],
      [0, 0, 0, 0],
    ],
  },
  {
    name: 'objectExtract_colores_adyacentes_distintos_son_componentes_separados',
    why: 'Dos columnas pegadas de colores distintos NO son un objeto de 4 celdas: son dos de 2. El empate lo resuelve minX y gana la columna de 1. Un port que agrupe por "todo lo que no es fondo" devuelve una grilla 2x2 con los dos colores.',
    program: [{ name: 'objectExtract', params: {} }],
    pre: [
      [0, 0, 0, 0],
      [0, 1, 2, 0],
      [0, 1, 2, 0],
      [0, 0, 0, 0],
    ],
  },
  {
    name: 'objectExtract_conectividad_4_no_une_diagonales',
    why: 'La celda diagonal suelta queda fuera del objeto grande: con vecindad 8 seria un unico componente de 4 celdas y el bbox cambiaria. El relleno de fondo en la esquina del bbox es la firma del resultado correcto.',
    program: [{ name: 'objectExtract', params: {} }],
    pre: [
      [0, 0, 0, 0],
      [0, 3, 0, 0],
      [0, 0, 3, 0],
      [0, 3, 3, 0],
    ],
  },
  {
    name: 'objectExtract_sin_componentes_es_no_op',
    why: 'Grilla uniforme: todo es fondo, no hay ningun componente y se devuelve la grilla entera sin cambios (no una grilla vacia).',
    program: [{ name: 'objectExtract', params: {} }],
    pre: [
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ],
  },
  {
    name: 'objectExtract_color_inexistente_es_no_op',
    why: 'Pedir un color que no esta en la grilla no es un error: el filtro deja cero componentes y sale un clon.',
    program: [{ name: 'objectExtract', params: { color: 9 } }],
    pre: [
      [0, 0, 0],
      [0, 5, 0],
      [0, 0, 0],
    ],
  },
  {
    name: 'objectExtract_color_igual_al_fondo_es_no_op',
    why: 'CONSECUENCIA NO OBVIA: el filtro de fondo corre ANTES que el de color, asi que pedir el color del fondo da cero componentes -> no-op. Un port que invierta ese orden devolveria el bbox del fondo.',
    program: [{ name: 'objectExtract', params: { color: 0 } }],
    pre: [
      [0, 0, 0],
      [0, 5, 0],
      [0, 0, 0],
    ],
  },
  {
    name: 'objectExtract_desempate_de_fondo_en_grilla_1x2',
    why: 'Grilla minima con empate de frecuencia: 0 y 5 aparecen una vez cada uno, gana 0 como fondo por ser el color menor, asi que el objeto es el 5. Si el port eligiera 5 como fondo, el resultado seria [[0]].',
    program: [{ name: 'objectExtract', params: {} }],
    pre: [[0, 5]],
  },
  {
    name: 'objectExtract_grilla_vacia_es_no_op',
    why: 'Grilla vacia: cero componentes, clon vacio, sin excepciones al calcular el bbox.',
    program: [{ name: 'objectExtract', params: {} }],
    pre: [],
  },
];
