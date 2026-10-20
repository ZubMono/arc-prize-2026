"""[arc-agi3-kaggle-agent/world_model/primitives] -- generadores de candidatos DATA-DRIVEN del
DSL a partir de un par (pre, post) observado. Cada propose_* se AUTO-VERIFICA (aplica y compara)
antes de proponerse -- solo devuelve pasos que YA explican el par completo en un solo paso.
enumerate_structural_steps es la contraparte CIEGA (sin `post`) que usa synthesis.py para
componer varios pasos. Puerto de arc-agi-runner/src/worldModel/primitives.ts (BL.20860).

El ORDEN de generacion es load-bearing: synthesis.py rankea los candidatos por prior de Occam con
desempate determinista por clave canonica, y consume esta enumeracion tal cual sale. Cambiar el
orden de un proposer, o el orden en que propose_all_steps los concatena, cambia QUE programa gana
un empate y por lo tanto que modelo de mundo aprende el agente. No reordenar por estetica."""
from __future__ import annotations

from typing import Final

# Los imports relativos van UNO POR LINEA a proposito: submission/build_notebook.py los desmonta
# con una regex de una sola linea (`^from \.\w* import .+$`) para aplanar el paquete dentro del
# notebook de Kaggle. Un import multilinea entre parentesis dejaria las lineas del medio sueltas
# y romperia el .ipynb generado.
from .grid import Grid, detect_background_color, foreground_bounding_box, grids_equal
from .primitive_ops import EMPTY_CONTEXT, PrimitiveContext, Program, ProgramStep
from .primitive_ops import apply_program, apply_step, program_key
from .primitive_ops import make_conditional_recolor, make_crop_to_bbox, make_flood_fill
from .primitive_ops import make_object_extract, make_overlay, make_recolor, make_reflect
from .primitive_ops import make_replicate, make_rotate, make_translate

__all__ = [
    "propose_all_steps",
    "enumerate_structural_steps",
    "apply_step",
    "apply_program",
    "program_key",
    "PrimitiveContext",
    "EMPTY_CONTEXT",
    "Program",
    "ProgramStep",
]

# Desplazamientos que enumera la busqueda ciega. Incluye 0 en cada eje POR SEPARADO para cubrir
# movimientos puramente horizontales o verticales; el par (0, 0) se excluye porque seria un no-op.
_TRANSLATE_DELTAS: Final[tuple[int, ...]] = (-2, -1, 0, 1, 2)
# Factores de tileo de la busqueda ciega. (1, 1) se excluye por la misma razon: es identidad.
_REPLICATE_FACTORS: Final[tuple[int, ...]] = (1, 2, 3)
# Tope duro de tileos por eje al INFERIR replicate de un par observado. Sin el, una grilla de una
# celda "explicaria" cualquier post uniforme con un factor gigante -- coincidencia numerica, no
# una regla de tileo.
_MAX_INFERRED_REPLICATE_FACTOR: Final[int] = 6


def _row_width(grid: Grid) -> int:
    """Ancho segun la fila 0, igual que `grid[0]?.length ?? 0` del TS. Las grillas se asumen
    rectangulares (invariante del world model); grilla vacia y filas vacias dan 0."""
    return len(grid[0]) if grid else 0


def _verifies(step: ProgramStep, pre: Grid, post: Grid, ctx: PrimitiveContext) -> bool:
    """Auto-verificacion: un candidato solo se propone si YA explica el par COMPLETO en un paso.
    Proponer sin verificar ensuciaria la busqueda con hipotesis que despues hay que descartar
    contra todas las observaciones, que es el trabajo caro."""
    return grids_equal(apply_step(step, pre, ctx), post)


def _diff_cells(pre: Grid, post: Grid) -> list[tuple[int, int]] | None:
    """Celdas que cambiaron, en orden ROW-MAJOR (y externo, x interno). Devuelve `None` si las
    grillas no tienen la misma forma -- distinto de `[]` (misma forma, sin cambios): un cambio de
    forma no lo puede explicar ningun primitivo local, mientras que un diff vacio lo explica el
    programa identidad. El orden row-major es load-bearing: la semilla de floodFill es diffs[0]."""
    if len(pre) != len(post):
        return None
    diffs: list[tuple[int, int]] = []
    for y in range(len(pre)):
        row_pre = pre[y]
        row_post = post[y]
        if len(row_pre) != len(row_post):
            return None
        for x in range(len(row_pre)):
            if row_pre[x] != row_post[x]:
                diffs.append((x, y))
    return diffs


