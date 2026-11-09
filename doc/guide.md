# Fona Guide

## 1. What is Fona

Fona is a minimalist framework for building **background AI agents** on top of PyAgentProlog. An agent is written in Prolog (logic) and Python (actions), runs as an HTTP server with UI and REST API, and can interact with users and other agents. The dashboard is an optional layer for managing a team.

**Three packages:**

| Package | Role |
|---|---|
| `pyagentprolog` | Core: Prolog interpreter, parser, agent |
| `pyagentprolog-hf` | HuggingFace model wrapper as PyAgentProlog models |
| `pyagentprolog-fona` | Public Fona package: `Agent`, decorators, server, dashboard |

---

## 2. Installation

```bash
pip install pyagentprolog-fona
```

**Core dependencies:** `fastapi`, `uvicorn`, `httpx`, `pydantic`, `transformers`, `huggingface_hub`, `pyagentprolog`, `pyagentprolog-hf`. `torch` and `sentence-transformers` are optional (`pip install pyagentprolog-fona[torch]`).

**Python 3.10+.**

---

## 3. Quick start: your first agent

Create `hello.py`:

```python
from fona import agent

agent.program("""
run :-
    ui_print('Hello! I am a Fona agent.'),
    ui_print('Say something.').
""")

if __name__ == '__main__':
    agent.run(port=8000)
```

Run:

```bash
python hello.py
```

Open `http://127.0.0.1:8000/` — you'll see a chat UI.

**What happened:**
1. `agent` is the `Agent()` singleton.
2. `agent.program(...)` set `PROGRAM` — the agent's Prolog program.
3. `agent.run(port=8000)` built the model, created a FastAPI app with UI and REST, and started uvicorn in the current process.

**The dashboard is not needed.** This is a full-fledged agent. The dashboard (§13) is only a convenience wrapper for a team of several agents.

---

## 4. Basics

### 4.1. `@agent.program` — agent logic

Three equivalent forms:

```python
# Form 1: assignment
agent.program = "run :- ui_print('hi')."

# Form 2: call
agent.program("run :- ui_print('hi').")

# Form 3: decorator
@agent.program
def PROGRAM():
    return "run :- ui_print('hi')."
```

Multiple calls are **concatenated** with `\n`.

For HF models (`Agent.from_hub`) `PROGRAM` is **prepended** to the model's `config.program`: your rules fire first, HF rules act as fallback.

### 4.2. `@agent.action` — predicate returning a value

```python
@agent.action
def add(X, Y):
    return X + Y
```

→ `add/3` (2 inputs + 1 output, `output_arg=2`). `add(2, 3, R)` → `R = 5`.

**Arity from the signature:**
- `def add(X, Y)` → `add/3`.
- `def ask(prompt, context)` → `ask/2` (`context` not counted, output is `prompt`).

**`context`** is reserved: it receives `agent.context` (a dict), is not part of arity, and is not visible to Prolog.

**Semantics (P5):**
- `None` → **fail**.
- Exception → **fail** (suppressed).

**Decorator parameters:**
- `name='custom'` — predicate name (defaults to function name).
- `arity=4` — total arity (default `len(params) + 1`).
- `output_arg=0` — output index (default last).

### 4.3. `@agent.effect` — side effect, always succeeds

```python
@agent.effect
def log_event(message):
    print(f"[log] {message}")
```

→ `log_event/1`. On success — success. On exception — fail.

### 4.4. `@agent.generate` — solution generator

```python
@agent.generate
def numbers(limit):
    for i in range(1, limit + 1):
        yield i
```

→ `numbers/2`. `numbers(3, L)` → `L = [1, 2, 3]` (all solutions).

---

## 5. Launch: `agent.run()`

```python
agent.run(
    host='127.0.0.1',     # address
    port=8000,            # port
    ui=True,              # mount HTML UI at /
    rest=True,            # enable /api/v1/*
    token=None,           # FONA_TOKEN (None = no auth)
    background=False,     # True = pythonw without console (Windows)
)
```

**`background=True`** — run as a background process without console (Windows: `pythonw.exe`). Requires a `.py` file as `__main__`.

**`token`** — if set, all `/api/v1/*` (except `/health`) require `X-API-Key: <token>`.

**`host != '127.0.0.1'` + empty `token`** → warning in stderr. By default we listen on localhost.

---

