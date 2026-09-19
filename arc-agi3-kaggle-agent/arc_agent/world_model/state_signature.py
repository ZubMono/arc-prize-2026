"""[arc-agi3-kaggle-agent/world_model/state_signature] -- firma hasheable de un estado (grilla +
acciones disponibles) y deteccion de no-ops entre frames sucesivos. Puerto de
arc-agi-runner/src/worldModel/stateSignature.ts (BL.20860).

Misma idea que policy.py::compute_signature, pero sobre el tipo Grid del world model y con un hash
entero estable y portable: NO se usa el hash() de Python, que esta aleatorizado por proceso via
PYTHONHASHSEED y por lo tanto no es reproducible entre corridas ni comparable contra un fixture.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Protocol

# MASK32 se importa de grid.py (fuente unica de la aritmetica de 32 bits del motor): Python tiene
# enteros de precision arbitraria y sin la mascara el hash divergiria del TS al primer overflow.
from .grid import MASK32, Grid, VolatilityMask, grids_equal_masked, hash_grid_masked

# Constante de mezcla de la familia Fibonacci hashing (2^32 / phi), la misma del TS.
_GOLDEN_RATIO_32: Final[int] = 0x9E3779B9


class FrameLike(Protocol):
    """Lo UNICO que este modulo necesita del wire format ARC-AGI-3. Protocol en vez de importar
    FrameData desde `..types`: el builder del notebook solo desmonta imports relativos de UN punto,
    asi que un import de dos puntos sobrevive al stripping y rompe el .ipynb de submission (que
    corre en namespace plano, sin paquetes). arc_agent.types.FrameData lo satisface
    ESTRUCTURALMENTE, sin herencia ni registro."""

    frame: Sequence[Sequence[Sequence[int]]]
    available_actions: Sequence[int]


def extract_grid(frame: "FrameLike") -> Grid | None:
    """Grilla observable de un frame: la API devuelve UNA O MAS capas consecutivas y la ultima es
    el estado visible tras aplicar el comando. None cuando el frame no trae capas o la ultima viene
    vacia -- ningun consumidor debe asumir grilla presente.

    Fuente unica: la usan la politica y el runner, que DEBEN coincidir en que es "el estado" o la
    firma persistida describiria otra cosa que la que vio quien decidio.

    La conversion a list[list[int]] es la frontera unica entre el wire format (FrameData guarda
    tuplas para ser hasheable) y el world model (listas mutables). La copia ademas protege la
    inmutabilidad del frame frente a los primitivos que mutan celdas por indice."""
    layers = frame.frame
    if not layers:
        return None
    last = layers[len(layers) - 1]
    if not last:
        return None
    return [list(row) for row in last]


def extraer_grid_multicapa(frame: "FrameLike") -> list[Grid]:
    """BL.22236 -- TODAS las capas OBSERVABLES de un frame, no solo la ultima (ver `extract_grid`).

    El wire oficial `arcengine.FrameData.frame` es `list[list[list[int]]]`: el motor acumula UNA
    capa por cada `step()` interno mientras la accion anima antes de asentarse
    (arcengine/base_game.py:210-253). `extract_grid` toma deliberadamente SOLO la ultima -- "el
    estado visible tras aplicar el comando" -- porque asi debe seguir siendo LA firma de estado
    (memoria de exploracion, no-ops, mascara de volatilidad: todas comparan el mismo "estado" o
    dejan de ser comparables entre si). Pero esa decision descarta evidencia real: el hilo de
    Kaggle discussion/734369 midio 13/25 juegos publicos con informacion que SOLO existe en una
    capa intermedia (ej. sp80, 624 pixeles visibles unicamente durante la animacion de "pouring").

    Esta funcion NO reemplaza `extract_grid` en ningun consumidor de firma -- expone las capas
    intermedias para que OTRO consumidor (memoria de mecanica objeto-centrica, BL.22236) las use
    como evidencia ADICIONAL de la transicion, nunca como el estado. Capas vacias se descartan
    (mismo criterio que `extract_grid`: ninguna vale como grilla)."""
    layers = frame.frame
    if not layers:
        return []
    return [[list(row) for row in layer] for layer in layers if layer]


def compute_frame_signature(
    frame: "FrameLike", mask: VolatilityMask | None = None
) -> str | None:
    """Firma de un frame completo, lista para persistir. Un frame sin grilla devuelve None en vez
    de una firma inventada: el campo ausente se trata como "sin evidencia" y no como "no hubo
    cambio" -- afirmar una firma falsa marcaria transiciones reales como no-ops."""
    grid = extract_grid(frame)
    if grid is None:
        return None
    return str(compute_state_signature(grid, frame.available_actions or [], mask))


def compute_state_signature(
    grid: Grid, available_actions: Sequence[int], mask: VolatilityMask | None = None
) -> int:
    """Firma entera estable de un estado -- combina el hash de la grilla con las acciones
    disponibles NORMALIZADAS (el orden no importa: se ordenan ascendente antes de mezclar). Dos
    frames con la MISMA firma se consideran el mismo estado a efectos de memoria de exploracion y
    deduplicacion de nodos visitados en el planner. Devuelve un entero SIN SIGNO en [0, 2**32).

    Por que esto reproduce el TS exactamente: en JS la suma es aritmetica de Number (exacta, todos
    los operandos caben en 2^53) y solo el ^ posterior aplica ToInt32. `hash << 6` en JS es un
    int32 con signo, pero la diferencia entre su lectura con y sin signo es exactamente 2**32, que
    se cancela al enmascarar la suma; y `hash >>> 2` con hash ya en [0, 2**32) es identico al >> 2
    de Python. El `hash >>> 0` final del TS equivale al & MASK32.

    BL.21558 -- `mask` firma SOLO las celdas estables. Sin ella, un contador de HUD que avanza en
    cada frame hace que ninguna firma se repita jamas y toda la memoria por-estado queda inerte. El
    default None conserva la firma historica exacta."""
    h = hash_grid_masked(grid, mask)
    for action in sorted(available_actions):
        mixed = (action + _GOLDEN_RATIO_32 + ((h << 6) & MASK32) + (h >> 2)) & MASK32
        h = (h ^ mixed) & MASK32
    return h


def is_no_op_transition(
    before: Grid | None, after: Grid | None, mask: VolatilityMask | None = None
) -> bool:
    """True cuando una accion NO cambio nada visible en la grilla -- no-op observado. None en
    cualquiera de los dos lados (sin grilla previa/actual conocida) nunca se afirma no-op: no hay
    evidencia suficiente.

    BL.21558 -- con `mask`, "nada visible" excluye las celdas volatiles. Ese es el punto: sin
    mascara, en ar25-0c556536 se detecto UN solo no-op en 77 pasos pese al round-robin contra las
    paredes del tablero."""
    if before is None or after is None:
        return False
    return grids_equal_masked(before, after, mask)
