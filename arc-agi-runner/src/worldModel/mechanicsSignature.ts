/* [arc-agi-runner/worldModel/mechanicsSignature] BL.21741 -- la capa de VOCABULARIO de
   `objectMechanics`: como se NOMBRA una transicion ya detectada. Espejo exacto de
   `arc-agi3-kaggle-agent/arc_agent/world_model/mechanics_signature.py`, y las dos mitades las
   arbitra el fixture `__fixtures__/mechanicsParity.json` (GATE-DSL-PARITY).

   POR QUE VIVE APARTE. DETECTAR (que le paso a los objetos) y NOMBRAR (con que etiqueta se acumula
   la evidencia) son dos responsabilidades con consumidores distintos: `mechanicsMemory` acumula por
   FIRMA, `directionBeliefs` decide por TIPO. La dependencia va en un solo sentido: este modulo
   importa de `objectMechanics` y nunca al reves.

   LO QUE LA FIRMA SI SOSTIENE Y LO QUE NO, MEDIDO SOBRE EL CORPUS PERSISTIDO DE SUBIDAS DE NIVEL
   (14 eventos, 8 transiciones distintas, 6 juegos; sha256 86ec7f5ffe39):
   - SI: 7 firmas distintas sobre 8 transiciones. Con la firma anterior a BL.21741 era 1 sola
     ("desconocida" en 14 de 14) -- y este motor TypeScript, el que juega contra la API oficial
     cada hora, seguia en ese 14/14 hasta esta correccion. Caveat de fuerza: solo 4 de las 8
     transiciones tienen mas de una captura con que contrastarse, asi que "0 firmas inestables" se
     mide sobre esas 4 y las otras 4 estan sin medir.
   - NO: NO hay evidencia de que el vocabulario transfiera entre mundos. De los 28 pares de
     transiciones, 26 son entre juegos DISTINTOS y NINGUNO comparte firma. El unico par que
     comparte (vc33:nivel1 + vc33:nivel2) es del MISMO juego y lo que comparte es
     `compuesta:desconocida=1`: UN cluster que el detector no supo nombrar. Compartir el silencio
     no es generalizar. */

import { TIPOS_DE_NO_MIRE, type Mecanica, type Traslacion } from './objectMechanics';

/** El tipo de cluster que el detector MIRO y no supo nombrar. Constante y no literal porque la
 *  firma compuesta lo deletrea DENTRO de la etiqueta (`compuesta:desconocida=1`). */
export const TIPO_SIN_NOMBRAR = 'desconocida';

/** Prefijo de la firma COMPUESTA. */
export const PREFIJO_DE_FIRMA_COMPUESTA = 'compuesta:';

/** Cortes de los cubos con que la firma compuesta cuenta clusters. NO son un adorno: con el conteo
 *  EXACTO, la misma transicion medida dos veces produce firmas distintas (ft09:nivel1 da 3 clusters
 *  `desconocida` en un evento y 2 en el otro), o sea que memoriza el evento en vez de nombrar la
 *  transicion; con el conjunto de tipos PELADO (sin conteo), 4 de las 8 transiciones del corpus
 *  colapsan en la misma etiqueta y la firma vuelve a no distinguir nada. */
export const CORTES_DE_CUBO = [1, 2, 4, 10] as const;

/** Cuantos clusters de cada tipo trae la transicion, ordenado por nombre de tipo. FUENTE UNICA de
 *  ese desglose (BL.21741). */
export function conteoDeTiposDeCluster(mecanica: Mecanica): Record<string, number> {
  // Map y no un objeto plano: las claves son tipos de cluster (una union cerrada del motor), pero
  // acumular sobre `{}` es la forma que el gate de prototype pollution marca -- y con razon como
  // patron general. `fromEntries` reconstruye el objeto ya ordenado por nombre de tipo, que es el
  // orden que el puerto Python produce con `sorted(conteo)` y que el fixture de paridad arbitra.
  const conteo = new Map<string, number>();
  for (const cluster of mecanica.clusters) {
    conteo.set(cluster.tipo, (conteo.get(cluster.tipo) ?? 0) + 1);
  }
  const ordenado = [...conteo.entries()].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  return Object.fromEntries(ordenado);
}

