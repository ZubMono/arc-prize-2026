#!/usr/bin/env python3
"""[arc-agi3-kaggle-agent] BL.20783/BL.21555 -- chequeo AUXILIAR: el NUCLEO (`arc_agent/`) corre
con la red deshabilitada a nivel de PROCESO (se bloquea `socket.socket`/`socket.create_connection`/
`socket.getaddrinfo` ANTES de importar el paquete, para detectar tambien intentos de red ocultos
en tiempo de import). Si el nucleo intenta abrir un socket, falla temprano con error explicito.

NO es el criterio de la cadena de entrega (BL.21555). La corrida real de la competencia SI usa
sockets: el framework oficial habla HTTP con un gateway sidecar local (`http://gateway:8001`),
asi que "cero sockets" mediria lo equivocado sobre el entregable. El criterio es
`make verify-local` / `make play-local` (el agente contra juegos reales, offline). Este script
conserva una propiedad mas chica pero valiosa: la POLITICA en si no depende de red ni de LLMs.

Uso: python3 scripts/verify_no_network.py
"""
from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class NetworkDisabledError(RuntimeError):
    """Se dispara si algun codigo intenta abrir un socket de red durante esta corrida."""


def _blocked_socket(*_args: object, **_kwargs: object) -> "socket.socket":
    raise NetworkDisabledError(
        "[verify_no_network] intento de abrir un socket de red detectado -- el agente DEBE ser "
        "100% offline (restriccion dura del notebook Kaggle: SIN INTERNET)."
    )


def _disable_network() -> None:
    socket.socket = _blocked_socket  # type: ignore[assignment,method-assign]
    socket.create_connection = _blocked_socket  # type: ignore[assignment]
    socket.getaddrinfo = _blocked_socket  # type: ignore[assignment]


def _run_smoke_swarm() -> tuple[object, dict]:
    # Import DESPUES de deshabilitar la red -- cualquier import-time network call tambien queda
    # atrapado por el bloqueo de socket.
    from arc_agent.local_harness import LocalGameConfig, LocalGameEnvironment
    from arc_agent.prng import generate_seed
    from arc_agent.prometheus_agent import PrometheusOfflineAgent
    from arc_agent.runner import play_game
    from arc_agent.runtime_report import build_runtime_report, write_runtime_report
    from arc_agent.swarm import SwarmConfig, run_swarm

    game_ids = [f"smoke-game-{i}" for i in range(6)]

    def agent_factory(game_id: str, seed: str) -> "PrometheusOfflineAgent":
        return PrometheusOfflineAgent(game_id=game_id, seed=seed, max_actions=40)

    def environment_factory(game_id: str) -> "LocalGameEnvironment":
        return LocalGameEnvironment(LocalGameConfig(game_id=game_id, win_after_steps=5))

    def bound_play_game(game_id: str, seed: str, deadline_ts: float):
        return play_game(
            game_id=game_id,
            seed=seed,
            deadline_ts=deadline_ts,
            agent_factory=agent_factory,
            environment_factory=environment_factory,
        )

    result = run_swarm(
        game_ids=game_ids,
        play_game=bound_play_game,
        seed_for=lambda _gid: generate_seed(),
        config=SwarmConfig(max_workers=4, budget_seconds=60, safety_margin_seconds=5),
    )

    report = build_runtime_report(result, budget_seconds=60)
    report_path = Path(__file__).resolve().parent.parent / "runtime_reports" / "no_network_smoke.json"
    write_runtime_report(report, report_path)
    return result, report


def main() -> int:
    _disable_network()

    started = time.monotonic()
    result, report = _run_smoke_swarm()
    elapsed = time.monotonic() - started

    game_ids_count = 6
    print("[verify_no_network] OK -- red deshabilitada, sin fugas detectadas.")
    print(
        f"[verify_no_network] {len(result.outcomes)} juegos, {report['gamesWon']} ganados, "
        f"runtime {elapsed:.3f}s (presupuesto smoke: 60s)."
    )
    report_path = Path(__file__).resolve().parent.parent / "runtime_reports" / "no_network_smoke.json"
    print(f"[verify_no_network] reporte: {report_path}")

    if len(result.outcomes) != game_ids_count:
        print("[verify_no_network] ERROR: no todos los juegos completaron.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
