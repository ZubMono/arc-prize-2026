"""[arc-agi3-kaggle-agent/world_model/grid] -- utilidades puras sobre grillas ARC
(list[list[int]], colores 4-bit 0-15). Puerto de arc-agi-runner/src/worldModel/grid.ts.
Sin red, sin I/O, sin terceros -- helpers deterministas reusados por primitive_ops.py,
primitives.py, synthesis.py, state_signature.py y planner.py."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, NamedTuple

Grid = list[list[int]]

# BL.21558 -- mascara de volatilidad de UN episodio: True en las celdas cuyo valor cambia sin
# relacion con la accion ejecutada (HUD, contador de pasos, animaciones de fondo). Toda comparacion
# "enmascarada" las IGNORA. Se indexa [y][x]; una fila mas corta que la grilla (o ausente) se lee
# como "no volatil", porque la mascara se APRENDE en vivo (volatility_mask.py) y puede ir por
# detras de un cambio de forma del frame. Puerto de VolatilityMask en grid.ts.
VolatilityMask = list[list[bool]]

# Aritmetica de 32 bits: Python tiene enteros de precision arbitraria, asi que CADA paso del
# hash se enmascara para reproducir bit a bit el Math.imul del TS (ver hash_grid).
MASK32: Final[int] = 0xFFFFFFFF
FNV_OFFSET_BASIS: Final[int] = 0x811C9DC5
FNV_PRIME: Final[int] = 0x01000193
# Separador de fila -- evita que [[1],[2]] colisione con [[1,2]].
ROW_SEPARATOR: Final[int] = 0xFF
# BL.21558 -- valor que se mezcla al hash en lugar del contenido real de una celda volatil. 16 esta
# FUERA del rango de colores ARC (0-15), asi que no puede colisionar con un color legitimo.
VOLATILE_CELL_HASH_PLACEHOLDER: Final[int] = 0x10


@dataclass(frozen=True)
class BoundingBox:
    """Rectangulo inclusivo (min y max pertenecen a la caja). Campos en snake_case porque NO
    viaja al JSON del fixture: es interna del motor, el TS nunca la serializa."""

    min_x: int
    min_y: int
    max_x: int
    max_y: int


class GridDimensions(NamedTuple):
    """Orden de campos (width, height) -- coincide con la declaracion del tipo TS. Construir
    SIEMPRE por keyword para que el orden posicional no sea una trampa."""

    width: int
    height: int


def clone_grid(grid: Grid) -> Grid:
    """Copia profunda de 2 niveles: los enteros son inmutables, no hace falta mas."""
    return [row[:] for row in grid]


def grid_dimensions(grid: Grid) -> GridDimensions:
    """El ancho se deriva de la fila 0 (invariante de rectangularidad, ver CONTRATO 0.2)."""
    return GridDimensions(width=len(grid[0]) if grid else 0, height=len(grid))


def is_volatile_cell(mask: "VolatilityMask | None", y: int, x: int) -> bool:
    """Lectura tolerante de la mascara -- fuera de rango = no volatil (ver VolatilityMask).
    El chequeo explicito de indices reemplaza al `mask[y]?.[x]` del TS: en Python un indice
    negativo NO da None, lee desde el otro extremo, que seria un bug silencioso."""
    if mask is None or y < 0 or y >= len(mask):
        return False
    row = mask[y]
    if x < 0 or x >= len(row):
        return False
    return row[x] is True


def grids_equal(a: Grid, b: Grid) -> bool:
    """Comparacion explicita celda a celda en vez de `a == b`: mantiene la MISMA tolerancia del
    TS frente a filas de distinto largo (devuelve False, nunca lanza). Delega en la version
    enmascarada -- una sola implementacion, igual que en grid.ts."""
    return grids_equal_masked(a, b, None)


def grids_equal_masked(a: Grid, b: Grid, mask: "VolatilityMask | None") -> bool:
    """BL.21558 -- igualdad IGNORANDO las celdas volatiles. `mask=None` es igualdad estricta.
    La FORMA (alto y largo de cada fila) se sigue comparando siempre: un cambio de tamano nunca es
    ruido de HUD, es otro estado."""
    if len(a) != len(b):
        return False
    for y in range(len(a)):
        row_a = a[y]
        row_b = b[y]
        if len(row_a) != len(row_b):
            return False
        for x in range(len(row_a)):
            if row_a[x] != row_b[x] and not is_volatile_cell(mask, y, x):
                return False
    return True


def cell_diff_count(a: Grid, b: Grid) -> int:
    """Distancia de Hamming entre dos grillas -- cantidad de celdas distintas. Si difieren en
    forma, cada celda fuera de la interseccion cuenta como distinta (penaliza cambios de tamano
    no explicados). Heuristica admisible-en-la-practica para el planner (nunca sobreestima el
    costo real de igualar dos grillas identicas: da 0 solo si son iguales).

    El centinela -1 para "celda ausente" no colisiona nunca con un color real (0-15), asi que
    dos ausencias enfrentadas cuentan como iguales, igual que los `undefined` del TS."""
    height = max(len(a), len(b))
    diff = 0
    for y in range(height):
        row_a = a[y] if y < len(a) else []
        row_b = b[y] if y < len(b) else []
        width = max(len(row_a), len(row_b))
        for x in range(width):
            value_a = row_a[x] if x < len(row_a) else -1
            value_b = row_b[x] if x < len(row_b) else -1
            if value_a != value_b:
                diff += 1
    return diff


def detect_background_color(grid: Grid) -> int:
    """Color de fondo -- el mas frecuente en la grilla (heuristica estandar ARC: el fondo domina
    el area). Empate: el de menor indice de color, para determinismo. Grilla vacia (o de filas
    vacias): 0, igual que el `best = 0` inicial del TS."""
    counts: dict[int, int] = {}
    for row in grid:
        for cell in row:
            counts[cell] = counts.get(cell, 0) + 1
    best = 0
    best_count = -1
    # Ascendente por color + comparacion ESTRICTA: el primero en superar al mejor gana, asi el
    # empate lo resuelve siempre el indice de color mas bajo.
    for color in sorted(counts):
        count = counts[color]
        if count > best_count:
            best = color
            best_count = count
    return best


def foreground_bounding_box(grid: Grid, background_color: int) -> BoundingBox | None:
    """Bounding box de las celdas que NO son `background_color`. None si la grilla es uniforme
    (no hay foreground). El TS arranca con centinelas Infinity y compara `maxX < minX` al final;
    aca el flag `found` expresa lo mismo sin depender de un valor magico."""
    found = False
    min_x = 0
    min_y = 0
    max_x = 0
    max_y = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell == background_color:
                continue
            if not found:
                found = True
                min_x = x
                max_x = x
                min_y = y
                max_y = y
                continue
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
    if not found:
        return None
    return BoundingBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def hash_grid(grid: Grid) -> int:
    """Hash entero estable (FNV-1a de 32 bits, con separador de fila para no colisionar grillas
    de distinta forma con el mismo contenido concatenado). Usado por state_signature.py para
    detectar estados repetidos y por planner.py para deduplicar nodos de la busqueda.

    Por que `& MASK32` reproduce Math.imul exactamente: Math.imul(a, b) devuelve los 32 bits
    bajos del producto interpretados como int32 con signo. Todas las operaciones posteriores
    (^, imul, el `>>> 0` final) dependen SOLO de esos 32 bits bajos, y el XOR es invariante ante
    la interpretacion con/sin signo. Mantener `h` sin signo enmascarado da el mismo valor final
    que el `hash >>> 0` del TS. Retorno: entero sin signo en [0, 2**32)."""
    return hash_grid_masked(grid, None)


def hash_grid_masked(grid: Grid, mask: "VolatilityMask | None") -> int:
    """BL.21558 -- hash que IGNORA el contenido de las celdas volatiles: cada una aporta
    VOLATILE_CELL_HASH_PLACEHOLDER en vez de su color, asi que la posicion sigue contando (la forma
    no se pierde) pero el valor cambiante no. Con `mask=None` reproduce `hash_grid` bit a bit."""
    h = FNV_OFFSET_BASIS
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            valor = VOLATILE_CELL_HASH_PLACEHOLDER if is_volatile_cell(mask, y, x) else cell
            h = (h ^ valor) & MASK32
            h = (h * FNV_PRIME) & MASK32
        h = (h ^ ROW_SEPARATOR) & MASK32
        h = (h * FNV_PRIME) & MASK32
    return h


def neutralize_volatile_cells(
    reference: Grid, target: Grid, mask: "VolatilityMask | None"
) -> Grid:
    """BL.21558 -- copia de `target` con las celdas volatiles reemplazadas por el valor que tienen
    en `reference`. Es la forma de meter la mascara en un consumidor que NO la conoce:
    `synthesize_program` recibe (pre, neutralize_volatile_cells(pre, post, mask)) y ve un par donde
    las celdas de HUD son identicas, con lo cual solo tiene que explicar el cambio REAL del
    tablero. Sin esto habria que cablear la mascara por todo el DSL y romper la paridad con el
    motor TypeScript.

    `mask=None` devuelve un clon fiel (nunca la misma referencia: quien lo recibe puede mutarlo sin
    corromper la ventana de observaciones). Una celda sin equivalente en `reference` conserva su
    valor de `target` -- sin referencia no hay con que neutralizarla."""
    salida: Grid = []
    for y, row in enumerate(target):
        fila_ref = reference[y] if y < len(reference) else []
        nueva: list[int] = []
        for x, cell in enumerate(row):
            if is_volatile_cell(mask, y, x) and x < len(fila_ref):
                nueva.append(fila_ref[x])
            else:
                nueva.append(cell)
        salida.append(nueva)
    return salida
