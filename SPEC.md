# RoboHome: Project Specification

**Repository:** https://github.com/knd8412/RoboHome
**Team:** Kamyar Nadarkhanidinehkaboudi, Armita
**Purpose:** Submission for Humanoid Robotics Software Engineering Internship + portfolio project
**Status:** Specification locked, ready to build

---

## 0. How to Use This Document

This file is the single source of truth for the project. Both team members should commit it to the repo root as `SPEC.md` on Day 1 and refer back to it whenever a design question comes up.

If you are giving this to an AI coding assistant (Claude, ChatGPT, Cursor, etc.), paste it in as part of your system prompt or initial context, then ask for the specific component you are working on. Example:

> "Here is the full spec for the RoboHome project I'm building. I am working on the observation system (see Section 5 and my ownership in Section 14). Help me implement `robohome/harness/observation.py` according to the spec, starting with the function that converts world state into the observation JSON."

Do not let the AI deviate from this spec without checking with the human teammate first. Interface contracts between components are locked here for a reason.

---

## 1. Project Overview

**One-liner:** A harness that wires an LLM into a simulated 2D household and asks it to do chores. The agent perceives its environment, reasons about it, picks an action, and the world responds. The interesting engineering is the interface between the LLM and the world.

**The hook:** The application is to Humanoid, a humanoid robotics company. A household chore agent is on-brand and the demo video sells itself.

**Why this scope:** A 2D grid is fast to build and visualize but rich enough to demand real planning, partial observability, and tool use. We do not waste time wrestling with 3D physics.

---

## 2. The Challenge (Verbatim Requirements)

From the Humanoid intern brief, at minimum the system must:

1. Create a virtual environment the agent can exist in
2. Define an observation format that represents the agent's current state and surroundings
3. Define an action space the agent can use to interact with the world
4. Wire up an LLM to observe state, reason, and choose actions in a loop
5. Demonstrate the agent completing at least one goal-directed task

What they grade on (their exact words):

1. Quality of the agent harness, how well you've designed the interface between the LLM and the environment
2. Whether the agent can actually accomplish tasks, not just generate plausible text
3. Thoughtfulness about observation representation
4. Creativity in the world, the tasks, or the agent's capabilities
5. Simplicity and usability of your solution

What they explicitly said does NOT matter: the world itself. *"The core challenge isn't the world itself, it's the harness."*

Submission requirements:
- Public GitHub repository
- README with run instructions and a short note on design choices
- Working codebase
- Example input(s) and output(s), ideally a recording or log

---

## 3. Tech Stack (Locked)

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | Universal, great LLM SDKs, both team members know it |
| Rendering | Pygame | Used purely as a drawing library to produce PNGs, no game loop |
| Web backend | Flask + Flask-SocketIO | Smallest viable server for live updates |
| Web frontend | Plain HTML/CSS/JS (no framework) | No build step, zero npm headaches |
| LLM (primary) | Gemini 2.5 Flash via `google-generativeai` | 1500 req/day free, 1M context, function calling, no credit card |
| LLM (fallback) | Groq Llama 3.3 70B via `groq` SDK | Fast, free, drop-in when Gemini quota hits |
| Data validation | Pydantic v2 | Typed schemas for actions and observations |
| Testing | pytest | Standard |
| Config | `python-dotenv` | API keys via `.env`, never committed |

We are deliberately not using LangChain, LangGraph, or any agent framework. Humanoid is grading the harness, so writing it ourselves is the point.

---

## 4. The World

### 4.1 Grid

- 20 cells wide, 15 cells tall (300 cells total)
- Coordinate system: `(x, y)` where `(0, 0)` is top-left, x increases east, y increases south
- Cell types:
  - `floor`: walkable
  - `wall`: blocks movement and vision
  - `door`: walkable only if `is_open == True`

### 4.2 Rooms

Five rooms connected by doors:

- **Kitchen** (bottom-left quadrant)
- **Living room** (bottom-right quadrant)
- **Hallway** (middle strip, connects everything)
- **Bedroom** (top-left quadrant)
- **Bathroom** (top-right quadrant)

