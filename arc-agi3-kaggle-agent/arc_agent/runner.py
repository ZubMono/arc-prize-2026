"""[arc-agi3-kaggle-agent/runner] BL.20783 -- SOLO REPO, no viaja al entregable (BL.21555): el
loop real lo maneja `Agent.main()` del framework oficial; este queda para tests locales y
scripts/verify_no_network.py. Ver submission/build_agent.py (frontera).

Adaptador generico que conecta un `Agent`
(is_done + choose_action) a cualquier entorno que implemente el protocolo `GameEnvironment`
(reset/step) -- mismo principio de "cliente inyectable" que `GameRunnerClient` en gameRunner.ts
(BL.20775). En produccion (notebook Kaggle), `environment_factory` construye el entorno REAL que
provee el harness oficial de la competencia; en tests/smoke-test usa `LocalGameEnvironment`
(100% local, ver local_harness.py) -- ver CLAUDE.md, seccion "Punto de integracion"."""
from __future__ import annotations

import time
from typing import Callable, Protocol

from .agent import Agent
from .swarm import GameOutcome
from .types import ActionDecision, FrameData, GameState

DEFAULT_MAX_STEPS = 500


def _nivel(frame: FrameData, campo: str) -> int:
    """Lectura defensiva de un contador de niveles del wire (BL.21557). Un entorno que no lo
    implemente, o que devuelva basura, no debe poder corromper la metrica de seleccion."""
    valor = getattr(frame, campo, 0)
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return 0


class GameEnvironment(Protocol):
    def reset(self) -> FrameData: ...
    def step(self, decision: ActionDecision) -> FrameData: ...


AgentFactory = Callable[[str, str], Agent]
EnvironmentFactory = Callable[[str], GameEnvironment]


def play_game(
    game_id: str,
    seed: str,
    deadline_ts: float,
    agent_factory: AgentFactory,
    environment_factory: EnvironmentFactory,
    now: Callable[[], float] = time.monotonic,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> GameOutcome:
    """Juega UN juego hasta que el agente lo de por terminado (`is_done`), se agote el deadline
    del batch o se alcance `max_steps` -- red de seguridad adicional independiente del tiempo
    (mismo criterio que DEFAULT_MAX_STEPS en gameRunner.ts, BL.20775)."""
    agent = agent_factory(game_id, seed)
    env = environment_factory(game_id)

    latest = env.reset()
    frames: list[FrameData] = [latest]
    steps = 0
    # BL.21557 -- SENAL DENSA: MAXIMO observado, no el ultimo. El frame terminal de un GAME_OVER
    # puede traer `levels_completed` ya en cero, y quedarse con ese valor tiraria a la basura el
    # unico credito parcial que produce una partida perdida -- que es justamente lo que permite
    # comparar dos versiones del agente cuando ninguna gana.
    max_levels = _nivel(latest, "levels_completed")
    win_levels = _nivel(latest, "win_levels")

    def _outcome(success: bool, error: str | None = None) -> GameOutcome:
        return GameOutcome(
            game_id=game_id,
            final_state=latest.state.value,
            steps=steps,
            success=success,
            error=error,
            levels_completed=max_levels,
            win_levels=win_levels,
        )

    while not agent.is_done(frames, latest):
        if now() >= deadline_ts:
            return _outcome(success=False, error="deadline")
        if steps >= max_steps:
            return _outcome(success=False, error="max_steps")

        decision = agent.choose_action(frames, latest)
        latest = env.step(decision)
        frames.append(latest)
        steps += 1
        max_levels = max(max_levels, _nivel(latest, "levels_completed"))
        win_levels = max(win_levels, _nivel(latest, "win_levels"))

    return _outcome(success=latest.state == GameState.WIN)