## 6. User interaction (HITL)

**`ui_print/1`** — effector, prints text to the UI session.
**`ui_read/1`** — action, **blocks** until user input, returns text.

```prolog
run :-
    ui_print('What is your name?'),
    ui_read(Name),
    format(atom(Msg), 'Hello, ~w!', [Name]),
    ui_print(Msg).
```

**Loop:**

```prolog
run :- ui_print('Ready.'), on_user_input.

on_user_input :-
    ui_read(Input),
    dispatch(Input).

dispatch(quit) :- !, ui_print('Bye.').
dispatch(Input) :-
    format(atom(Msg), 'You said: ~w', [Input]),
    ui_print(Msg),
    on_user_input.
```

`ui_read` blocks the session, not the server thread. Each `POST /api/v1/ui/input` wakes the session. `QueryOneSession._run` calls `agent.query_one(start_query)` **once** — `run/0` is not re-executed.

---

## 7. Inter-agent interaction

All calls go through `POST /api/v1/query` with body `{"query": "<Prolog text>"}`. Response: `{"success": bool, "solutions": [{"Var": value}], "count": int}`.

### 7.1. Incoming requests: `handle_request/3`

```python
from fona import register_protocol

register_protocol(agent)  # ping/echo/status
```

Or with extras:

```python
register_protocol(agent, extra={
    "echo": lambda p: p,
    "facts": lambda _: f"ok facts={len(agent.build().agent.solver.database.facts)}",
})
```

A peer calls:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "handle_request(\"ping\", R)."}'
# → {"success": true, "solutions": [{"R": "pong"}], ...}
```

### 7.2. Outgoing requests: `call_peer/3`

```python
from fona import register_peers, load_config, team_resolver

CFG = load_config(
    peers=("FONA_PEERS", "peers", {}),
    token=("FONA_TOKEN", str, None),
)
register_peers(agent, CFG, resolver=team_resolver)
```

→ registers `call_peer/3` and `broadcast_ping/0`.

**Semantics:** returns an **atom** `"ok:<value>"` or `"err:<reason>"`. Errors are strings, not exceptions.

```prolog
run :-
    call_peer(warehouse, 'handle_request("check", "lamp 2", R).', Result),
    ui_print(Result).  % → "ok:10"
```

**`call_peer` in `peers.py`:**

```python
url = resolver(peer_name) if resolver else None      # team_resolver → live scan
if not url:
    url = (cfg.peers or {}).get(peer_name)           # fallback: FONA_PEERS
if not url:
    return f"err:unknown peer {peer_name}"
```

### 7.3. How an agent learns other agents' ports

Ports are **not** stored in `team.json` (v4). They are assigned at `Start` (by the dashboard or manually via `FONA_PORT`). The only way to know "who is on which port" is via `team_resolver`.

**Mechanism of `team_resolver(name)` (in `fona/team.py`):**

1. **Self** — if `name == FONA_AGENT_NAME`, return `http://127.0.0.1:$FONA_PORT`. No scan needed.
2. **Static** — if the peer has a `port` in `team.json` (v2/v3), use it. v4 has no such field.
3. **Live scan** — `scan_range(*port_range)` → on each port `GET /api/v1/model` → match `agent_name` → `port` → URL. Result cached for **2 seconds** (`_CACHE_TTL`).

If nothing yields a URL, `team_resolver` returns `None`, `call_peer` falls back to `cfg.peers` (`FONA_PEERS`). If that fails too — `"err:unknown peer <name>"`.

**Three env vars the dashboard sets automatically:**

| Env | Value | Set by |
|---|---|---|
| `FONA_TEAM_FILE` | absolute path to `team.json` | dashboard on `Start` |
| `FONA_AGENT_NAME` | agent name in `team.json` (`WH`, `ORDERS`, `CHAT`) | dashboard |
| `FONA_PORT` | actual port | dashboard |

**Critical:** the `name` in `call_peer(name, …)` must **match** the `name` field in `team.json`. If `team.json` says `"WH"` but `chat_agent.py` calls `call_peer("warehouse", …)`, `team_resolver` returns `None` and `call_peer` falls back to `FONA_PEERS` (if set) or `err:unknown peer`.

**Cache and restarts.** If a peer dies and restarts on a new port, `call_peer` may return `err:unknown peer` for up to 2 s. After `_CACHE_TTL` the cache refreshes and the peer is found. If a cached peer becomes unreachable — `call_peer` returns `err:http …`, and after 2 s `_live_scan` drops it from the cache.

