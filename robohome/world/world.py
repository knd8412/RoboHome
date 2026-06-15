from typing import Any, Dict, Optional
from robohome.world.models import InternalRobotState, ObjectState, Position
from robohome.world.house import build_house_grid
from robohome.world.grid import CellType


class World:
    """The main physics engine and state manager for the simulation."""

    def __init__(self):
        self.grid, self.rooms = build_house_grid()
        self.objects: Dict[str, ObjectState] = {}
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

    def _is_adjacent(self, pos: Position) -> bool:
        """Checks if a position is within 1 cell of the robot."""
        return abs(pos.x - self.robot.position.x) <= 1 and \
               abs(pos.y - self.robot.position.y) <= 1

    def observe(self) -> Dict[str, Any]:
        """CONTRACT: Returns the WorldView expected by the harness."""
        current_room = self.get_room_at(self.robot.position)

        visible_objs = []
        for obj in self.objects.values():
            if isinstance(obj.position, Position) and \
               self.get_room_at(obj.position) == current_room:
                dx = obj.position.x - self.robot.position.x
                dy = obj.position.y - self.robot.position.y
                distance = abs(dx) + abs(dy)
                if dx == 0 and dy < 0: direction = "north"
                elif dx == 0 and dy > 0: direction = "south"
                elif dx > 0: direction = "east"
                else: direction = "west"
                visible_objs.append({
                    "id": obj.id,
                    "type": obj.type,
                    "direction": direction,
                    "distance": distance,
                    "state": obj.properties
                })

        # Find exits from current room
        exits = []
        door_map = {
            (4, 5):  ("bedroom",     "hallway",     "south", "north"),
            (14, 5): ("bathroom",    "hallway",     "south", "north"),
            (4, 9):  ("kitchen",     "hallway",     "north", "south"),
            (14, 9): ("living_room", "hallway",     "north", "south"),
        }
        for (dx, dy), (room_a, room_b, dir_from_a, dir_from_b) in door_map.items():
            cell = self.grid.get_cell(dx, dy)
            if cell and cell.cell_type.value == "door":
                if current_room in (room_a, room_b):
                    other_room = room_b if current_room == room_a else room_a
                    direction = dir_from_a if current_room == room_a else dir_from_b
                    exits.append({
                        "to_room": other_room,
                        "direction": direction,
                        "via": f"door_{dx}_{dy}",
                        "is_open": cell.is_open
            })

        return {
            "current_room": current_room,
            "room_description": f"You are in the {current_room.replace('_', ' ')}.",
            "visible_objects": visible_objs,
            "exits": exits
        }

    def execute(self, action: Any) -> Dict[str, Any]:
        """CONTRACT: Executes an action and returns an ActionResult."""

        # ── TURN ──────────────────────────────────────────────────
        if action.type == "turn":
            self.robot.facing = action.direction
            return {"status": "success", "message": f"You turned to face {action.direction}.", "state_changes": {}}

        # ── MOVE ──────────────────────────────────────────────────
        elif action.type == "move":
            dx, dy = 0, 0
            if action.direction == "north": dy = -1
            elif action.direction == "south": dy = 1
            elif action.direction == "east": dx = 1
            elif action.direction == "west": dx = -1

            new_x = self.robot.position.x + dx
            new_y = self.robot.position.y + dy
            target_cell = self.grid.get_cell(new_x, new_y)

            if not target_cell or not target_cell.is_walkable:
                return {"status": "failed", "message": "You cannot move there. The path is blocked.", "state_changes": {}}

            self.robot.position = Position(x=new_x, y=new_y)
            return {"status": "success", "message": f"You moved {action.direction}.", "state_changes": {}}

        # ── LOOK AROUND ───────────────────────────────────────────
        elif action.type == "look_around":
            return {"status": "success", "message": "You look around the room.", "state_changes": {}}

        # ── PICK UP ───────────────────────────────────────────────
        elif action.type == "pick_up":
            if self.robot.holding is not None:
                return {"status": "failed", "message": f"You are already holding {self.robot.holding}. Put it down first.", "state_changes": {}}

            obj_id = getattr(action, "object_id", None)
            if obj_id not in self.objects:
                return {"status": "failed", "message": f"No object with id '{obj_id}' exists.", "state_changes": {}}

            obj = self.objects[obj_id]

            if not isinstance(obj.position, Position):
                return {"status": "failed", "message": f"{obj_id} is inside a container. Open the container first.", "state_changes": {}}

            if not self._is_adjacent(obj.position):
                return {"status": "failed", "message": f"{obj_id} is too far away. Move closer first.", "state_changes": {}}

            if "pickable" not in obj.affordances:
                return {"status": "failed", "message": f"You cannot pick up {obj_id}.", "state_changes": {}}

            self.robot.holding = obj_id
            obj.position = "held"
            return {"status": "success", "message": f"You picked up {obj_id}.", "state_changes": {"holding": obj_id}}

        # ── PUT DOWN ──────────────────────────────────────────────
        elif action.type == "put_down":
            if self.robot.holding is None:
                return {"status": "failed", "message": "You are not holding anything.", "state_changes": {}}

            obj_id = self.robot.holding
            target_id = getattr(action, "target_id", "floor")

            if target_id == "floor":
                self.objects[obj_id].position = Position(
                    x=self.robot.position.x,
                    y=self.robot.position.y
                )
            else:
                if target_id not in self.objects:
                    return {"status": "failed", "message": f"No surface or container called '{target_id}' found.", "state_changes": {}}
                target = self.objects[target_id]
                if not self._is_adjacent(target.position) if isinstance(target.position, Position) else False:
                    return {"status": "failed", "message": f"{target_id} is too far away.", "state_changes": {}}
                if "placeable_on" not in target.affordances and "container" not in target.affordances:
                    return {"status": "failed", "message": f"You cannot place things on {target_id}.", "state_changes": {}}
                self.objects[obj_id].position = target_id

            self.robot.holding = None
            return {"status": "success", "message": f"You put down {obj_id}.", "state_changes": {"holding": None}}

        # ── OPEN ──────────────────────────────────────────────────
        elif action.type == "open":
            obj_id = getattr(action, "object_id", None)

            # Check if it's a door (on the grid)
            door_positions = [(4, 5), (14, 5), (4, 9), (14, 9)]
            for (dx, dy) in door_positions:
                cell = self.grid.get_cell(dx, dy)
                if cell and cell.cell_type.value == "door":
                    if abs(dx - self.robot.position.x) <= 2 and abs(dy - self.robot.position.y) <= 2:
                        if obj_id and ("door" in obj_id or obj_id == f"door_{dx}_{dy}"):
                            cell.is_open = True
                            return {"status": "success", "message": f"You opened the door.", "state_changes": {"door": f"{dx},{dy}"}}

            # Check if it's an object (fridge, cupboard)
            if obj_id in self.objects:
                obj = self.objects[obj_id]
                if "openable" not in obj.affordances:
                    return {"status": "failed", "message": f"You cannot open {obj_id}.", "state_changes": {}}
                if not self._is_adjacent(obj.position) if isinstance(obj.position, Position) else True:
                    return {"status": "failed", "message": f"{obj_id} is too far away.", "state_changes": {}}
                obj.properties["is_open"] = True
                return {"status": "success", "message": f"You opened {obj_id}.", "state_changes": {}}

            return {"status": "failed", "message": f"Nothing to open called '{obj_id}'.", "state_changes": {}}

        # ── CLOSE ─────────────────────────────────────────────────
        elif action.type == "close":
            obj_id = getattr(action, "object_id", None)

            door_positions = [(4, 5), (14, 5), (4, 9), (14, 9)]
            for (dx, dy) in door_positions:
                cell = self.grid.get_cell(dx, dy)
                if cell and cell.cell_type.value == "door":
                    if obj_id and ("door" in obj_id or obj_id == f"door_{dx}_{dy}"):
                        cell.is_open = False
                        return {"status": "success", "message": "You closed the door.", "state_changes": {}}

            if obj_id in self.objects:
                obj = self.objects[obj_id]
                obj.properties["is_open"] = False
                return {"status": "success", "message": f"You closed {obj_id}.", "state_changes": {}}

            return {"status": "failed", "message": f"Nothing to close called '{obj_id}'.", "state_changes": {}}

        # ── USE ───────────────────────────────────────────────────
        elif action.type == "use":
            obj_id = getattr(action, "object_id", None)
            target_id = getattr(action, "target_id", None)

            if obj_id not in self.objects:
                return {"status": "failed", "message": f"No object '{obj_id}' found.", "state_changes": {}}
            if target_id not in self.objects:
                return {"status": "failed", "message": f"No target '{target_id}' found.", "state_changes": {}}

            obj = self.objects[obj_id]
            target = self.objects[target_id]

            # kettle + sink → fill with water
            if obj.type == "kettle" and target.type == "sink":
                obj.properties["contains"] = "water"
                obj.properties["temperature"] = "cold"
                return {"status": "success", "message": "You filled the kettle with cold water.", "state_changes": {}}

            # kettle + stove → boil
            if obj.type == "kettle" and target.type == "stove":
                if obj.properties.get("contains") != "water":
                    return {"status": "failed", "message": "The kettle is empty. Fill it with water first.", "state_changes": {}}
                obj.properties["temperature"] = "hot"
                return {"status": "success", "message": "You boiled the water in the kettle.", "state_changes": {}}

            # kettle + mug → pour
            if obj.type == "kettle" and target.type == "mug":
                if obj.properties.get("temperature") != "hot":
                    return {"status": "failed", "message": "The water is not hot yet.", "state_changes": {}}
                target.properties["contains"] = "hot_water"
                obj.properties["contains"] = "empty"
                return {"status": "success", "message": "You poured hot water into the mug.", "state_changes": {}}

            # tea_bag + mug → brew
            if obj.type == "tea_bag" and target.type == "mug":
                if target.properties.get("contains") != "hot_water":
                    return {"status": "failed", "message": "The mug needs hot water first.", "state_changes": {}}
                target.properties["contains"] = "tea"
                target.properties["temperature"] = "hot"
                return {"status": "success", "message": "You added the tea bag. The mug now contains hot tea!", "state_changes": {}}

            # milk + mug → add milk
            if obj.type == "milk" and target.type == "mug":
                target.properties["has_milk"] = True
                return {"status": "success", "message": "You added milk to the mug.", "state_changes": {}}

            # dirty_dish + trash_bin → dispose
            if obj.type == "dirty_dish" and target.type == "trash_bin":
                del self.objects[obj_id]
                if self.robot.holding == obj_id:
                    self.robot.holding = None
                return {"status": "success", "message": "You disposed of the dirty dish.", "state_changes": {}}

            return {"status": "failed", "message": f"You can't use {obj.type} with {target.type}.", "state_changes": {}}

        # ── DONE ──────────────────────────────────────────────────
        elif action.type == "done":
            return {"status": "success", "message": "You declared the task complete.", "state_changes": {}}

        # ── CATCH-ALL ─────────────────────────────────────────────
        return {"status": "failed", "message": f"Unknown action '{action.type}'.", "state_changes": {}}