def _single_color_diff(pre: Grid, post: Grid) -> tuple[list[tuple[int, int]], int, int] | None:
    """(diffs, color_origen, color_destino) cuando el cambio observado sustituye UN solo color por
    UN solo color. `None` en cualquier otro caso. Es la precondicion compartida de floodFill y
    conditionalRecolor: ambos solo saben expresar un reemplazo mono-color."""
    diffs = _diff_cells(pre, post)
    if not diffs:
        return None
    from_colors = {pre[y][x] for x, y in diffs}
    to_colors = {post[y][x] for x, y in diffs}
    if len(from_colors) != 1 or len(to_colors) != 1:
        return None
    return diffs, next(iter(from_colors)), next(iter(to_colors))


def _flood_region_for_proposal(
    grid: Grid, sx: int, sy: int, color: int
) -> list[tuple[int, int]]:
    """Recalcula la region 4-conexa desde una semilla -- misma logica que el `_flood_region`
    interno de primitive_ops.py, REIMPLEMENTADA aca a proposito (ese helper es privado de aquel
    modulo, no se exporta): permite VERIFICAR que el diff observado es EXACTAMENTE una region
    completa antes de proponer floodFill, en vez de proponer a ciegas y descartar despues.

    Pila explicita, nunca recursion: una region de 64x64 (4096 celdas) desborda el limite de
    recursion de Python."""
    h = len(grid)
    w = _row_width(grid)
    visited: set[tuple[int, int]] = set()
    stack: list[tuple[int, int]] = [(sx, sy)]
    region: list[tuple[int, int]] = []
    while stack:
        x, y = stack.pop()
        if (x, y) in visited:
            continue
        # Las cotas se chequean ANTES de indexar. En JS `grid[-1]` es `undefined` (inofensivo);
        # en Python `grid[-1]` es la ULTIMA fila y la region envolveria la grilla en silencio.
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


def _propose_translate(pre: Grid, post: Grid) -> list[ProgramStep]:
    if len(pre) != len(post) or _row_width(pre) != _row_width(post):
        return []
    # El fondo se detecta sobre `pre` y se usa para AMBOS bbox: medir cada grilla con su propio
    # fondo cambiaria el marco de referencia y el desplazamiento dejaria de ser comparable.
    bg = detect_background_color(pre)
    bbox_pre = foreground_bounding_box(pre, bg)
    bbox_post = foreground_bounding_box(post, bg)
    if bbox_pre is None or bbox_post is None:
        return []
    # Ancho/alto medidos como max - min (SIN +1), igual que el TS: solo se comparan entre si para
    # descartar cambios de forma del foreground, nunca se usan como dimension real.
    if (bbox_pre.max_x - bbox_pre.min_x) != (bbox_post.max_x - bbox_post.min_x):
        return []
    if (bbox_pre.max_y - bbox_pre.min_y) != (bbox_post.max_y - bbox_post.min_y):
        return []
    dx = bbox_post.min_x - bbox_pre.min_x
    dy = bbox_post.min_y - bbox_pre.min_y
    if dx == 0 and dy == 0:
        return []
    step = make_translate(dx, dy)
    return [step] if _verifies(step, pre, post, EMPTY_CONTEXT) else []


def _propose_reflect(pre: Grid, post: Grid) -> list[ProgramStep]:
    out: list[ProgramStep] = []
    for axis in ("horizontal", "vertical"):
        step = make_reflect(axis)
        if _verifies(step, pre, post, EMPTY_CONTEXT):
            out.append(step)
    return out


def _propose_rotate(pre: Grid, post: Grid) -> list[ProgramStep]:
    out: list[ProgramStep] = []
    for quarter_turns in (1, 2, 3):
        step = make_rotate(quarter_turns)
        if _verifies(step, pre, post, EMPTY_CONTEXT):
            out.append(step)
    return out


