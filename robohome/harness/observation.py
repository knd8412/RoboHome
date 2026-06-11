"""
Observation system for the RoboHome agent.

This module defines:
  * The Pydantic models that describe what the robot observes each turn.
  * ``WorldView``, the data contract with ``World.observe()``.
  * ``build_observation()``, the function that assembles a complete
    ``Observation`` from a ``WorldView`` plus harness-side context.
  * ``summarize_observation()``, a token-cheap stringification used for
    the recent-history block in subsequent prompts.

Design choices worth knowing
----------------------------

1. Partial observability is by object state, not by topology. The
   agent receives the static floor plan in its system prompt, like a
   real robot has a SLAM map. What it discovers by acting is dynamic
   state: what is in the fridge, whether the kettle is full, where the
   keys were left. This matches how real robotic agents work and keeps
   the harness focused on planning under uncertainty rather than maze
   exploration.

2. Only the current room's objects are visible. Anything elsewhere
   must be remembered via the agent's own ``note()`` action. This is
   the harness's main memory mechanism.

3. Closed containers hide their contents until opened.

4. Visible objects are sorted nearest-first, then by id for
   determinism. Same world state should produce the same observation
   string across runs, which makes debugging far easier.

5. Directions are absolute compass (north/east/south/west), not
   robot-relative. Movement actions take absolute directions, so
   keeping the same frame across the observation avoids needless
   mental conversion for the LLM.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from robohome.harness.actions import Direction


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class VisibleObject(BaseModel):
    """An object the robot currently sees in its room.

    ``direction`` is the primary cardinal direction from the robot
    (largest-delta wins for objects not on a pure axis). ``distance``
    is Manhattan distance in cells.
    """

    model_config = {"extra": "forbid"}

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    direction: Direction
    distance: int = Field(ge=0)
    state: dict[str, Any] = Field(default_factory=dict)


class Exit(BaseModel):
    """A door leading out of the current room.

    ``to_room`` is the room on the other side. ``via`` is the door's
    object id so the agent can ``open`` it if it is closed.
    """

    model_config = {"extra": "forbid"}

    to_room: str = Field(min_length=1)
    direction: Direction
    via: str = Field(min_length=1)
    is_open: bool


class HeldObject(BaseModel):
    """The object currently in the robot's single hand slot."""

    model_config = {"extra": "forbid"}

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    state: dict[str, Any] = Field(default_factory=dict)


class RobotState(BaseModel):
    """The robot's own state at this step."""

    model_config = {"extra": "forbid"}

    room: str = Field(min_length=1)
    position: tuple[int, int]
    facing: Direction
    holding: Optional[HeldObject] = None


class LastAction(BaseModel):
    """What the agent did on the previous step and what came of it.

    ``message`` is the world's human-readable explanation, which the
    LLM reads to learn from a failure. Bad: ``"IllegalMoveException"``.
    Good: ``"You tried to move north but a wall is blocking you."``.

    ``result`` includes ``"noted"`` for the agent-side ``note`` action
    which does not go through ``World.execute``.
    """

    model_config = {"extra": "forbid"}

    action: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)
    result: Literal["success", "failed", "noted"]
    message: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# WorldView (locked contract with the world simulator)
# ---------------------------------------------------------------------------


class WorldView(BaseModel):
    """Returned by ``World.observe(robot_position, facing, holding)``.

    LOCKED INTERFACE. This is what world code produces and
    what ``build_observation()`` consumes. Do not change field names
    or types here without coordinating; both sides break otherwise.
    """

    model_config = {"extra": "forbid"}

    current_room: str = Field(min_length=1)
    room_description: str = Field(min_length=1)
    visible_objects: list[VisibleObject] = Field(default_factory=list)
    exits: list[Exit] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Final observation (what the LLM sees)
# ---------------------------------------------------------------------------


class Observation(BaseModel):
    """The complete observation passed to the LLM each turn.

    ``step`` and ``task`` are constants in spirit (the task does not
    change within a run). ``robot`` is the agent's own state.
    ``room_description``, ``visible_objects``, ``exits`` come from the
    ``WorldView``. ``last_action`` is the immediate consequence of the
    previous action, included even though a fuller history sits in a
    separate block of the prompt. ``notes`` is the agent-written
    scratchpad replayed back. ``stuck_hint`` is a one-time nudge set
    by the loop when no progress has been made for a while.
    """

    model_config = {"extra": "forbid"}

    step: int = Field(ge=0)
    task: str = Field(min_length=1)
    robot: RobotState
    room_description: str = Field(min_length=1)
    visible_objects: list[VisibleObject] = Field(default_factory=list)
    exits: list[Exit] = Field(default_factory=list)
    last_action: Optional[LastAction] = None
    notes: str = ""
    stuck_hint: Optional[str] = None


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_observation(
    *,
    step: int,
    task: str,
    world_view: WorldView,
    robot: RobotState,
    last_action: Optional[LastAction] = None,
    notes: str = "",
    stuck_hint: Optional[str] = None,
) -> Observation:
    """Assemble a complete ``Observation`` for the LLM.

    world simulator produces the ``WorldView``. Everything
    else comes from the harness: the step counter, the task string,
    the agent's notes, any stuck hint.

    Visible objects are sorted by ``(distance, id)`` so identical
    world states produce identical observation strings. Determinism
    matters more than you would expect when debugging agent runs.
    """
    sorted_objects = sorted(
        world_view.visible_objects, key=lambda o: (o.distance, o.id)
    )
    return Observation(
        step=step,
        task=task,
        robot=robot,
        room_description=world_view.room_description,
        visible_objects=sorted_objects,
        exits=list(world_view.exits),
        last_action=last_action,
        notes=notes,
        stuck_hint=stuck_hint,
    )


def summarize_observation(obs: Observation) -> str:
    """Compact one-line summary of an observation.

    Used for the recent-history block, where verbosity costs tokens
    and the LLM does not need full state, only a reminder of what was
    happening. Sample output::

        "step 12 in kitchen, holding kettle, saw sink/fridge/counter, last: pick_up -> success"
    """
    parts: list[str] = [f"step {obs.step} in {obs.robot.room}"]

    if obs.robot.holding is not None:
        parts.append(f"holding {obs.robot.holding.type}")

    if obs.visible_objects:
        names = [o.type for o in obs.visible_objects[:5]]
        suffix = "..." if len(obs.visible_objects) > 5 else ""
        parts.append(f"saw {'/'.join(names)}{suffix}")

    if obs.last_action is not None:
        parts.append(
            f"last: {obs.last_action.action} -> {obs.last_action.result}"
        )

    return ", ".join(parts)


def observation_to_llm_text(obs: Observation) -> str:
    """Render an Observation as a JSON string ready for the LLM prompt.

    Excludes ``None`` fields so absent values do not clutter the
    prompt, but keeps empty strings (the absence of notes is itself
    informative).
    """
    return obs.model_dump_json(indent=2, exclude_none=True)


__all__ = [
    "VisibleObject",
    "Exit",
    "HeldObject",
    "RobotState",
    "LastAction",
    "WorldView",
    "Observation",
    "build_observation",
    "summarize_observation",
    "observation_to_llm_text",
]
