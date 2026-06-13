from robohome.world.world import World
from robohome.world.object import spawn_object
from robohome.world.models import Position


class Task:
    def __init__(self, name, objective, setup_fn, success_fn):
        self.name = name
        self.objective = objective
        self._setup_fn = setup_fn
        self._success_fn = success_fn

    def setup_world(self, world: World):
        self._setup_fn(world)

    def is_successful(self, world: World) -> bool:
        return self._success_fn(world)


def _setup_tea(world: World):
    world.objects["kettle_1"] = spawn_object(
        obj_id="kettle_1",
        obj_type="kettle",
        location=Position(x=5, y=10),
        affordances=["pickable", "pourable", "heatable"],
        properties={"contains": "empty", "temperature": "cold"}
    )
    world.objects["mug_1"] = spawn_object(
        obj_id="mug_1",
        obj_type="mug",
        location=Position(x=4, y=6),
        affordances=["fillable"],
        properties={"contains": "empty"}
    )


def _eval_tea(world: World) -> bool:
    return world.robot.holding in ["kettle_1", "mug_1"]


TASKS = {
    "make_tea": Task(
        name="make_tea",
        objective="Make a cup of tea. Find the kettle, fill it with water, boil it on the stove, and pour it into the mug.",
        setup_fn=_setup_tea,
        success_fn=_eval_tea,
    )
}