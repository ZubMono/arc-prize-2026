/* [arc-agi-runner/scripts/mechanicsParityCases] BL.21741 (correccion) -- los CASOS del fixture de
   paridad de la percepcion objeto-centrica. Los consume
   `scripts/generateMechanicsParityFixture.ts`, que calcula el esperado con el motor canonico.

   QUE TIENE QUE CUBRIR. Un caso por cada tipo de `TIPOS_DE_MECANICA` (el generador lo EXIGE) mas
   las dos formas de firma que se pueden confundir entre si: la compuesta INFORMATIVA (al menos un
   tipo nombrado) y la compuesta de SILENCIO (todos los componentes `desconocida`). Esa segunda es
   la que dejo ciego al contador de "transiciones calladas" del experimento del tope.

   GRILLAS CHICAS a proposito: el fixture se lee a ojo cuando un port falla. El tope se ejercita con
   `opciones.maxCeldasCambiadas`, no con una grilla de 4097 celdas. */

import type { Grid } from '../src/worldModel/grid';
import type { OpcionesDeMecanica } from '../src/worldModel/objectMechanics';

export interface CasoDeMecanica {
  /** Identificador ASCII: del otro lado nombra un test parametrizado. */
  name: string;
  /** Que semantica bloquea el caso. Documentacion, no dato. */
  why: string;
  pre: Grid;
  post: Grid;
  /** Mascara de volatilidad, opcional: `true` = celda que se ignora. */
  mask?: boolean[][];
  opciones?: OpcionesDeMecanica;
}

const FONDO = 0;

/** Tablero 8x8 de fondo con las celdas pintadas que se le pidan. */
function tablero(pintadas: Array<[number, number, number]> = []): Grid {
  const grid: Grid = Array.from({ length: 8 }, () => Array.from({ length: 8 }, () => FONDO));
  for (const [y, x, color] of pintadas) grid[y][x] = color;
  return grid;
}

