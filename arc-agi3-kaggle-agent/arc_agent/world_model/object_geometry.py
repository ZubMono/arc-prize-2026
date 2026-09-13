"""[arc-agi3-kaggle-agent/world_model/object_geometry] BL.21561 -- geometria de objetos sobre una
grilla: agrupacion de celdas cambiadas en clusters, bounding boxes y las dos mediciones que
distinguen "aca se movio un OBJETO" de "aca se recorto un pedazo del fondo".

Puerto de arc-agi-runner/src/worldModel/objectGeometry.ts. Sin estado y sin dependencias fuera de
grid.py.
"""
from __future__ import annotations

from typing import Final

# Imports relativos en UNA sola linea a proposito: submission/build_notebook.py los desmonta con
# un regex de una linea y la forma con parentesis dejaria un `)` colgando en el notebook.
from .grid import BoundingBox, Grid, VolatilityMask, is_volatile_cell

# Radio del anillo de contexto con el que se estima el fondo LOCAL alrededor de un cluster. El
# fondo GLOBAL de la grilla no sirve: en dc22-fdcac232 el color mas frecuente del frame es la pared
# del marco (4) y el piso de la arena por el que se mueve el cursor es otro (2).
RADIO_DE_FONDO_LOCAL: Final[int] = 2

Celda = tuple[int, int]


def agrupar_en_clusters(celdas: list[Celda]) -> list[list[Celda]]:
    """Agrupa celdas en clusters 8-conexos. 8 y no 4 a proposito: un objeto que se mueve en
    diagonal deja la region que abandona y la que ocupa tocandose solo por la esquina, y son UN
    evento."""
    pendientes = set(celdas)
    grupos: list[list[Celda]] = []
    for inicio in celdas:
        if inicio not in pendientes:
            continue
        pendientes.discard(inicio)
        pila = [inicio]
        grupo: list[Celda] = []
        while pila:
            y, x = pila.pop()
            grupo.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    vecina = (y + dy, x + dx)
                    if vecina in pendientes:
                        pendientes.discard(vecina)
                        pila.append(vecina)
        grupos.append(grupo)
    return grupos


def caja_de_celdas(celdas: list[Celda]) -> BoundingBox:
    ys = [c[0] for c in celdas]
    xs = [c[1] for c in celdas]
    return BoundingBox(min_x=min(xs), min_y=min(ys), max_x=max(xs), max_y=max(ys))


def cobertura_de_objetos(grid: Grid, caja: BoundingBox, max_tamano_objeto: int) -> float:
    """Fraccion de `caja` ocupada por componentes 4-conexas monocromas ENTERAMENTE contenidas en
    ella y de tamano <= `max_tamano_objeto` -- la definicion operativa de "aca hay un objeto
    acotado". Un cursor da 1.0; un recorte del piso da 0, porque su componente se escapa."""
    alto = len(grid)
    ancho = len(grid[0]) if grid else 0
    visto: set[Celda] = set()
    cubiertas = 0
    for y0 in range(caja.min_y, caja.max_y + 1):
        for x0 in range(caja.min_x, caja.max_x + 1):
            if (y0, x0) in visto:
                continue
            color = grid[y0][x0]
            visto.add((y0, x0))
            pila = [(y0, x0)]
            tamano = 0
            se_escapa = False
            while pila:
                y, x = pila.pop()
                tamano += 1
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if ny < 0 or nx < 0 or ny >= alto or nx >= ancho:
                        continue
                    if grid[ny][nx] != color:
                        continue
                    if ny < caja.min_y or ny > caja.max_y or nx < caja.min_x or nx > caja.max_x:
                        se_escapa = True
                        continue
                    if (ny, nx) in visto:
                        continue
                    visto.add((ny, nx))
                    pila.append((ny, nx))
            if not se_escapa and tamano <= max_tamano_objeto:
                cubiertas += tamano
    area = (caja.max_y - caja.min_y + 1) * (caja.max_x - caja.min_x + 1)
    return cubiertas / area


def fondo_local(grid: Grid, excluidas: list[Celda], caja: BoundingBox) -> int:
    """Color mas frecuente de `grid` en el anillo que rodea a `caja`, IGNORANDO `excluidas` (las
    celdas que cambiaron: son el evento, no el contexto). Empate: el color de menor indice, para
    determinismo bit a bit con el motor TypeScript."""
    fuera = set(excluidas)
    conteo: dict[int, int] = {}
    desde_y = max(0, caja.min_y - RADIO_DE_FONDO_LOCAL)
    hasta_y = min(len(grid) - 1, caja.max_y + RADIO_DE_FONDO_LOCAL)
    for y in range(desde_y, hasta_y + 1):
        desde_x = max(0, caja.min_x - RADIO_DE_FONDO_LOCAL)
        hasta_x = min(len(grid[y]) - 1, caja.max_x + RADIO_DE_FONDO_LOCAL)
        for x in range(desde_x, hasta_x + 1):
            if (y, x) in fuera:
                continue
            conteo[grid[y][x]] = conteo.get(grid[y][x], 0) + 1
    fondo = -1
    mejor = -1
    for color in sorted(conteo):
        if conteo[color] > mejor:
            fondo = color
            mejor = conteo[color]
    return fondo


