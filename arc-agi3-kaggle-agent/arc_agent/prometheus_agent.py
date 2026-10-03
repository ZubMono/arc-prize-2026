"""[arc-agi3-kaggle-agent/prometheus_agent] BL.20783 -- SOLO REPO, no viaja al entregable
(BL.21555): subclasea el MIRROR local de `Agent` y por eso no encaja en el framework real; su
reemplazo oficial es `kaggle_adapter.MyAgent`, que hereda del `Agent` verdadero. Queda para los
tests del nucleo y scripts/verify_no_network.py, que corren sin el framework instalado. Ver
submission/build_agent.py (frontera).

Politica 100% local: sin llamadas a red ni a APIs de modelos de lenguaje en inferencia --
busqueda/heuristica de exploracion con memoria de estados visitados (ver policy.py)."""
from __future__ import annotations

from .agent import Agent, DEFAULT_MAX_ACTIONS
from .policy import ExplorationPolicy
from .prng import create_seeded_random
from .types import ActionDecision, FrameData


class PrometheusOfflineAgent(Agent):
    """Implementa `is_done`/`choose_action` del framework ARC-AGI-3-Agents con una politica
    completamente offline (sin red, sin LLM): exploracion con memoria de estados + deteccion de
    bordes para ACTION6. Ver policy.py::ExplorationPolicy para el detalle de la heuristica."""

    def __init__(self, game_id: str, seed: str, max_actions: int = DEFAULT_MAX_ACTIONS) -> None:
        super().__init__(game_id)
        self.max_actions = max_actions
        self.seed = seed
        self._policy = ExplorationPolicy(create_seeded_random(seed))

    def is_done(self, frames: list[FrameData], latest_frame: FrameData) -> bool:
        return super().is_done(frames, latest_frame)

    def choose_action(self, frames: list[FrameData], latest_frame: FrameData) -> ActionDecision:
        self.action_counter += 1
        return self._policy.decide(latest_frame)
