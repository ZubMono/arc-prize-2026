"""[arc-agi3-kaggle-agent/world_model/primitive_ops] -- tipos del DSL de transformaciones
grilla-a-grilla + ejecucion (apply_step/apply_program) de cada primitivo + serializacion
canonica (program_key). Puerto de arc-agi-runner/src/worldModel/primitiveOps.ts.
Los generadores de candidatos data-driven (propose_*) viven en primitives.py -- separado solo
para respetar el limite de 500 lineas, misma responsabilidad conceptual (el DSL)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, TypedDict

# Import relativo en UNA sola linea a proposito: submission/build_notebook.py lo desmonta con
# `^from \.\w* import .+$` (regex de una linea), y la forma con parentesis dejaria los nombres
# sueltos y un `)` colgando dentro del notebook de Kaggle -- SyntaxError en la submission.
from .grid import BoundingBox, Grid, clone_grid, detect_background_color, foreground_bounding_box

class ProgramStep(TypedDict):
    """Un paso del DSL. Es un dict PLANO a proposito: serializa directo al JSON del fixture sin
    capa de conversion, y `json.loads` de un fixture produce el mismo objeto que el codigo
    construye. TypedDict = tipado estatico con cero costo en runtime."""

    name: str
    params: dict[str, Any]

# Composicion de pasos DSL -- ES el campo `program` de una KnownTransition (ver
# transition_memory.py), no un sistema paralelo. Programa vacio = identidad (no-op).
Program = list[ProgramStep]

class TranslateParams(TypedDict):
    dx: int
    dy: int

class ReflectParams(TypedDict):
    # 'horizontal' invierte columnas (espejo izquierda-derecha); 'vertical', filas (arriba-abajo).
    axis: str

class RotateParams(TypedDict):
    quarterTurns: int

class RecolorParams(TypedDict):
    # Color-origen -> color-destino; los colores ausentes quedan sin cambios (identidad). Claves
    # int EN MEMORIA, str al serializar (JS solo admite claves string en objetos).
    mapping: dict[int, int]

class FloodFillParams(TypedDict):
    x: int
    y: int
    to: int

class CropToBBoxParams(TypedDict):
    backgroundColor: int

class ReplicateParams(TypedDict):
    timesX: int
    timesY: int

class ObjectExtractParams(TypedDict, total=False):
    # Color a extraer. Si se OMITE (clave ausente, nunca None): la componente 4-conexa mas grande.
    color: int

OverlayParams = dict[str, Any]  # el TS lo declara Record<string, never>: siempre {}

# `from` es palabra reservada de Python -> forma FUNCIONAL obligatoria. Acceso SIEMPRE por
# subscript: params["from"], nunca por atributo. predicate: 'border' = celdas de `from` que tocan
# el borde de la grilla o un color distinto; 'interior' = el complemento; 'all' = todas.
ConditionalRecolorParams = TypedDict(
    "ConditionalRecolorParams", {"from": int, "to": int, "predicate": str}
)

PROGRAM_STEP_NAMES: Final[tuple[str, ...]] = (
    "translate", "reflect", "rotate", "recolor", "floodFill",
    "cropToBBox", "overlay", "replicate", "objectExtract", "conditionalRecolor",
)

# Orden canonico de claves de params por primitivo -- ES el orden de insercion de los object
# literals del TS, y por lo tanto el orden que emite JSON.stringify. Fija el desempate por clave
# del ranking Occam (ver synthesis.rank_programs).
PARAM_KEY_ORDER: Final[dict[str, tuple[str, ...]]] = {
    "translate": ("dx", "dy"),
    "reflect": ("axis",),
    "rotate": ("quarterTurns",),
    "recolor": ("mapping",),
    "floodFill": ("x", "y", "to"),
    "cropToBBox": ("backgroundColor",),
    "overlay": (),
    "replicate": ("timesX", "timesY"),
    "objectExtract": ("color",),
    "conditionalRecolor": ("from", "to", "predicate"),
}

# Constructores -- existen para que dos implementadores produzcan dicts identicos sin
# coordinarse: misma clave, mismo tipo, `color` omitido cuando corresponde.
def make_translate(dx: int, dy: int) -> ProgramStep:
    return {"name": "translate", "params": {"dx": dx, "dy": dy}}

def make_reflect(axis: str) -> ProgramStep:
    return {"name": "reflect", "params": {"axis": axis}}

def make_rotate(quarter_turns: int) -> ProgramStep:
    return {"name": "rotate", "params": {"quarterTurns": quarter_turns}}

def make_recolor(mapping: dict[int, int]) -> ProgramStep:
    return {"name": "recolor", "params": {"mapping": dict(mapping)}}

def make_flood_fill(x: int, y: int, to: int) -> ProgramStep:
    return {"name": "floodFill", "params": {"x": x, "y": y, "to": to}}

def make_crop_to_bbox(background_color: int) -> ProgramStep:
    return {"name": "cropToBBox", "params": {"backgroundColor": background_color}}

def make_overlay() -> ProgramStep:
    return {"name": "overlay", "params": {}}

def make_replicate(times_x: int, times_y: int) -> ProgramStep:
    return {"name": "replicate", "params": {"timesX": times_x, "timesY": times_y}}

def make_object_extract(color: int | None = None) -> ProgramStep:
    """Sin color, `params` queda VACIO -- nunca {"color": None}: el TS emite
    {"name":"objectExtract","params":{}} y un `null` seria otro JSON, rompiendo el fixture y el
    desempate por clave."""
    if color is None:
        return {"name": "objectExtract", "params": {}}
    return {"name": "objectExtract", "params": {"color": color}}

def make_conditional_recolor(from_color: int, to: int, predicate: str) -> ProgramStep:
    return {
        "name": "conditionalRecolor",
        "params": {"from": from_color, "to": to, "predicate": predicate},
    }

@dataclass(frozen=True)
class PrimitiveContext:
    """Grilla ancla para 'overlay' -- por diseno, el primer frame observado del episodio. Sin
    ancla, 'overlay' degrada a identidad (defensivo). `frozen=True` con un campo Grid mutable es
    intencional: congela la REFERENCIA, no la grilla. El contexto se comparte entre miles de
    nodos de la BFS de synthesis.py; clonarlo seria costo puro. Nadie muta anchor_grid."""

    anchor_grid: Grid | None = None

    def to_dict(self) -> dict[str, Any]:
        # Clave OMITIDA cuando no hay ancla -- replica el drop de `undefined` de JSON.stringify.
        return {} if self.anchor_grid is None else {"anchorGrid": self.anchor_grid}

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PrimitiveContext":
        return PrimitiveContext(anchor_grid=raw.get("anchorGrid"))

EMPTY_CONTEXT: Final[PrimitiveContext] = PrimitiveContext()

# Colacion raiz de ICU (la que usa String.prototype.localeCompare en Node) restringida al
# alfabeto que produce program_to_json. NO es orden de codepoint: en ASCII '}' (125) va DESPUES
# de los digitos, en ICU la puntuacion va ANTES. La diferencia es observable cuando un literal
# entero es prefijo numerico de otro en la ultima posicion de un objeto ({"color":1} vs
# {"color":15}); usar orden de codepoint invertiria ese par respecto del TS.
_PUNCTUATION_ORDER: Final[str] = '-,:"[]{}'

def _build_collation_rank() -> dict[str, int]:
    rank: dict[str, int] = {char: index for index, char in enumerate(_PUNCTUATION_ORDER)}
    for digit in range(10):
        rank[str(digit)] = len(_PUNCTUATION_ORDER) + digit
    letters_base = len(_PUNCTUATION_ORDER) + 10
    for i in range(26):
        # Rango primario por letra base; desempate terciario: minuscula ANTES de mayuscula.
        rank[chr(ord("a") + i)] = letters_base + 2 * i
        rank[chr(ord("A") + i)] = letters_base + 2 * i + 1
    return rank

_COLLATION_RANK: Final[dict[str, int]] = _build_collation_rank()

def _json_scalar(value: Any) -> str:
    """Strings entre comillas dobles sin escapes (el alfabeto del DSL es ASCII alfabetico puro),
    enteros con str() (negativos como -2, igual que JSON)."""
    if isinstance(value, bool):
        # bool es subclase de int en Python y "True" no es JSON valido: falla ruidosa antes que
        # fixture corrupto (el DSL no tiene booleanos).
        raise ValueError(f"valor booleano no admitido en params del DSL: {value!r}")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return '"' + value + '"'
    raise ValueError(f"valor no serializable en params del DSL: {value!r}")

def _mapping_to_json(mapping: dict[Any, int]) -> str:
    """`mapping` se emite con claves string y ORDENADAS ascendente por valor numerico: asi es
    como JS ordena las claves enteras de un objeto, sin importar el orden de insercion."""
    items = sorted(((int(key), value) for key, value in mapping.items()), key=lambda kv: kv[0])
    return "{" + ",".join('"' + str(k) + '":' + _json_scalar(v) for k, v in items) + "}"

def step_to_json(step: ProgramStep) -> str:
    # .get y no ["name"]: un step malformado (sin la clave) debe fallar con el MISMO ValueError en
    # espanol que un nombre desconocido, no con un KeyError que no dice nada del DSL.
    name = step.get("name")
    key_order = PARAM_KEY_ORDER.get(name)
    if key_order is None:
        raise ValueError(f"paso de DSL desconocido: {name!r}")
    params = step.get("params") or {}
    parts: list[str] = []
    for key in key_order:
        if key not in params:  # `color` de objectExtract: clave ausente, no null
            continue
        value = params[key]
        encoded = _mapping_to_json(value) if key == "mapping" else _json_scalar(value)
        parts.append('"' + key + '":' + encoded)
    return '{"name":"' + name + '","params":{' + ",".join(parts) + "}}"

def program_to_json(program: Program) -> str:
    """Reproduce byte a byte lo que produce JSON.stringify(program) en el TS: sin espacios,
    claves del step en orden name/params y claves de params en el orden de PARAM_KEY_ORDER,
    omitiendo las ausentes."""
    return "[" + ",".join(step_to_json(step) for step in program) + "]"

program_key = program_to_json  # alias publico: MISMO objeto, nunca un segundo serializador

def compare_program_keys(a: str, b: str) -> int:
    """Desempate del TS (`programKey(a).localeCompare(programKey(b))`), que NO es orden de
    codepoint. Devuelve -1 / 0 / 1.
    Por que la aproximacion caracter-a-caracter es exacta aca (ICU compara TODOS los pesos
    primarios antes de los terciarios, asi que en general no lo seria): en la gramatica de este
    DSL no existe ninguna posicion de primera divergencia entre dos claves canonicas donde ambos
    lados sean la misma letra base con distinta caja. Los 10 nombres no son prefijo unos de otros
    y divergen siempre en minusculas (recolor/reflect/replicate divergen en la posicion 2 con
    c/f/p); los valores string son todos minusculas; y las claves de params nunca divergen porque
    dentro de un mismo `name` el orden y los nombres son fijos.
    Solo se valida el caracter de la PRIMERA divergencia: uno fuera de la tabla ahi significa que
    el DSL crecio y la tabla quedo desactualizada, y fallar ruidosamente es la unica forma de que
    un desempate nuevo no se rompa en silencio."""
    for char_a, char_b in zip(a, b):
        if char_a == char_b:
            continue
        rank_a = _COLLATION_RANK.get(char_a)
        rank_b = _COLLATION_RANK.get(char_b)
        if rank_a is None or rank_b is None:
            desconocido = char_a if rank_a is None else char_b
            raise ValueError(
                f"caracter fuera de la tabla de colacion del DSL: {desconocido!r} -- "
                "actualizar _COLLATION_RANK al ampliar el alfabeto"
            )
        return -1 if rank_a < rank_b else 1
    # Prefijo propio: el mas corto va primero (coincide ICU y codepoint).
    if len(a) == len(b):
        return 0
    return -1 if len(a) < len(b) else 1

def _flood_region(grid: Grid, sx: int, sy: int, color: int) -> list[tuple[int, int]]:
    """DFS 4-conexa con PILA EXPLICITA -- nunca recursion: una region de 64x64 desborda el limite
    de recursion de Python. El orden de push (derecha, izquierda, abajo, arriba) + pop() LIFO fija
    el orden de la region resultante, load-bearing para el determinismo de los fixtures.
    `visited` es un set de tuplas donde el TS usa strings "x,y": mismo conjunto de claves, mas
    rapido. La guarda de limites va ANTES de todo acceso a grid[y][x] porque en Python un indice
    negativo NO falla, envuelve por el otro extremo (en TS daria undefined)."""
    h = len(grid)
    w = len(grid[0]) if grid else 0
    visited: set[tuple[int, int]] = set()
    stack: list[tuple[int, int]] = [(sx, sy)]
    region: list[tuple[int, int]] = []
    while stack:
        x, y = stack.pop()
        if (x, y) in visited:
            continue
        if x < 0 or y < 0 or x >= w or y >= h:
            continue
        if grid[y][x] != color:
            continue
        visited.add((x, y))
        region.append((x, y))
        stack.append((x + 1, y))
        stack.append((x - 1, y))
        stack.append((x, y + 1))
        stack.append((x, y - 1))
    return region

def _find_components(
    grid: Grid, background_color: int, only_color: int | None = None
) -> list[list[tuple[int, int]]]:
    """Barrido row-major saltando celdas ya vistas, de fondo y (si only_color no es None) de otro
    color. Devuelve las componentes en ORDEN DE DESCUBRIMIENTO."""
    h = len(grid)
    w = len(grid[0]) if grid else 0
    seen: set[tuple[int, int]] = set()
    components: list[list[tuple[int, int]]] = []
    for y in range(h):
        for x in range(w):
            color = grid[y][x]
            if (x, y) in seen:
                continue
            if color == background_color:
                continue
            if only_color is not None and color != only_color:
                continue
            region = _flood_region(grid, x, y, color)
            for cell in region:
                seen.add(cell)
            components.append(region)
    return components

def _bbox_of_cells(cells: list[tuple[int, int]]) -> BoundingBox:
    if not cells:
        # Nunca ocurre con componentes reales (siempre traen al menos una celda). El TS devuelve
        # centinelas Infinity, que hacen que ningun recorrido posterior itere; el rectangulo
        # degenerado (max < min) tiene ese mismo efecto en Python.
        return BoundingBox(min_x=0, min_y=0, max_x=-1, max_y=-1)
    xs = [cell[0] for cell in cells]
    ys = [cell[1] for cell in cells]
    return BoundingBox(min_x=min(xs), min_y=min(ys), max_x=max(xs), max_y=max(ys))

# Los params se leen con .get y defaults inertes: params invalidos dentro de un primitivo
# CONOCIDO nunca lanzan, degradan a un no-op defensivo -- mismo comportamiento que los
# `undefined` del TS, donde toda comparacion contra undefined es false.

def _apply_translate(params: dict[str, Any], grid: Grid) -> Grid:
    dx = params.get("dx", 0)
    dy = params.get("dy", 0)
    bg = detect_background_color(grid)
    h = len(grid)
    w = len(grid[0]) if grid else 0
    out: Grid = []
    for y in range(h):
        row: list[int] = []
        for x in range(w):
            sx = x - dx
            sy = y - dy
            # Guarda de limites OBLIGATORIA en AMBOS extremos: con sx = -1, grid[y][-1] en Python
            # devuelve la ULTIMA columna (en TS seria undefined) y el translate "envolveria" el
            # contenido en vez de rellenar con fondo -- el bug de port mas probable de este DSL.
            row.append(grid[sy][sx] if 0 <= sy < h and 0 <= sx < w else bg)
        out.append(row)
    return out

def _apply_reflect(params: dict[str, Any], grid: Grid) -> Grid:
    if params.get("axis") == "horizontal":
        return [row[::-1] for row in grid]
    # El TS trata todo lo que no sea 'horizontal' como vertical (no valida el axis): replicado.
    return [row[:] for row in reversed(grid)]

def _rotate90_cw(grid: Grid) -> Grid:
    h = len(grid)
    w = len(grid[0]) if grid else 0
    out: Grid = [[0] * h for _ in range(w)]
    for y in range(h):
        for x in range(w):
            out[x][h - 1 - y] = grid[y][x]
    return out

def _apply_rotate(params: dict[str, Any], grid: Grid) -> Grid:
    quarter_turns = params.get("quarterTurns", 0)
    # Con quarter_turns <= 0 el bucle no corre y queda el clon. El TS devuelve la MISMA
    # referencia; el clon es equivalente en valor y evita aliasing accidental en Python.
    out = clone_grid(grid)
    for _ in range(quarter_turns if quarter_turns > 0 else 0):
        out = _rotate90_cw(out)
    return out

def _apply_recolor(params: dict[str, Any], grid: Grid) -> Grid:
    """BL.20865 -- las claves pueden venir en int O en str, y las dos tienen que funcionar.

    En TypeScript el mapping es `Record<number, number>`, pero las claves de objeto de JavaScript
    son strings por debajo, asi que `mapping[5]` y el JSON `{"5": 3}` son la MISMA cosa y el
    round-trip por JSON es transparente. En Python no: un mapping construido a mano tiene claves
    int y uno deserializado de JSON las tiene str, y `{"5": 3}.get(5)` falla en silencio dejando la
    celda intacta -- el recolor se vuelve un no-op y el agente aprende un modelo de mundo
    equivocado sin que nada explote.

    No es hipotetico: es la via por la que viaja el conocimiento destilado al notebook de Kaggle
    (JSON embebido). Los tests unitarios no lo veian porque construyen el mapping en Python; lo
    caza el fixture de paridad, que cruza el limite JSON de verdad.
    """
    crudo = params.get("mapping") or {}
    mapping: dict[int, int] = {}
    for clave, valor in crudo.items():
        try:
            mapping[int(clave)] = int(valor)
        except (TypeError, ValueError):
            continue  # @no-log-ok: clave no numerica = mapping corrupto, se ignora esa entrada
    return [[mapping.get(cell, cell) for cell in row] for row in grid]

def _apply_flood_fill(params: dict[str, Any], grid: Grid) -> Grid:
    # Defaults -1: una semilla ausente cae fuera de rango y degrada a no-op igual que el
    # undefined del TS, y de paso ningun indice negativo llega a envolver por el otro extremo.
    x = params.get("x", -1)
    y = params.get("y", -1)
    to = params.get("to", 0)
    h = len(grid)
    w = len(grid[0]) if grid else 0
    if y < 0 or y >= h or x < 0 or x >= w:
        return clone_grid(grid)
    from_color = grid[y][x]
    region = _flood_region(grid, x, y, from_color)
    out = clone_grid(grid)
    for rx, ry in region:
        out[ry][rx] = to
    return out

def _apply_crop_to_bbox(params: dict[str, Any], grid: Grid) -> Grid:
    # Default -1: nunca coincide con un color real (0-15), asi que el bbox cubre la grilla entera
    # y el recorte equivale a un clon -- exactamente lo que hace el TS con undefined.
    background_color = params.get("backgroundColor", -1)
    bbox = foreground_bounding_box(grid, background_color)
    if bbox is None:
        return clone_grid(grid)
    return [grid[y][bbox.min_x : bbox.max_x + 1] for y in range(bbox.min_y, bbox.max_y + 1)]

def _apply_overlay(params: dict[str, Any], grid: Grid, ctx: PrimitiveContext) -> Grid:
    anchor = ctx.anchor_grid
    if anchor is None:
        return clone_grid(grid)
    bg = detect_background_color(grid)  # el fondo se calcula sobre `grid`, NO sobre el ancla
    out: Grid = []
    for y, row in enumerate(grid):
        new_row: list[int] = []
        for x, cell in enumerate(row):
            if cell != bg:
                new_row.append(cell)
            elif 0 <= y < len(anchor) and 0 <= x < len(anchor[y]):
                # `anchor[y]?.[x] ?? cell` del TS: el ancla puede ser mas chica que la grilla.
                new_row.append(anchor[y][x])
            else:
                new_row.append(cell)
        out.append(new_row)
    return out

def _apply_replicate(params: dict[str, Any], grid: Grid) -> Grid:
    times_x = params.get("timesX", 0)
    times_y = params.get("timesY", 0)
    h = len(grid)
    w = len(grid[0]) if grid else 0
    out: Grid = []
    # Con h == 0 (o times_* <= 0) el rango es vacio y nunca se divide por cero.
    for y in range(h * times_y):
        out.append([grid[y % h][x % w] for x in range(w * times_x)])
    return out

def _apply_object_extract(params: dict[str, Any], grid: Grid) -> Grid:
    bg = detect_background_color(grid)
    components = _find_components(grid, bg, params.get("color"))
    if not components:
        return clone_grid(grid)
    with_bbox = [(cells, _bbox_of_cells(cells)) for cells in components]
    # Desempate critico: mayor cantidad de celdas primero; a igual cantidad, menor min_y; a igual
    # min_y, menor min_x. sorted() de Python es estable igual que Array.prototype.sort en V8.
    with_bbox.sort(key=lambda item: (-len(item[0]), item[1].min_y, item[1].min_x))
    chosen_cells, bbox = with_bbox[0]
    chosen_set = set(chosen_cells)
    out: Grid = []
    for y in range(bbox.min_y, bbox.max_y + 1):
        row: list[int] = []
        for x in range(bbox.min_x, bbox.max_x + 1):
            # Las celdas del rectangulo que NO pertenecen a la componente se ponen en fondo.
            row.append(grid[y][x] if (x, y) in chosen_set else bg)
        out.append(row)
    return out

def _apply_conditional_recolor(params: dict[str, Any], grid: Grid) -> Grid:
    from_color = params.get("from")
    to = params.get("to", 0)
    predicate = params.get("predicate")
    h = len(grid)
    w = len(grid[0]) if grid else 0
    out = clone_grid(grid)
    for y in range(h):
        for x in range(w):
            if grid[y][x] != from_color:
                continue
            is_border = x == 0 or y == 0 or x == w - 1 or y == h - 1
            if not is_border:
                # Los 4 vecinos ortogonales estan SIEMPRE dentro de rango justamente porque la
                # celda no toca el borde -- por eso no hace falta guarda de limites aca.
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if grid[ny][nx] != from_color:
                        is_border = True
                        break
            should_recolor = (
                predicate == "all"
                or (predicate == "border" and is_border)
                or (predicate == "interior" and not is_border)
            )
            if should_recolor:
                out[y][x] = to
    return out

def apply_step(step: ProgramStep, grid: Grid, ctx: PrimitiveContext | None = None) -> Grid:
    """Ejecuta un unico paso del DSL sobre `grid`. Un primitivo CONOCIDO con params invalidos
    (fuera de rango, sin ancla, etc.) degrada a un no-op defensivo (clon sin cambios); un NOMBRE
    desconocido lanza. El TS cubre el nombre con exhaustividad en compilacion y su rama default
    devolveria basura en runtime: en Python la falla ruidosa es la traduccion honesta."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    name = step.get("name")  # ver step_to_json: sin la clave, ValueError del DSL, no KeyError
    params = step.get("params") or {}
    if name == "translate":
        return _apply_translate(params, grid)
    if name == "reflect":
        return _apply_reflect(params, grid)
    if name == "rotate":
        return _apply_rotate(params, grid)
    if name == "recolor":
        return _apply_recolor(params, grid)
    if name == "floodFill":
        return _apply_flood_fill(params, grid)
    if name == "cropToBBox":
        return _apply_crop_to_bbox(params, grid)
    if name == "overlay":
        return _apply_overlay(params, grid, ctx)
    if name == "replicate":
        return _apply_replicate(params, grid)
    if name == "objectExtract":
        return _apply_object_extract(params, grid)
    if name == "conditionalRecolor":
        return _apply_conditional_recolor(params, grid)
    raise ValueError(f"paso de DSL desconocido: {name!r}")

def apply_program(program: Program, grid: Grid, ctx: PrimitiveContext | None = None) -> Grid:
    """Ejecuta un programa (secuencia de pasos) sobre `grid`. Programa vacio = identidad, pero
    devuelve un CLON, nunca la grilla de entrada."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    acc = clone_grid(grid)
    for step in program:
        acc = apply_step(step, acc, ctx)
    return acc
