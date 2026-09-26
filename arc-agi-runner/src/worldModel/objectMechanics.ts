/* [arc-agi-runner/worldModel/objectMechanics] BL.21561 -- analizador de mecanicas OBJETO-CENTRICO.
   REEMPLAZA a `proposeAllSteps` (primitives.ts) como el analizador que alimenta
   `TransitionMemory.recordObservation`: en vez de preguntar "que funcion grilla->grilla explica el
   par", pregunta "que le paso a los OBJETOS".

   POR QUE. Medido sobre 1.569 pasos reales de ARC-AGI-3, el DSL global confirmo regla en 253 pasos
   y las 253 son la IDENTIDAD -- cero reglas no triviales. Las causas son estructurales, no de
   presupuesto: `proposeTranslate` usa el bbox GLOBAL del foreground, que las paredes del tablero
   fijan (dx=dy=0 siempre); `proposeRecolor` exige un mapping color->color consistente en TODA la
   grilla, y un objeto que se mueve pide mapear fondo->jugador y jugador->fondo a la vez;
   `proposeFloodFill`/`proposeConditionalRecolor` exigen UN color origen y UNO destino sobre el
   diff, y un movimiento tiene dos. Ninguna profundidad de busqueda arregla eso: la respuesta no
   esta en ese espacio.

   QUE DETECTA (todo parametrico sobre objetos y deltas, NUNCA sobre game_id -- generaliza por
   construccion):
   1. traslacion  -- una region acotada se movio (dy,dx) conservando su contenido: cursor/jugador.
      Es lo que mapea ACTION1..5 a direcciones.
   2. recoloreo   -- un grupo de celdas cambio de color en el lugar: toggle/pintado.
   3. aparicion / desaparicion -- un grupo aparecio sobre el fondo o volvio al fondo:
      recoleccion/consumo.
   Los detectores 4 (marco/HUD estatico) y 5 (contador monotono) son de EPISODIO y no de
   transicion: viven en mechanicsMemory.ts.

   MEDIDO SOBRE DATO REAL (`__fixtures__/volatilityRealGames.json`, 4 partidas contra la API
   oficial): detecta cursor en los 4 juegos y recupera el mapeo canonico de direcciones sin una
   sola contradiccion -- ka59 y ar25 con ACTION1=arriba ACTION2=abajo ACTION3=izquierda
   ACTION4=derecha de paso 3; dc22 lo mismo con paso 2; lf52 la unica traslacion de la partida
   (ACTION6, dx=+6). Ver `__tests__/bl21561.realGames.effect.test.ts`. */

import { isVolatileCell, type BoundingBox, type Grid, type VolatilityMask } from './grid';
import {
  agruparEnClusters,
  cajaDeCeldas,
  coberturaDeObjetos,
  fondoLocal,
  traslacionDeObjetoEntero,
  type Celda,
} from './objectGeometry';

/** Area maxima del bbox de un cluster de cambios que se analiza. Por encima, el "objeto" seria
 *  medio tablero y la hipotesis de traslacion rigida no describe nada -- se declara desconocida y
 *  se ahorra el barrido cuadratico. */
export const MAX_AREA_CAJA_DE_CAMBIOS = 4096;

/** Tope de celdas cambiadas analizadas en una transicion. Por encima, `detectarMecanica` NO
 *  ANALIZA y lo dice con un tipo propio (`sobreElTope`), nunca con `desconocida`.
 *
 *  EL NUMERO SALE DE UN EXPERIMENTO (BL.21741), no de ser redondo. 2048 -- la mitad exacta de una
 *  grilla 64x64 -- venia de BL.21561 sin medicion detras. Medido con
 *  `arc-agi3-kaggle-agent/scripts/medir_tope_de_mecanica.py` sobre el corpus persistido de subidas
 *  de nivel (8 transiciones distintas, 6 juegos, sha256 86ec7f5ffe39), cuantas quedan con firmas
 *  DIFERENTES entre si segun el corte, y cuantas quedan CALLADAS (firma que no nombra ninguna
 *  mecanica, contada con `esFirmaDeSilencio` -- que mira dentro de `compuesta:`):
 *    tope 1024 -> 3 firmas distintas | 6 transiciones calladas
 *    tope 2048 -> 5 firmas distintas | 4 calladas   <- el corte historico
 *    tope 3072 -> 7 firmas distintas | 3 calladas
 *    tope 4096 -> 7 firmas distintas | 2 calladas   <- este
 *  4096 es la grilla 64x64 ENTERA: con este corte `sobreElTope` no puede dispararse en ARC-AGI-3
 *  (hace falta cambiar 4097 celdas de 4096) y el detector MIRA siempre. Las 2 transiciones que
 *  siguen calladas son las de vc33, y ya no las calla el tope: el detector las mira y no sabe
 *  nombrarlas (`compuesta:desconocida=1`), asi que subir mas el tope no compra nada.
 *  COSTO MEDIDO (272 pares consecutivos del corpus, minimo de repeticiones interleaved): el
 *  sobrecosto NO esta repartido -- 266 de los 272 pares recorren el MISMO camino con los dos topes
 *  y miden igual; los 6 que cruzan el corte cuestan ~84 ms cada uno, o sea +40-55% sobre el costo
 *  por accion (0,154-0,202 s) y SOLO en el frame de la subida de nivel. Amortizado sobre la
 *  partida son ~1,8 ms/paso contra un presupuesto entregado de 8,0 h. */
