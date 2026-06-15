"""
tests/test_world.py

Tests for the World class — grid, rooms, robot state, and execute() actions.
"""

import pytest
from robohome.world.world import World
from robohome.world.models import Position
from robohome.world.object import spawn_object


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_action(action_type, **kwargs):
    """Creates a mock action object — same shape as what Kamyar's loop sends."""
    class Action:
        pass
    a = Action()
    a.type = action_type
    for k, v in kwargs.items():
        setattr(a, k, v)
    return a


def place_object(world, obj_id, obj_type, x, y, affordances, properties=None):
    """Shortcut to drop an object into the world at a position."""
    world.objects[obj_id] = spawn_object(
        obj_id=obj_id,
        obj_type=obj_type,
        location=Position(x=x, y=y),
        affordances=affordances,
        properties=properties or {}
    )


# ── Grid tests ────────────────────────────────────────────────────────────────

def test_grid_size():
    world = World()
    assert world.grid.width == 20
    assert world.grid.height == 15


def test_walls_exist():
    world = World()
    # Row y=5 should be all walls (top of hallway)
    for x in range(20):
        cell = world.grid.get_cell(x, 5)
        assert cell.cell_type.value == "wall" or cell.cell_type.value == "door"


def test_doors_exist():
    world = World()
    door_positions = [(4, 5), (14, 5), (4, 9), (14, 9)]
    for x, y in door_positions:
        cell = world.grid.get_cell(x, y)
        assert cell.cell_type.value == "door"


def test_doors_start_closed():
    world = World()
    door_positions = [(4, 5), (14, 5), (4, 9), (14, 9)]
    for x, y in door_positions:
        cell = world.grid.get_cell(x, y)
        assert cell.is_open is False


def test_floor_is_walkable():
    world = World()
    cell = world.grid.get_cell(5, 12)  # kitchen floor
    assert cell.is_walkable is True


def test_wall_is_not_walkable():
    world = World()
    cell = world.grid.get_cell(0, 5)  # wall row
    assert cell.is_walkable is False


def test_closed_door_is_not_walkable():
    world = World()
    cell = world.grid.get_cell(4, 9)  # kitchen door, closed
    assert cell.is_walkable is False


def test_open_door_is_walkable():
    world = World()
    cell = world.grid.get_cell(4, 9)
    cell.is_open = True
    assert cell.is_walkable is True


# ── Room detection tests ───────────────────────────────────────────────────────

def test_robot_starts_in_kitchen():
    world = World()
    room = world.get_room_at(world.robot.position)
    assert room == "kitchen"


def test_room_detection_bedroom():
    world = World()
    assert world.get_room_at(Position(x=2, y=2)) == "bedroom"


def test_room_detection_bathroom():
    world = World()
    assert world.get_room_at(Position(x=15, y=2)) == "bathroom"


def test_room_detection_hallway():
    world = World()
    assert world.get_room_at(Position(x=10, y=7)) == "hallway"


def test_room_detection_living_room():
    world = World()
    assert world.get_room_at(Position(x=15, y=12)) == "living_room"


# ── Move tests ────────────────────────────────────────────────────────────────

def test_move_north():
    world = World()
    start_y = world.robot.position.y
    result = world.execute(make_action("move", direction="north"))
    assert result["status"] == "success"
    assert world.robot.position.y == start_y - 1


def test_move_blocked_by_wall():
    world = World()
    # Move robot to just below the wall at y=9
    world.robot.position = Position(x=5, y=10)
    result = world.execute(make_action("move", direction="north"))
    assert result["status"] == "failed"
    assert "blocked" in result["message"].lower()


def test_move_blocked_by_closed_door():
    world = World()
    # Place robot just south of kitchen door at (4, 9)
    world.robot.position = Position(x=4, y=10)
    result = world.execute(make_action("move", direction="north"))
    assert result["status"] == "failed"


def test_move_through_open_door():
    world = World()
    world.robot.position = Position(x=4, y=10)
    world.grid.get_cell(4, 9).is_open = True
    result = world.execute(make_action("move", direction="north"))
    assert result["status"] == "success"


# ── Turn tests ────────────────────────────────────────────────────────────────

def test_turn():
    world = World()
    result = world.execute(make_action("turn", direction="east"))
    assert result["status"] == "success"
    assert world.robot.facing == "east"


# ── Pick up tests ─────────────────────────────────────────────────────────────

def test_pick_up_adjacent_object():
    world = World()
    place_object(world, "kettle_1", "kettle", 5, 11, ["pickable"])
    result = world.execute(make_action("pick_up", object_id="kettle_1"))
    assert result["status"] == "success"
    assert world.robot.holding == "kettle_1"


def test_pick_up_too_far():
    world = World()
    place_object(world, "kettle_1", "kettle", 1, 1, ["pickable"])
    result = world.execute(make_action("pick_up", object_id="kettle_1"))
    assert result["status"] == "failed"
    assert "too far" in result["message"].lower()


