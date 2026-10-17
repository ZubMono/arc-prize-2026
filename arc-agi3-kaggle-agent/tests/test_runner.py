"""[arc-agi3-kaggle-agent] BL.20783 -- tests de arc_agent/runner.py (adaptador Agent<->Environment)."""
from __future__ import annotations

import time

from arc_agent.local_harness import LocalGameConfig, LocalGameEnvironment
from arc_agent.prometheus_agent import PrometheusOfflineAgent
from arc_agent.runner import play_game


def _agent_factory(game_id: str, seed: str) -> PrometheusOfflineAgent:
    return PrometheusOfflineAgent(game_id=game_id, seed=seed, max_actions=50)


def test_play_game_reaches_win_with_prometheus_agent() -> None:
    def environment_factory(game_id: str) -> LocalGameEnvironment:
        return LocalGameEnvironment(LocalGameConfig(game_id=game_id, win_after_steps=5))

    outcome = play_game(
        game_id="g1",
        seed="seed-1",
        deadline_ts=time.monotonic() + 30,
        agent_factory=_agent_factory,
        environment_factory=environment_factory,
    )
    assert outcome.success is True
    assert outcome.final_state == "WIN"
    assert outcome.steps <= 50


def test_play_game_respects_deadline() -> None:
    def agent_factory(game_id: str, seed: str) -> PrometheusOfflineAgent:
        return PrometheusOfflineAgent(game_id=game_id, seed=seed, max_actions=10_000)

    def environment_factory(game_id: str) -> LocalGameEnvironment:
        return LocalGameEnvironment(LocalGameConfig(game_id=game_id, win_after_steps=10_000))

    outcome = play_game(
        game_id="g1",
        seed="seed-1",
        deadline_ts=time.monotonic() - 1,  # ya vencido
        agent_factory=agent_factory,
        environment_factory=environment_factory,
    )
    assert outcome.success is False
    assert outcome.error == "deadline"


def test_play_game_respects_max_steps() -> None:
    def agent_factory(game_id: str, seed: str) -> PrometheusOfflineAgent:
        return PrometheusOfflineAgent(game_id=game_id, seed=seed, max_actions=10_000)

    def environment_factory(game_id: str) -> LocalGameEnvironment:
        return LocalGameEnvironment(LocalGameConfig(game_id=game_id, win_after_steps=10_000))

    outcome = play_game(
        game_id="g1",
        seed="seed-1",
        deadline_ts=time.monotonic() + 30,
        agent_factory=agent_factory,
        environment_factory=environment_factory,
        max_steps=3,
    )
    assert outcome.success is False
    assert outcome.error == "max_steps"
    assert outcome.steps == 3