/** Cubo por orden de magnitud de `cantidad`: "1", "2-3", "4-9", "10+". */
function cubo(cantidad: number): string {
  for (let i = CORTES_DE_CUBO.length - 1; i >= 0; i--) {
    const piso = CORTES_DE_CUBO[i];
    if (cantidad >= piso) {
      if (i + 1 >= CORTES_DE_CUBO.length) return `${piso}+`;
      const techo = CORTES_DE_CUBO[i + 1] - 1;
      return piso === techo ? String(piso) : `${piso}-${techo}`;
    }
  }
  return String(cantidad);
}

/** Firma de una transicion HETEROGENEA: el desglose por tipo de cluster, con los conteos cubeteados
 *  por orden de magnitud.
 *
 *  POR QUE EXISTE (BL.21741, medido). `firmaDeMecanica` colapsaba a "desconocida" en cuanto los
 *  clusters no eran todos del mismo tipo -- y una subida de nivel es SIEMPRE una mezcla. Resultado:
 *  la firma valia "desconocida" en los 14 eventos del corpus persistido y las 8 transiciones
 *  distintas eran indistinguibles entre si. "6 desapariciones + 1 recoloreo" distingue un objetivo
 *  de otro; "desconocida" no distingue nada.
 *
 *  OJO -- LA ETIQUETA NO GARANTIZA CONTENIDO: `compuesta:desconocida=1` es una compuesta cuyo unico
 *  componente es el silencio. Para eso esta `esFirmaDeSilencio`. */
export function firmaCompuesta(mecanica: Mecanica): string {
  const conteo = conteoDeTiposDeCluster(mecanica);
  const tipos = Object.keys(conteo);
  if (tipos.length === 0) return TIPO_SIN_NOMBRAR;
  return `${PREFIJO_DE_FIRMA_COMPUESTA}${tipos.map((t) => `${t}=${cubo(conteo[t])}`).join(',')}`;
}

/** Etiqueta canonica de una mecanica -- la unidad sobre la que mechanicsMemory.ts acumula
 *  evidencia Beta por accion. Dos pasos con la misma firma son "la misma mecanica, dos veces". */
export function firmaDeMecanica(mecanica: Mecanica): string {
  switch (mecanica.tipo) {
    case 'sinCambio':
      return 'sinCambio';
    case 'traslacion': {
      const t = mecanica.traslacionPrincipal as Traslacion;
      return `traslacion:${t.dy},${t.dx}`;
    }
    case 'recoloreo':
    case 'aparicion':
    case 'desaparicion': {
      const c = mecanica.cambioDeColorPrincipal;
      return c === null ? mecanica.tipo : `${mecanica.tipo}:${c.desde}>${c.hasta}`;
    }
    default:
      // Los dos silencios de "no mire" se nombran, no se disfrazan de "desconocida" (BL.21741).
      // La lista sale de `TIPOS_DE_NO_MIRE`, que es la fuente unica declarada.
      if ((TIPOS_DE_NO_MIRE as readonly string[]).includes(mecanica.tipo)) return mecanica.tipo;
      return firmaCompuesta(mecanica);
  }
}

/** La firma NO NOMBRA NINGUNA mecanica: es el silencio del detector, con cualquiera de sus tres
 *  deletreos -- los dos tipos de NO MIRE, `desconocida` pelada, y una compuesta cuyos componentes
 *  son TODOS `desconocida`.
 *
 *  POR QUE EXISTE (correccion de BL.21741). El experimento del tope contaba el silencio con un
 *  `startsWith(('sobreElTope','formaIncompatible','desconocida'))`, y `'compuesta:desconocida=1'`
 *  no empieza con ninguno de los tres: la tabla publicaba "0 transiciones calladas" con el tope en
 *  4096 habiendo dos. Una compuesta con al menos un tipo nombrado NO es silencio. */
export function esFirmaDeSilencio(firma: string): boolean {
  if ((TIPOS_DE_NO_MIRE as readonly string[]).includes(firma) || firma === TIPO_SIN_NOMBRAR) {
    return true;
  }
  if (!firma.startsWith(PREFIJO_DE_FIRMA_COMPUESTA)) return false;
  const componentes = firma.slice(PREFIJO_DE_FIRMA_COMPUESTA.length).split(',').filter(Boolean);
  if (componentes.length === 0) return true;
  return componentes.every((parte) => parte.split('=')[0] === TIPO_SIN_NOMBRAR);
}
