"""
Action schemas for the RoboHome agent.

This module defines the 10 primitive actions the agent can take, the
``ActionResult`` type the World returns when executing them, and the
adapter functions that move between Gemini's function-calling format and
our Pydantic models.

Design choices worth knowing
----------------------------
1. We use a generic ``use(object_id, target_id)`` instead of typed verbs
   like ``fill``, ``pour``, ``boil``. The dispatch lives in the world, so
   we can add new interactions without changing the LLM's tool list.
   Keeping the action space tight matters: every extra tool the LLM sees
   is more prompt tokens and one more way to hallucinate.

2. Directions are full lowercase words (``"north"`` etc.) rather than
   ``"N"`` etc. The LLM produces full words more reliably and there's no
   meaningful token-cost reason to be terse here.

3. ``note(text)`` and ``done`` are agent-side actions: the world does not
   execute them but they go through the same schema so the loop can
   handle them uniformly.

4. Every action is a frozen Pydantic model with ``extra='forbid'``. The
   LLM cannot smuggle in extra fields, and once we have an Action object
   the rest of the harness treats it as immutable.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------------


class Direction(str, Enum):
    """Cardinal directions used for movement and facing."""

    NORTH = "north"
    EAST = "east"
    SOUTH = "south"
    WEST = "west"


# ---------------------------------------------------------------------------
# Action models
# ---------------------------------------------------------------------------
# All actions share a ``type`` literal discriminator. The LLM returns one
# of these as a function call; the parser validates against the union; the
# loop dispatches on ``type``.


class _ActionBase(BaseModel):
    """Internal base. Subclass and set a Literal ``type``."""

    model_config = {"extra": "forbid", "frozen": True}


class Move(_ActionBase):
    """Step one cell in a cardinal direction."""

    type: Literal["move"] = "move"
    direction: Direction = Field(
        description="Cardinal direction to step toward (one cell)."
    )


class Turn(_ActionBase):
    """Face a direction without moving."""

    type: Literal["turn"] = "turn"
    direction: Direction = Field(description="Cardinal direction to face.")


class LookAround(_ActionBase):
    """Refresh the observation. No arguments, no state change.

    Useful when the agent is uncertain or wants a fresh listing of nearby
    objects without changing anything.
    """

    type: Literal["look_around"] = "look_around"


class PickUp(_ActionBase):
    """Grab an object into the robot's single hand slot.

    The object must be within one cell and have the ``pickable``
    affordance. The robot can only hold one object at a time.
    """

    type: Literal["pick_up"] = "pick_up"
    object_id: str = Field(
        description="The id of the object to pick up, e.g. 'kettle_1'.",
        min_length=1,
    )


class PutDown(_ActionBase):
    """Place the held object on a surface or the current floor cell.

    Pass ``target_id='floor'`` to drop on the robot's current cell.
    """

    type: Literal["put_down"] = "put_down"
    target_id: str = Field(
        description=(
            "Either the id of a surface object to place onto "
            "(e.g. 'counter_1') or the literal string 'floor' to drop "
            "on the current cell."
        ),
        min_length=1,
    )


class Open(_ActionBase):
    """Open a door, fridge, cupboard, or other openable object."""

    type: Literal["open"] = "open"
    object_id: str = Field(
        description="The id of the openable object.", min_length=1
    )


class Close(_ActionBase):
    """Close a previously opened object."""

    type: Literal["close"] = "close"
    object_id: str = Field(
        description="The id of the openable object to close.", min_length=1
    )


class Use(_ActionBase):
    """Use one object on another. Generic interaction verb.

    The world resolves the result from the affordances of the pair.
    Examples: ``use(kettle_1, sink_1)`` fills the kettle; ``use(kettle_1,
    mug_1)`` pours; ``use(tea_bag_1, mug_1)`` places the tea bag.
    """

    type: Literal["use"] = "use"
    object_id: str = Field(
        description=(
            "The id of the object the robot is acting with "
            "(often the held object)."
        ),
        min_length=1,
    )
    target_id: str = Field(
        description="The id of the object being acted upon.",
        min_length=1,
    )


class Note(_ActionBase):
    """Append a line to the agent's persistent scratchpad.

    Use this to remember things the current observation does not
    include: object locations in other rooms, plan steps, hypotheses
    to revisit. The notes are replayed back to the agent every turn.
    """

    type: Literal["note"] = "note"
    text: str = Field(
        description="A short reminder to record. Keep under one sentence.",
        min_length=1,
        max_length=500,
    )

    @field_validator("text")
    @classmethod
    def _strip_and_check(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("note text must not be blank after stripping")
        return v


class Done(_ActionBase):
    """Declare the task complete. The harness will verify against the goal."""

    type: Literal["done"] = "done"


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------

AnyAction = Annotated[
    Union[Move, Turn, LookAround, PickUp, PutDown, Open, Close, Use, Note, Done],
    Field(discriminator="type"),
]


# Tool order seen by the LLM. Navigation first, then object manipulation,
# then meta-actions. Models tend to slightly favour earlier tools, so this
# ordering encodes a soft priority.
ALL_ACTION_TYPES: tuple[type[_ActionBase], ...] = (
    Move,
    Turn,
    LookAround,
    PickUp,
    PutDown,
    Open,
    Close,
    Use,
    Note,
    Done,
)


# ---------------------------------------------------------------------------
# Action result (contract with the World)
# ---------------------------------------------------------------------------


class ActionResult(BaseModel):
    """Returned by ``World.execute(action)``.

    ``message`` is shown back to the LLM on the next turn, so it should
    read like something you would tell a robot in plain English. Bad
    message: ``"IllegalMoveException"``. Good message: ``"You tried to
    move north but a wall is blocking you."``
    """

    model_config = {"extra": "forbid"}

    status: Literal["success", "failed"]
    message: str = Field(min_length=1)
    state_changes: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured diff for debugging and logs.",
    )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


class _ActionEnvelope(BaseModel):
    """Wrapper used to leverage Pydantic's discriminated-union validation."""

    model_config = {"extra": "forbid"}

    action: AnyAction