# ── BL.21853 -- objeto ENTERO: la via que ve al multicelda que se va lejos ─────────────────────

#: Tope de celdas de un OBJETO (no del area de su caja). Es la diferencia que hace a esta via: el
#: analisis por cluster acota el AREA DE LA CAJA (`MAX_TAMANO_OBJETO`, 256) y un objeto de 153
#: celdas repartido en una caja de 17x17=289 ya no entra, aunque el objeto sea chico. Medido sobre
#: las 7.258 transiciones de `arcReplayFrames` (BL.21853): los objetos que esta via recupera miden
#: 53 y 153 celdas, o sea que 256 celdas los cubre a los dos.
MAX_CELDAS_DE_OBJETO_ENTERO: Final[int] = 256

#: Tope de pares (objeto de pre, objeto de post) con la MISMA forma que se prueban antes de
#: rendirse. Guarda de costo para el tablero embaldosado: una grilla con 40 fichas identicas da
#: 1.600 pares y ninguno explica el cambio.
MAX_PARES_DE_OBJETO: Final[int] = 64


def objetos_que_tocan(
    grid: Grid, fondo: int, semillas: list[Celda], max_celdas: int
) -> list[list[Celda]]:
    """Componentes 4-conexas de celdas distintas de `fondo` que contienen alguna celda de
    `semillas`. Color-AGNOSTICO puertas adentro: un avatar de dos colores es UN objeto, no dos.

    NO es la misma nocion de objeto que `cobertura_de_objetos`: aquella exige MONOCROMIA y se ata a
    una caja; esta no hace ninguna de las dos cosas. Son dos definiciones distintas de "objeto"
    conviviendo en el arbol (la tercera es `primitive_ops._find_components`, 4-conexa monocroma,
    que alimenta las features de click) -- esta enumerado a proposito en vez de decir que se reusa
    una sola: BL.21853 lo afirmo de mas y la revision lo midio.

    Descarta la componente que supera `max_celdas` celdas -- eso ya no es un objeto, es el tablero
    -- y la descarta ENTERA: al pasarse el tope sigue recorriendola solo para marcarla como vista,
    porque cortar el recorrido dejaba el resto sin visitar y una semilla posterior lo volvia a
    floodear y emitia un PEDAZO de esa misma componente como si fuera un objeto. Medido (BL.21853,
    revision): corredor 4-conexo de 304 celdas con tope 256, semillas en los dos extremos ->
    devolvia un "objeto" de 47 celdas; con una sola semilla devolvia []. O sea que la salida
    dependia de QUE celdas cambiaron y no solo de la grilla.

    Orden DETERMINISTA (el de `semillas`, que llega en barrido por filas): los dos puertos tienen
    que elegir el mismo candidato cuando hay varios."""
    alto = len(grid)
    ancho = len(grid[0]) if alto else 0
    visto: set[Celda] = set()
    salida: list[list[Celda]] = []
    for (sy, sx) in semillas:
        if (sy, sx) in visto or grid[sy][sx] == fondo:
            continue
        pila = [(sy, sx)]
        visto.add((sy, sx))
        celdas: list[Celda] = []
        excedido = False
        while pila:
            y, x = pila.pop()
            if not excedido:
                celdas.append((y, x))
                if len(celdas) > max_celdas:
                    # Al pasarse el tope se sigue recorriendo SOLO para dejar la componente entera
                    # en `visto`. Sin esto, el remanente no visitado quedaba disponible para una
                    # semilla posterior y salia como objeto propio.
                    excedido = True
                    celdas = []
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if ny < 0 or nx < 0 or ny >= alto or nx >= ancho:
                    continue
                if (ny, nx) in visto or grid[ny][nx] == fondo:
                    continue
                visto.add((ny, nx))
                pila.append((ny, nx))
        if not excedido:
            celdas.sort()
            salida.append(celdas)
    return salida


def forma_con_color(celdas: list[Celda], grid: Grid) -> tuple[frozenset, Celda]:
    """Forma del objeto normalizada a su esquina superior izquierda, con el color de cada celda, y
    esa esquina. Dos objetos con la misma `forma_con_color` son el MISMO objeto en otra posicion."""
    my = min(c[0] for c in celdas)
    mx = min(c[1] for c in celdas)
    return frozenset((y - my, x - mx, grid[y][x]) for y, x in celdas), (my, mx)