**Self-resolver.** If an agent calls `call_peer(own_name, …)` — `team_resolver` returns its own URL without scanning (from `FONA_AGENT_NAME` + `FONA_PORT`). Useful for broadcast.

### 7.4. Running without the dashboard

`team_resolver` works without the dashboard — as long as `FONA_TEAM_FILE`, `FONA_AGENT_NAME`, `FONA_PORT` are set. Without `team.json`, only `FONA_PEERS` (static URL list) is available.

```bash
# Three terminals
FONA_AGENT_NAME=WH FONA_TEAM_NAME=test1 \
FONA_TEAM_FILE=/path/to/team.json FONA_PORT=8020 \
python warehouse_agent.py

FONA_AGENT_NAME=ORDERS FONA_TEAM_NAME=test1 \
FONA_TEAM_FILE=/path/to/team.json FONA_PORT=8021 \
python orders_agent.py

FONA_AGENT_NAME=CHAT FONA_TEAM_NAME=test1 \
FONA_TEAM_FILE=/path/to/team.json FONA_PORT=8022 \
python chat_agent.py
```

Each agent is a normal process. `team_resolver` on `call_peer("WH", …)` finds WH via `scan_range([8020, 8099])` from `team.json`.

---

## 8. Configuration: `load_config`

Declarative env-var loader.

```python
from fona import load_config

CFG = load_config(
    port=("FONA_PORT", int, 8000),
    token=("FONA_TOKEN", str, None),
    peers=("FONA_PEERS", "peers", {}),
    timeout=("FONA_HTTP_TIMEOUT", float, 10.0),
    peers_headers=True,  # X-API-Key for CFG.http
)
```

**Spec:** `name = (env_var, parser, default)`.

**Parsers:** `int`, `float`, `str`, `bool`, `"peers"`, `"csv"`, `"json"`, callable.

**Result:** `CFG.port`, `CFG.peers`, `CFG.http` (shared `httpx.Client`), `CFG.as_dict()`.

**Rule:** `load_config` is called **once** at import. Immutable (`frozen=True`).

---

## 9. NL ↔ Prolog: HITL companions

**Not part of the protocol.** Ordinary `@agent.action`s called from `PROGRAM` **before** and **after** `query_one`.

```python
@agent.action
def nl_to_prolog(text):
    # Stub. Replace with an HF/LLM call:
    # from transformers import AutoModel
    # model = AutoModel.from_pretrained("user/pyagent-prolog-nl",
    #                                   trust_remote_code=True)
    # return model.generate(texts=[text]).results[0]["answers"][0]["Answer"]
    return f"err:nl_to_prolog not configured ({text!r})"

@agent.action
def prolog_to_nl(term):
    return f"err:prolog_to_nl not configured ({term!r})"
```

In `PROGRAM`:

```prolog
on_user_input :-
    ui_read(Text),
    (   Text == quit -> ui_print('Bye.')
    ;   sub_atom(Text, 0, 3, _, 'nl ')
    ->  sub_atom(Text, 3, _, 0, NL),
        nl_to_prolog(NL, Prolog),
        run_query(Prolog)
    ;   run_query(Text)
    ).

run_query(Query) :-
    query_one(Query, Result),
    (   Result == '' -> ui_print('No solution.')
    ;   prolog_to_nl(Result, NL),
        (   sub_atom(NL, 0, 4, _, 'err:') -> ui_print(Result)
        ;   ui_print(NL)
        )
    ),
    on_user_input.
```

`PROGRAM` **does not parse** the content. It strips the `nl ` prefix and passes the rest to the action. Conversion happens in Python.

---

## 10. `query_one/1`: the internal bridge to the engine

```python
@agent.action
def query_one(prolog_text):
    sol = agent.query_one(prolog_text)
    return "" if sol is None else str(sol)
```

**Purpose:** execute arbitrary Prolog text from the middle of `PROGRAM`. `PROGRAM` can't "execute text" — only unify goals.

**Used only in the HITL loop.** Peer and UI session take other paths:
- **Peer:** `server.py` → `agent.query(q)` directly.
- **UI session:** `QueryOneSession._run` → `agent.query_one(start_query)` once on start.

