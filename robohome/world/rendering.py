"""
robohome/world/rendering.py

Converts world state to a PNG image using Pygame.
Used for logging and the replay system.
"""

import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from robohome.world.world import World

# Colours
COL_FLOOR       = (26,  32,  53)
COL_FLOOR_ALT   = (22,  28,  46)
COL_WALL        = (10,  14,  24)
COL_DOOR_CLOSED = (124, 60,  14)
COL_DOOR_OPEN   = (217, 119, 6)
COL_ROBOT       = (0,   212, 255)
COL_ROBOT_FACE  = (255, 255, 255)
COL_GRID        = (30,  45,  71)

TILE = 32  # pixels per cell


def render_to_png(world: "World", tile_size: int = TILE) -> bytes:
    """
    Draws the current world state and returns raw PNG bytes.
    Call this after every step to save frames for replay.
    """
    try:
        import pygame
    except ImportError:
        raise ImportError("pygame is required for rendering. Run: pip install pygame")

    pygame.init()

    w = world.grid.width  * tile_size
    h = world.grid.height * tile_size
    surface = pygame.Surface((w, h))

    # 1. Draw floor tiles
    for y in range(world.grid.height):
        for x in range(world.grid.width):
            col = COL_FLOOR if (x + y) % 2 == 0 else COL_FLOOR_ALT
            pygame.draw.rect(surface, col, (x * tile_size, y * tile_size, tile_size, tile_size))

    # 2. Draw walls and doors
    for y in range(world.grid.height):
        for x in range(world.grid.width):
            cell = world.grid.get_cell(x, y)
            if cell is None:
                continue
            if cell.cell_type.value == "wall":
                pygame.draw.rect(surface, COL_WALL, (x * tile_size, y * tile_size, tile_size, tile_size))
            elif cell.cell_type.value == "door":
                col = COL_DOOR_OPEN if cell.is_open else COL_DOOR_CLOSED
                pygame.draw.rect(surface, col, (x * tile_size, y * tile_size, tile_size, tile_size))

    # 3. Draw grid lines
    for x in range(world.grid.width + 1):
        pygame.draw.line(surface, COL_GRID, (x * tile_size, 0), (x * tile_size, h))
    for y in range(world.grid.height + 1):
        pygame.draw.line(surface, COL_GRID, (0, y * tile_size), (w, y * tile_size))

    # 4. Draw objects
    font = pygame.font.SysFont("segoeui", int(tile_size * 0.45))
    for obj in world.objects.values():
        pos = obj.position
        if hasattr(pos, "x"):
            cx = pos.x * tile_size + tile_size // 2
            cy = pos.y * tile_size + tile_size // 2
            label = font.render(obj.type[0].upper(), True, (148, 163, 184))
            surface.blit(label, label.get_rect(center=(cx, cy)))

    # 5. Draw robot
    rx = world.robot.position.x
    ry = world.robot.position.y
    cx = rx * tile_size + tile_size // 2
    cy = ry * tile_size + tile_size // 2
    radius = int(tile_size * 0.36)

    pygame.draw.circle(surface, COL_ROBOT, (cx, cy), radius)

    # Facing arrow
    arrow_len = int(radius * 0.8)
    facing = world.robot.facing
    if facing == "north":   ex, ey = cx, cy - arrow_len
    elif facing == "south": ex, ey = cx, cy + arrow_len
    elif facing == "east":  ex, ey = cx + arrow_len, cy
    else:                   ex, ey = cx - arrow_len, cy

    pygame.draw.line(surface, (0, 0, 0), (cx, cy), (ex, ey), 2)
    pygame.draw.circle(surface, COL_ROBOT_FACE, (ex, ey), 3)

    # 6. Export to PNG bytes
    buf = io.BytesIO()
    pygame.image.save(surface, buf, "PNG")
    pygame.quit()
    return buf.getvalue()


def save_png(world: "World", path: str, tile_size: int = TILE) -> None:
    """Convenience wrapper — renders and saves to a file path."""
    png_bytes = render_to_png(world, tile_size)
    with open(path, "wb") as f:
        f.write(png_bytes)