from typing import Any, Dict, Optional
from robohome.world.models import InternalRobotState, ObjectState, Position
from robohome.world.house import build_house_grid
from robohome.world.grid import CellType

class World:
    """The main physics engine and state manager for the simulation."""

    def __init__(self):
        # 1. Build the physical house
        self.grid, self.rooms = build_house_grid()
        
        # 2. Track all items in the house
        self.objects: Dict[str, ObjectState] = {}
        
        # 3. Drop the robot into the Kitchen to start
        self.robot = InternalRobotState(
            position=Position(x=5, y=12), 
            facing="north", 
            holding=None
        )

    def get_room_at(self, pos: Position) -> str:
        """Finds which room a specific coordinate belongs to."""
        for room_name, room_def in self.rooms.items():
            if (room_def.top_left.x <= pos.x <= room_def.bottom_right.x and
                room_def.top_left.y <= pos.y <= room_def.bottom_right.y):
                return room_name
        return "unknown"

    def observe(self) -> Dict[str, Any]:
        """
        CONTRACT: Returns the WorldView expected by the harness.
        This represents exactly what the robot sees right now.
        """
        current_room = self.get_room_at(self.robot.position)
        
        # Find all objects currently sitting in the same room
        visible_objs = []
        for obj in self.objects.values():
            if isinstance(obj.position, Position) and self.get_room_at(obj.position) == current_room:
                # We will add distance calculations later
                visible_objs.append({
                    "id": obj.id,
                    "type": obj.type,
                    "direction": "north", # Placeholder
                    "distance": 1,        # Placeholder
                    "state": obj.properties
                })

        return {
            "current_room": current_room,
            "room_description": f"You are in the {current_room}.",
            "visible_objects": visible_objs,
            "exits": [] # We will populate exits later
        }

    def execute(self, action: Any) -> Dict[str, Any]:
        """
        CONTRACT: Executes an action from the LLM and returns an ActionResult.
        """
        # --- Handle Turning ---
        if action.type == "turn":
            self.robot.facing = action.direction
            return {"status": "success", "message": f"You turned to face {action.direction}.", "state_changes": {}}
        
        # --- Handle Moving ---
        elif action.type == "move":
            # Calculate the next tile based on facing direction
            dx, dy = 0, 0
            if action.direction == "north": dy = -1
            elif action.direction == "south": dy = 1
            elif action.direction == "east": dx = 1
            elif action.direction == "west": dx = -1
            
            new_x = self.robot.position.x + dx
            new_y = self.robot.position.y + dy
            
            target_cell = self.grid.get_cell(new_x, new_y)
            
            # Reject if walking into a wall or out of bounds
            if not target_cell or not target_cell.is_walkable:
                return {"status": "failed", "message": "You cannot move there. The path is blocked.", "state_changes": {}}
            
            # Update robot position on success
            self.robot.position = Position(x=new_x, y=new_y)
            return {"status": "success", "message": f"You moved {action.direction}.", "state_changes": {}}

        # Catch-all for actions we haven't built yet
        return {"status": "failed", "message": f"The '{action.type}' action is not fully implemented in the world yet.", "state_changes": {}}