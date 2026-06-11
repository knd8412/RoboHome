"""
robohome/viewer/server.py

Flask + Flask-SocketIO backend for the RoboHome mission control viewer.
Serves the static frontend and bridges SocketIO events to the harness loop.
"""

import json
import threading
from pathlib import Path

from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit

# ── App setup ─────────────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
app.config["SECRET_KEY"] = "robohome-dev"

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# ── SocketIO events ───────────────────────────────────────────────────────────
_run_thread: threading.Thread | None = None
_stop_event = threading.Event()


@socketio.on("start_run")
def handle_start_run(data: dict):
    """Client pressed START. Launch the harness in a background thread."""
    global _run_thread, _stop_event

    task_name = data.get("task", "make_tea")
    _stop_event.clear()

    def run():
        try:
            from robohome.harness.loop import run_task
            from robohome.world.world import World
            from robohome.harness.tasks import TASKS

            world = World()
            task = TASKS.get(task_name)
            if task is None:
                emit("task_complete", {"status": "failed", "message": f"Unknown task: {task_name}", "steps": 0})
                return

            def on_step(step_record: dict):
                """Called by the harness after every step."""
                if _stop_event.is_set():
                    return
                # Attach live grid snapshot for the canvas renderer
                step_record["grid"] = _serialise_grid(world)
                step_record["objects"] = _serialise_objects(world)
                socketio.emit("step_event", step_record)

            outcome, history, steps = run_task(
                task=task,
                world=world,
                on_step=on_step,
                stop_event=_stop_event,
            )

            socketio.emit("task_complete", {
                "status": outcome,
                "steps": steps,
                "message": "Mission accomplished!" if outcome == "success" else "Max steps reached or task failed.",
            })

        except Exception as exc:
            socketio.emit("task_complete", {
                "status": "failed",
                "message": str(exc),
                "steps": 0,
            })

    _run_thread = threading.Thread(target=run, daemon=True)
    _run_thread.start()


@socketio.on("reset")
def handle_reset():
    """Client pressed RESET — stop any running task."""
    _stop_event.set()


# ── Serialisation helpers ─────────────────────────────────────────────────────
def _serialise_grid(world) -> dict:
    """
    Convert the Grid into a flat {x,y -> cell_info} dict the canvas can draw.
    Only sends non-floor cells to keep payload small.
    """
    result = {}
    for y in range(world.grid.height):
        for x in range(world.grid.width):
            cell = world.grid.get_cell(x, y)
            if cell and cell.cell_type.value != "floor":
                result[f"{x},{y}"] = {
                    "cell_type": cell.cell_type.value,
                    "is_open": getattr(cell, "is_open", False),
                }
    return result


def _serialise_objects(world) -> dict:
    """Convert all world objects to JSON-safe dicts."""
    result = {}
    for obj_id, obj in world.objects.items():
        pos = obj.position
        if hasattr(pos, "x"):
            pos_data = {"x": pos.x, "y": pos.y}
        else:
            pos_data = str(pos)          # inside a container — skip drawing
        result[obj_id] = {
            "id": obj.id,
            "type": obj.type,
            "position": pos_data,
            "properties": obj.properties,
            "affordances": obj.affordances,
        }
    return result


# ── Entry point ───────────────────────────────────────────────────────────────
def run_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
    """Start the viewer server. Called by cli.py when --viewer flag is set."""
    print(f"  RoboHome viewer  →  http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    run_server(debug=True)