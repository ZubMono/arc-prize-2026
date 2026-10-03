"""[arc-agi3-kaggle-agent/runtime_report] BL.20783 -- SOLO REPO, no viaja al entregable
(BL.21555): el parquet de la submission lo emite el gateway de Kaggle, no nosotros. Queda para
el reporte local de scripts/verify_no_network.py. Ver submission/build_agent.py (frontera).

Mide el runtime total de una corrida del
Swarm y arma un reporte JSON local. Sin persistir a ningun backend remoto -- el notebook Kaggle no
tiene red ni Mongo; el reporte es un artefacto de archivo plano que queda en el output del
notebook (mismo espiritu que replayMetadata en arc-agi-runner, pero sin el destino Mongo)."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from .swarm import SwarmResult

NINE_HOURS_SECONDS = 9 * 60 * 60


def run_score(outcome) -> int:
    """BL.21557 -- score ENTERO con CREDITO PARCIAL de una partida, alineado con el `score` del
    submission.parquet que produce el gateway oficial de Kaggle (el leaderboard NO es binario).

    Una victoria nunca puntua menos que 1 aunque el juego no informe niveles: sin ese piso, ganar un
    juego de un solo nivel que reporta `levels_completed: 0` valdria lo mismo que perderlo, y la
    regresion frente al conteo de victorias anterior pasaria inadvertida.

    Espejo exacto de `computeRunScore` en projects/arc-agi-runner/src/levelProgress.ts."""
    base = max(0, int(getattr(outcome, "levels_completed", 0) or 0))
    return max(base, 1) if outcome.success else base


def build_runtime_report(result: SwarmResult, budget_seconds: float = NINE_HOURS_SECONDS) -> dict:
    wins = sum(1 for o in result.outcomes if o.success)
    # BL.21557 -- el numero que hay que ver SUBIR entre versiones del agente. Antes el reporte solo
    # traia `gamesWon`, que en la practica era 0 en todos los batches: dos versiones distintas
    # producian exactamente el mismo reporte y era imposible elegir entre ellas.
    scores = [run_score(o) for o in result.outcomes]
    max_level = max((int(getattr(o, "levels_completed", 0) or 0) for o in result.outcomes), default=0)
    return {
        "elapsedSeconds": round(result.elapsed_seconds, 3),
        "elapsedHours": round(result.elapsed_seconds / 3600, 4),
        "budgetSeconds": budget_seconds,
        "withinBudget": result.elapsed_seconds <= budget_seconds,
        "deadlineHit": result.deadline_hit,
        "gamesPlayed": len(result.outcomes),
        "gamesWon": wins,
        "totalScore": sum(scores),
        "maxLevelReached": max_level,
        "gamesWithProgress": sum(1 for s in scores if s > 0),
        "outcomes": [asdict(o) for o in result.outcomes],
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def write_runtime_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
