"""[arc-agi3-kaggle-agent/world_model/mechanics_signature] BL.21741 -- la capa de VOCABULARIO de
`object_mechanics`: como se NOMBRA una transicion ya detectada. Puerto de la mitad de firma de
arc-agi-runner/src/worldModel/objectMechanics.ts.

POR QUE VIVE APARTE (BL.21741 correccion). `object_mechanics.py` cruzo el limite de 500 lineas del
repo al agregarsele `es_firma_de_silencio`. El corte no es arbitrario: DETECTAR (que le paso a los
objetos) y NOMBRAR (con que etiqueta se acumula la evidencia) son dos responsabilidades con
consumidores distintos -- `mechanics_memory` acumula por firma, `direction_beliefs` decide por
TIPO. La dependencia va en un solo sentido: este modulo importa de `object_mechanics` y nunca al
reves.

LO QUE LA FIRMA SI SOSTIENE Y LO QUE NO, MEDIDO SOBRE EL CORPUS PERSISTIDO (14 eventos, 8
transiciones distintas, 6 juegos; sha256 86ec7f5ffe39):
  - SI: 7 firmas distintas sobre 8 transiciones. Con la firma anterior a BL.21741 era 1 sola
    ("desconocida" en 14 de 14).
  - CON QUE FUERZA ES "ESTABLE" (corregido): la estabilidad se afirmaba "en los 14 eventos", pero
    solo 4 de las 8 transiciones tienen mas de una captura con que compararse (ft09:nivel1 x2,
    g50t:nivel1 x2, lp85:nivel1 x4, vc33:nivel1 x2); las otras cuatro tienen UNA sola. O sea: 0
    firmas inestables sobre las 4 transiciones que se pueden contrastar, y 4 sin medir. Ademas cada
    firma tiene al menos un componente pegado al borde de su cubo (sc25 recoloreo=9 en el cubo 4-9,
    vc33 desconocida=1 en el cubo exacto "1"), asi que un cluster de mas o de menos -- ruido de
    segmentacion, no cambio de mecanica -- puede moverla: un roll global de control (3,5) sobre pre
    y post cambia la firma en 2 de los 14 eventos.
  - NO: NO hay evidencia de que el vocabulario transfiera entre mundos. De los 28 pares de
    transiciones, 26 son entre juegos DISTINTOS y NINGUNO comparte firma. El unico par que
    comparte (vc33:nivel1 + vc33:nivel2) es del MISMO juego y lo que comparte es
    `compuesta:desconocida=1`: UN cluster que el detector no supo nombrar. Compartir el silencio
    no es generalizar -- es fallar igual. El commit 246fc969fc vendio ese par como "la evidencia de
    que generaliza en vez de memorizar"; la cuenta honesta es 6 de 8 transiciones con firma propia
    informativa, 2 con la firma del silencio, y 0 de 26 pares entre juegos con firma compartida.
`es_firma_de_silencio` existe para que esa distincion no vuelva a perderse en un `startswith`.
"""
from __future__ import annotations

from typing import Final

from .object_mechanics import Mecanica, TIPOS_DE_NO_MIRE, TIPO_SIN_NOMBRAR

# Prefijo de la firma COMPUESTA. Constante y no literal suelto: lo leen `firma_compuesta`,
# `es_firma_de_silencio` y los scripts de analisis, y una copia desincronizada del literal es
# exactamente como `FIRMAS_DE_SILENCIO` quedo ciega a `compuesta:desconocida=N`.
PREFIJO_DE_FIRMA_COMPUESTA: Final[str] = "compuesta:"

# Cortes de los cubos con que la firma compuesta cuenta clusters. NO son un adorno: con el conteo
# EXACTO, la misma transicion medida dos veces produce firmas distintas (ft09:nivel1 da 3 clusters
# `desconocida` en un evento y 2 en el otro), o sea que memoriza el evento en vez de nombrar la
# transicion; con el conjunto de tipos PELADO (sin conteo), 4 de las 8 transiciones del corpus
# colapsan en la misma etiqueta `aparicion+desaparicion+desconocida+recoloreo` y la firma vuelve a
# no distinguir nada. Los cubos por orden de magnitud son el punto medio MEDIDO entre esos dos
# fracasos: 7 firmas distintas sobre 8 transiciones, estables en los 14 eventos.
CORTES_DE_CUBO: Final[tuple[int, ...]] = (1, 2, 4, 10)


def conteo_de_tipos_de_cluster(mecanica: Mecanica) -> dict[str, int]:
    """Cuantos clusters de cada tipo trae la transicion, ordenado por nombre de tipo.

    FUENTE UNICA de ese desglose (BL.21741): antes lo recontaban por su cuenta el informe de
    completados y el script del tope, con la misma logica escrita dos veces."""
    conteo: dict[str, int] = {}
    for cluster in mecanica.clusters:
        conteo[cluster.tipo] = conteo.get(cluster.tipo, 0) + 1
    return {tipo: conteo[tipo] for tipo in sorted(conteo)}


def _cubo(cantidad: int) -> str:
    """Cubo por orden de magnitud de `cantidad`: "1", "2-3", "4-9", "10+"."""
    for i in range(len(CORTES_DE_CUBO) - 1, -1, -1):
        piso = CORTES_DE_CUBO[i]
        if cantidad >= piso:
            if i + 1 >= len(CORTES_DE_CUBO):
                return f"{piso}+"
            techo = CORTES_DE_CUBO[i + 1] - 1
            return str(piso) if piso == techo else f"{piso}-{techo}"
    return str(cantidad)


