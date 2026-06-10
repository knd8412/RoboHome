"""Tests for ``robohome.harness.observation``."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from robohome.harness.actions import Direction
from robohome.harness.observation import (
    Exit,
    HeldObject,
    LastAction,
    Observation,
    RobotState,
    VisibleObject,
    WorldView,
    build_observation,
    observation_to_llm_text,
    summarize_observation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_robot_state(**overrides) -> RobotState:
    defaults = dict(
        room="kitchen",
        position=(5, 8),
        facing=Direction.NORTH,
        holding=None,
    )
    defaults.update(overrides)
    return RobotState(**defaults)


def make_world_view(**overrides) -> WorldView:
    defaults = dict(
        current_room="kitchen",
        room_description="You are in the kitchen.",
        visible_objects=[],
        exits=[],
    )
    defaults.update(overrides)
    return WorldView(**defaults)


# ---------------------------------------------------------------------------
# VisibleObject
# ---------------------------------------------------------------------------


class TestVisibleObject:
    def test_valid(self):
        obj = VisibleObject(
            id="sink_1",
            type="sink",
            direction=Direction.NORTH,
            distance=1,
            state={"water_running": False},
        )
        assert obj.id == "sink_1"
        assert obj.direction == Direction.NORTH

    def test_state_defaults_to_empty(self):
        obj = VisibleObject(
            id="sink_1",
            type="sink",
            direction=Direction.NORTH,
            distance=1,
        )
        assert obj.state == {}

    def test_rejects_negative_distance(self):
        with pytest.raises(ValidationError):
            VisibleObject(
                id="sink_1",
                type="sink",
                direction=Direction.NORTH,
                distance=-1,
            )

    def test_rejects_empty_id(self):
        with pytest.raises(ValidationError):
            VisibleObject(
                id="",
                type="sink",
                direction=Direction.NORTH,
                distance=1,
            )

    def test_rejects_unknown_direction(self):
        with pytest.raises(ValidationError):
            VisibleObject(
                id="sink_1",
                type="sink",
                direction="northwest",  # not in Direction
                distance=1,
            )

    def test_rejects_extra_field(self):
        with pytest.raises(ValidationError):
            VisibleObject(
                id="sink_1",
                type="sink",
                direction=Direction.NORTH,
                distance=1,
                color="silver",
            )


# ---------------------------------------------------------------------------
# Exit
# ---------------------------------------------------------------------------


class TestExit:
    def test_valid(self):
        e = Exit(
            to_room="hallway",
            direction=Direction.SOUTH,
            via="door_2",
            is_open=True,
        )
        assert e.to_room == "hallway"
        assert e.is_open is True

    def test_rejects_missing_fields(self):
        with pytest.raises(ValidationError):
            Exit(to_room="hallway", direction=Direction.SOUTH)


# ---------------------------------------------------------------------------
# HeldObject
# ---------------------------------------------------------------------------


class TestHeldObject:
    def test_valid(self):
        h = HeldObject(
            id="kettle_1",
            type="kettle",
            state={"contains": "water"},
        )
        assert h.id == "kettle_1"

    def test_state_optional(self):
        h = HeldObject(id="kettle_1", type="kettle")
        assert h.state == {}


# ---------------------------------------------------------------------------
# RobotState
# ---------------------------------------------------------------------------


class TestRobotState:
    def test_valid_empty_hand(self):
        r = RobotState(
            room="kitchen",
            position=(5, 8),
            facing=Direction.NORTH,
        )
        assert r.holding is None
        assert r.position == (5, 8)

    def test_valid_with_held(self):
        r = RobotState(
            room="kitchen",
            position=(5, 8),
            facing=Direction.NORTH,
            holding=HeldObject(id="kettle_1", type="kettle"),
        )
        assert r.holding is not None
        assert r.holding.type == "kettle"

    def test_position_serializes_as_list(self):
        r = RobotState(
            room="kitchen",
            position=(5, 8),
            facing=Direction.NORTH,
        )
        blob = json.loads(r.model_dump_json())
        assert blob["position"] == [5, 8]


# ---------------------------------------------------------------------------
# LastAction
# ---------------------------------------------------------------------------


class TestLastAction:
    def test_valid_success(self):
        la = LastAction(
            action="pick_up",
            args={"object_id": "kettle_1"},
            result="success",
            message="You picked up the kettle.",
        )
        assert la.result == "success"

    def test_valid_noted(self):
        la = LastAction(
            action="note",
            args={"text": "bedroom is north"},
            result="noted",
            message="Note recorded.",
        )
        assert la.result == "noted"

    def test_rejects_bad_result(self):
        with pytest.raises(ValidationError):
            LastAction(
                action="pick_up",
                args={},
                result="maybe",
                message="...",
            )


# ---------------------------------------------------------------------------
# WorldView
# ---------------------------------------------------------------------------


class TestWorldView:
    def test_minimal(self):
        wv = WorldView(
            current_room="kitchen",
            room_description="You are in the kitchen.",
        )
        assert wv.visible_objects == []
        assert wv.exits == []

    def test_with_objects_and_exits(self):
        wv = make_world_view(
            visible_objects=[
                VisibleObject(
                    id="sink_1",
                    type="sink",
                    direction=Direction.NORTH,
                    distance=1,
                ),
            ],
            exits=[
                Exit(
                    to_room="hallway",
                    direction=Direction.SOUTH,
                    via="door_2",
                    is_open=True,
                ),
            ],
        )
        assert len(wv.visible_objects) == 1
        assert len(wv.exits) == 1

    def test_rejects_empty_room_name(self):
        with pytest.raises(ValidationError):
            WorldView(current_room="", room_description="x")


# ---------------------------------------------------------------------------
# build_observation
# ---------------------------------------------------------------------------


class TestBuildObservation:
    def test_minimal(self):
        obs = build_observation(
            step=0,
            task="go to the bedroom",
            world_view=make_world_view(),
            robot=make_robot_state(),
        )
        assert obs.step == 0
        assert obs.task == "go to the bedroom"
        assert obs.last_action is None
        assert obs.notes == ""
        assert obs.stuck_hint is None

    def test_passes_through_world_view(self):
        wv = make_world_view(
            room_description="You see a cozy kitchen.",
            exits=[
                Exit(
                    to_room="hallway",
                    direction=Direction.SOUTH,
                    via="door_2",
                    is_open=True,
                ),
            ],
        )
        obs = build_observation(
            step=1,
            task="explore",
            world_view=wv,
            robot=make_robot_state(),
        )
        assert obs.room_description == "You see a cozy kitchen."
        assert obs.exits[0].to_room == "hallway"

    def test_sorts_objects_by_distance(self):
        wv = make_world_view(
            visible_objects=[
                VisibleObject(
                    id="far_1",
                    type="fridge",
                    direction=Direction.EAST,
                    distance=3,
                ),
                VisibleObject(
                    id="near_1",
                    type="sink",
                    direction=Direction.NORTH,
                    distance=1,
                ),
                VisibleObject(
                    id="mid_1",
                    type="counter",
                    direction=Direction.NORTH,
                    distance=2,
                ),
            ]
        )
        obs = build_observation(
            step=0,
            task="x",
            world_view=wv,
            robot=make_robot_state(),
        )
        assert [o.id for o in obs.visible_objects] == ["near_1", "mid_1", "far_1"]

    def test_stable_secondary_sort_by_id(self):
        # Two objects at the same distance should sort by id alphabetically
        # for deterministic output.
        wv = make_world_view(
            visible_objects=[
                VisibleObject(
                    id="zebra_1",
                    type="zebra",
                    direction=Direction.EAST,
                    distance=2,
                ),
                VisibleObject(
                    id="apple_1",
                    type="apple",
                    direction=Direction.EAST,
                    distance=2,
                ),
            ]
        )
        obs = build_observation(
            step=0,
            task="x",
            world_view=wv,
            robot=make_robot_state(),
        )
        assert [o.id for o in obs.visible_objects] == ["apple_1", "zebra_1"]

    def test_with_last_action_notes_and_hint(self):
        la = LastAction(
            action="pick_up",
            args={"object_id": "kettle_1"},
            result="success",
            message="You picked up the kettle.",
        )
        obs = build_observation(
            step=12,
            task="make tea",
            world_view=make_world_view(),
            robot=make_robot_state(
                holding=HeldObject(id="kettle_1", type="kettle"),
            ),
            last_action=la,
            notes="bedroom is north of the hallway",
            stuck_hint="You appear stuck, reconsider your plan.",
        )
        assert obs.step == 12
        assert obs.last_action is not None
        assert obs.last_action.message.startswith("You picked")
        assert "bedroom" in obs.notes
        assert obs.stuck_hint is not None


# ---------------------------------------------------------------------------
# summarize_observation
# ---------------------------------------------------------------------------


class TestSummarizeObservation:
    def test_minimal(self):
        obs = build_observation(
            step=0,
            task="x",
            world_view=make_world_view(),
            robot=make_robot_state(),
        )
        s = summarize_observation(obs)
        assert "step 0" in s
        assert "kitchen" in s

    def test_includes_held(self):
        obs = build_observation(
            step=5,
            task="x",
            world_view=make_world_view(),
            robot=make_robot_state(
                holding=HeldObject(id="kettle_1", type="kettle"),
            ),
        )
        s = summarize_observation(obs)
        assert "holding kettle" in s

    def test_includes_visible_objects(self):
        wv = make_world_view(
            visible_objects=[
                VisibleObject(
                    id="sink_1",
                    type="sink",
                    direction=Direction.NORTH,
                    distance=1,
                ),
                VisibleObject(
                    id="fridge_1",
                    type="fridge",
                    direction=Direction.EAST,
                    distance=2,
                ),
            ]
        )
        obs = build_observation(
            step=0,
            task="x",
            world_view=wv,
            robot=make_robot_state(),
        )
        s = summarize_observation(obs)
        assert "sink" in s and "fridge" in s

    def test_truncates_long_visible_lists(self):
        wv = make_world_view(
            visible_objects=[
                VisibleObject(
                    id=f"obj_{i}",
                    type=f"thing_{i}",
                    direction=Direction.NORTH,
                    distance=1,
                )
                for i in range(8)
            ]
        )
        obs = build_observation(
            step=0,
            task="x",
            world_view=wv,
            robot=make_robot_state(),
        )
        s = summarize_observation(obs)
        assert "..." in s

    def test_includes_last_action(self):
        la = LastAction(
            action="move",
            args={"direction": "north"},
            result="failed",
            message="A wall blocks you.",
        )
        obs = build_observation(
            step=1,
            task="x",
            world_view=make_world_view(),
            robot=make_robot_state(),
            last_action=la,
        )
        s = summarize_observation(obs)
        assert "move" in s
        assert "failed" in s


# ---------------------------------------------------------------------------
# observation_to_llm_text
# ---------------------------------------------------------------------------


class TestObservationToLlmText:
    def test_produces_valid_json(self):
        obs = build_observation(
            step=0,
            task="x",
            world_view=make_world_view(),
            robot=make_robot_state(),
        )
        text = observation_to_llm_text(obs)
        parsed = json.loads(text)
        assert parsed["step"] == 0
        assert parsed["task"] == "x"

    def test_excludes_none_fields(self):
        obs = build_observation(
            step=0,
            task="x",
            world_view=make_world_view(),
            robot=make_robot_state(),
        )
        parsed = json.loads(observation_to_llm_text(obs))
        assert "last_action" not in parsed
        assert "stuck_hint" not in parsed
        # Empty notes IS kept (absence is informative).
        assert parsed["notes"] == ""

    def test_position_is_list_in_json(self):
        obs = build_observation(
            step=0,
            task="x",
            world_view=make_world_view(),
            robot=make_robot_state(),
        )
        parsed = json.loads(observation_to_llm_text(obs))
        assert parsed["robot"]["position"] == [5, 8]

    def test_includes_optional_fields_when_set(self):
        la = LastAction(
            action="move",
            args={"direction": "north"},
            result="success",
            message="You moved.",
        )
        obs = build_observation(
            step=3,
            task="x",
            world_view=make_world_view(),
            robot=make_robot_state(),
            last_action=la,
            stuck_hint="hint",
        )
        parsed = json.loads(observation_to_llm_text(obs))
        assert parsed["last_action"]["action"] == "move"
        assert parsed["stuck_hint"] == "hint"

    def test_holding_object_serializes(self):
        obs = build_observation(
            step=0,
            task="x",
            world_view=make_world_view(),
            robot=make_robot_state(
                holding=HeldObject(
                    id="kettle_1",
                    type="kettle",
                    state={"contains": "water"},
                ),
            ),
        )
        parsed = json.loads(observation_to_llm_text(obs))
        assert parsed["robot"]["holding"]["type"] == "kettle"
        assert parsed["robot"]["holding"]["state"]["contains"] == "water"