export const todosLosCasos: CasoDeMecanica[] = [
  {
    name: 'sinCambio_dos_grillas_identicas',
    why: 'cero celdas cambiadas es sinCambio y su firma es "sinCambio": es el UNICO cero legitimo',
    pre: tablero([[2, 2, 3]]),
    post: tablero([[2, 2, 3]]),
  },
  {
    name: 'traslacion_bloque_2x2_una_celda_a_la_derecha',
    why: 'la mecanica que mapea una accion a una direccion: la firma lleva el (dy,dx) del objeto',
    pre: tablero([
      [3, 2, 7],
      [3, 3, 7],
      [4, 2, 7],
      [4, 3, 7],
    ]),
    post: tablero([
      [3, 3, 7],
      [3, 4, 7],
      [4, 3, 7],
      [4, 4, 7],
    ]),
  },
  {
    name: 'traslacion_ignora_la_celda_volatil',
    why: 'la mascara de volatilidad (BL.21558) se aplica ANTES de contar cambios en los dos puertos',
    pre: tablero([
      [3, 2, 7],
      [3, 3, 7],
    ]),
    post: (() => {
      const g = tablero([
        [3, 3, 7],
        [3, 4, 7],
      ]);
      g[0][0] = 9; // barra de progreso: fuera del tablero de juego
      return g;
    })(),
    mask: Array.from({ length: 8 }, (_, y) => Array.from({ length: 8 }, () => y === 0)),
  },
  {
    name: 'recoloreo_de_un_bloque_en_el_lugar',
    why: 'un solo par (desde -> hasta) sobre un color que no es el fondo: la firma lleva el par',
    pre: tablero([
      [2, 2, 5],
      [2, 3, 5],
    ]),
    post: tablero([
      [2, 2, 8],
      [2, 3, 8],
    ]),
  },
  {
    name: 'aparicion_sobre_el_fondo',
    why: 'un grupo que nace del fondo: recoleccion/consumo al reves, y no puede confundirse con recoloreo',
    pre: tablero(),
    post: tablero([
      [5, 5, 6],
      [5, 6, 6],
    ]),
  },
  {
    name: 'desaparicion_al_fondo',
    why: 'un grupo que vuelve al fondo. Espejo exacto de la aparicion: el desempate lo da fondoLocal',
    pre: tablero([
      [1, 1, 4],
      [1, 2, 4],
    ]),
    post: tablero(),
  },
  {
    name: 'desconocida_un_cluster_con_dos_pares_de_color',
    why: 'UN cluster con dos pares (desde,hasta) distintos no es una mecanica nombrable: "desconocida" es informacion, inventar un nombre no',
    pre: tablero([
      [4, 4, 3],
      [4, 5, 3],
    ]),
    post: tablero([
      [4, 4, 7],
      [4, 5, 9],
    ]),
  },
  {
    name: 'compuesta_informativa_aparicion_mas_recoloreo',
    why: 'dos clusters de tipos DISTINTOS: la firma compuesta nombra el desglose en vez de colapsar a "desconocida" (BL.21741)',
    pre: tablero([
      [1, 1, 5],
      [1, 2, 5],
    ]),
    post: tablero([
      [1, 1, 8],
      [1, 2, 8],
      [6, 6, 3],
      [6, 7, 3],
    ]),
  },
  {
    name: 'compuesta_de_silencio_todos_los_clusters_sin_nombrar',
    why: 'compuesta cuyo UNICO componente es "desconocida": tiene el prefijo compuesta: y no nombra nada. Es la firma de las dos transiciones de vc33 y la que dejaba ciego al contador de silencio',
    pre: tablero([
      [2, 2, 3],
      [2, 3, 3],
      [6, 6, 4],
      [6, 7, 4],
    ]),
    post: tablero([
      [2, 2, 7],
      [2, 3, 9],
      [6, 6, 1],
      [6, 7, 5],
    ]),
  },
  {
    name: 'sobreElTope_no_analiza_y_lo_dice',
    why: 'por encima del tope el detector NO MIRA y devuelve un tipo propio, nunca "desconocida". El tope se inyecta por opciones para no necesitar una grilla de 4097 celdas',
    pre: tablero([
      [1, 1, 4],
      [1, 2, 4],
      [3, 3, 5],
    ]),
    post: tablero([
      [1, 1, 7],
      [1, 2, 7],
      [3, 3, 8],
    ]),
    opciones: { maxCeldasCambiadas: 2 },
  },
  {
    name: 'formaIncompatible_grillas_que_no_se_pueden_comparar',
    why: 'dos grillas de forma distinta: "ni pude comparar", que NO es "mire y no supe". Sale con celdasCambiadas 0 y ese cero no puede leerse como sinCambio',
    pre: [
      [1, 2],
      [3, 4],
    ],
    post: [[1], [2], [3]],
  },
  {
    name: 'objeto_entero_salta_mas_lejos_que_su_ancho',
    why: 'BL.21853 -- origen y destino quedan DISJUNTOS: son dos clusters y ninguno se explica solo, asi que el analisis por cluster devolvia "desconocida". Es la clase de las 146 transiciones del corpus que la via de objeto entero recupera, y tiene que dar traslacion:0,4 en los dos puertos',
    pre: tablero([
      [2, 1, 3],
      [2, 2, 3],
      [3, 1, 3],
      [3, 2, 3],
    ]),
    post: tablero([
      [2, 5, 3],
      [2, 6, 3],
      [3, 5, 3],
      [3, 6, 3],
    ]),
  },
  {
    name: 'objeto_entero_no_inventa_traslacion_en_tablero_embaldosado',
    why: 'BL.21853 -- el falso positivo del criterio flojo: con la misma forma repetida "alguna coincide desplazada" siempre es cierto. Aca una baldosa cambia de COLOR (no se movio nada) y ningun puerto puede llamarlo traslacion. Sobre el corpus el criterio flojo produce 418 de estos',
    pre: tablero([
      [1, 1, 3],
      [1, 2, 3],
      [1, 5, 3],
      [1, 6, 3],
      [5, 1, 3],
      [5, 2, 3],
    ]),
    post: tablero([
      [1, 1, 3],
      [1, 2, 3],
      [1, 5, 8],
      [1, 6, 8],
      [5, 1, 3],
      [5, 2, 3],
    ]),
  },
];