Each room is a named rectangular region. A cell can be queried for which room it belongs to.

### 4.3 Robot State

```python
{
    "position": (x, y),        # current cell
    "facing": "N" | "E" | "S" | "W",
    "holding": object_id or None,  # one-hand limit
}
```

### 4.4 Object Schema

Every object in the world conforms to:

```python
{
    "id": str,              # unique, e.g. "kettle_1"
    "type": str,            # e.g. "kettle"
    "position": (x, y) or container_id,  # cell coords OR inside another object
    "properties": dict,     # type-specific state
    "affordances": list[str],  # what can be done with it
}
```

Standard affordances: `pickable`, `pourable`, `fillable`, `openable`, `heatable`, `readable`, `sittable`, `placeable_on`, `container`.

### 4.5 Object Catalogue

| Room | Objects |
|---|---|
| Kitchen | kettle, mug, tea_bag, fridge (container), milk (in fridge), sink, stove, counter (surface), cupboard (container), trash_bin (container), dirty_dish |
| Living room | sofa, tv, bookshelf (surface), book_1, book_2, coffee_table (surface) |
| Bedroom | bed, desk (surface), lamp, chair, keys |
| Bathroom | toilet, basin, towel |
| Hallway | coat_rack |

Containers (fridge, cupboard, trash_bin) hide their contents from observation until opened.

### 4.6 World Rules (Enforced by `World.execute`)

- Cannot walk through walls
- Cannot walk through closed doors
- Cannot pick up objects more than 1 cell away from the robot
- Cannot pick up an object if already holding one
- Cannot pick up non-pickable objects (e.g. stove)
- Cannot put down on a non-surface cell unless target is `floor`
- Cannot pour from an empty container
- Cannot use objects that don't support the relevant affordance pair

When the world rejects an action, it returns a structured failure reason that gets fed back to the agent.

---

## 5. Observation Format

This is what the LLM actually sees on every step. Format is JSON, built by `robohome/harness/observation.py`.

```json
{
  "step": 12,
  "task": "make a cup of tea and bring it to the bedroom",
  "robot": {
    "room": "kitchen",
    "position": [5, 8],
    "facing": "north",
    "holding": {
      "id": "kettle_1",
      "type": "kettle",
      "state": {"contains": "empty", "temperature": "cold"}
    }
  },
  "room_description": "You are in the kitchen. To your north is a counter with a sink. To the east is a fridge. The door to the hallway is south.",
  "visible_objects": [
    {
      "id": "sink_1",
      "type": "sink",
      "direction": "north",
      "distance": 1,
      "state": {"water_running": false}
    },
    {
      "id": "fridge_1",
      "type": "fridge",
      "direction": "east",
      "distance": 2,
      "state": {"is_open": false}
    }
  ],
  "exits": [
    {"to_room": "hallway", "direction": "south", "via": "door_2", "is_open": true}
  ],
  "last_action": {
    "action": "pick_up",
    "args": {"object_id": "kettle_1"},
    "result": "success",
    "message": "You picked up the kettle."
  },
  "notes": "Saw a mug in the kitchen cupboard at step 4. Bedroom is north of the hallway."
}
```

### 5.1 Partial Observability

- The agent sees only objects in its current room
- Containers hide contents unless `is_open == True`
- Anything in another room must be remembered (via the `notes` field, agent-written)

### 5.2 The `notes` Field

Agent-written persistent scratchpad. The agent appends to it via the `note(text)` action. We always replay the current notes back into the observation. This is the project's main memory mechanism, by design (Section 7.5).

---

## 6. Action Space

### 6.1 Primitive Actions

These are the actions the world actually executes. Defined as Pydantic models in `robohome/harness/actions.py`. Each becomes a function-call schema sent to the LLM.

