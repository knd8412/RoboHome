from typing import Dict, Tuple
from robohome.world.models import Position, RoomDef
from robohome.world.grid import Grid

def build_house_grid() -> Tuple[Grid, Dict[str, RoomDef]]:
    """Constructs the 20x15 house with 5 rooms, walls, and doors."""
    
    # Start with a blank 20x15 floor
    grid = Grid(width=20, height=15)
    
    # Define the boundaries for all 5 rooms
    rooms = {
        "bedroom": RoomDef(
            name="bedroom",
            top_left=Position(x=0, y=0),
            bottom_right=Position(x=9, y=5)
        ),
        "bathroom": RoomDef(
            name="bathroom",
            top_left=Position(x=10, y=0),
            bottom_right=Position(x=19, y=5)
        ),
        "hallway": RoomDef(
            name="hallway",
            top_left=Position(x=0, y=6),
            bottom_right=Position(x=19, y=8)
        ),
        "kitchen": RoomDef(
            name="kitchen",
            top_left=Position(x=0, y=9),
            bottom_right=Position(x=9, y=14)
        ),
        "living_room": RoomDef(
            name="living_room",
            top_left=Position(x=10, y=9),
            bottom_right=Position(x=19, y=14)
        )
    }

    # Build horizontal walls to frame the hallway
    for x in range(20):
        grid.set_wall(x, 5) # Top of hallway
        grid.set_wall(x, 9) # Bottom of hallway

    # Build vertical walls to split the left and right rooms
    for y in range(0, 5):   
        grid.set_wall(9, y) # Splits bedroom / bathroom
    for y in range(10, 15): 
        grid.set_wall(9, y) # Splits kitchen / living room

    # Add closed doors connecting each room to the hallway
    grid.set_door(4, 5, is_open=False)   # Bedroom door
    grid.set_door(14, 5, is_open=False)  # Bathroom door
    grid.set_door(4, 9, is_open=False)   # Kitchen door
    grid.set_door(14, 9, is_open=False)  # Living room door

    return grid, rooms