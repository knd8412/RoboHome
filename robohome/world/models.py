from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

class Position(BaseModel):
    """Represents an (x, y) coordinate on our grid home."""
    x: int = Field(..., description="The X coordinate (horizontal axis, increases east)")
    y: int = Field(..., description="The Y coordinate (vertical axis, increases south)")

    def to_tuple(self) -> Tuple[int, int]:
        """Helper to pass (x,y) to Kamyar's observation builder."""
        return (self.x, self.y)

class ObjectState(BaseModel):
    """Matches the Object Schema from Spec Section 4.4."""
    id: str = Field(..., description="Unique string identifier like 'kettle_1'")
    type: str = Field(..., description="Category of the object, like 'kettle'")
    
    # Position can be a precise coordinate OR the ID of a container 
    position: Union[Position, str] = Field(..., description="Cell coords OR inside another object ID")
    
    # This maps directly to the 'state' dictionary Kamyar expects
    properties: Dict[str, Any] = Field(default_factory=dict, description="Type-specific state like 'is_open: False'")
    
    # What the robot is allowed to do with this item
    affordances: List[str] = Field(default_factory=list, description="e.g., 'pickable', 'openable', 'container'")

class RoomDef(BaseModel):
    """Defines a bounding box area for a room."""
    name: str = Field(..., description="Name of the room (e.g., 'kitchen')")
    top_left: Position
    bottom_right: Position

class InternalRobotState(BaseModel):
    """The world's internal tracking of the robot."""
    position: Position
    facing: str = Field(..., description="Must be 'north', 'east', 'south', or 'west'")
    holding: Optional[str] = Field(None, description="Object ID the robot is holding, or None")