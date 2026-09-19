"""[arc-agi3-kaggle-agent] BL.20783 -- tests de arc_agent/swarm.py (orquestacion paralela)."""
from __future__ import annotations

import time

from arc_agent.swarm import GameOutcome, SwarmConfig, run_swarm


def test_run_swarm_plays_all_games_and_reports_elapsed() -> None:
    def fake_play_game(game_id: str, seed: str, deadline_ts: float) -> GameOutcome:
        return GameOutcome(game_id=game_id, final_state="WIN", steps=3, success=True)

    result = run_swarm(
        game_ids=["g1", "g2", "g3"],
        play_game=fake_play_game,
        seed_for=lambda gid: f"seed-{gid}",
        config=SwarmConfig(max_workers=2, budget_seconds=30, safety_margin_seconds=1),
    )

    assert len(result.outcomes) == 3
    assert all(o.success for o in result.outcomes)
    assert result.elapsed_seconds >= 0
    assert result.deadline_hit is False


def test_run_swarm_captures_individual_game_failures_without_aborting_batch() -> None:
    def flaky_play_game(game_id: str, seed: str, deadline_ts: float) -> GameOutcome:
        if game_id == "bad":
            raise RuntimeError("boom")
        return GameOutcome(game_id=game_id, final_state="WIN", steps=1, success=True)

    result = run_swarm(
        game_ids=["ok1", "bad", "ok2"],
        play_game=flaky_play_game,
        seed_for=lambda gid: "seed",
        config=SwarmConfig(max_workers=3, budget_seconds=30, safety_margin_seconds=1),
    )

    assert len(result.outcomes) == 3
    bad_outcome = next(o for o in result.outcomes if o.game_id == "bad")
    assert bad_outcome.success is False
    assert bad_outcome.error == "boom"


def test_run_swarm_with_already_expired_budget_plays_nothing() -> None:
    def fake_play_game(game_id: str, seed: str, deadline_ts: float) -> GameOutcome:
        return GameOutcome(game_id=game_id, final_state="WIN", steps=1, success=True)

    result = run_swarm(
        game_ids=["g1", "g2"],
        play_game=fake_play_game,
        seed_for=lambda gid: "seed",
        config=SwarmConfig(max_workers=2, budget_seconds=0, safety_margin_seconds=0),
    )
    assert result.outcomes == []
    assert result.deadline_hit is True


def test_run_swarm_stops_at_soft_deadline_leaving_games_unplayed() -> None:
    def slow_play_game(game_id: str, seed: str, deadline_ts: float) -> GameOutcome:
        time.sleep(0.15)
        return GameOutcome(game_id=game_id, final_state="WIN", steps=1, success=True)

    result = run_swarm(
        game_ids=["g1", "g2", "g3", "g4", "g5"],
        play_game=slow_play_game,
        seed_for=lambda gid: "seed",
        config=SwarmConfig(max_workers=1, budget_seconds=0.4, safety_margin_seconds=0),
    )

    assert result.deadline_hit is True
    assert len(result.outcomes) < 5
