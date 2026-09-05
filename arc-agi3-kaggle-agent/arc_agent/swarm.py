"""[arc-agi3-kaggle-agent/swarm] BL.20783 -- SOLO REPO, no viaja al entregable (BL.21555): el
framework oficial `ARC-AGI-3-Agents` trae su propio Swarm y orquesta el los juegos; este queda
para los tests locales y scripts/verify_no_network.py. Ver submission/build_agent.py (frontera).

Paraleliza la ejecucion de un batch de juegos bajo
un presupuesto de tiempo GLOBAL duro (diseno: 9 horas, restriccion del notebook Kaggle). Mismo
principio de deadline inyectable que projects/arc-agi-runner/src/gameRunner.ts (BL.20775), pero a
nivel de BATCH completo (no de un solo juego) y con paralelismo real (ThreadPoolExecutor) -- 9h
para docenas de juegos exige correr varios en simultaneo. El Swarm NO puede matar un hilo a la
fuerza si `play_game` se cuelga: confia en que respeta `deadline_ts` (mismo contrato de "deadline
inyectable, chequeado en cada vuelta" que gameRunner.ts -- nunca un kill forzado)."""
from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Protocol


class PlayGameFn(Protocol):
    def __call__(self, game_id: str, seed: str, deadline_ts: float) -> "GameOutcome": ...


@dataclass(frozen=True)
class GameOutcome:
    game_id: str
    final_state: str
    steps: int
    success: bool
    error: str | None = None
    # BL.21557 -- SENAL DENSA. Sin esto un batch entero de derrotas es indistinguible de otro: todas
    # las partidas reportan success=False y no hay forma de decir si una version del agente es mejor
    # que la anterior. `levels_completed` es el credito parcial que puntua el leaderboard oficial
    # (submission.parquet tiene columna `score` ENTERA); `win_levels` permite normalizar entre juegos
    # de distinta longitud. Con default 0 para no romper a quien construya un GameOutcome sin ellos
    # (los caminos de error del Swarm, por ejemplo, donde no hay progreso que informar).
    levels_completed: int = 0
    win_levels: int = 0


@dataclass(frozen=True)
class SwarmResult:
    outcomes: list[GameOutcome]
    elapsed_seconds: float
    deadline_hit: bool


DEFAULT_BUDGET_SECONDS = 9 * 60 * 60  # 9 horas -- tope duro del notebook Kaggle
DEFAULT_SAFETY_MARGIN_SECONDS = 5 * 60  # margen para cerrar prolijo antes del limite real


@dataclass
class SwarmConfig:
    max_workers: int = 4
    budget_seconds: float = DEFAULT_BUDGET_SECONDS
    safety_margin_seconds: float = DEFAULT_SAFETY_MARGIN_SECONDS


def run_swarm(
    game_ids: list[str],
    play_game: PlayGameFn,
    seed_for: Callable[[str], str],
    config: SwarmConfig | None = None,
    now: Callable[[], float] = time.monotonic,
) -> SwarmResult:
    """Corre `game_ids` en paralelo (hasta `max_workers` a la vez) respetando un deadline global
    blando (`budget_seconds - safety_margin_seconds`). Una falla de un juego individual (excepcion
    en `play_game`) se captura como `GameOutcome` fallido -- nunca tumba el batch completo."""
    cfg = config or SwarmConfig()
    started_at = now()
    soft_deadline = started_at + cfg.budget_seconds - cfg.safety_margin_seconds

    outcomes: list[GameOutcome] = []
    remaining = list(game_ids)
    pending: dict[Future, str] = {}
    deadline_hit = False

    pool = ThreadPoolExecutor(max_workers=max(1, cfg.max_workers))
    try:

        def submit_next() -> None:
            nonlocal deadline_hit
            if not remaining:
                return
            if now() >= soft_deadline:
                deadline_hit = True
                return
            game_id = remaining.pop(0)
            future = pool.submit(play_game, game_id, seed_for(game_id), soft_deadline)
            pending[future] = game_id

        for _ in range(min(cfg.max_workers, len(remaining))):
            submit_next()

        while pending:
            if now() >= soft_deadline:
                deadline_hit = deadline_hit or bool(remaining)
                break
            done, _ = wait(pending.keys(), timeout=1.0, return_when=FIRST_COMPLETED)
            for future in done:
                game_id = pending.pop(future)
                try:
                    outcomes.append(future.result())
                except Exception as exc:  # noqa: BLE001 -- un juego individual no tumba el batch
                    outcomes.append(
                        GameOutcome(
                            game_id=game_id,
                            final_state="GAME_OVER",
                            steps=0,
                            success=False,
                            error=str(exc),
                        )
                    )
                submit_next()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)

    elapsed = now() - started_at
    return SwarmResult(outcomes=outcomes, elapsed_seconds=elapsed, deadline_hit=deadline_hit)