def firma_compuesta(mecanica: Mecanica) -> str:
    """Firma de una transicion HETEROGENEA: el desglose por tipo de cluster, con los conteos
    cubeteados por orden de magnitud.

    POR QUE EXISTE (BL.21741, medido). `firma_de_mecanica` colapsaba a "desconocida" en cuanto los
    clusters de cambio no eran todos del mismo tipo -- y las subidas de nivel medidas son SIEMPRE
    mezclas (lp85:nivel1 = 17 apariciones + 9 desconocidas + 4 desapariciones + 1 recoloreo;
    sc25:nivel1 = 9 recoloreos + 3 desapariciones + 2 desconocidas + 1 aparicion). Resultado: la
    firma valia "desconocida" en los 14 eventos del corpus y las 8 transiciones distintas eran
    indistinguibles entre si. "6 desapariciones + 1 recoloreo" distingue un objetivo de otro;
    "desconocida" no distingue nada.

    OJO -- LA ETIQUETA NO GARANTIZA CONTENIDO. `compuesta:desconocida=1` es una firma compuesta
    cuyo unico componente es el silencio, y en el corpus le toca a las dos transiciones de vc33.
    Un consumidor que solo mire el prefijo `compuesta:` la lee como si nombrara algo: para eso esta
    `es_firma_de_silencio`.

    Devuelve "desconocida" si no hay clusters que desglosar: sin desglose no hay firma compuesta
    que dar, y inventar una seria peor que admitir el silencio."""
    conteo = conteo_de_tipos_de_cluster(mecanica)
    if not conteo:
        return TIPO_SIN_NOMBRAR
    partes = ",".join(f"{tipo}={_cubo(cantidad)}" for tipo, cantidad in conteo.items())
    return f"{PREFIJO_DE_FIRMA_COMPUESTA}{partes}"


def firma_de_mecanica(mecanica: Mecanica) -> str:
    """Etiqueta canonica -- la unidad sobre la que mechanics_memory.py acumula evidencia Beta por
    accion. Dos pasos con la misma firma son "la misma mecanica, dos veces"."""
    if mecanica.tipo == "sinCambio":
        return "sinCambio"
    if mecanica.tipo == "traslacion":
        t = mecanica.traslacion_principal
        return f"traslacion:{t.dy},{t.dx}"
    if mecanica.tipo in ("recoloreo", "aparicion", "desaparicion"):
        c = mecanica.cambio_de_color_principal
        if c is None:
            return mecanica.tipo
        return f"{mecanica.tipo}:{c.desde}>{c.hasta}"
    # Los dos silencios de "no mire" se nombran, no se disfrazan de "desconocida" (BL.21741). La
    # lista sale de `TIPOS_DE_NO_MIRE` y no de dos literales repetidos aca: la constante se declara
    # FUENTE UNICA y hasta esta correccion su propio modulo la ignoraba dos lineas mas abajo.
    if mecanica.tipo in TIPOS_DE_NO_MIRE:
        return mecanica.tipo
    return firma_compuesta(mecanica)


def es_firma_de_silencio(firma: str) -> bool:
    """La firma NO NOMBRA NINGUNA mecanica: es el silencio del detector, con cualquiera de sus
    tres deletreos.

    POR QUE EXISTE (correccion de BL.21741, defecto medido). El experimento del tope contaba las
    "transiciones en silencio" con
    `firma.startswith(("sobreElTope", "formaIncompatible", "desconocida"))`, y
    `"compuesta:desconocida=1".startswith(...)` es False. Con esa ceguera la tabla imprimia "0
    transiciones calladas" con el tope en 4096 cuando en realidad hay DOS (vc33:nivel1 y
    vc33:nivel2), y ese "0" era el unico argumento que separaba 4096 de 3072. Aguas abajo pasaba lo
    mismo: `MECANICAS_DE_OBJETO_UNICA` excluye todo `compuesta:` en bloque, asi que
    `compuesta:desconocida=1` (nada nombrado) y
    `compuesta:aparicion=10+,desaparicion=4-9,desconocida=4-9,recoloreo=1` (cuatro tipos nombrados)
    se leian igual -- justo la distincion que BL.21741 dice haber comprado.

    Los tres deletreos del silencio:
      1. los dos tipos de NO MIRE (`sobreElTope`, `formaIncompatible`);
      2. `desconocida` pelada (mire y no supe nombrar, sin clusters que desglosar);
      3. una firma compuesta cuyos componentes son TODOS `desconocida`.
    Una compuesta con al menos un tipo nombrado NO es silencio, aunque tambien traiga desconocidas:
    "9 recoloreos + 2 desconocidas" dice algo."""
    if firma in TIPOS_DE_NO_MIRE or firma == TIPO_SIN_NOMBRAR:
        return True
    if not firma.startswith(PREFIJO_DE_FIRMA_COMPUESTA):
        return False
    componentes = [
        parte for parte in firma[len(PREFIJO_DE_FIRMA_COMPUESTA) :].split(",") if parte
    ]
    if not componentes:
        return True
    return all(parte.split("=")[0] == TIPO_SIN_NOMBRAR for parte in componentes)


# SIN `__all__` a proposito: en el entregable plano (`agent/my_agent.py`) todos los modulos
# comparten UN namespace, y un segundo `__all__` top-level pisaria al de `primitives.py` en
# silencio. Lo verifica `tests/test_build_agent.py::test_ningun_nombre_top_level_se_repite...`.
# La superficie publica la declara el barrel `world_model/__init__.py`.
