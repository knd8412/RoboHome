"""Tests for ``robohome.harness.actions``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from robohome.harness.actions import (
    ALL_ACTION_TYPES,
    ActionResult,
    Close,
    Direction,
    Done,
    LookAround,
    Move,
    Note,
    Open,
    PickUp,
    PutDown,
    Turn,
    Use,
    gemini_function_call_to_action,
    parse_action,
    to_gemini_tools,
)


# ---------------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------------


class TestDirection:
    def test_accepts_all_four(self):
        assert Direction("north") == Direction.NORTH
        assert Direction("south") == Direction.SOUTH
        assert Direction("east") == Direction.EAST
        assert Direction("west") == Direction.WEST

    def test_rejects_unknown(self):
        with pytest.raises(ValueError):
            Direction("up")

    def test_rejects_uppercase(self):
        # We use lowercase consistently. If the LLM returns "North" the
        # parser should fail and ask it to retry.
        with pytest.raises(ValueError):
            Direction("North")

    def test_rejects_single_letter(self):
        with pytest.raises(ValueError):
            Direction("N")


# ---------------------------------------------------------------------------
# Individual action models
# ---------------------------------------------------------------------------


class TestMove:
    def test_valid(self):
        m = Move(direction=Direction.NORTH)
        assert m.type == "move"
        assert m.direction == Direction.NORTH

    def test_accepts_string_direction(self):
        m = Move(direction="east")
        assert m.direction == Direction.EAST

    def test_rejects_bad_direction(self):
        with pytest.raises(ValidationError):
            Move(direction="up")

    def test_rejects_missing_direction(self):
        with pytest.raises(ValidationError):
            Move()

    def test_rejects_extra_field(self):
        with pytest.raises(ValidationError):
            Move(direction="north", object_id="kettle_1")


class TestTurn:
    def test_valid(self):
        t = Turn(direction="south")
        assert t.type == "turn"
        assert t.direction == Direction.SOUTH


class TestLookAround:
    def test_valid_no_args(self):
        la = LookAround()
        assert la.type == "look_around"

    def test_rejects_extra_field(self):
        with pytest.raises(ValidationError):
            LookAround(direction="north")


class TestPickUp:
    def test_valid(self):
        p = PickUp(object_id="kettle_1")
        assert p.object_id == "kettle_1"
        assert p.type == "pick_up"

    def test_rejects_empty_id(self):
        with pytest.raises(ValidationError):
            PickUp(object_id="")

    def test_rejects_missing_id(self):
        with pytest.raises(ValidationError):
            PickUp()


class TestPutDown:
    def test_valid_object_target(self):
        p = PutDown(target_id="counter_1")
        assert p.target_id == "counter_1"

    def test_valid_floor_target(self):
        p = PutDown(target_id="floor")
        assert p.target_id == "floor"

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            PutDown(target_id="")


class TestOpenClose:
    def test_open_valid(self):
        o = Open(object_id="fridge_1")
        assert o.type == "open"

    def test_close_valid(self):
        c = Close(object_id="fridge_1")
        assert c.type == "close"


class TestUse:
    def test_valid(self):
        u = Use(object_id="kettle_1", target_id="sink_1")
        assert u.object_id == "kettle_1"
        assert u.target_id == "sink_1"

    def test_rejects_missing_target(self):
        with pytest.raises(ValidationError):
            Use(object_id="kettle_1")

    def test_rejects_missing_object(self):
        with pytest.raises(ValidationError):
            Use(target_id="sink_1")


class TestNote:
    def test_valid(self):
        n = Note(text="bedroom is north")
        assert n.text == "bedroom is north"

    def test_strips_whitespace(self):
        n = Note(text="  remember the keys  ")
        assert n.text == "remember the keys"

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            Note(text="")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValidationError):
            Note(text="   ")

    def test_rejects_too_long(self):
        with pytest.raises(ValidationError):
            Note(text="x" * 501)


class TestDone:
    def test_valid(self):
        d = Done()
        assert d.type == "done"


class TestImmutability:
    def test_actions_are_frozen(self):
        m = Move(direction="north")
        with pytest.raises(ValidationError):
            m.direction = Direction.SOUTH  # type: ignore[misc]


# ---------------------------------------------------------------------------
# parse_action
# ---------------------------------------------------------------------------


class TestParseAction:
    def test_parses_move(self):
        a = parse_action({"type": "move", "direction": "north"})
        assert isinstance(a, Move)
        assert a.direction == Direction.NORTH

    def test_parses_look_around(self):
        a = parse_action({"type": "look_around"})
        assert isinstance(a, LookAround)

    def test_parses_done(self):
        a = parse_action({"type": "done"})
        assert isinstance(a, Done)

    def test_parses_use(self):
        a = parse_action(
            {"type": "use", "object_id": "kettle_1", "target_id": "sink_1"}
        )
        assert isinstance(a, Use)

    def test_rejects_unknown_type(self):
        with pytest.raises(ValidationError):
            parse_action({"type": "teleport"})

    def test_rejects_missing_type(self):
        with pytest.raises(ValidationError):
            parse_action({"direction": "north"})

    def test_rejects_wrong_args_for_type(self):
        # Move with object_id should fail because Move forbids extras.
        with pytest.raises(ValidationError):
            parse_action({"type": "move", "object_id": "kettle_1"})

    @pytest.mark.parametrize(
        "payload,expected_cls",
        [
            ({"type": "move", "direction": "south"}, Move),
            ({"type": "turn", "direction": "east"}, Turn),
            ({"type": "look_around"}, LookAround),
            ({"type": "pick_up", "object_id": "kettle_1"}, PickUp),
            ({"type": "put_down", "target_id": "floor"}, PutDown),
            ({"type": "open", "object_id": "fridge_1"}, Open),
            ({"type": "close", "object_id": "fridge_1"}, Close),
            (
                {"type": "use", "object_id": "kettle_1", "target_id": "sink_1"},
                Use,
            ),
            ({"type": "note", "text": "remember keys"}, Note),
            ({"type": "done"}, Done),
        ],
    )
    def test_all_actions_round_trip(self, payload, expected_cls):
        a = parse_action(payload)
        assert isinstance(a, expected_cls)
        # And the model dump should round-trip back to a parseable payload.
        assert parse_action(a.model_dump()) == a


# ---------------------------------------------------------------------------
# ActionResult
# ---------------------------------------------------------------------------


class TestActionResult:
    def test_minimal_success(self):
        r = ActionResult(status="success", message="ok")
        assert r.status == "success"
        assert r.state_changes == {}

    def test_failed_with_message(self):
        r = ActionResult(
            status="failed",
            message="You tried to move north but a wall blocks you.",
        )
        assert r.status == "failed"

    def test_rejects_bad_status(self):
        with pytest.raises(ValidationError):
            ActionResult(status="maybe", message="...")  # type: ignore[arg-type]

    def test_rejects_empty_message(self):
        with pytest.raises(ValidationError):
            ActionResult(status="success", message="")

    def test_accepts_state_changes(self):
        r = ActionResult(
            status="success",
            message="picked up kettle",
            state_changes={"robot.holding": "kettle_1"},
        )
        assert r.state_changes == {"robot.holding": "kettle_1"}


# ---------------------------------------------------------------------------
# Gemini tool schemas
# ---------------------------------------------------------------------------


class TestGeminiTools:
    def test_one_declaration_per_action(self):
        tools = to_gemini_tools()
        assert len(tools) == len(ALL_ACTION_TYPES) == 10

    def test_each_declaration_has_required_keys(self):
        for tool in to_gemini_tools():
            assert set(tool.keys()) >= {"name", "description", "parameters"}
            assert tool["name"]
            assert tool["description"]
            assert isinstance(tool["parameters"], dict)

    def test_names_match_action_types(self):
        names = {tool["name"] for tool in to_gemini_tools()}
        expected = {
            "move",
            "turn",
            "look_around",
            "pick_up",
            "put_down",
            "open",
            "close",
            "use",
            "note",
            "done",
        }
        assert names == expected

    def test_type_field_stripped_from_parameters(self):
        for tool in to_gemini_tools():
            props = tool["parameters"].get("properties", {})
            assert "type" not in props, (
                f"tool {tool['name']} still has 'type' in parameters"
            )

    def test_no_args_actions_have_no_required(self):
        tools_by_name = {t["name"]: t for t in to_gemini_tools()}
        for name in ("look_around", "done"):
            params = tools_by_name[name]["parameters"]
            assert not params.get("required")

    def test_refs_are_inlined(self):
        # No $ref or $defs should leak into the final tool schemas.
        import json

        for tool in to_gemini_tools():
            blob = json.dumps(tool)
            assert "$ref" not in blob, f"{tool['name']} contains $ref"
            assert "$defs" not in blob, f"{tool['name']} contains $defs"

    def test_direction_enum_present_in_move(self):
        tools_by_name = {t["name"]: t for t in to_gemini_tools()}
        move_params = tools_by_name["move"]["parameters"]
        direction = move_params["properties"]["direction"]
        assert set(direction.get("enum", [])) == {
            "north",
            "east",
            "south",
            "west",
        }


class TestGeminiFunctionCallAdapter:
    def test_round_trip(self):
        action = gemini_function_call_to_action(
            "move", {"direction": "north"}
        )
        assert isinstance(action, Move)
        assert action.direction == Direction.NORTH

    def test_no_args_action(self):
        action = gemini_function_call_to_action("look_around", {})
        assert isinstance(action, LookAround)

    def test_invalid_name_raises(self):
        with pytest.raises(ValidationError):
            gemini_function_call_to_action("fly", {})