**Architectural rule:** `query_one/1` is a thin bridge. It does not process the request. Any interpretation belongs in `PROGRAM` or in a separate action **before** `query_one`.

---

## 11. REST API

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | HTML UI (if `ui=True`) |
| `/api/v1/health` | GET | `{"status": "ok", "pid": N}` — no token |
| `/api/v1/model` | GET | `rules_count`, `kb_file`, `actions`, `agent_name`, `team_name` |
| `/api/v1/query` | POST | Prolog query `{"query": "..."}` |
| `/api/v1/query_one` | POST | First solution |
| `/api/v1/stream` | POST | SSE stream of solutions |
| `/api/v1/facts` | POST | `?fact=light(kitchen,on).` |
| `/api/v1/actions` | GET | List of actions |
| `/api/v1/ui/start` | POST | Start HITL session → `{"session_id": "..."}` |
| `/api/v1/ui/input` | POST | `{"session_id": "...", "text": "...", "ui_values": {}}` |
| `/api/v1/ui/stream` | GET | SSE: `event: output`, `event: state` |
| `/api/v1/ui/stop` | POST | `?session_id=...` |

**`/api/v1/query` — contract for inter-agent interaction.** Returns `{"success": bool, "solutions": [...], "count": int}`. Errors — `{"success": false, "error": "..."}`.

**`api_lock`:** all REST requests against the template model run under `threading.RLock`. `Database` is not thread-safe.

---

## 12. HF models

### 12.1. Loading

```python
from fona import Agent

a = Agent.from_hub("user/repo-name", revision="main")
# or
a = Agent.from_hub("/local/path/to/model")
```

**Download location:** global HuggingFace cache.
- Linux/macOS: `~/.cache/huggingface/hub/`
- Windows: `C:\Users\<user>\.cache\huggingface\hub\`

**Override:** `HF_HOME=/path` or `HF_HUB_CACHE=/path`.

### 12.2. Merge with `PROGRAM`

```python
a = Agent.from_hub("user/repo")
@a.program
PROGRAM = "run :- ui_print('my rule')."
a.run()
```

**Prepend:** your `run/0` is first, HF's is fallback. Order: `_ensure_solver()` → merge `PROGRAM` → `_ensure_kb_loaded()`.

### 12.3. Modes

- **`FONA_LOCAL_ONLY=1`** — local cache only, no network.
- **`FONA_HF_TOKEN`** — token for private models. Never logged.

---

## 13. Dashboard

```bash
python -m fona.dashboard --port 7861
# or
fona-dashboard --port 7861
```

**Concept:** a project = a folder. Inside: `team.json` (team description), `scripts/` (script copies), `logs/` (runtime logs). The dashboard is the single UI for managing the team: start, monitor, restart, stop, "adopt" already-running agents.

### 13.1. Launch and project autodetection

On `fona-dashboard` startup, the dashboard tries to find a project:

1. If `FONA_TEAM_FILE` is set and the file exists — use it.
2. Otherwise — recursively search for `team.json` under `cwd` up to **3 levels deep**, skipping `.git`, `node_modules`, `venv`, `build`, `dist`, `.idea`, `.vscode`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `site-packages`.

Possible outcomes:

- **Exactly one** `team.json` — opened automatically (`autodetected project: <path>` in stderr), agents loaded, `autostart` agents started.
- **None** — no project open, cards empty. The `Adopted / Live` tab still populates: `_live_scan_any()` scans the standard Fona range `[8020, 8099]`.
- **Several** — no auto-open. stderr lists the found paths; the user opens a project explicitly.

### 13.2. Project section

Three buttons in one row: `Open` / `Create` / `Close`. No manual path, project name, or port range fields.

- **Open** → folder picker. `Project.from_folder(root)`:
  1. If the folder has `team.json` — open it.
  2. Otherwise search for `team.json` up to 3 levels deep. If exactly one — open; if several — `gr.Warning`, refuse; if none — **offer to create** a project in that folder.
- **Create** → picker for an **empty** folder. Creates `team.json` with `port_range: [8020, 8099]` and name = folder name. If `team.json` already exists — opens it (no overwrite).
- **Close** → `_active_project = None`, adopted agents **released** (not killed, §13.6). Cards cleared, `Adopted` tab keeps working.

**Status bar** under the buttons: `✓ <name> — N agents, ports START-END` + full project folder path.

**`team.json` auto-reload:** on external change (manual edit, `git pull`) the dashboard re-reads it automatically. `_maybe_reload_team()` in each 2-second tick compares `mtime` with cache. Reload **does not** kill adopted, **does not** start anything — only updates cards by `id`. Saving via «Save» updates the `mtime` cache, so it doesn't trigger double reload.

### 13.3. Team section

Two buttons: `Save` / `Load and start`.

- **Save** — writes `team.json` from current `_manager` state. Starts nothing, leaves `Adopted` untouched.
- **Load and start** — re-reads `team.json` and starts **everyone** who is not `online`/`adopted`. An explicit user action, so it starts all, not just `autostart`.

### 13.4. Agent cards

Each card shows status (`ONLINE` / `OFFLINE` / `STARTING` / `STOPPED` / `ERROR` / `ADOPTED`), address, `uptime`, `latency`, rule and action counts, KB file, `source` (if added from a file), orchestrator template (if set), health success ratio, error line (if any), sparkline.

Card buttons:

- **Open UI** — `http://127.0.0.1:<port>/` (when `status == online`).
- **Orchestrator** — UI of the orchestrator if the agent has `orchestrator_template` and a second port was allocated from `port_range`.
- **Logs** — `/dashboard/logs?id=<id>&kind=err`.
- **Start / Stop / Restart / Remove** — normal operations.
- **Autostart** — checkbox, §13.7.

