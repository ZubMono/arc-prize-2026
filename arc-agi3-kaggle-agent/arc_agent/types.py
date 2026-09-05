"""[arc-agi3-kaggle-agent/types] BL.20783 -- representacion INTERNA de la politica (nacio como
mirror del wire format oficial de docs.arcprize.org/rest_overview, mismo contrato que
projects/arc-agi-runner/src/types.ts). Desde BL.21555 el wire real lo hablan los tipos de
`arcengine` y `kaggle_adapter.py` traduce hacia estos; este modulo SI viaja al entregable porque
es el vocabulario que consume todo el nucleo (frames como tuplas hasheables para la firma de
estado, enums por NOMBRE de accion). Ver submission/build_agent.py (frontera)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GameState(str, Enum):
    NOT_FINISHED = "NOT_FINISHED"
    NOT_STARTED = "NOT_STARTED"
    WIN = "WIN"
    GAME_OVER = "GAME_OVER"


class GameAction(str, Enum):
    """Las 7 acciones estandar + RESET de todo juego ARC-AGI-3 (docs.arcprize.org/actions)."""

    RESET = "RESET"
    ACTION1 = "ACTION1"
    ACTION2 = "ACTION2"
    ACTION3 = "ACTION3"
    ACTION4 = "ACTION4"
    ACTION5 = "ACTION5"
    ACTION6 = "ACTION6"
    ACTION7 = "ACTION7"


COMPLEX_ACTION = GameAction.ACTION6
GRID_MAX_COORD = 63


@dataclass(frozen=True)
class FrameData:
    """Espejo de FrameData del framework oficial ARC-AGI-3-Agents. `frame` es una tupla de
    grillas 64x64 (indices de color 0-15) -- normalmente un solo frame, el wire format permite
    mas de uno por respuesta. Tuplas (no listas) para que la instancia sea hasheable -- se usa
    como firma de estado en la memoria de exploracion (ver policy.py)."""

    game_id: str
    guid: str
    frame: tuple[tuple[tuple[int, ...], ...], ...]
    state: GameState
    available_actions: tuple[int, ...]
    levels_completed: int = 0
    win_levels: int = 0


@dataclass(frozen=True)
class ActionDecision:
    """Decision de accion + razonamiento declarado -- misma transparencia/auditoria de replay
    que ArcEvaluationStep.reasoning en arc-agi-runner (BL.20775)."""

    action: GameAction
    x: int | None = None
    y: int | None = None
    reasoning: str = ""