export const MAX_CELDAS_CAMBIADAS = 4096;

/** `k` del enunciado: tamano maximo (en celdas) de la caja que puede ser un OBJETO. Los cursores
 *  de los juegos medidos miden 4-27 celdas; 256 deja margen sin admitir "medio tablero se movio". */
export const MAX_TAMANO_OBJETO = 256;

/** Evidencia minima (0-1) para aceptar una hipotesis de traslacion. Se mide de dos formas
 *  independientes y alcanza con UNA (ver `traslacionDeCluster`). */
export const MIN_EVIDENCIA_DE_OBJETO = 0.5;

/** Los tipos que `detectarMecanica` puede devolver. Es una LISTA y no solo una union de tipos
 *  porque hay consumidores que la recorren en tiempo de ejecucion -- el generador del fixture de
 *  paridad exige un caso por tipo, para que agregar un tipo al motor sin caso que lo fije falle el
 *  build. Espejo de `TIPOS_DE_MECANICA` (Python). */
export const TIPOS_DE_MECANICA = [
  'sinCambio',
  'traslacion',
  'recoloreo',
  'aparicion',
  'desaparicion',
  'desconocida',
  // BL.21741 -- los dos casos de "NO MIRE", que hasta ese BL se confundian con "mire y no
  // encontre". El silencio del detector se leia como quietud.
  'sobreElTope',
  'formaIncompatible',
] as const;

export type TipoMecanica = (typeof TIPOS_DE_MECANICA)[number];

/** Los tipos que significan "NO MIRE" -- el detector no analizo los clusters, ni bien ni mal.
 *  FUENTE UNICA (BL.21741) para cualquier consumidor que distinga "no paso nada" de "no se". */
export const TIPOS_DE_NO_MIRE = ['sobreElTope', 'formaIncompatible'] as const;

/** El unico tipo cuyo `celdasCambiadas` NO ES UNA MEDICION sino la ausencia de una.
 *
 *  POR QUE ESTA SEPARADO DE `TIPOS_DE_NO_MIRE` (BL.21741). `sobreElTope` no analizo los CLUSTERS
 *  pero conto las celdas antes de rendirse, y ese conteo es exacto: un consumidor que solo mira el
 *  TAMANO del cambio (la firma `cambioDeEscena` de `IncognitaDeMecanica`) sigue teniendo dato
 *  bueno. `formaIncompatible` sale con `celdasCambiadas === 0` sin haber contado nada, y ese cero
 *  es indistinguible del cero legitimo de `sinCambio`: los dos consumidores que deciden si una
 *  accion es INERTE (`eventoSinTraslacion` e `IncognitaDeMecanica.clasificar`, directionBeliefs.ts)
 *  preguntaban `celdasCambiadas === 0`, o sea que "ni pude comparar las grillas" alimentaba la
 *  evidencia de que el boton no hace nada -- la inferencia OPUESTA a la correcta. */
export const TIPO_SIN_MEDICION = 'formaIncompatible';

/** Traslacion rigida detectada: la caja `[minY..minY+alto-1] x [minX..minX+ancho-1]` de `pre`
 *  reaparece intacta en `post` desplazada (dy,dx). */