### 13.5. Adopted / Live tab

Shows **all** live agents in known port ranges — **regardless** of whether a project is open. Columns: `Team / Name / Port / PID / Status / Actions (Open UI, Kill)`.

Sources of "known ranges":

1. `_active_project.port_range` if a project is open.
2. `port_range` from **every** `team.json` found recursively under `cwd` (up to 3 levels).
3. If nothing found — fallback `[8020, 8099]`.

`scan_range` returns only ports that answered `GET /api/v1/model`, so foreign python processes that are not Fona agents are filtered out. The tab is populated on **page load** (`demo.load`) and every 2 s. Belonging to the current project is highlighted (`team-ours`, blue): if `team_name` from `/api/v1/model` matches `_active_project.name`.

**Kill** in the tab — `POST /dashboard/kill_live?port=<port>`, kills the python listener on that port. For an adopted agent this is a real kill (unlike `Stop`, §13.6).

### 13.6. "Processes survive the dashboard" model

Ctrl+C in the dashboard does **not** kill children. Only explicit commands:

| Action | Adopted agent | Own agent |
|---|---|---|
| **Stop** | **Release** — `adopted=False`, `process=None`, `status=stopped`, process **alive** | `taskkill /F /T` + sweep, process dies |
| **Restart** | Release + Start (may re-adopt) | Stop + Start |
| **Remove** | Release + remove from `_manager` | Stop + remove |
| **Kill (Adopted)** | `taskkill /F` by PID | — |
| **Close project** | Release all adopted, `_manager.agents.clear()` | Stop all, `clear()` |
| **Ctrl+C** | Does nothing, processes alive | Does nothing, processes alive |

"Adopted" = an agent the dashboard **did not** start (it was alive at `Project.open` / `_ensure_startup_project` / `Start`). The dashboard knows about it from `/api/v1/model` but **does not own** its PID: `process = None`, and `pid` is looked up via `netstat`/`lsof` by port.

### 13.7. Autostart

The `autostart` flag in `team.json` (`"autostart": true|false`) — "start automatically when the project is opened".

**Fires at:**
- Auto-open on dashboard startup (`_ensure_startup_project`).
- The `Open` button (`_open_after_load`).

For each agent with `autostart=True` and `status != "online"`, `_manager.start()` is called. If the process is already alive on the port, `start()` **adopts** it instead of starting.

**Does NOT fire at:**
- `team.json` auto-reload (`_maybe_reload_team`) — read only, starts nothing.
- `Load and start` — starts **all** non-online agents.
- `Save` — writes the file only.
- Manual `Start` on a card — starts that specific agent.

Card checkbox — `POST /dashboard/autostart?id=<id>&value=1|0`; after the response, `window.fonaRefresh()` is called.

### 13.8. Adding an agent

The "Add Agent" accordion is **collapsed by default**. Contents:

