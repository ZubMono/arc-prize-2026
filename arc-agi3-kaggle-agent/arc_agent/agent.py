"""[arc-agi3-kaggle-agent/agent] BL.20783 -- mirror manual del contrato publico de la clase
`Agent` del framework oficial ARC-AGI-3-Agents (github.com/arcprize/ARC-AGI-3-Agents):
`is_done(frames, latest_frame)` y `choose_action(frames, latest_frame)`.

SOLO REPO, no viaja al entregable (BL.21555): el entregable hereda del `Agent` REAL del framework
(que viaja en el dataset de la competencia) via `kaggle_adapter.MyAgent`. Este mirror queda para
testear el nucleo 100% offline sin instalar el framework (lo usan los tests locales, swarm.py y
prometheus_agent.py). Ver submission/build_agent.py (frontera)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .types import ActionDecision, FrameData, GameState

DEFAULT_MAX_ACTIONS = 500


class Agent(ABC):
    """Clase base -- mismo nombre/metodos que el framework oficial. Subclases DEBEN implementar
    `choose_action`; `is_done` trae un default razonable (fin de partida o tope de acciones) que
    puede overridearse si hace falta un criterio distinto."""

    max_actions: int = DEFAULT_MAX_ACTIONS

    def __init__(self, game_id: str) -> None:
        self.game_id = game_id
        self.action_counter = 0

    def is_done(self, frames: list[FrameData], latest_frame: FrameData) -> bool:
        if latest_frame.state in (GameState.WIN, GameState.GAME_OVER):
            return True
        return self.action_counter >= self.max_actions

    @abstractmethod
    def choose_action(self, frames: list[FrameData], latest_frame: FrameData) -> ActionDecision:
        ...
