"""[arc-agi3-kaggle-agent] BL.20783 -- tests de arc_agent/types.py."""
from __future__ import annotations

from arc_agent.types import ActionDecision, FrameData, GameAction, GameState


def test_game_action_values_match_arc_agi3_wire_format() -> None:
    assert GameAction.RESET.value == "RESET"
    assert GameAction.ACTION6.value == "ACTION6"
    assert {a.value for a in GameAction} == {
        "RESET",
        "ACTION1",
        "ACTION2",
        "ACTION3",
        "ACTION4",
        "ACTION5",
        "ACTION6",
        "ACTION7",
    }


def test_frame_data_is_hashable_for_use_as_memory_signature() -> None:
    frame = FrameData(
        game_id="g1",
        guid="guid-1",
        frame=((tuple(range(4)),) * 4,),
        state=GameState.NOT_FINISHED,
        available_actions=(1, 2),
    )
    signature = hash((frame.frame, frame.available_actions))
    assert isinstance(signature, int)


def test_action_decision_defaults() -> None:
    decision = ActionDecision(action=GameAction.ACTION1)
    assert decision.x is None
    assert decision.y is None
    assert decision.reasoning == ""
