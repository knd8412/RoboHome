from typing import Any, Dict, List, Union
from robohome.world.models import ObjectState, Position

# Standard affordances (actions the robot can take on objects)
PICKABLE = "pickable"
POURABLE = "pourable"
FILLABLE = "fillable"
OPENABLE = "openable"
HEATABLE = "heatable"
READABLE = "readable"
SITTABLE = "sittable"
PLACEABLE_ON = "placeable_on"
CONTAINER = "container"

def spawn_object(
    obj_id: str, 
    obj_type: str, 
    location: Union[Position, str], 
    affordances: List[str],
    properties: Dict[str, Any] = None
) -> ObjectState:
    """Helper to quickly create a new household item."""
    
    # Default to an empty dictionary if no properties are given
    if properties is None:
        properties = {}
        
    return ObjectState(
        id=obj_id,
        type=obj_type,
        position=location,
        properties=properties,
        affordances=affordances
    )