def _propose_recolor(pre: Grid, post: Grid) -> list[ProgramStep]:
    if len(pre) != len(post):
        return []
    mapping: dict[int, int] = {}
    for y in range(len(pre)):
        if len(pre[y]) != len(post[y]):
            return []
        for x in range(len(pre[y])):
            from_color = pre[y][x]
            to_color = post[y][x]
            # Contradiccion: el mismo color de origen apunta a dos destinos distintos, asi que
            # NINGUN recolor global explica el par. Abandonar entero, no quedarse con la mitad.
            if from_color in mapping and mapping[from_color] != to_color:
                return []
            mapping[from_color] = to_color
    # Recorrido ASCENDENTE por color de origen: el TS itera `Object.entries(mapping)`, que para
    # claves enteras devuelve orden numerico ascendente sin importar el orden de insercion. Fijarlo
    # aca mantiene identica la clave canonica del paso y, con ella, el desempate del ranking.
    non_trivial = {color: mapping[color] for color in sorted(mapping) if color != mapping[color]}
    if not non_trivial:
        return []
    # UNICO proposer que no se auto-verifica: el mapping se construyo recorriendo TODAS las celdas,
    # asi que aplicarlo reproduce `post` por construccion (misma excepcion que el TS).
    return [make_recolor(non_trivial)]


def _propose_flood_fill(pre: Grid, post: Grid) -> list[ProgramStep]:
    single = _single_color_diff(pre, post)
    if single is None:
        return []
    diffs, from_color, to_color = single
    # Semilla = primera celda en row-major. Cualquier celda de la region sirve para pintar lo
    # mismo, pero fijar la primera hace la propuesta DETERMINISTA y la clave canonica estable.
    seed_x, seed_y = diffs[0]
    region = _flood_region_for_proposal(pre, seed_x, seed_y, from_color)
    # El diff tiene que ser la region COMPLETA, no una parte ni una union de blobs sueltos: si
    # sobran o faltan celdas, lo que paso no fue un flood fill aunque los colores coincidan.
    if len(region) != len(diffs):
        return []
    region_set = set(region)
    for cell in diffs:
        if cell not in region_set:
            return []
    step = make_flood_fill(seed_x, seed_y, to_color)
    return [step] if _verifies(step, pre, post, EMPTY_CONTEXT) else []


def _propose_crop_to_bbox(pre: Grid, post: Grid) -> list[ProgramStep]:
    step = make_crop_to_bbox(detect_background_color(pre))
    return [step] if _verifies(step, pre, post, EMPTY_CONTEXT) else []


def _propose_overlay(pre: Grid, post: Grid, ctx: PrimitiveContext) -> list[ProgramStep]:
    # Sin ancla el primitivo degrada a identidad: proponerlo seria proponer un no-op disfrazado.
    if ctx.anchor_grid is None:
        return []
    step = make_overlay()
    # Unico proposer que verifica con el `ctx` recibido en vez de EMPTY_CONTEXT: overlay es el
    # unico primitivo cuyo resultado depende del contexto.
    return [step] if _verifies(step, pre, post, ctx) else []


def _propose_replicate(pre: Grid, post: Grid) -> list[ProgramStep]:
    pre_h = len(pre)
    pre_w = _row_width(pre)
    post_h = len(post)
    post_w = _row_width(post)
    if pre_h == 0 or pre_w == 0:
        return []
    if post_h % pre_h != 0 or post_w % pre_w != 0:
        return []
    # Division entera: la divisibilidad ya quedo validada arriba, asi que el cociente es exacto
    # (el `/` de JS produce un entero aca por la misma razon).
    times_y = post_h // pre_h
    times_x = post_w // pre_w
    if times_x == 1 and times_y == 1:
        return []
    if times_x > _MAX_INFERRED_REPLICATE_FACTOR or times_y > _MAX_INFERRED_REPLICATE_FACTOR:
        return []
    step = make_replicate(times_x, times_y)
    return [step] if _verifies(step, pre, post, EMPTY_CONTEXT) else []


def _propose_object_extract(pre: Grid, post: Grid) -> list[ProgramStep]:
    bg = detect_background_color(pre)
    colors: set[int] = set()
    for row in pre:
        for cell in row:
            if cell != bg:
                colors.add(cell)
    # `None` primero (el objeto mas grande, sin fijar color) y despues cada color ASCENDENTE: el
    # candidato mas GENERAL se enumera antes que los especificos, que es exactamente lo que
    # premia el prior de Occam aguas arriba (a igual longitud gana el que hardcodea menos params).
    candidates: list[int | None] = [None]
    candidates.extend(sorted(colors))
    out: list[ProgramStep] = []
    for color in candidates:
        step = make_object_extract(color)
        if _verifies(step, pre, post, EMPTY_CONTEXT):
            out.append(step)
    return out


