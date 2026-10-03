"""[arc-agi3-kaggle-agent] BL.20783 -- tests de arc_agent/local_harness.py (entorno de prueba)."""
from __future__ import annotations

from arc_agent.local_harness import LocalGameConfig, LocalGameEnvironment
from arc_agent.types import ActionDecision, GameAction, GameState


def test_local_environment_wins_after_configured_steps() -> None:
    env = LocalGameEnvironment(LocalGameConfig(game_id="g1", win_after_steps=2))
    frame = env.reset()
    assert frame.state == GameState.NOT_FINISHED

    decision = ActionDecision(action=GameAction.ACTION1, reasoning="test")
    frame = env.step(decision)
    assert frame.state == GameState.NOT_FINISHED
    frame = env.step(decision)
    assert frame.state == GameState.WIN


def test_local_environment_game_over_on_action6_at_origin() -> None:
    env = LocalGameEnvironment(LocalGameConfig(game_id="g1"))
    env.reset()
    decision = ActionDecision(action=GameAction.ACTION6, x=0, y=0, reasoning="test")
    frame = env.step(decision)
    assert frame.state == GameState.GAME_OVER


def test_local_environment_grids_are_deterministic() -> None:
    env_a = LocalGameEnvironment(LocalGameConfig(game_id="g1", grid_seed_value=3))
    env_b = LocalGameEnvironment(LocalGameConfig(game_id="g1", grid_seed_value=3))
    assert env_a.reset().frame == env_b.reset().frame