export interface Traslacion {
  dy: number;
  dx: number;
  minY: number;
  minX: number;
  alto: number;
  ancho: number;
  /** Fraccion de la caja cubierta por componentes 4-conexas enteramente contenidas en ella. */
  cobertura: number;
  /** Fraccion de las celdas desalojadas que quedaron con el color del fondo local. */
  relleno: number;
}

export interface CambioDeColor {
  desde: number;
  hasta: number;
  celdas: number;
}

export interface MecanicaDeCluster {
  tipo: Exclude<TipoMecanica, 'sinCambio'>;
  celdas: number;
  caja: BoundingBox;
  traslacion: Traslacion | null;
  cambioDeColor: CambioDeColor | null;
}

export interface Mecanica {
  tipo: TipoMecanica;
  celdasCambiadas: number;
  clusters: MecanicaDeCluster[];
  /** Traslacion del objeto mas grande -- la que mapea la accion a una direccion. */
  traslacionPrincipal: Traslacion | null;
  /** Cambio de color dominante cuando el paso no es una traslacion. */
  cambioDeColorPrincipal: CambioDeColor | null;
}

export interface OpcionesDeMecanica {
  maxTamanoObjeto?: number;
  minEvidencia?: number;
  /** Tope de celdas cambiadas de ESTA llamada. Existe para que el experimento del tope y el
   *  fixture de paridad puedan moverlo sin parchear la constante del modulo (que es lo que hacia
   *  `medir_tope_de_mecanica.py`: sustituir el atributo global y restaurarlo en un `finally`).
   *  Por defecto, `MAX_CELDAS_CAMBIADAS`. */
  maxCeldasCambiadas?: number;
}

/** Detecta que le paso a los objetos entre `pre` y `post`, ignorando las celdas volatiles
 *  (BL.21558: la barra de progreso avanza una celda por paso y no es una mecanica de tablero).
 *  Nunca lanza: ante dos grillas que ni siquiera se pueden comparar devuelve `formaIncompatible`, y
 *  por encima de `MAX_CELDAS_CAMBIADAS` devuelve `sobreElTope` sin analizar (BL.21741). Ninguno de
 *  los dos es `desconocida`, que significa "mire los clusters y no supe nombrarlos". */
