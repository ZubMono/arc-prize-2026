"""[arc-agi3-kaggle-agent/tests] BL.20783 -- helpers compartidos entre archivos de tests
(construccion de FrameData sinteticos, sin depender de red ni del harness real)."""
from __future__ import annotations

from arc_agent.types import FrameData, GameState


def make_frame(
    game_id: str = "g1",
    guid: str = "guid-1",
    state: GameState = GameState.NOT_FINISHED,
    available_actions: tuple[int, ...] = (1, 2, 3),
    grid_value: int = 0,
    levels_completed: int = 0,
    win_levels: int = 0,
) -> FrameData:
    row = tuple(grid_value for _ in range(8))
    grid = (tuple(row for _ in range(8)),)
    return FrameData(
        game_id=game_id,
        guid=guid,
        frame=grid,
        state=state,
        available_actions=available_actions,
        levels_completed=levels_completed,
        win_levels=win_levels,
    )