| Action | Args | Effect |
|---|---|---|
| `move` | `direction: N\|E\|S\|W` | Step one cell if not blocked |
| `turn` | `direction: N\|E\|S\|W` | Face a direction without moving |
| `look_around` | none | Refresh observation, no state change |
| `pick_up` | `object_id: str` | Grab an adjacent pickable object into hand |
| `put_down` | `target_id: str \| "floor"` | Place held object on surface or current floor |
| `open` | `object_id: str` | Open door, fridge, cupboard |
| `close` | `object_id: str` | Inverse of `open` |
| `use` | `object_id: str, target_id: str` | Generic interaction (fill kettle at sink, pour mug into kettle, put tea_bag in mug, etc.) |
| `note` | `text: str` | Append a line to the agent's scratchpad |
| `done` | none | Declare task complete (triggers goal check) |

### 6.2 Macros (Optional Sugar)

| Macro | Args | Expansion |
|---|---|---|
| `go_to_room` | `room_name: str` | A* pathfinding through doors to a cell in target room |
| `go_to_object` | `object_id: str` | A* pathfinding to a cell adjacent to the object |

Macros execute as a sequence of primitive `move` actions, one per step. This way the viewer animates smoothly and the agent can detect mid-route failures. If the macro fails (e.g. door is locked), the agent sees a structured failure and can replan.

### 6.3 Use-Action Semantics

`use(A, B)` is the catch-all for object interactions. The world resolves it based on the affordances of A and B:

| A | B | Effect |
|---|---|---|
| empty kettle | sink | Fill kettle with water |
| kettle (water) | stove | Boil water in kettle |
| kettle (hot water) | mug | Pour hot water into mug |
| tea_bag | mug | Place tea bag in mug |
| mug (with hot water and tea_bag) | (auto after time) | Becomes a mug of tea |
| milk | mug | Add splash of milk |
| dirty_dish | trash_bin | Dispose |
| key | lock | Unlock (future, not in v1) |

The full `use` dispatch table lives in `robohome/world/world.py`.

---

## 7. Agent Design

### 7.1 LLM Choice

- **Primary:** Gemini 2.5 Flash (`gemini-2.5-flash` or current equivalent) via the `google-generativeai` Python SDK
- **Fallback:** Groq Llama 3.3 70B via the `groq` SDK
- Swap is a one-line config change (`LLM_PROVIDER=gemini` or `groq` in `.env`)

### 7.2 Prompt Structure

**System prompt** (sent once, established at session start):

```
You are a household robot operating in a 2D simulated house.
You receive an observation each turn and must choose exactly one action.
Available actions are provided as function tools.

Rules:
- You can only hold one object at a time.
- You can only interact with objects in your current room and within 1 cell.
- Doors must be opened before you can pass through them.
- Containers (fridge, cupboard) hide their contents until opened.
- Use the `note` action to remember things across steps; otherwise you will forget.
- When the task is complete, call `done`.

Always think briefly about your goal before acting.
```

**Per-step user message:**

```
<observation JSON from Section 5>

What is your next action?
```

### 7.3 Function Calling (Critical)

Instead of asking the LLM for free-text JSON and parsing it, we register each action from Section 6.1 as a function/tool in the Gemini SDK. The model returns a structured `function_call` object directly. This eliminates ~90% of parse errors.

For the Groq fallback (no native function calling on Llama 3.3 free tier), we fall back to instructed JSON output with retry-on-parse-error.

### 7.4 Action History

The last 8 (observation summary, action, result) tuples are included in each prompt as a recent-history block. This is the agent's short-term memory.

### 7.5 The Notes Scratchpad

The agent's main long-term memory. It writes via the `note(text)` action and we always include the current notes string in the observation. No vector DB, no RAG, deliberately simple. This choice is one of the main things we explain in `design_notes.md` because "we did the simple thing because the harness doesn't need more" is itself a design statement.

### 7.6 Bad-Action Handling

- Function-call schema validation handles most issues at the SDK level
- For Groq/JSON mode: validate against Pydantic, retry up to 3 times with parse error fed back
- If 3 retries fail: take a `look_around` action automatically and continue
- If the action is well-formed but illegal in the world (e.g. pick up something out of reach): execute and let the world return a failure reason, the agent sees it next step and adapts

### 7.7 Stuck Detection

If the robot's `position` and `holding` haven't changed in 8 consecutive steps, inject a one-time hint into the next observation:

> "You appear stuck. Reconsider your plan and try a different approach."

### 7.8 Termination

A run ends when any of these is true:

