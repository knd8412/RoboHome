from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

from robohome.world.models import Position

class CellType(str, Enum):
    """The three types of tiles allowed in the house."""
    FLOOR = "floor"
    WALL = "wall"
    DOOR = "door"

class Cell(BaseModel):
    """A single square on our 20x15 floor plan."""
    position: Position
    cell_type: CellType
    is_open: bool = Field(False, description="Only matters if the cell is a door")

    @property
    def is_walkable(self) -> bool:
        """Rules for whether the robot is allowed to step here."""
        if self.cell_type == CellType.FLOOR:
            return True
        if self.cell_type == CellType.DOOR and self.is_open:
            return True
        return False

    @property
    def blocks_vision(self) -> bool:
        """Walls block the robot's line of sight."""
        return self.cell_type == CellType.WALL

class Grid:
    """The actual 2D map of the house."""
    def __init__(self, width: int = 20, height: int = 15):
        self.width = width
        self.height = height
        
        # This builds a blank 20x15 grid completely made of floor tiles
        self.cells: List[List[Cell]] = []
        for y in range(height):
            row = []
            for x in range(width):
                pos = Position(x=x, y=y)
                row.append(Cell(position=pos, cell_type=CellType.FLOOR))
            self.cells.append(row)

    def get_cell(self, x: int, y: int) -> Optional[Cell]:
        """Safely grab a cell. Returns None if we ask for a coordinate outside the house."""
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.cells[y][x]
        return None

    def set_wall(self, x: int, y: int):
        """Helper to quickly build a wall on a specific tile."""
        if cell := self.get_cell(x, y):
            cell.cell_type = CellType.WALL

    def set_door(self, x: int, y: int, is_open: bool = False):
        """Helper to quickly build a door on a specific tile."""
        if cell := self.get_cell(x, y):
            cell.cell_type = CellType.DOOR
            cell.is_open = is_open