def parse_action(data: dict[str, Any]) -> Any:
    """Parse an arbitrary dict (e.g. from the LLM) into a concrete Action.

    Raises ``pydantic.ValidationError`` if the dict does not match any
    action schema. The agent loop catches this and feeds the error back
    to the LLM as a retry hint.
    """
    return _ActionEnvelope.model_validate({"action": data}).action


# ---------------------------------------------------------------------------
# Gemini tool schemas
# ---------------------------------------------------------------------------


def _strip_discriminator(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove the ``type`` discriminator from a Pydantic JSON schema.

    Gemini receives the function name separately, so re-including the
    discriminator in the parameters confuses the model.
    """
    schema = dict(schema)
    props = dict(schema.get("properties", {}))
    props.pop("type", None)
    schema["properties"] = props
    required = [r for r in schema.get("required", []) if r != "type"]
    if required:
        schema["required"] = required
    elif "required" in schema:
        schema.pop("required")
    return schema


def _inline_refs_and_strip_titles(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve internal ``$ref`` references and remove ``title`` fields.

    Gemini's function-call schema supports a subset of OpenAPI 3.0 and
    does not reliably handle ``$ref`` / ``$defs``. We inline everything
    and drop the cosmetic ``title`` keys Pydantic injects.

    A ``$ref`` may appear alongside sibling fields like ``description``.
    In that case we inline the referenced schema and merge the siblings
    on top (so a field-level description overrides the enum's own).
    """
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                if ref.startswith("#/$defs/"):
                    target = walk(dict(defs[ref.split("/")[-1]]))
                    siblings = {
                        k: walk(v)
                        for k, v in node.items()
                        if k not in {"$ref", "title"}
                    }
                    merged = {**target, **siblings}
                    return merged
                return node
            return {k: walk(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(schema)


def _action_to_function_declaration(model: type[_ActionBase]) -> dict[str, Any]:
    """Convert one Action model into a Gemini-compatible function declaration."""
    raw_schema = model.model_json_schema()
    parameters = _strip_discriminator(raw_schema)
    parameters = _inline_refs_and_strip_titles(parameters)

    name: str = model.model_fields["type"].default  # the Literal default
    description = (model.__doc__ or "").strip().split("\n\n")[0]

    return {
        "name": name,
        "description": description,
        "parameters": parameters,
    }


def to_gemini_tools() -> list[dict[str, Any]]:
    """Return the full action set as Gemini function declarations.

    Pass the result into the ``tools`` parameter when calling Gemini::

        from google import genai
        from google.genai import types
        from robohome.harness.actions import to_gemini_tools

        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[...],
            config=types.GenerateContentConfig(
                tools=[types.Tool(function_declarations=to_gemini_tools())],
            ),
        )
    """
    return [_action_to_function_declaration(m) for m in ALL_ACTION_TYPES]


def gemini_function_call_to_action(name: str, args: dict[str, Any]) -> Any:
    """Adapter for the LLM's function-call response.

    Gemini returns ``function_call.name`` and ``function_call.args`` as
    two separate fields. This combines them back into the dict shape
    ``parse_action`` expects.
    """
    return parse_action({"type": name, **args})


__all__ = [
    "Direction",
    "Move",
    "Turn",
    "LookAround",
    "PickUp",
    "PutDown",
    "Open",
    "Close",
    "Use",
    "Note",
    "Done",
    "AnyAction",
    "ALL_ACTION_TYPES",
    "ActionResult",
    "parse_action",
    "to_gemini_tools",
    "gemini_function_call_to_action",
]
