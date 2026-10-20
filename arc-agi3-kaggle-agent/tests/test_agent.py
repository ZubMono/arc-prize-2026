"""[arc-agi3-kaggle-agent] BL.20783 -- tests de arc_agent/agent.py (contrato base is_done)."""
from __future__ import annotations

import pytest
from _helpers import make_frame

from arc_agent.agent import Agent
from arc_agent.types import ActionDecision, GameAction, GameState


class _DummyAgent(Agent):
    def choose_action(self, frames, latest_frame):  # noqa: D102 -- test double
        return ActionDecision(action=GameAction.ACTION1, reasoning="dummy")


def test_is_done_true_on_win() -> None:
    agent = _DummyAgent(game_id="g1")
    frame = make_frame(state=GameState.WIN)
    assert agent.is_done([frame], frame) is True


def test_is_done_true_on_game_over() -> None:
    agent = _DummyAgent(game_id="g1")
    frame = make_frame(state=GameState.GAME_OVER)
    assert agent.is_done([frame], frame) is True


def test_is_done_false_while_not_finished_and_under_budget() -> None:
    agent = _DummyAgent(game_id="g1")
    frame = make_frame(state=GameState.NOT_FINISHED)
    assert agent.is_done([frame], frame) is False


def test_is_done_true_when_max_actions_reached() -> None:
    agent = _DummyAgent(game_id="g1")
    agent.max_actions = 1
    agent.action_counter = 1
    frame = make_frame(state=GameState.NOT_FINISHED)
    assert agent.is_done([frame], frame) is True


def test_agent_cannot_be_instantiated_without_choose_action() -> None:
    with pytest.raises(TypeError):
        Agent(game_id="g1")  # type: ignore[abstract]