def _objeto_explica_el_cambio(
    pre: Grid,
    post: Grid,
    cambios: set[Celda],
    fondo: int,
    objeto: list[Celda],
    dy: int,
    dx: int,
    mask: VolatilityMask | None,
) -> bool:
    """RECONSTRUYE `post` a partir de `pre` moviendo `objeto` por (dy,dx) y exige que quede EXACTO.

    Es lo que separa esta via de un match de formas: en un tablero embaldosado hay decenas de
    objetos con la misma forma y "alguno coincide desplazado" no dice nada. Aca se pide (a) que
    TODA celda cambiada este en el origen o en el destino y (b) que el destino tenga el contenido
    del objeto y el origen desalojado tenga el fondo. La diferencia entre los dos criterios esta
    MEDIDA sobre el corpus: 564 transiciones con el criterio flojo contra 146 con este."""
    alto = len(pre)
    ancho = len(pre[0])
    destino: dict[Celda, int] = {}
    for (y, x) in objeto:
        ny, nx = y + dy, x + dx
        if ny < 0 or nx < 0 or ny >= alto or nx >= ancho:
            return False
        destino[(ny, nx)] = pre[y][x]
    tocadas = set(objeto) | set(destino)
    for celda in cambios:
        if celda not in tocadas:
            return False
    for (y, x) in tocadas:
        if is_volatile_cell(mask, y, x):
            continue
        if post[y][x] != destino.get((y, x), fondo):
            return False
    return True


def traslacion_de_objeto_entero(
    pre: Grid,
    post: Grid,
    cambios: list[Celda],
    fondo: int,
    mask: VolatilityMask | None = None,
    max_celdas: int = MAX_CELDAS_DE_OBJETO_ENTERO,
    max_pares: int = MAX_PARES_DE_OBJETO,
) -> tuple[int, int, list[Celda]] | None:
    """(dy, dx, celdas del objeto) si UN objeto entero se movio y eso explica TODO el cambio.

    POR QUE HACE FALTA (BL.21853, medido sobre 7.258 transiciones reales). El analisis por cluster
    de `object_mechanics` despeja la caja `R` del bbox del cluster, o sea que solo ve al objeto que
    se mueve MENOS que su propio ancho; y acota `R` por AREA (256), que un objeto grande desborda
    aunque tenga pocas celdas. Un objeto que salta lejos deja dos clusters disjuntos y ninguno se
    explica solo. Resultado medido: 146 transiciones (2,01% del corpus) que hoy caen en
    `desconocida` son traslaciones rigidas CARDINALES de objetos de 53 y 153 celdas.

    ALCANCE DE ESE 146, que la revision midio y el enunciado original no decia: las 146 salen de
    DOS juegos de los 27 con transiciones (re86-8af5384d 77, cn04-2fe56bfb 69). Es el mismo
    criterio con el que el BL descarto `rotacion` por venir de un solo juego, asi que lo honesto es
    "medido en dos escenas", no "confirmado sobre el corpus". Se conserva porque es la unica
    informacion NUEVA del paquete y porque su criterio de aceptacion es una reconstruccion exacta;
    no hay evidencia de que generalice a los otros 25 juegos.

    NO reemplaza al analisis por cluster: `object_mechanics` la llama SOLO cuando ese analisis y su
    respaldo fusionado no dieron NINGUNA traslacion (`if not con_traslacion`). Esa guarda no dice
    "la transicion no estaba explicada": un paso cuyo tipo global es `recoloreo`/`aparicion`/
    `desaparicion` entra igual y estructuralmente puede cambiar de respuesta. Lo medido es mas
    chico que eso -- sobre las 7.258 transiciones del corpus las 146 salen las 146 de
    `desconocida` -- y es lo unico que se afirma. La version anterior de esta linea decia "ninguna
    transicion que hoy se explica cambia de respuesta", que es una propiedad universal que el
    codigo no sostiene (RFM-07, corregido en la revision de BL.21853)."""
    if not cambios:
        return None
    conjunto = set(cambios)
    objetos_pre = objetos_que_tocan(pre, fondo, cambios, max_celdas)
    if not objetos_pre:
        return None
    objetos_post = objetos_que_tocan(post, fondo, cambios, max_celdas)
    if not objetos_post:
        return None
    indice: dict[frozenset, list[Celda]] = {}
    for celdas in objetos_post:
        forma, esquina = forma_con_color(celdas, post)
        indice.setdefault(forma, []).append(esquina)
    aceptadas: list[tuple[int, int, int, int, list[Celda]]] = []
    pares = 0
    for celdas in objetos_pre:
        forma, esquina = forma_con_color(celdas, pre)
        for destino in indice.get(forma, ()):
            dy = destino[0] - esquina[0]
            dx = destino[1] - esquina[1]
            if dy == 0 and dx == 0:
                continue
            pares += 1
            if pares > max_pares:
                return None
            if _objeto_explica_el_cambio(pre, post, conjunto, fondo, celdas, dy, dx, mask):
                aceptadas.append((abs(dy) + abs(dx), dy, dx, -len(celdas), celdas))
    if not aceptadas:
        return None
    aceptadas.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    elegida = aceptadas[0]
    return (elegida[1], elegida[2], elegida[4])