- **Script file** (`gr.File`, `.py`) — copied to `<project>/scripts/` with `sha256` dedup. `team.json` stores `source`, `source_sha256`, `source_mtime`. On external change of the source — a `⚠ source changed` badge and an `Update` button → `POST /dashboard/update_source` (overwrites the copy, restarts the agent).
- **Or absolute path** — "in place", no copy.
- **Orchestrator template** — optional, copied like a normal script.
- **Name** — optional; defaults to `Path(script).stem`.

The `Add` button creates an entry in `_manager`, but **does not** write `team.json` — that's `Save`'s job.

### 13.9. Ports

- `port_range` is set in `team.json` at project level. No UI field — by design: the range is a project property.
- `_allocate_for()` allocates **two** free ports from `port_range`: first for the agent, second for the orchestrator. The second is allocated **only** if `orchestrator_template` is set; otherwise `orchestrator_gradio_port=None`, and the Orchestrator button is not drawn.
- The port is **not** stored in `team.json`: assigned on each `Start`. After `Stop`/`Start` an agent may get a different port if the old one is taken. `Open UI` always uses the current `a.port`.
- Free port is guaranteed before `Popen`: `start()` calls `_kill_python_on_port(agent_port)` **before** spawn. If the port is still busy (race), the next free one is allocated.

### 13.10. How to change the port range

`port_range` is stored in `team.json` (top-level field). Change it by editing the file. No UI field.

**Format:**

```json
{
  "version": 4,
  "name": "warehouse_team",
  "port_range": [8020, 8099],
  "agents": [ ... ]
}
```

**Step by step:**

1. **Close the project** in the dashboard (`Close` button). This releases adopted agents, but **does not kill** them.
2. **Stop all team agents** if they were started by the dashboard: `Stop` on each card, or just close the dashboard. If agents are running on the old ports and you change the range to an **overlapping** one, old processes will occupy part of the new range — `_allocate_port` will see that and pick the next free ones.
3. **Open `team.json`** in an editor and replace `"port_range": [START, END]`. Constraints:
   - `1 <= START <= END <= 65535`.
   - The range must contain **at least** `2 * N_orch + N_agents + 1` ports, where `N_orch` is the number of agents with `orchestrator_template`. If no orchestrators — `N_agents + 1` is enough.
   - Avoid system/foreign services. The Fona standard is `8020–8099`.
4. **Save the file.** The dashboard will pick up the change automatically within 2 s (`_maybe_reload_team`). If the dashboard was closed — on the next `fona-dashboard` (or after `Open`) the new range applies immediately.
5. Click **Load and start** if you want to bring up the whole team on the new ports immediately. Or press `Start` on the cards.

**Important:**

