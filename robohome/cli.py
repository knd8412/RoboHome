"""
robohome/cli.py

Entry point for RoboHome. Run with:
    python -m robohome.cli --task make_tea --viewer
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description="RoboHome — LLM-powered household robot simulator"
    )
    parser.add_argument(
        "--task",
        type=str,
        default="make_tea",
        help="Task name to run (e.g. make_tea, go_to_bedroom)"
    )
    parser.add_argument(
        "--viewer",
        action="store_true",
        help="Launch the web viewer at http://localhost:5000"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for the viewer server (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port for the viewer server (default: 5000)"
    )
    parser.add_argument(
        "--no-viewer",
        action="store_true",
        help="Run headless (no web viewer)"
    )

    args = parser.parse_args()

    if args.viewer and not args.no_viewer:
        # Launch the web viewer — it runs the task internally via SocketIO
        from robohome.viewer.server import run_server
        print(f"  Task: {args.task}")
        print(f"  Open http://{args.host}:{args.port} and press START")
        run_server(host=args.host, port=args.port, debug=False)

    else:
        # Headless mode — run the task directly in the terminal
        import threading
        from robohome.world.world import World
        from robohome.harness.loop import run_task
        from robohome.harness.tasks import TASKS

        task = TASKS.get(args.task)
        if task is None:
            print(f"Unknown task '{args.task}'. Available: {list(TASKS.keys())}")
            sys.exit(1)

        print(f"Running task: {task.objective}")
        print("-" * 50)

        def on_step(record: dict):
            step = record["step"]
            action = record["last_action"]["action"]
            result = record["last_action"]["result"]
            message = record["last_action"]["message"]
            room = record["robot"]["room"]
            symbol = "✓" if result == "success" else "✗"
            print(f"  [{step:02d}] {symbol} {action:12s} | {room:12s} | {message}")

        stop_event = threading.Event()
        world = World()
        outcome, history, steps = run_task(
            task=task,
            world=world,
            on_step=on_step,
            stop_event=stop_event,
        )

        print("-" * 50)
        print(f"  Result: {outcome.upper()} in {steps} steps")


if __name__ == "__main__":
    main()