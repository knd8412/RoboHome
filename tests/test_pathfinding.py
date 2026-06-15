"""
tests/test_pathfinding.py

Tests for the A* pathfinding algorithm.
"""

import pytest
from robohome.world.world import World
from robohome.harness.pathfinding import shortest_path


def test_path_within_same_room():
    """Robot can find a path across open floor."""
    world = World()
    path = shortest_path(world, (5, 12), (7, 12))
    assert path is not None
    assert path[0] == (5, 12)
    assert path[-1] == (7, 12)


def test_path_starts_and_ends_at_same_cell():
    """Trivial path — start equals goal."""
    world = World()
    path = shortest_path(world, (5, 12), (5, 12))
    assert path is not None
    assert len(path) == 1
    assert path[0] == (5, 12)


def test_path_blocked_by_closed_door():
    """Cannot path through a closed door."""
    world = World()
    path = shortest_path(world, (4, 10), (4, 7))
    assert path is None


def test_path_through_open_door():
    """Can path through a door once it's open."""
    world = World()
    world.grid.get_cell(4, 9).is_open = True
    path = shortest_path(world, (4, 10), (4, 7))
    assert path is not None


def test_path_blocked_by_wall():
    """Cannot path through a wall."""
    world = World()
    path = shortest_path(world, (4, 4), (4, 10))
    assert path is None


def test_path_length_is_reasonable():
    """Path shouldn't be absurdly long for nearby cells."""
    world = World()
    path = shortest_path(world, (1, 10), (7, 10))
    assert path is not None
    assert len(path) <= 10


def test_path_does_not_go_out_of_bounds():
    """Every step in the path should be a valid cell."""
    world = World()
    path = shortest_path(world, (5, 12), (8, 12))
    assert path is not None
    for (x, y) in path:
        assert 0 <= x < world.grid.width
        assert 0 <= y < world.grid.height


def test_path_only_walks_on_walkable_cells():
    """Every cell in the path must be walkable."""
    world = World()
    path = shortest_path(world, (2, 12), (7, 12))
    assert path is not None
    for (x, y) in path:
        cell = world.grid.get_cell(x, y)
        assert cell.is_walkable


def test_path_across_hallway_with_two_open_doors():
    """Robot can navigate from kitchen to bedroom with both doors open."""
    world = World()
    world.grid.get_cell(4, 9).is_open = True
    world.grid.get_cell(4, 5).is_open = True
    path = shortest_path(world, (4, 12), (4, 2))
    assert path is not None
    assert path[-1] == (4, 2)