def _propose_conditional_recolor(pre: Grid, post: Grid) -> list[ProgramStep]:
    single = _single_color_diff(pre, post)
    if single is None:
        return []
    _diffs, from_color, to_color = single
    out: list[ProgramStep] = []
    # Orden "all" -> "border" -> "interior": con una sola observacion los tres predicados pueden
    # coincidir, y el desempate de complejidad aguas arriba penaliza "all" (es redundante con
    # recolor). El orden de enumeracion se mantiene igual al TS para no mover ese empate.
    for predicate in ("all", "border", "interior"):
        step = make_conditional_recolor(from_color, to_color, predicate)
        if _verifies(step, pre, post, EMPTY_CONTEXT):
            out.append(step)
    return out


def propose_all_steps(
    pre: Grid, post: Grid, ctx: PrimitiveContext | None = None
) -> list[ProgramStep]:
    """TODOS los candidatos data-driven de UN solo paso que expliquen `pre -> post`, cada uno ya
    auto-verificado. Se usa como "finisher" en cada nodo de la busqueda de synthesis.py (tanto en
    profundidad 0 como para cerrar la brecha despues de expandir pasos estructurales).

    Pares identicos devuelven `[]`: ese caso lo cubre el programa vacio (identidad), y proponer un
    paso que no cambia nada solo agregaria ruido al ranking."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    if grids_equal(pre, post):
        return []
    steps: list[ProgramStep] = []
    steps.extend(_propose_translate(pre, post))
    steps.extend(_propose_reflect(pre, post))
    steps.extend(_propose_rotate(pre, post))
    steps.extend(_propose_recolor(pre, post))
    steps.extend(_propose_flood_fill(pre, post))
    steps.extend(_propose_crop_to_bbox(pre, post))
    steps.extend(_propose_overlay(pre, post, ctx))
    steps.extend(_propose_replicate(pre, post))
    steps.extend(_propose_object_extract(pre, post))
    steps.extend(_propose_conditional_recolor(pre, post))
    return steps


def enumerate_structural_steps(grid: Grid) -> list[ProgramStep]:
    """Enumeracion CIEGA y acotada de pasos "estructurales" (geometricos, no necesitan el `post`
    final) -- la usa synthesis.py para EXPANDIR la busqueda mas alla de profundidad 1, ya que los
    propose_* data-driven solo pueden inferir params comparando contra el `post` final, que en una
    composicion de 2+ pasos no coincide con el resultado de un paso intermedio.

    Los primitivos "semanticos" (recolor / floodFill / overlay / conditionalRecolor) se excluyen a
    proposito: solo se prueban como finisher data-driven (propose_all_steps), nunca a ciegas --
    su espacio de params es enorme y sin el `post` no hay nada que lo acote.

    Son 39 pasos en orden fijo (24 translate + 2 reflect + 3 rotate + 8 replicate + 1 cropToBBox
    + 1 objectExtract); ese orden fija el orden de expansion de la BFS y, con el, que programa se
    encuentra primero."""
    steps: list[ProgramStep] = []
    for dx in _TRANSLATE_DELTAS:
        for dy in _TRANSLATE_DELTAS:
            if dx == 0 and dy == 0:
                continue
            steps.append(make_translate(dx, dy))
    for axis in ("horizontal", "vertical"):
        steps.append(make_reflect(axis))
    for quarter_turns in (1, 2, 3):
        steps.append(make_rotate(quarter_turns))
    for times_x in _REPLICATE_FACTORS:
        for times_y in _REPLICATE_FACTORS:
            if times_x == 1 and times_y == 1:
                continue
            steps.append(make_replicate(times_x, times_y))
    steps.append(make_crop_to_bbox(detect_background_color(grid)))
    # objectExtract sin color: la variante mas general (el objeto mas grande). Las variantes por
    # color solo tienen sentido con el `post` a la vista, asi que viven en el proposer.
    steps.append(make_object_extract())
    return steps