- Agent calls `done` action
- Task goal predicate returns `True` independently (auto-detected)
- Step counter hits `max_steps` (default 60)

---

## 8. Harness Loop (Pseudocode)

```python
def run(task, world, agent, max_steps=60):
    history = []
    notes = ""

    for step in range(max_steps):
        obs = build_observation(
            world=world,
            task=task,
            step=step,
            recent_history=history[-8:],
            notes=notes,
            stuck_hint=detect_stuck(history),
        )

        response = agent.think(obs)  # returns parsed Action
        action = response.action
        thought = response.thought

        if action.type == "note":
            notes += "\n" + action.text
            result = {"status": "noted"}
        elif action.type == "done":
            if task.is_complete(world.state):
                return ("success", history, step)
            else:
                result = {"status": "failed", "message": "Task not actually complete."}
        else:
            result = world.execute(action)

        history.append({
            "step": step,
            "observation_summary": summarize(obs),
            "thought": thought,
            "action": action.model_dump(),
            "result": result,
        })

        if task.is_complete(world.state):
            return ("success", history, step)

    return ("timeout", history, max_steps)
```

---

## 9. Viewer

### 9.1 Backend

- Flask app serving `index.html` at `/`
- Flask-SocketIO endpoint `/run` accepts a task name and runs the harness in a background thread
- Emits `step_event` on each loop iteration with the full step record
- Emits `task_complete` at the end with success/fail and metrics

### 9.2 Frontend Layout

- **Top bar:** task dropdown, start/pause/reset buttons, step counter, status indicator (running/success/failed)
- **Left pane (60% width):** HTML5 canvas rendering the grid live
  - Cells: pale gray floor, dark gray walls, brown doors (closed) or open gaps (open)
  - Objects: emoji or simple colored squares with text labels
  - Robot: distinct color with a small triangle showing facing direction
- **Right pane (40% width):** scrolling log of step cards, each showing:
  - Step number
  - Action and result (color-coded green/red)
  - Thought (collapsed by default, click to expand)

### 9.3 Replay Mode

`python -m robohome.viewer.replay path/to/run.jsonl` loads a saved log and replays it in the viewer without making any LLM calls. Essential for:

- Recording the demo video without burning API quota
- Iterating on viewer UI without re-running expensive task runs
- Debugging failed runs

### 9.4 Logging

Every run writes a JSONL file to `logs/<timestamp>_<task_name>.jsonl`. One line per step. Includes everything needed for replay.

---

## 10. Task Suite

Eight tasks in `robohome/harness/tasks.py`. Each has a `description` (the natural language task the LLM sees) and an `is_complete(world)` predicate.

| # | Difficulty | Task | Goal Predicate (informal) | Tests |
|---|---|---|---|---|
| 1 | Easy | Go to the bedroom | `robot.room == "bedroom"` | Navigation, doors |
| 2 | Easy | Find the keys and say where they are | Agent has noted location AND called `done` | Search across rooms, memory use |
| 3 | Medium | Bring the book to the living room | `book_1.room == "living_room"` | Navigation + carry |
| 4 | Medium | Open the fridge and report the contents | `fridge.is_open AND agent has noted contents` | Interaction + observation |
| 5 | Medium | Tidy the kitchen | `dirty_dish.position == trash_bin` | Multi-step plan |
| 6 | Hard | Make a cup of tea | `mug.contains == "tea" AND mug.temperature == "hot"` | Multi-object recipe |
| 7 | Hard | Make tea and bring it to the bedroom | Above + `mug.room == "bedroom"` | Recipe + transport |
| 8 | Hard | Find the keys and put them on the bedroom desk | `keys.position on desk surface` | Search + plan + place |

---

## 11. Evaluation

Run via `python -m robohome.eval`. Behaviour:

- Runs each of the 8 tasks N times (default N=3)
- Logs every run to `eval_results/<timestamp>/<task_name>_<run>.jsonl`
- Tracks per-task: success rate, average steps, average LLM calls, average prompt tokens, average completion tokens
- Writes a summary `results.md` with a markdown table at the end
- Total cost: 24 runs × ~40 calls = ~1000 Gemini calls, fits comfortably in 1 day of free quota

