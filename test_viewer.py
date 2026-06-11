from flask import Flask, send_from_directory
from flask_socketio import SocketIO
from pathlib import Path
import threading, time

STATIC = Path(__file__).parent / "robohome/viewer/static"
app = Flask(__name__, static_folder=str(STATIC))
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC, filename)

# The house grid — walls and doors as the world module would produce them
GRID = {}

# Top of hallway: y=5, full row = walls
for x in range(20):
    GRID[f"{x},5"] = {"cell_type": "wall", "is_open": False}
    GRID[f"{x},8"] = {"cell_type": "wall", "is_open": False}

# Vertical wall between bedroom/bathroom
for y in range(5):
    GRID[f"9,{y}"] = {"cell_type": "wall", "is_open": False}

# Vertical wall between kitchen/living room
for y in range(10, 15):
    GRID[f"9,{y}"] = {"cell_type": "wall", "is_open": False}

# Doors (all start closed)
GRID["4,5"]  = {"cell_type": "door", "is_open": False}
GRID["14,5"] = {"cell_type": "door", "is_open": False}
GRID["4,8"]  = {"cell_type": "door", "is_open": False}
GRID["14,8"] = {"cell_type": "door", "is_open": False}

@socketio.on("start_run")
def handle_start(data):
    def fake_run():
        steps = [
            # (action, args, message, room, x, y, facing, holding, open_door)
            (1,  "look_around", "",             "Surveying the kitchen.",         "kitchen",  5, 12, "N", None,     None),
            (2,  "move",        "direction=N",  "Moved north.",                   "kitchen",  5, 11, "N", None,     None),
            (3,  "move",        "direction=N",  "Moved north.",                   "kitchen",  5, 10, "N", None,     None),
            (4,  "pick_up",     "object=kettle","You picked up the kettle.",      "kitchen",  5, 10, "N", "kettle", None),
            (5,  "use",         "kettle→sink",  "Filled kettle with water.",      "kitchen",  6, 10, "E", "kettle", None),
            (6,  "use",         "kettle→stove", "Boiling water on stove.",        "kitchen",  7, 11, "S", "kettle", None),
            (7,  "note",        "text=kettle boiling on stove", "Noted.",         "kitchen",  7, 11, "N", "kettle", None),
            (8,  "move",        "direction=N",  "Moving toward hallway door.",    "kitchen",  5, 10, "N", "kettle", None),
            (9,  "open",        "object=door",  "Opened kitchen door.",           "kitchen",  5,  9, "N", "kettle", "4,8"),
            (10, "move",        "direction=N",  "Entered hallway.",               "hallway",  4,  7, "N", "kettle", None),
            (11, "move",        "direction=N",  "Moving through hallway.",        "hallway",  4,  6, "N", "kettle", None),
            (12, "put_down",    "target=mug",   "Poured hot water into mug.",     "hallway",  4,  6, "N", "mug",    None),
            (13, "use",         "tea_bag→mug",  "Tea bag added. Brewing...",      "hallway",  4,  6, "N", "mug",    None),
            (14, "done",        "",             "Task complete! Tea is ready. ☕", "hallway",  4,  6, "N", "mug",    None),
        ]

        notes = ""
        grid = dict(GRID)  # copy so we can mutate doors

        for (step, action, args, msg, room, x, y, facing, hold, open_door) in steps:
            time.sleep(2.0)  # slow enough to watch

            if open_door:
                grid[open_door] = {"cell_type": "door", "is_open": True}

            if action == "note":
                notes += args.replace("text=", "") + "\n"

            socketio.emit("step_event", {
                "step": step,
                "task": "Make a cup of tea",
                "thought": "I need to follow the tea-making steps carefully — kettle, water, stove, mug, tea bag.",
                "robot": {
                    "room": room,
                    "position": {"x": x, "y": y},
                    "facing": facing,
                    "holding": hold,
                },
                "notes": notes.strip(),
                "last_action": {
                    "action": action,
                    "args": {"detail": args},
                    "result": "success",
                    "message": msg,
                },
                "grid": grid,
                "objects": {},
            })

        time.sleep(1)
        socketio.emit("task_complete", {
            "status": "success",
            "steps": len(steps),
            "message": "Mission accomplished!",
        })

    threading.Thread(target=fake_run, daemon=True).start()


if __name__ == "__main__":
    print("Open http://localhost:5000")
    socketio.run(app, port=5000, debug=False)