import json
import os
import time
import threading
from datetime import datetime
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

    # Open a log file for this run
    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = f"logs/{timestamp}_{task.name}.jsonl"
    log_file = open(log_path, "w", encoding="utf-8")
    print(f"  Logging to {log_path}")

    try:
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
            action.object_id = action_data.get("object_id", None)
            action.target_id = action_data.get("target_id", "floor")
            action.text = action_data.get("text", "")

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

            # Save to log file
            log_file.write(json.dumps(step_record) + "\n")
            log_file.flush()

            on_step(step_record)

            if task.is_successful(world):
                # Write outcome into last record for replay
                step_record["outcome"] = "success"
                return "success", history, step

            time.sleep(1.0)

        return "failed", history, max_steps

    finally:
        log_file.close()