export function detectarMecanica(
  pre: Grid,
  post: Grid,
  mask: VolatilityMask | null = null,
  opciones: OpcionesDeMecanica = {},
): Mecanica {
  const maxTamanoObjeto = opciones.maxTamanoObjeto ?? MAX_TAMANO_OBJETO;
  const minEvidencia = opciones.minEvidencia ?? MIN_EVIDENCIA_DE_OBJETO;
  const maxCeldasCambiadas = opciones.maxCeldasCambiadas ?? MAX_CELDAS_CAMBIADAS;

  // BL.21741: NO es "desconocida". "Desconocida" significa "mire los clusters y no supe
  // nombrarlos"; esto significa "ni siquiera pude comparar las dos grillas".
  if (!mismaForma(pre, post)) return mecanicaVacia(TIPO_SIN_MEDICION, 0);

  const cambios: Celda[] = [];
  for (let y = 0; y < pre.length; y++) {
    const fila = pre[y];
    for (let x = 0; x < fila.length; x++) {
      if (fila[x] !== post[y][x] && !isVolatileCell(mask, y, x)) cambios.push([y, x]);
    }
  }
  if (cambios.length === 0) return mecanicaVacia('sinCambio', 0);
  // BL.21741: tipo PROPIO. Devolver "desconocida" aca hacia que "no mire porque cambio demasiado"
  // fuera indistinguible de "mire y no encontre" -- y como la transicion de nivel es siempre el
  // frame que mas cambia, el detector callaba justo donde se decide el score.
  if (cambios.length > maxCeldasCambiadas) return mecanicaVacia('sobreElTope', cambios.length);

  let clusters = agruparEnClusters(cambios).map((grupo) =>
    clasificarCluster(pre, post, grupo, maxTamanoObjeto, minEvidencia),
  );

  let conTraslacion = clusters.filter((c) => c.traslacion !== null);
  if (conTraslacion.length === 0 && clusters.length > 1) {
    /* Un objeto que se mueve MENOS que su propio ancho deja dos regiones cambiadas separadas por la
       parte que se solapa y no cambio (un 2x2 que avanza una celda cambia la columna que abandona
       y la que ocupa, y la del medio queda igual). Son dos clusters y ninguno se explica solo, pero
       la union si. Se intenta recien como respaldo: sobre las partidas reales el analisis por
       cluster ya resuelve todo, y fusionar de entrada juntaria eventos independientes. */
    const fusionado = clasificarCluster(pre, post, cambios, maxTamanoObjeto, minEvidencia);
    if (fusionado.traslacion !== null) {
      clusters = [fusionado];
      conTraslacion = [fusionado];
    }
  }
  /* BL.21853 -- ULTIMO respaldo: el objeto ENTERO. Las dos vias de arriba despejan la caja `R` del
     bbox del CLUSTER, asi que solo ven al objeto que se mueve menos que su propio ancho, y acotan
     `R` por AREA (256): un objeto de 153 celdas en una caja de 17x17 no entra aunque el objeto sea
     chico. Medido sobre las 7.258 transiciones de `arcReplayFrames`: 146 (2,01%) --de DOS juegos
     de los 27 con transiciones, o sea una medicion en dos escenas y no una propiedad del corpus--
     son traslaciones rigidas CARDINALES de objetos de 53 y 153 celdas que hoy caen en
     `desconocida`. Va TERCERA: si una de las dos vias anteriores ya explico el paso, esta ni se
     llama. ALCANCE EXACTO, que no es
     "solo toca `desconocida`": estructuralmente tambien puede reetiquetar un paso cuyo tipo global
     era `recoloreo`/`aparicion`/`desaparicion`. Sobre el corpus NO paso -- las 146 salen las 146 de
     `desconocida` -- pero la guarda no lo impide. */
  let traslacionEntera: Traslacion | null = null;
  if (conTraslacion.length === 0) {
    const fondoDelCambio = fondoLocal(pre, cambios, cajaDeCeldas(cambios));
    const entera = traslacionDeObjetoEntero(pre, post, cambios, fondoDelCambio, mask);
    if (entera !== null) {
      const cajaObj = cajaDeCeldas(entera.objeto);
      const altoObj = cajaObj.maxY - cajaObj.minY + 1;
      const anchoObj = cajaObj.maxX - cajaObj.minX + 1;
      /* `cobertura` y `relleno` NO se miden igual que en `traslacionDeCluster`, y decirlo importa:
         alla son las dos evidencias que rompen la ambiguedad objeto/hueco, aca esa ambiguedad ya la
         rompio la RECONSTRUCCION exacta (que es mas fuerte que las dos). `cobertura` es la fraccion
         de la caja que ocupa el objeto y `relleno` es 1.0 porque la reconstruccion exigio el fondo
         en cada celda desalojada -- salvo las VOLATILES, que saltea: el 1.0 es exacto solo fuera
         de la mascara. */
      traslacionEntera = {
        dy: entera.dy,
        dx: entera.dx,
        minY: cajaObj.minY,
        minX: cajaObj.minX,
        alto: altoObj,
        ancho: anchoObj,
        cobertura: entera.objeto.length / (altoObj * anchoObj),
        relleno: 1.0,
      };
    }
  }

  conTraslacion.sort((a, b) => {
    const ta = a.traslacion as Traslacion;
    const tb = b.traslacion as Traslacion;
    return tb.alto * tb.ancho - ta.alto * ta.ancho || ta.minY - tb.minY || ta.minX - tb.minX;
  });

  let tipo: TipoMecanica;
  if (conTraslacion.length > 0 || traslacionEntera !== null) {
    tipo = 'traslacion';
  } else {
    const tipos = new Set(clusters.map((c) => c.tipo));
    tipo = tipos.size === 1 ? (clusters[0].tipo as TipoMecanica) : 'desconocida';
  }

  const conColor = clusters
    .filter((c) => c.cambioDeColor !== null)
    .sort(
      (a, b) =>
        (b.cambioDeColor as CambioDeColor).celdas - (a.cambioDeColor as CambioDeColor).celdas,
    );

  return {
    tipo,
    celdasCambiadas: cambios.length,
    clusters,
    traslacionPrincipal: conTraslacion[0]?.traslacion ?? traslacionEntera,
    cambioDeColorPrincipal: conColor[0]?.cambioDeColor ?? null,
  };
}