- The port is **not** tied to an agent. On the next `Start` each agent gets the **first free** port from the new `port_range` in allocation order. If you want to pin an agent to a specific port — set `env: {"FONA_PORT": "8123"}` in its record. `_child_env` merges `extra=a.env`, and `FONA_PORT` from `env` overrides the default passed by the dashboard.
- Changing `port_range` **does not** migrate already-running processes. Adopted processes on old ports stay on old ports; `_scan_and_adopt` looks for them by `team_name` + `agent_name` in the **new** range and **won't find them**. To let the dashboard "see" adopted again, simply stop the old processes (`Kill` in the `Adopted` tab or `taskkill`), then start the team on the new ports.
- If multiple `team.json` under `cwd` have **overlapping** ranges, `_live_scan_any()` takes `min(START)` and `max(END)` — scans the union. Safe (extra ports just won't answer), but creates load on `netstat`/HTTP for large unions.

**Example: change from 8020–8099 to 9000–9099 for a team of 3 agents without an orchestrator.**

```json
{
  "version": 4,
  "name": "warehouse_team",
  "port_range": [9000, 9099],
  "agents": [
    { "id": "e48fdec6", "name": "WH",     "script": "scripts/warehouse_agent.py", "autostart": false },
    { "id": "21b0c058", "name": "ORDERS", "script": "scripts/orders_agent.py",    "autostart": false },
    { "id": "2c87ef27", "name": "CHAT",   "script": "scripts/chat_agent.py",      "autostart": false }
  ]
}
```

Saved → dashboard picked it up → `Load and start` → three agents on ports 9000, 9001, 9002 (first free in allocation order).

**Example: with an orchestrator on one agent.**

```json
{
  "version": 4,
  "name": "warehouse_team",
  "port_range": [9000, 9099],
  "agents": [
    { "id": "a1", "name": "WH",     "script": "scripts/warehouse_agent.py", "autostart": false },
    { "id": "a2", "name": "ORDERS", "script": "scripts/orders_agent.py",    "autostart": false,
      "orchestrator_template": "scripts/orchestrator_template.py" },
    { "id": "a3", "name": "CHAT",   "script": "scripts/chat_agent.py",      "autostart": false }
  ]
}
```

`Start` for ORDERS allocates **two** ports (agent + orchestrator); WH and CHAT get one each. Five ports total from `[9000, 9099]`.

### 13.11. Dashboard HTTP endpoints

All `/dashboard/*` mount into the Gradio FastAPI app. Token is not checked — the dashboard listens on `127.0.0.1` by default.

| Endpoint | Method | Purpose |
|---|---|---|
| `/dashboard/project` | GET | Current project (JSON) |
| `/dashboard/project/open` | POST | `{"root": "..."}` → `Project.from_folder` + `load_team` + autostart |
| `/dashboard/project/create` | POST | `{"root", "name", "port_range"}` → create |
| `/dashboard/project/close` | POST | Release all, clear `_manager` |
| `/dashboard/start`, `/stop`, `/restart`, `/remove` | POST | Manage agent by `id` |
| `/dashboard/release` | POST | Release adopted (no kill) |
| `/dashboard/kill_live` | POST | `?port=<n>` — kill python listener |
| `/dashboard/autostart` | POST | `?id=<id>&value=1|0` |
| `/dashboard/update_source` | POST | `?id=<id>` — overwrite copy from `source` |
| `/dashboard/logs` | GET | `?id=<id>&kind=out|err&tail=<n>` — tail log |
| `/dashboard/env` | GET | Diagnostics: `sys_executable`, `PYTHONPATH`, `uvicorn_reload`, `strict_pid`, `project`, `autodetected_teams` |
| `/dashboard/teams/save` | POST | Write `team.json` |
| `/dashboard/teams/load` | POST | `{"start_flagged": bool, "force_start": bool}` |

### 13.12. Runtime

- `logs/<agent_id>.out.log` / `logs/<agent_id>.err.log` — stdout/stderr of each child (`Logs` button).
- Ctrl+C: the dashboard prints `dashboard shutting down (children left running)` and exits; children keep running.

### 13.13. Known limitations

- **One project at a time.** Multi-project is an RFC.
- **`port_range` is not editable in the UI.** Only via `team.json` (§13.10).
- **Orphan cleanup only on `Open`.** `_ensure_startup_project` does not kill "foreign" agents (`team_name != project.name`), to avoid killing a manual launch. Explicit kill — `Kill` in the `Adopted` tab.
- **`autostart` does not fire on `team.json` auto-reload** — only on `Open` and dashboard startup (§13.7).
- **`_install_script` does not delete old versions** on `renamed` — `scripts/` grows.
- **`/dashboard/*` without a token.** For `0.0.0.0` use a reverse proxy with TLS (§16).
- **`orchestrator_gradio_port` without starting the orchestrator.** The port is allocated, the button is drawn, but the dashboard does not start the orchestrator process — that's the agent's responsibility (§14).

---

## 14. Orchestrator

```bash
python -m fona.orchestrator_app \
  --orchestrator http://127.0.0.1:8000 \
  --port 8010
```

**UI:** URL + Connect + Refresh bar, chat (HITL) on the left, panels from `cfg.panels` on the right, logs at the bottom.

**Customization** via `OrchestratorConfig`:

```python
from fona.orchestrator_ui import OrchestratorConfig, Panel, Action

def fetch_status(client):
    return client.get_json("/api/v1/model")

def render_status(data, lang):
    return f"<pre>{data}</pre>"

cfg = OrchestratorConfig(
    base_url="http://127.0.0.1:8000",
    panels=[
        Panel(key="status", title_en="Status", title_ru="Статус",
              fetcher=fetch_status, renderer=render_status),
    ],
    actions=[
        Action(key="ping", title_en="Ping", title_ru="Пинг",
               handler=lambda client, _: client.post_json(
                   "/api/v1/query", {"query": "handle_request(\"ping\", R)."})),
    ],
)
```

Connecting to the orchestrator:
- `/api/v1/ui/*` — HITL session (chat).
- Arbitrary endpoints — via `client.get_json(path)` / `client.post_json(path, body)`.

The dashboard **does not** start the orchestrator process: `FONA_ORCHESTRATOR_PORT` is set in the child env, but interpreting it is the script's responsibility (e.g. `orchestrator_app.main()` may read the env var and use it as `--port`).

---

## 15. Agent template

```python
from fona import (
    agent, load_config, register_peers, register_protocol,
    team_resolver,
)

CFG = load_config(
    port=("FONA_PORT", int, 8000),
    token=("FONA_TOKEN", str, None),
    peers=("FONA_PEERS", "peers", {}),
    timeout=("FONA_HTTP_TIMEOUT", float, 10.0),
    peers_headers=True,
)
register_peers(agent, CFG, resolver=team_resolver)
register_protocol(agent)

@agent.program
PROGRAM = """
run :- ui_print('ready'), on_user_input.
on_user_input :-
    ui_read(T),
    (T == quit -> ui_print('bye')
    ; ui_print(T), on_user_input).
"""

if __name__ == "__main__":
    agent.run(port=CFG.port, token=CFG.token)
```

**What it covers:**
1. HITL: `ui_print`/`ui_read`.
2. Outgoing: `call_peer/3` via `team_resolver`.
3. Incoming: `handle_request/3` (ping/echo/status).
4. Launch: `agent.run()` — without the dashboard; or the dashboard starts it.

---

## 16. Security

- **`FONA_TOKEN`:** if empty — `/api/v1/*` without auth. Default `127.0.0.1`. For `0.0.0.0` — always set a token and a TLS proxy.
- **`trust_remote_code=True`:** required for HF. Model must come from a trusted source.
- **`read_env`:** always whitelist. Otherwise `read_env("FONA_TOKEN")` returns the token.
- **Tokens are never logged.** `_ensure_kb_loaded` prints `repo_id`, never the token.

---

## 17. Testing and benchmarks

**Coverage:** ≥ 80% for `fona/*.py`.

**Required tests:** decorators (arity, None→fail, context), build (standalone/HF/prepend), clone, semantics (`_start_query`), integration (TestClient, SSE, HITL).

**Forbidden:** real network in tests (`fake_llm`), `sleep > 100ms`.

**Benchmarks (manual):**
- `import fona` < 500ms (without transformers).
- `Agent().build()` standalone < 100ms.
- `query_one('run.')` of a hello agent < 50ms.

---

## 18. Release process (short)

1. **Freeze:** `release/vX.Y.Z` from `main`.
2. **Changelog:** `Unreleased` → `[X.Y.Z] — YYYY-MM-DD`.
3. **Tag:** `git tag -s vX.Y.Z`, push → `release.yml` → PyPI (trusted publishing).
4. **Post-release:** merge back to `main`, version `X.Y.Z.dev0`.

**Semver:**
- **major** — breaking changes to public API/semantics (P2, P5, P6).
- **minor** — new methods/parameters.
- **patch** — fixes.

**Deprecation:** `DeprecationWarning` for two minor releases, removal in the next major.

---

## 19. Developer checklist (short)

- [ ] Type hints on public API.
- [ ] Google-style docstrings.
- [ ] No `print()` (only `sys.stderr` / `logging`).
- [ ] No `# noqa` without a reason.
- [ ] Tests: unit + integration.
- [ ] Coverage ≥ 80%.
- [ ] `CHANGELOG.md` updated.
- [ ] Example in `examples/` (if user-visible).
- [ ] `_ensure_kb_loaded` after `_ensure_solver` (HF).
- [ ] Prepend maintained.

---

## 20. Known limitations

- **`Database` is not thread-safe** — only `api_lock` or separate clones for HITL.
- **Dashboard:** one project at a time. Multi-project is an RFC.
- **`port_range` is not editable in the UI** — only via `team.json`.
- **`_install_script` does not delete old versions** on `renamed` — `scripts/` grows.
- **`orchestrator_app.py`** expects `/orch/*` endpoints that `server.py` does not provide — the orchestrator agent (or custom `Panel.fetcher`s) must implement them.
- **Names in `call_peer` must match `name` in `team.json`** — otherwise `team_resolver` returns `None`.
- **Changing `port_range` does not migrate adopted processes** — old ones stay on old ports, and `_scan_and_adopt` won't find them (§13.10).