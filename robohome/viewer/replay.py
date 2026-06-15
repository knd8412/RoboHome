"""
robohome/viewer/replay.py

Replays a saved JSONL run log in the mission control viewer.
No LLM calls are made — it just reads the file and re-emits the steps.

Usage:
    python -m robohome.viewer.replay logs/2026_make_tea.jsonl
    python -m robohome.viewer.replay logs/2026_make_tea.jsonl --speed 2.0
"""

import json
import sys
import time
import threading
from pathlib import Path

from flask import Flask, send_from_directory
from flask_socketio import SocketIO

STATIC_DIR = Path(__file__).parent / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
app.config["SECRET_KEY"] = "robohome-replay"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Set by main() before the server starts
_replay_path: Path | None = None
_replay_speed: float = 1.0


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@socketio.on("connect")
def on_connect():
    """As soon as the browser connects, start the replay automatically."""
    def run():
        # Small delay so the browser has time to finish loading
        time.sleep(1.0)

        try:
            lines = _replay_path.read_text(encoding="utf-8").strip().splitlines()
        except Exception as e:
            socketio.emit("task_complete", {
                "status": "failed",
                "message": f"Could not read replay file: {e}",
                "steps": 0,
            })
            return

        steps = []
        for line in lines:
            try:
                steps.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip malformed lines

        if not steps:
            socketio.emit("task_complete", {
                "status": "failed",
                "message": "Replay file is empty or malformed.",
                "steps": 0,
            })
            return

        delay = 1.0 / _replay_speed

        for record in steps:
            socketio.emit("step_event", record)
            time.sleep(delay)

        # Final status — check last step or look for a stored outcome
        last = steps[-1]
        outcome = last.get("outcome", "success")
        total = last.get("step", len(steps))

        socketio.emit("task_complete", {
            "status": outcome,
            "steps": total,
            "message": "Replay complete.",
        })

    threading.Thread(target=run, daemon=True).start()


@socketio.on("start_run")
def on_start_run(data):
    """
    The frontend's START button fires this event.
    In replay mode we ignore the task selection and just re-run the file.
    """
    on_connect()


def run_replay(path: Path, speed: float = 1.0, port: int = 5001):
    global _replay_path, _replay_speed
    _replay_path = path
    _replay_speed = speed

    print(f"  RoboHome Replay  →  http://127.0.0.1:{port}")
    print(f"  File  : {path}")
    print(f"  Speed : {speed}x")
    print()
    socketio.run(app, host="127.0.0.1", port=port, debug=False, use_reloader=False)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Replay a RoboHome run log in the viewer")
    parser.add_argument("logfile", type=str, help="Path to the .jsonl log file")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="Playback speed multiplier (e.g. 2.0 = twice as fast)")
    parser.add_argument("--port", type=int, default=5001,
                        help="Port to serve on (default 5001 so it doesn't clash with the main server)")
    args = parser.parse_args()

    path = Path(args.logfile)
    if not path.exists():
        print(f"Error: file not found: {path}")
        sys.exit(1)

    run_replay(path=path, speed=args.speed, port=args.port)


if __name__ == "__main__":
    main()