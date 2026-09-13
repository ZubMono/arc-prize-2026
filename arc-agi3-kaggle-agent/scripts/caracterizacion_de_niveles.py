"""[arc-agi3-kaggle-agent/scripts/caracterizacion_de_niveles] BL.21695 paso 1 -- CARACTERIZA, con
numeros, que cambia en la grilla en el momento exacto en que el juego dice que subimos de nivel.

REGLA DE ORO DE ESTE ARCHIVO: no se escribe percepcion nueva. Todos los detectores ya existen
(BL.21561) y se usan tal cual -- `_find_components`, `detect_background_color`,
`foreground_bounding_box`, `detectar_mecanica`/`firma_de_mecanica` (traslacion, recoloreo,
aparicion, desaparicion). Lo unico que agrega este modulo es CONTABILIDAD sobre sus salidas: cuantas
componentes de cada color habia antes y despues, cuanto se movio el objeto movil, a que distancia
quedo de cada color, que fraccion del tablero dejo de ser fondo. Si una medicion necesitara un
detector nuevo, el detector va a `arc_agent/world_model/`, no aca.

QUE PREGUNTA CONTESTA CADA MEDICION (son los candidatos a vocabulario de objetivos que hay que
CONFIRMAR o DESCARTAR con el dato, nunca postular de memoria):
  - `celdas_cambiadas` / `fraccion_cambiada` -> el nivel termina con una transicion de pantalla
    completa o con un cambio local? Distingue "gane y el tablero se rehizo" de "toque la celda
    correcta".
  - `colores_agotados` -> RECOLECTAR-TODO: un color cuyas componentes bajan hasta cero.
  - `distancia_minima_por_color` -> ALCANZAR-DESTINO: el objeto movil se acerca monotonamente a un
    color y termina pegado a el.
  - `fraccion_no_fondo` -> PINTAR/LLENAR: el area ocupada crece hasta su maximo en el evento.
  - `firmas_previas` -> que mecanica venia ejecutando el agente en la maniobra que resolvio. Desde
    BL.21765 la percepcion de cada transicion previa se corre UNA vez: el resultado va a los pasos
    de la maniobra (que es donde lo leen los criterios de objetivo) y `firmas_previas` es su cola.
Ninguna de estas mediciones DECIDE nada: `caracterizar_completados.py` agrega los conteos y el
informe dice en cuantos de los completados capturados se sostiene cada candidato.

Stdlib pura. SOLO REPO (vive en `scripts/`, no viaja al entregable de Kaggle)."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from arc_agent.world_model import _find_components  # noqa: E402
from arc_agent.world_model.grid import (  # noqa: E402
    detect_background_color,
    foreground_bounding_box,
)
from arc_agent.world_model.object_mechanics import detectar_mecanica  # noqa: E402
from arc_agent.world_model.mechanics_signature import (  # noqa: E402
    conteo_de_tipos_de_cluster,
    firma_de_mecanica,
)
from maniobra_previa import (  # noqa: E402
    PasoPrevio,
    construir_vista,
    creciente_monotona,
    decreciente_monotona,
)
# Re-exportado a proposito: `MedicionDeEvento` se mudo a su propio modulo por tamano (BL.21728) y
# los llamadores lo siguen importando desde aca, que es donde se PRODUCE.
from medicion_de_evento import MedicionDeEvento  # noqa: E402

Grilla = list[list[int]]

#: Frames previos al evento sobre los que se calcula la distancia del objeto movil a cada color.
#: 5 y no la ventana entera por costo: la distancia se calcula contra TODAS las celdas de CADA
#: color (64x64x16 comparaciones por frame), y lo que interesa es la TENDENCIA final -- si el objeto
#: llego a destino, se ve en los ultimos pasos.
FRAMES_DE_APROXIMACION = 5

#: Distancia (Chebyshev, en celdas) por debajo de la cual se considera que el objeto movil LLEGO a
#: una region de ese color. 1 = adyacente, incluida la diagonal: un avatar que pisa la casilla suele
#: TAPARLA, asi que exigir distancia 0 descartaria justo el caso que interesa.
DISTANCIA_DE_LLEGADA = 1

#: Fraccion de la grilla que tiene que cambiar para llamar a la transicion "pantalla nueva". 0,5 es
#: deliberadamente alto: por debajo de eso siguen siendo cambios locales sobre el mismo tablero.
FRACCION_DE_PANTALLA_NUEVA = 0.5


@dataclass(frozen=True)
class ConteoDeColor:
    """Contabilidad de un color en una grilla: cuantas celdas y cuantas componentes conexas."""

    celdas: int
    componentes: int


def _dimensiones(grilla: Grilla) -> tuple[int, int]:
    return len(grilla), (len(grilla[0]) if grilla else 0)


def conteos_por_color(grilla: Grilla) -> dict[int, ConteoDeColor]:
    """Celdas y componentes de cada color que NO es el fondo. Usa `_find_components` (BL.21561) --
    la misma agrupacion 4-conexa que ve el ranker de clicks, para que dos partes del sistema no
    cuenten objetos de forma distinta."""
    fondo = detect_background_color(grilla)
    celdas: dict[int, int] = {}
    for fila in grilla:
        for color in fila:
            celdas[color] = celdas.get(color, 0) + 1
    componentes: dict[int, int] = {}
    for grupo in _find_components(grilla, fondo):
        x, y = grupo[0]
        color = grilla[y][x]
        componentes[color] = componentes.get(color, 0) + 1
    return {
        color: ConteoDeColor(celdas=celdas.get(color, 0), componentes=componentes.get(color, 0))
        for color in sorted(set(celdas) | set(componentes))
        if color != fondo
    }


def fraccion_no_fondo(grilla: Grilla) -> float:
    """Fraccion de celdas distintas del fondo. Sube cuando se PINTA y baja cuando se RECOLECTA."""
    alto, ancho = _dimensiones(grilla)
    if alto == 0 or ancho == 0:
        return 0.0
    fondo = detect_background_color(grilla)
    ocupadas = sum(1 for fila in grilla for celda in fila if celda != fondo)
    return ocupadas / (alto * ancho)


def celdas_cambiadas(pre: Grilla, post: Grilla) -> int:
    alto, ancho = _dimensiones(pre)
    if (alto, ancho) != _dimensiones(post):
        return alto * ancho
    return sum(1 for y in range(alto) for x in range(ancho) if pre[y][x] != post[y][x])


@dataclass(frozen=True)
class PosicionMovil:
    """Donde quedo el objeto movil tras la traslacion detectada en un paso, y cuanto se movio."""

    paso: int
    centro_y: float
    centro_x: float
    dy: int
    dx: int
    area: int


def trayectoria_del_movil(frames: Sequence[dict[str, Any]]) -> list[PosicionMovil]:
    """Posiciones sucesivas del objeto que SE MUEVE, leidas de `detectar_mecanica`.

    No hay tracker nuevo: la traslacion principal de cada transicion ya trae la caja en `pre` y el
    desplazamiento (dy,dx), asi que el centro en `post` es caja + delta. Los pasos sin traslacion
    detectada simplemente no aportan posicion (el objeto no se movio o el cambio no era de objeto);
    eso es informacion, no un hueco a rellenar."""
    posiciones: list[PosicionMovil] = []
    for i in range(1, len(frames)):
        pre = frames[i - 1]["grilla"]
        post = frames[i]["grilla"]
        mecanica = detectar_mecanica(pre, post)
        traslacion = mecanica.traslacion_principal
        if traslacion is None:
            continue
        centro_y = traslacion.min_y + (traslacion.alto - 1) / 2 + traslacion.dy
        centro_x = traslacion.min_x + (traslacion.ancho - 1) / 2 + traslacion.dx
        posiciones.append(
            PosicionMovil(
                paso=frames[i]["paso"],
                centro_y=centro_y,
                centro_x=centro_x,
                dy=traslacion.dy,
                dx=traslacion.dx,
                area=traslacion.alto * traslacion.ancho,
            )
        )
    return posiciones


def distancia_a_colores(grilla: Grilla, centro_y: float, centro_x: float) -> dict[int, int]:
    """Distancia Chebyshev del punto dado a la celda mas cercana de cada color que no es fondo.

    Chebyshev y no Manhattan porque el movimiento de estos juegos incluye la diagonal (los clusters
    de `object_geometry` se agrupan 8-conexos justamente por eso): con Manhattan, un objeto pegado
    en diagonal mediria 2 y pareceria lejos."""
    fondo = detect_background_color(grilla)
    distancias: dict[int, int] = {}
    for y, fila in enumerate(grilla):
        dy = abs(y - centro_y)
        for x, color in enumerate(fila):
            if color == fondo:
                continue
            distancia = int(max(dy, abs(x - centro_x)))
            actual = distancias.get(color)
            if actual is None or distancia < actual:
                distancias[color] = distancia
    return distancias


def componente_bajo_el_click(grilla: Grilla, x: int, y: int) -> tuple[int, int] | None:
    """(color, celdas) de la componente que contiene a la celda (y, x). None si el click cayo
    fuera de la grilla o sobre el FONDO -- un click al vacio no toco ningun objeto, y decir que si
    seria inventar el objeto.

    Usa `_find_components` (BL.21561), el mismo agrupamiento que ve el ranker de clicks: si el
    ranker y el analisis de objetivos contaran objetos distintos, no habria forma de razonar sobre
    lo que el agente creyo estar tocando."""
    alto, ancho = _dimensiones(grilla)
    if not (0 <= y < alto and 0 <= x < ancho):
        return None
    fondo = detect_background_color(grilla)
    if grilla[y][x] == fondo:
        return None
    for grupo in _find_components(grilla, fondo):
        if (x, y) in grupo:
            return grilla[y][x], len(grupo)
    return None


def _caja(grilla: Grilla) -> tuple[int, int, int, int] | None:
    caja = foreground_bounding_box(grilla, detect_background_color(grilla))
    if caja is None:
        return None
    return (caja.min_y, caja.min_x, caja.max_y, caja.max_x)


def _colores_agotados_entre(pre: Grilla, post: Grilla) -> list[int]:
    """Colores con componentes en `pre` que ya no existen en `post`."""
    antes = conteos_por_color(pre)
    despues = conteos_por_color(post)
    return sorted(c for c, v in antes.items() if v.componentes > 0 and c not in despues)


def _aproximacion_a_colores(
    tramo: Sequence[dict[str, Any]],
) -> tuple[int, list[int], list[int]]:
    """(pasos con traslacion, colores alcanzados, colores a los que se acerco monotonamente) sobre
    el tramo de frames que se le pase.

    Existe como funcion y no en linea porque BL.21728 la corre DOS veces sobre tramos distintos: el
    que incluye el frame del evento (para poder mostrar el artefacto) y el que no (el unico que
    puede sostener el candidato `alcanzarDestino`)."""
    posiciones = trayectoria_del_movil(tramo)
    if not posiciones:
        return 0, [], []
    serie: dict[int, list[int]] = {}
    for posicion in posiciones:
        frame = next((f for f in tramo if f["paso"] == posicion.paso), None)
        if frame is None:
            continue
        for color, distancia in distancia_a_colores(
            frame["grilla"], posicion.centro_y, posicion.centro_x
        ).items():
            serie.setdefault(color, []).append(distancia)
    alcanzados: list[int] = []
    monotonas: list[int] = []
    for color, distancias in sorted(serie.items()):
        if distancias and distancias[-1] <= DISTANCIA_DE_LLEGADA:
            alcanzados.append(color)
        if (
            len(distancias) >= 3
            and all(distancias[i] <= distancias[i - 1] for i in range(1, len(distancias)))
            and distancias[-1] < distancias[0]
        ):
            monotonas.append(color)
    return len(posiciones), alcanzados, monotonas


def indice_del_evento(frames: Sequence[dict[str, Any]], paso: int) -> int:
    """Posicion del frame del EVENTO dentro de la ventana, o -1 si no esta.

    Publica y exportada (correccion de BL.21728): `medir_tope_de_mecanica.py` tenia su propia
    copia identica. Dos copias de "donde esta el evento" es la forma mas facil de que dos
    mediciones del mismo corpus dejen de hablar del mismo frame."""
    for i, frame in enumerate(frames):
        if frame["paso"] == paso:
            return i
    return -1


def pasos_de_la_ventana(
    frames: Sequence[dict[str, Any]],
    hasta: int,
    ocupacion: Sequence[float] | None = None,
) -> list[PasoPrevio]:
    """Los `PasoPrevio` de las transiciones `frames[i-1] -> frames[i]` para `i` en `1..hasta-1`.

    FUENTE UNICA DE LA CONSTRUCCION DEL PASO (BL.21794). Hasta este BL esta lista se armaba en linea
    dentro de `medir_evento`, o sea que solo existia en el momento del INFORME. La captura no podia
    registrar la clasificacion de sus propios frames sin escribir una segunda version de la misma
    construccion -- y dos versiones de "que fue este paso" es exactamente como se termina con dos
    muestras que no se pueden comparar. Ahora la captura (`captura_de_niveles.clases_de_los_frames`)
    y el informe llaman a ESTA funcion, con los mismos frames, y por lo tanto no pueden discrepar.

    `ocupacion` se puede pasar ya calculada para no recorrer las grillas dos veces; si no viene, se
    calcula aca. La percepcion (`detectar_mecanica`) se corre UNA vez por transicion."""
    if ocupacion is None:
        ocupacion = [fraccion_no_fondo(f["grilla"]) for f in frames[:hasta]]
    pasos: list[PasoPrevio] = []
    for i in range(1, hasta):
        mecanica = detectar_mecanica(frames[i - 1]["grilla"], frames[i]["grilla"])
        pasos.append(
            PasoPrevio(
                paso=int(frames[i]["paso"]),
                celdas_cambiadas=celdas_cambiadas(frames[i - 1]["grilla"], frames[i]["grilla"]),
                ocupacion=ocupacion[i],
                # BL.21765: la firma de BL.21741 de ESTA transicion previa. Es lo unico que le
                # faltaba a la vista de la maniobra para dejar de ser ciega a la percepcion
                # objeto-centrica.
                firma=firma_de_mecanica(mecanica),
                clusters=tuple(conteo_de_tipos_de_cluster(mecanica).items()),
            )
        )
    return pasos


def medir_evento(ventana: dict[str, Any]) -> MedicionDeEvento | None:
    """Mide UNA ventana capturada. Devuelve None si la ventana no tiene el par (pre, post) del
    evento: sin el frame ANTERIOR no hay transicion que caracterizar, y afirmar algo sobre el
    evento con un solo frame seria inventar."""
    frames = ventana.get("frames") or []
    indice = indice_del_evento(frames, ventana.get("pasoDelEvento", -1))
    if indice <= 0:
        return None

    pre = frames[indice - 1]["grilla"]
    post = frames[indice]["grilla"]
    del_evento = frames[indice]
    x_click = del_evento.get("x")
    y_click = del_evento.get("y")
    hubo_click = isinstance(x_click, int) and isinstance(y_click, int)
    bajo_el_click = componente_bajo_el_click(pre, x_click, y_click) if hubo_click else None
    clicks_previos = 0
    clicks_previos_en_objeto = 0
    for i in range(1, indice):
        anterior = frames[i]
        x_previo = anterior.get("x")
        y_previo = anterior.get("y")
        if not (isinstance(x_previo, int) and isinstance(y_previo, int)):
            continue
        clicks_previos += 1
        if componente_bajo_el_click(frames[i - 1]["grilla"], x_previo, y_previo) is not None:
            clicks_previos_en_objeto += 1
    alto, ancho = _dimensiones(post)
    total = max(1, alto * ancho)
    cambiadas = celdas_cambiadas(pre, post)

    mecanica = detectar_mecanica(pre, post)
    # BL.21741: el desglose sale de `conteo_de_tipos_de_cluster`, la fuente unica del modulo de
    # percepcion. Recontarlo aca era la misma logica escrita dos veces.
    tipos_de_cluster = conteo_de_tipos_de_cluster(mecanica)

    antes = conteos_por_color(pre)
    despues = conteos_por_color(post)
    # FUENTE UNICA (correccion de BL.21728): el mismo `sorted(...)` estaba escrito aca y dentro de
    # `_colores_agotados_entre`, que este BL acababa de crear. Con dos copias, cambiar la definicion
    # de "color agotado" haria que la columna CONTRASTE del informe -- que compara justamente estas
    # dos mediciones -- pasara a comparar peras con manzanas sin que ningun test lo note.
    agotados = _colores_agotados_entre(pre, post)
    reducidos = sorted(
        c
        for c, v in antes.items()
        if c in despues and despues[c].componentes < v.componentes
    )
    aparecidos = sorted(c for c in despues if c not in antes)

    ocupacion = [fraccion_no_fondo(f["grilla"]) for f in frames[: indice + 1]]
    llenado = creciente_monotona(ocupacion)
    vaciado = decreciente_monotona(ocupacion)

    aproximacion = frames[max(0, indice - FRAMES_DE_APROXIMACION) : indice + 1]
    traslaciones, alcanzados, monotonas = _aproximacion_a_colores(aproximacion)

    # --- BL.21728: lo mismo, EXCLUYENDO el frame del evento --------------------------------------
    # `ocupacion[:-1]` es la serie de la MANIOBRA. Toda la diferencia entre "el agente vacio el
    # tablero" y "el tablero se rehizo al ganar" esta en ese ultimo elemento: medido, la ocupacion
    # es plana los 10 frames previos y cae SOLO en el evento (ft09 0,4727 x10 -> 0,1553).
    ocupacion_previa = ocupacion[:-1]
    # FUENTE UNICA con la captura (BL.21794): la MISMA funcion que corre `captura_de_niveles` para
    # persistir la clase de cada frame. Si las dos discreparan, el informe estaria midiendo una
    # maniobra distinta de la que el corpus dice haber capturado.
    pasos_previos = pasos_de_la_ventana(frames, indice, ocupacion)
    # FUENTE UNICA: las firmas previas SON las de los pasos de la maniobra, ultimas
    # `FRAMES_DE_APROXIMACION`. No se vuelven a detectar.
    firmas_previas = [p.firma for p in pasos_previos][-FRAMES_DE_APROXIMACION:]
    tramo_previo = frames[max(0, indice - FRAMES_DE_APROXIMACION) : indice]
    traslaciones_previas, alcanzados_previos, monotonas_previas = _aproximacion_a_colores(
        tramo_previo
    )
    vista = construir_vista(
        pasos=pasos_previos,
        ocupacion=ocupacion_previa,
        # Agotados DURANTE la maniobra: del primer frame de la ventana al ULTIMO ANTERIOR al
        # evento. Comparar contra el frame del evento es lo que hacia que ft09 "agotara" tres
        # colores porque la transicion reescribio el 88% de la grilla.
        colores_agotados=(
            _colores_agotados_entre(frames[0]["grilla"], frames[indice - 1]["grilla"])
            if indice >= 2
            else []
        ),
        pasos_con_traslacion=traslaciones_previas,
        colores_alcanzados=alcanzados_previos,
        aproximacion_monotona=monotonas_previas,
        hubo_click_del_evento=hubo_click,
        color_bajo_el_click_previo=bajo_el_click[0] if bajo_el_click else None,
        clicks_previos=clicks_previos,
        clicks_previos_en_objeto=clicks_previos_en_objeto,
    )

    return MedicionDeEvento(
        juego=str(ventana.get("juego", "?")),
        corrida=str(ventana.get("corrida", "?")),
        paso_del_evento=int(ventana.get("pasoDelEvento", -1)),
        nivel_previo=int(ventana.get("nivelPrevio", 0)),
        nivel_nuevo=int(ventana.get("nivelNuevo", 0)),
        frames_antes=int(ventana.get("framesAntes", 0)),
        frames_despues=int(ventana.get("framesDespues", 0)),
        celdas_cambiadas=cambiadas,
        fraccion_cambiada=cambiadas / total,
        pantalla_nueva=(cambiadas / total) >= FRACCION_DE_PANTALLA_NUEVA,
        firma_del_evento=firma_de_mecanica(mecanica),
        accion_del_evento=str(del_evento.get("accion", "DESCONOCIDA")),
        click_del_evento=(x_click, y_click) if hubo_click else None,
        color_clickeado=bajo_el_click[0] if bajo_el_click else None,
        celdas_de_la_componente_clickeada=bajo_el_click[1] if bajo_el_click else None,
        # `clicks_previos` / `clicks_previos_en_objeto` NO se pasan: viven en la vista de la
        # maniobra y `MedicionDeEvento` los delega ahi (fuente unica, correccion de BL.21728).
        tipos_de_cluster=tipos_de_cluster,
        sobre_el_tope_de_mecanica=mecanica.tipo == "sobreElTope",
        firmas_previas=firmas_previas,
        colores_agotados=agotados,
        colores_reducidos=reducidos,
        colores_aparecidos=aparecidos,
        fraccion_no_fondo=ocupacion,
        llenado_monotono=llenado,
        vaciado_monotono=vaciado,
        pasos_con_traslacion=traslaciones,
        colores_alcanzados=alcanzados,
        aproximacion_monotona=monotonas,
        caja_del_frente_antes=_caja(pre),
        caja_del_frente_despues=_caja(post),
        maniobra=vista,
    )


__all__ = [
    "ConteoDeColor",
    "DISTANCIA_DE_LLEGADA",
    "FRACCION_DE_PANTALLA_NUEVA",
    "FRAMES_DE_APROXIMACION",
    "MedicionDeEvento",
    "PosicionMovil",
    "celdas_cambiadas",
    "componente_bajo_el_click",
    "conteos_por_color",
    "distancia_a_colores",
    "fraccion_no_fondo",
    "indice_del_evento",
    "medir_evento",
    "trayectoria_del_movil",
]
