"""[arc-agi3-kaggle-agent/local_harness] BL.20783 -- entorno LOCAL determinista y 100% offline,
usado UNICAMENTE por tests y por el chequeo auxiliar de red deshabilitada
(scripts/verify_no_network.py). SOLO REPO: jamas viaja al entregable (ver
submission/build_agent.py). NO es el juego real de ARC-AGI-3 (que corre detras de la API
oficial) -- es un motor de juguete que respeta el mismo contrato de wire (FrameData/GameAction/
GameState) para poder ejercitar Swarm + Agent + Policy de punta a punta sin red, probando que
ninguna dependencia oculta intenta abrir un socket."""
from __future__ import annotations

from dataclasses import dataclass

from .types import ActionDecision, FrameData, GameAction, GameState

GRID_SIZE = 64


@dataclass
class LocalGameConfig:
    game_id: str
    win_after_steps: int = 8
    grid_seed_value: int = 1
    # BL.21557 -- cada cuantos pasos el juego de juguete "sube de nivel". Existe para poder ejercitar
    # la senal densa (levels_completed/win_levels) de punta a punta sin red: antes el harness
    # devolvia siempre 0 y ningun test podia distinguir progreso de ausencia de progreso.
    steps_por_nivel: int = 4


class LocalGameEnvironment:
    """Simula un juego minimo: cada ACTION 'avanza' un contador; al llegar a `win_after_steps`
    devuelve WIN. ACTION6 en (0,0) fuerza GAME_OVER anticipado (ejercita el path de derrota).
    Grillas deterministicas (no aleatorias), derivadas del step actual."""

    def __init__(self, config: LocalGameConfig) -> None:
        self._config = config
        self._step = 0
        self._guid_counter = 0

    def _grid(self) -> tuple[tuple[tuple[int, ...], ...], ...]:
        value = (self._config.grid_seed_value + self._step) % 16
        row = tuple(value for _ in range(GRID_SIZE))
        grid = tuple(row for _ in range(GRID_SIZE))
        return (grid,)

    def _niveles(self) -> tuple[int, int]:
        """BL.21557 -- (levels_completed, win_levels) del estado actual. Deterministicos, derivados
        del paso: mismo criterio que el resto del harness (nada aleatorio, todo reproducible)."""
        por_nivel = max(1, self._config.steps_por_nivel)
        completados = self._step // por_nivel
        totales = max(1, -(-self._config.win_after_steps // por_nivel))  # ceil
        return completados, totales

    def _frame(self, state: GameState) -> FrameData:
        self._guid_counter += 1
        completados, totales = self._niveles()
        return FrameData(
            game_id=self._config.game_id,
            guid=f"{self._config.game_id}-guid-{self._guid_counter}",
            frame=self._grid(),
            state=state,
            available_actions=(1, 2, 3, 4, 5, 7) if state == GameState.NOT_FINISHED else (),
            levels_completed=completados,
            win_levels=totales,
        )

    def reset(self) -> FrameData:
        self._step = 0
        return self._frame(GameState.NOT_FINISHED)

    def step(self, decision: ActionDecision) -> FrameData:
        if decision.action == GameAction.ACTION6 and decision.x == 0 and decision.y == 0:
            return self._frame(GameState.GAME_OVER)
        self._step += 1
        if self._step >= self._config.win_after_steps:
            return self._frame(GameState.WIN)
        return self._frame(GameState.NOT_FINISHED)