function mecanicaVacia(tipo: TipoMecanica, celdasCambiadas: number): Mecanica {
  return {
    tipo,
    celdasCambiadas,
    clusters: [],
    traslacionPrincipal: null,
    cambioDeColorPrincipal: null,
  };
}

function mismaForma(a: Grid, b: Grid): boolean {
  if (a.length !== b.length) return false;
  for (let y = 0; y < a.length; y++) if (a[y].length !== b[y].length) return false;
  return a.length > 0 && a[0].length > 0;
}

function clasificarCluster(
  pre: Grid,
  post: Grid,
  grupo: Celda[],
  maxTamanoObjeto: number,
  minEvidencia: number,
): MecanicaDeCluster {
  const caja = cajaDeCeldas(grupo);
  const traslacion = traslacionDeCluster(pre, post, grupo, caja, maxTamanoObjeto, minEvidencia);
  if (traslacion !== null) {
    return { tipo: 'traslacion', celdas: grupo.length, caja, traslacion, cambioDeColor: null };
  }

  /* Sin traslacion: el cluster entero tiene que ser UN solo par (desde -> hasta) para llamarse
     mecanica. Dos pares distintos en el mismo cluster son un cambio compuesto que este analizador
     no pretende nombrar -- decir "desconocida" es informacion; inventar un nombre, no. */
  const desde = pre[grupo[0][0]][grupo[0][1]];
  const hasta = post[grupo[0][0]][grupo[0][1]];
  for (const [y, x] of grupo) {
    if (pre[y][x] !== desde || post[y][x] !== hasta) {
      return {
        tipo: 'desconocida',
        celdas: grupo.length,
        caja,
        traslacion: null,
        cambioDeColor: null,
      };
    }
  }

  const fondo = fondoLocal(pre, grupo, caja);
  const cambioDeColor: CambioDeColor = { desde, hasta, celdas: grupo.length };
  const tipo: MecanicaDeCluster['tipo'] =
    desde === fondo ? 'aparicion' : hasta === fondo ? 'desaparicion' : 'recoloreo';
  return { tipo, celdas: grupo.length, caja, traslacion: null, cambioDeColor };
}

/** Busca una caja `R` de `pre` y un desplazamiento `d != 0` tales que `post[R+d] === pre[R]` y todo
 *  cambio del cluster caiga dentro de `R U (R+d)`.
 *
 *  LA AMBIGUEDAD QUE HAY QUE ROMPER (medida en dato real, no teorica): cuando un objeto se mueve a
 *  un hueco vacio, la hipotesis simetrica "el HUECO se movio en sentido contrario" satisface las
 *  MISMAS ecuaciones y devuelve la direccion INVERTIDA -- con la version ingenua, dc22 daba
 *  ACTION2=arriba y ACTION4=izquierda en un tercio de los pasos. Se rompe con dos evidencias
 *  independientes de que lo que se movio es un OBJETO y no un recorte del fondo:
 *  - `cobertura`: fraccion de `R` ocupada por componentes 4-conexas contenidas en la caja.
 *  - `relleno`: fraccion de celdas desalojadas que quedaron del color del fondo local (un objeto
 *    que se va deja piso; un "hueco que se va" deja el objeto encima, que no es piso).
 *  Alcanza con UNA por encima del umbral: hay objetos articulados (ar25 mueve un cuerpo de 27
 *  celdas cuya componente se extiende fuera de la caja) que solo pasan por relleno, y tableros con
 *  fondo texturado (lf52) donde el relleno no es uniforme y solo pasan por cobertura. */