def test_pick_up_non_pickable():
    world = World()
    place_object(world, "stove_1", "stove", 5, 11, [])  # no pickable affordance
    result = world.execute(make_action("pick_up", object_id="stove_1"))
    assert result["status"] == "failed"


def test_pick_up_when_already_holding():
    world = World()
    place_object(world, "kettle_1", "kettle", 5, 11, ["pickable"])
    place_object(world, "mug_1", "mug", 5, 11, ["pickable"])
    world.execute(make_action("pick_up", object_id="kettle_1"))
    result = world.execute(make_action("pick_up", object_id="mug_1"))
    assert result["status"] == "failed"
    assert "already holding" in result["message"].lower()


# ── Put down tests ────────────────────────────────────────────────────────────

def test_put_down_on_floor():
    world = World()
    place_object(world, "kettle_1", "kettle", 5, 11, ["pickable"])
    world.execute(make_action("pick_up", object_id="kettle_1"))
    result = world.execute(make_action("put_down", target_id="floor"))
    assert result["status"] == "success"
    assert world.robot.holding is None


def test_put_down_when_holding_nothing():
    world = World()
    result = world.execute(make_action("put_down", target_id="floor"))
    assert result["status"] == "failed"
    assert "not holding" in result["message"].lower()


# ── Open / close tests ────────────────────────────────────────────────────────

def test_open_container():
    world = World()
    place_object(world, "fridge_1", "fridge", 5, 11, ["openable"], {"is_open": False})
    result = world.execute(make_action("open", object_id="fridge_1"))
    assert result["status"] == "success"
    assert world.objects["fridge_1"].properties["is_open"] is True


def test_open_non_openable():
    world = World()
    place_object(world, "mug_1", "mug", 5, 11, [])
    result = world.execute(make_action("open", object_id="mug_1"))
    assert result["status"] == "failed"


# ── Use tests ─────────────────────────────────────────────────────────────────

def test_fill_kettle_at_sink():
    world = World()
    place_object(world, "kettle_1", "kettle", 5, 11, ["pickable", "heatable"],
                 {"contains": "empty", "temperature": "cold"})
    place_object(world, "sink_1", "sink", 5, 11, [])
    result = world.execute(make_action("use", object_id="kettle_1", target_id="sink_1"))
    assert result["status"] == "success"
    assert world.objects["kettle_1"].properties["contains"] == "water"


def test_boil_kettle_on_stove():
    world = World()
    place_object(world, "kettle_1", "kettle", 5, 11, [],
                 {"contains": "water", "temperature": "cold"})
    place_object(world, "stove_1", "stove", 5, 11, [])
    result = world.execute(make_action("use", object_id="kettle_1", target_id="stove_1"))
    assert result["status"] == "success"
    assert world.objects["kettle_1"].properties["temperature"] == "hot"


def test_boil_empty_kettle_fails():
    world = World()
    place_object(world, "kettle_1", "kettle", 5, 11, [],
                 {"contains": "empty", "temperature": "cold"})
    place_object(world, "stove_1", "stove", 5, 11, [])
    result = world.execute(make_action("use", object_id="kettle_1", target_id="stove_1"))
    assert result["status"] == "failed"


def test_pour_hot_water_into_mug():
    world = World()
    place_object(world, "kettle_1", "kettle", 5, 11, [],
                 {"contains": "water", "temperature": "hot"})
    place_object(world, "mug_1", "mug", 5, 11, [], {"contains": "empty"})
    result = world.execute(make_action("use", object_id="kettle_1", target_id="mug_1"))
    assert result["status"] == "success"
    assert world.objects["mug_1"].properties["contains"] == "hot_water"


def test_make_tea():
    world = World()
    place_object(world, "mug_1", "mug", 5, 11, [], {"contains": "hot_water"})
    place_object(world, "tea_bag_1", "tea_bag", 5, 11, [])
    result = world.execute(make_action("use", object_id="tea_bag_1", target_id="mug_1"))
    assert result["status"] == "success"
    assert world.objects["mug_1"].properties["contains"] == "tea"


# ── Observe tests ─────────────────────────────────────────────────────────────

def test_observe_returns_current_room():
    world = World()
    obs = world.observe()
    assert obs["current_room"] == "kitchen"


def test_observe_shows_objects_in_same_room():
    world = World()
    place_object(world, "kettle_1", "kettle", 5, 11, ["pickable"])
    obs = world.observe()
    ids = [o["id"] for o in obs["visible_objects"]]
    assert "kettle_1" in ids


def test_observe_hides_objects_in_other_rooms():
    world = World()
    place_object(world, "bed_1", "bed", 2, 2, [])  # bedroom
    obs = world.observe()
    ids = [o["id"] for o in obs["visible_objects"]]
    assert "bed_1" not in ids


def test_observe_shows_exits():
    world = World()
    obs = world.observe()
    assert len(obs["exits"]) > 0