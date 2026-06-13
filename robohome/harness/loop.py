import time
import threading
from typing import Callable, Tuple, List

from robohome.world.world import World
from robohome.harness.tasks import Task


def get_llm_action(observation: dict) -> dict:
    """Placeholder — Kamyar will replace this with the real LLM call."""
    return {"type": "turn", "direction": "east"}


def run_task(
    task: Task,
    world: World,
    on_step: Callable[[dict], None],
    stop_event: threading.Event,
) -> Tuple[str, List[dict], int]:

    task.setup_world(world)
    max_steps = 30
    history = []

    for step in range(1, max_steps + 1):
        if stop_event.is_set():
            return "stopped", history, step

        obs = world.observe()

        action_data = get_llm_action(obs)

        class ActionObj:
            pass

        action = ActionObj()
        action.type = action_data.get("type", "look_around")
        action.direction = action_data.get("direction", "north")

        result = world.execute(action)

        step_record = {
            "step": step,
            "task": task.objective,
            "thought": "Awaiting LLM integration...",
            "robot": {
                "room": obs["current_room"],
                "position": {"x": world.robot.position.x, "y": world.robot.position.y},
                "facing": world.robot.facing,
                "holding": world.robot.holding,
            },
            "last_action": {
                "action": action.type,
                "args": action_data,
                "result": result["status"],
                "message": result["message"],
            },
            "notes": "",
        }
        history.append(step_record)
        on_step(step_record)

        if task.is_successful(world):
            return "success", history, step

        time.sleep(1.0)

    return "failed", history, max_steps