function traslacionDeCluster(
  pre: Grid,
  post: Grid,
  grupo: Celda[],
  caja: BoundingBox,
  maxTamanoObjeto: number,
  minEvidencia: number,
): Traslacion | null {
  const altoCaja = caja.maxY - caja.minY + 1;
  const anchoCaja = caja.maxX - caja.minX + 1;
  if (altoCaja * anchoCaja > MAX_AREA_CAJA_DE_CAMBIOS) return null;

  const alto = pre.length;
  const ancho = pre[0].length;
  const fondo = fondoLocal(pre, grupo, caja);
  const candidatas: Traslacion[] = [];

  for (let dy = -(altoCaja - 1); dy <= altoCaja - 1; dy++) {
    for (let dx = -(anchoCaja - 1); dx <= anchoCaja - 1; dx++) {
      if (dy === 0 && dx === 0) continue;
      /* `R U (R+d)` tiene exactamente el bbox del cluster, asi que `R` se despeja del bbox y de d
         sin buscar: el desplazamiento come |dy| filas y |dx| columnas del lado hacia el que va. */
      const r: BoundingBox = {
        minY: caja.minY - Math.min(0, dy),
        maxY: caja.maxY - Math.max(0, dy),
        minX: caja.minX - Math.min(0, dx),
        maxX: caja.maxX - Math.max(0, dx),
      };
      if (r.minY > r.maxY || r.minX > r.maxX) continue;
      if ((r.maxY - r.minY + 1) * (r.maxX - r.minX + 1) > maxTamanoObjeto) continue;

      if (!contenidoSeMovio(pre, post, r, dy, dx, alto, ancho)) continue;
      if (!cambiosDentroDeLaUnion(grupo, r, dy, dx)) continue;

      const cobertura = coberturaDeObjetos(pre, r, maxTamanoObjeto);
      const relleno = rellenoDeFondo(post, r, dy, dx, fondo);
      if (cobertura < minEvidencia && relleno < minEvidencia) continue;

      candidatas.push({
        // `dy === 0 ? 0 : dy` normaliza el MENOS CERO: con una caja de alto 1 el barrido arranca en
        // `-(1 - 1)` y JavaScript devuelve -0, que `Object.is` distingue de 0 y que el puerto Python
        // no puede producir (`range(-0, 1)` da 0). Lo encontro el fixture de paridad de mecanicas:
        // una divergencia que no cambia ninguna comparacion `=== 0` ni la firma, pero que ensucia
        // cualquier igualdad estructural entre los dos puertos.
        dy: dy === 0 ? 0 : dy,
        dx: dx === 0 ? 0 : dx,
        minY: r.minY,
        minX: r.minX,
        alto: r.maxY - r.minY + 1,
        ancho: r.maxX - r.minX + 1,
        cobertura,
        relleno,
      });
    }
  }

  if (candidatas.length === 0) return null;
  candidatas.sort(
    (a, b) =>
      b.cobertura - a.cobertura ||
      b.relleno - a.relleno ||
      Math.abs(a.dy) + Math.abs(a.dx) - (Math.abs(b.dy) + Math.abs(b.dx)) ||
      a.alto * a.ancho - b.alto * b.ancho ||
      a.dy - b.dy ||
      a.dx - b.dx,
  );
  return candidatas[0];
}

/** `post[R+d] === pre[R]` celda a celda, y el movimiento tiene que cambiar ALGO -- si no, cualquier
 *  region de fondo "se traslada" a otra region de fondo identica. */
function contenidoSeMovio(
  pre: Grid,
  post: Grid,
  r: BoundingBox,
  dy: number,
  dx: number,
  alto: number,
  ancho: number,
): boolean {
  let algoCambio = false;
  for (let y = r.minY; y <= r.maxY; y++) {
    for (let x = r.minX; x <= r.maxX; x++) {
      const ny = y + dy;
      const nx = x + dx;
      if (ny < 0 || nx < 0 || ny >= alto || nx >= ancho) return false;
      if (post[ny][nx] !== pre[y][x]) return false;
      if (pre[y][x] !== post[y][x]) algoCambio = true;
    }
  }
  return algoCambio;
}

function cambiosDentroDeLaUnion(grupo: Celda[], r: BoundingBox, dy: number, dx: number): boolean {
  for (const [y, x] of grupo) {
    const enR = y >= r.minY && y <= r.maxY && x >= r.minX && x <= r.maxX;
    const enDestino = y >= r.minY + dy && y <= r.maxY + dy && x >= r.minX + dx && x <= r.maxX + dx;
    if (!enR && !enDestino) return false;
  }
  return true;
}

function rellenoDeFondo(post: Grid, r: BoundingBox, dy: number, dx: number, fondo: number): number {
  let desalojadas = 0;
  let conFondo = 0;
  for (let y = r.minY; y <= r.maxY; y++) {
    for (let x = r.minX; x <= r.maxX; x++) {
      const enDestino =
        y >= r.minY + dy && y <= r.maxY + dy && x >= r.minX + dx && x <= r.maxX + dx;
      if (enDestino) continue;
      desalojadas++;
      if (post[y][x] === fondo) conFondo++;
    }
  }
  return desalojadas === 0 ? 0 : conFondo / desalojadas;
}