Sample results table (filled in after running):

```
| Task | Success | Avg Steps | Avg Calls |
|------|---------|-----------|-----------|
| 1. Go to bedroom | 3/3 | 12 | 12 |
| 6. Make tea | 2/3 | 38 | 41 |
...
```

---

## 12. Repository Structure (Locked)

```
RoboHome/
├── README.md
├── SPEC.md                       # this document
├── requirements.txt
├── .env.example
├── .gitignore
├── LICENSE                       # MIT
├── docs/
│   ├── architecture.md
│   ├── design_notes.md
│   └── architecture_diagram.png
├── robohome/
│   ├── __init__.py
│   ├── cli.py                    # entrypoint
│   ├── world/
│   │   ├── __init__.py
│   │   ├── grid.py               # cell types, walls, doors
│   │   ├── objects.py            # object class + affordances
│   │   ├── world.py              # World class, execute(), state
│   │   ├── house.py              # builds the 5-room layout
│   │   └── rendering.py          # world state -> PNG (Pygame)
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── llm.py                # LLMClient interface, Gemini + Groq adapters
│   │   ├── prompts.py            # system prompt, observation formatting
│   │   ├── parser.py             # tool call -> Action object
│   │   └── memory.py             # history window + scratchpad helpers
│   ├── harness/
│   │   ├── __init__.py
│   │   ├── observation.py        # World state -> observation JSON
│   │   ├── actions.py            # Pydantic action schemas + tool definitions
│   │   ├── pathfinding.py        # A* for macros
│   │   ├── loop.py               # main run() function
│   │   └── tasks.py              # 8 tasks + goal predicates
│   ├── viewer/
│   │   ├── __init__.py
│   │   ├── server.py             # Flask + SocketIO app
│   │   ├── replay.py             # log replay
│   │   ├── static/
│   │   │   ├── index.html
│   │   │   ├── app.js
│   │   │   └── style.css
│   └── eval/
│       ├── __init__.py
│       └── runner.py             # batch eval
├── tests/
│   ├── test_world.py
│   ├── test_actions.py
│   ├── test_pathfinding.py
│   ├── test_observation.py
│   ├── test_parser.py
│   └── test_tasks.py
├── examples/
│   ├── tea_success.jsonl
│   ├── tidy_kitchen.jsonl
│   └── README.md
├── logs/                         # gitignored
├── eval_results/                 # gitignored
└── scripts/
    ├── run_task.sh
    └── run_eval.sh
```

---

## 13. Conventions

### Code Style
- `black` for formatting (default settings)
- `ruff` for linting
- Type hints on all public functions
- Docstrings on all modules and public classes

### Testing
- `pytest` for tests
- Target 70%+ coverage on `world/` and `harness/`
- Viewer tests are optional (manual testing is fine)

