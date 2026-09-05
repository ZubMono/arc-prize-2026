"""[arc-agi3-kaggle-agent] BL.20783 -- tests de arc_agent/prometheus_agent.py."""
from __future__ import annotations

from _helpers import make_frame

from arc_agent.prometheus_agent import PrometheusOfflineAgent


def test_choose_action_increments_action_counter() -> None:
    agent = PrometheusOfflineAgent(game_id="g1", seed="seed-x")
    frame = make_frame(available_actions=(1, 2))
    assert agent.action_counter == 0
    agent.choose_action([frame], frame)
    assert agent.action_counter == 1


def test_is_done_respects_max_actions_override() -> None:
    agent = PrometheusOfflineAgent(game_id="g1", seed="seed-x", max_actions=2)
    frame = make_frame(available_actions=(1, 2))
    agent.choose_action([frame], frame)
    agent.choose_action([frame], frame)
    assert agent.is_done([frame], frame) is True


def test_same_seed_produces_deterministic_first_action() -> None:
    frame = make_frame(available_actions=(1, 2, 3))
    agent_a = PrometheusOfflineAgent(game_id="g1", seed="reproducible-seed")
    agent_b = PrometheusOfflineAgent(game_id="g1", seed="reproducible-seed")
    assert agent_a.choose_action([frame], frame) == agent_b.choose_action([frame], frame)