### Git
- Branch from `main`, feature branches named `feat/<topic>` or `fix/<topic>`
- PRs reviewed by the other person before merge (even if just a quick read)
- Conventional commit messages: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`
- For paired sessions, use `Co-authored-by:` trailer so both get credit
- Never push directly to `main` except for tiny doc fixes

### Secrets
- API keys in `.env` (gitignored)
- `.env.example` is committed with placeholder values:
  ```
  LLM_PROVIDER=gemini
  GEMINI_API_KEY=
  GROQ_API_KEY=
  ```

### License
- MIT, public repo

---

## 14. Work Split

### Kamyar's Ownership (the parts Humanoid grades)

Maps directly to Humanoid's grading criteria.

**Files:**
- `robohome/agent/` (all four files: `llm.py`, `prompts.py`, `parser.py`, `memory.py`)
- `robohome/harness/observation.py`
- `robohome/harness/actions.py`
- `robohome/harness/loop.py`
- `robohome/harness/tasks.py`
- `robohome/eval/runner.py`
- `docs/design_notes.md`
- `tests/test_actions.py`, `test_observation.py`, `test_parser.py`, `test_tasks.py`

**Owns:**
- LLM integration (Gemini primary, Groq fallback)
- Prompt design and iteration
- Observation format design
- Action schema and function-calling setup
- The main agent loop
- All 8 task definitions and goal predicates
- The evaluation runner
- The design notes write-up (the doc reviewers will read most carefully)

### Armita's Ownership (the supporting infrastructure)

Substantial engineering, gives her great CV material (full-stack + graphics + algorithms), but not the parts Humanoid grades.

**Files:**
- `robohome/world/` (all five files: `grid.py`, `objects.py`, `world.py`, `house.py`, `rendering.py`)
- `robohome/harness/pathfinding.py`
- `robohome/viewer/` (all files: `server.py`, `replay.py`, `static/*`)
- `robohome/cli.py`
- Top-level setup files: `requirements.txt`, `.env.example`, `.gitignore`, basic `README.md` skeleton (Kamyar will fill in design sections)
- `tests/test_world.py`, `test_pathfinding.py`

**Owns:**
- World simulator (grid, objects, state, execute method, house layout)
- World rendering (Pygame to PNG)
- A* pathfinding for macros
- Flask + SocketIO viewer backend
- Frontend canvas + log pane
- Replay mode
- CLI entry point
- Initial repo scaffolding

### Shared (do together)

- **Day 1 kickoff session** (~2 hours): both clone the repo, agree on file layout, verify Gemini keys work, write the skeleton of every module so imports resolve
- **Architecture sync** (~1 hour): whiteboard how World, Harness, and Agent communicate, specifically the `World.execute(action) -> result` and `world.observe() -> dict` contracts
- **Integration debugging**: the first full end-to-end run will break at the seams between modules, debug together
- **Demo recording**: record together, edit together, both names in the video credits
- **README "Team" section**: write together

### Interface Contracts (Locked, do NOT change without checking)

These are the boundary points where Kamyar's code and Armita's code meet. Get these right early so neither of you blocks the other.

**`World.execute(action: Action) -> ActionResult`**
```python
class ActionResult(BaseModel):
    status: Literal["success", "failed"]
    message: str   # human-readable, fed back to LLM
    state_changes: dict  # optional, for debugging
```

**`World.observe(robot_position, robot_facing, robot_holding) -> WorldView`**
```python
class WorldView(BaseModel):
    current_room: str
    room_description: str
    visible_objects: list[VisibleObject]
    exits: list[Exit]
```

The harness's `build_observation()` takes a `WorldView`, adds task/history/notes, and produces the final observation JSON shown in Section 5.

**`pathfinding.shortest_path(world, start, goal) -> list[(x,y)] | None`**
Returns ordered cells from start to goal, or `None` if no path.

---

## 15. Setup Checklist (Before Day 1)

Both of you complete this on your own machines.

**Accounts:**
- [ ] GitHub account (Armita: create if needed, share username with Kamyar so he can add you as collaborator)
- [ ] Google AI Studio API key from https://aistudio.google.com (free, Google login, takes 2 min)
- [ ] Groq API key from https://console.groq.com (free, no credit card, fallback)

**Software:**
- [ ] Python 3.11+ installed (`python3 --version`)
- [ ] Git installed (`git --version`)
- [ ] VS Code or Cursor installed
- [ ] (Recommended) GitHub Copilot for Students activated with your `.ac.uk` email

**Comms:**
- [ ] Agreed on a chat channel (WhatsApp, Discord, etc.)
- [ ] Agreed on a regular sync time

**Repo access:**
- [ ] Kamyar adds Armita as a collaborator on https://github.com/knd8412/RoboHome
- [ ] Both have cloned the repo locally and can `git push` a test commit on a branch

---

## 16. README Format (For When We Write It)

The README is what reviewers see first. Section order:

1. **Title + one-liner**
2. **Demo GIF or video link** (embed YouTube unlisted)
3. **The challenge** (2 sentences, what we built and why)
4. **Architecture diagram** (one image)
5. **Quickstart** (5 commands max):
   ```bash
   git clone https://github.com/knd8412/RoboHome
   cd RoboHome
   pip install -r requirements.txt
   cp .env.example .env  # add your GEMINI_API_KEY
   python -m robohome.cli --task make_tea --viewer
   ```
6. **Design notes summary** (3-4 paragraphs, links to `docs/design_notes.md` for the deep version)
7. **Results table** (the eval output)
8. **Project structure** (directory tree with one-line descriptions)
9. **Team** (who built what, honest)
10. **License**

---

## 17. Using This Spec with an AI Coding Assistant

You will both lean on AI heavily ("vibe coding"). To get good results, prompt your AI like this:

### Good prompt template

```
I'm working on the RoboHome project. Here is the full spec: [paste SPEC.md]

I am working on Section [X], specifically the file `robohome/[path/to/file.py]`.
According to Section 14, this file is in my ownership.

Please help me implement [specific function or class].

Constraints:
- Follow the interface contracts in Section 14, do not change them
- Use Pydantic v2 for data models
- Match the style of existing code I'll paste below
- Write a corresponding test in tests/[matching_file].py
```

### Things to NOT let the AI talk you into

- Switching to LangChain "because it's easier" (no, the point is to write the harness ourselves)
- Adding a vector database for memory (no, the scratchpad is the design)
- Building a 3D simulator (no, 2D is the scope)
- Changing the interface contracts in Section 14 (talk to your teammate first)
- Adding more than the 10 primitive actions in Section 6.1 (lock the action space)
- Using a JS framework for the viewer (vanilla JS, no build step)

### Things to ASK the AI for proactively

- Test cases for edge conditions (closed doors, full inventory, dead-end rooms)
- Better error messages in `ActionResult.message` (the LLM reads these, they should be helpful)
- Refactors when a file gets above ~300 lines
- Type hint corrections and `mypy` clean-up

### When you and your teammate's AI disagree

Default to whatever this spec says. If the spec is ambiguous, message your teammate and decide together, then update the spec.

---

## 18. Risk Register

Things most likely to go wrong, and how we handle them:

| Risk | Mitigation |
|---|---|
| Gemini quota exhausted mid-eval | Fallback to Groq, swap by env var |
| LLM produces invalid function calls | Pydantic validation + 3-retry loop in parser |
| Agent loops forever on hard tasks | Hard `max_steps=60` cap, stuck detection at 8 steps |
| Pathfinding macro fails (closed door) | Returns structured error, agent sees it next step |
| Viewer WebSocket hangs | Run the agent loop with `--no-viewer` flag as a fallback |
| Merge conflicts | Each person owns disjoint directories; conflicts mostly only on shared root files |
| Demo video too long | Target 60-90 seconds, can speed up replay 2x |
| One teammate falls behind | Spec is locked, so the other can pick up their next module from this doc without a meeting |

---

## 19. Definition of Done

The project is "submission ready" when all of these are true:

- [ ] All 8 tasks have at least one successful run logged in `examples/`
- [ ] `python -m robohome.cli --task make_tea --viewer` works end-to-end
- [ ] `python -m robohome.eval` completes and produces `results.md`
- [ ] At least 5 of 8 tasks have a 2/3 or better success rate
- [ ] README has demo GIF, quickstart, design notes summary, results table, team section
- [ ] `docs/design_notes.md` is written (3-5 pages, the deep version)
- [ ] Architecture diagram exists in `docs/`
- [ ] Repo is public at https://github.com/knd8412/RoboHome
- [ ] Both contributors visible in GitHub's "Contributors" view
- [ ] LICENSE file present (MIT)
- [ ] `.env` is NOT committed, `.env.example` IS committed
- [ ] `requirements.txt` works on a fresh `pip install`
- [ ] Demo video uploaded (YouTube unlisted) and linked in README

---

## 20. Out of Scope (Resist the Temptation)

These are explicitly NOT in v1. If we have spare time at the end, fine, but never block on these:

- 3D rendering
- Multiple agents
- NPCs the agent can talk to
- Multimodal (image-based) observations (could be a stretch goal)
- Saving/loading world state
- Procedurally generated houses
- Audio
- A mobile-friendly viewer
- A Dockerfile
- Cloud deployment
- Authentication or multi-user support

---

**End of specification.** If something isn't in this document and you're unsure, decide with your teammate and update the spec. The spec is the contract.
