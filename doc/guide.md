## 1. What is Fona

Fona is a minimalist framework for building **background AI agents** on top of PyAgentProlog. An agent is written in Prolog (logic) and Python (actions), runs as an HTTP server with a UI and REST API, and can interact with the user and with other agents.

**Three packages:**

| Package | Role |
|---|---|
| `pyagentprolog` | Core: Prolog interpreter, parser, agent |
| `pyagentprolog-hf` | Wraps HuggingFace models as PyAgentProlog models |
| `pyagentprolog-fona` | The public Fona package: `Agent`, decorators, server, dashboard |

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
    ui_print('Type something.').
""")

if __name__ == '__main__':
    agent.run(port=8000)
```

Run it:

```bash
python hello.py
```

Open `http://127.0.0.1:8000/` — you will see a chat interface. The agent works: `ui_print` outputs messages to the UI.

**What happened:**
1. `agent` is the `Agent()` singleton.
2. `agent.program(...)` set `PROGRAM` — the agent's Prolog program.
3. `agent.run(port=8000)` built the model, created a FastAPI app with UI and REST, and started uvicorn.

---

## 4. Fundamentals: decorators

### 4.1. `@agent.program` — the agent's logic

Three equivalent forms:

```python
# Form 1: assignment
agent.program = "run :- ui_print('hi')."

# Form 2: call
agent.program("run :- ui_print('hi').")

# Form 3: decorator on a function
@agent.program
def PROGRAM():
    return "run :- ui_print('hi')."
```

If `PROGRAM` is set multiple times, the pieces are **concatenated** (with `\n`).

For an HF model (`Agent.from_hub`), `PROGRAM` is **prepended** to the model's `config.program`: your rules fire first, HF rules act as fallback.

### 4.2. `@agent.action` — a predicate that returns a value

```python
@agent.action
def add(X, Y):
    return X + Y
```

→ registers `add/3` in Prolog. Calling `add(2, 3, R)` → `R = 5`.

**Arity is inferred from the signature:**
- `def add(X, Y)` → `add/3` (2 inputs + 1 output, `output_arg=2`).
- `def ask(context, prompt)` → `ask/2` (`context` is not counted; `prompt` is the output).

**The `context` parameter** is reserved: it receives `agent.context` (a dict), is not part of arity, and is not visible from Prolog.

**Semantics (P5):**
- If the function returns `None` → **fail**.
- If the function raises → **fail** (the exception is suppressed).

**Decorator parameters:**
- `name='custom_name'` — predicate name (defaults to the function name).
- `arity=4` — total arity (default `len(params) + 1`).
- `output_arg=0` — output argument index (default: the last one).

### 4.3. `@agent.effect` — side effect, always succeeds

```python
@agent.effect
def log_event(message):
    print(f"[log] {message}")
```

→ `log_event/1`. On success — always succeeds. On exception — fail (with no return value).

### 4.4. `@agent.generate` — solution generator

```python
@agent.generate
def numbers(limit):
    for i in range(1, limit + 1):
        yield i
```

→ `numbers/2` (input + output). `numbers(3, L)` → `L = [1, 2, 3]` (all solutions).

---

## 5. Launching: `agent.run()`

```python
agent.run(
    host='127.0.0.1',     # address
    port=8000,            # port
    ui=True,              # mount the HTML UI at /
    rest=True,            # enable /api/v1/*
    token=None,           # FONA_TOKEN for REST (None = no auth)
    background=False,     # True = pythonw with no window (Windows)
)
```

**`background=True`** — runs the agent as a background process with no console window (Windows: `pythonw.exe`). For this to work, the script must be a `.py` file.

**If `token` is set** (or `FONA_TOKEN` is in env) — every `/api/v1/*` endpoint (except `/health`) requires the header `X-API-Key: <token>`.

**If `host != '127.0.0.1'` and `token` is empty** — `create_app` writes a warning to stderr. This is intentional: by default we listen on localhost.

---

## 6. Interacting with the user (HITL)

HITL = Human-in-the-Loop. The mechanism is `ui_print` (output) and `ui_read` (input).

**`ui_print/1`** — an effector that writes text to the UI session.
**`ui_read/1`** — an action that **blocks** until the user types something and returns the text.

**Dialogue pattern:**

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

**Important:** `ui_read` blocks the session, but not the server thread. Each `POST /api/v1/ui/input` wakes the session up. `QueryOneSession._run` calls `agent.query_one(start_query)` **once** — `run/0` is not re-executed.

---

## 7. Inter-agent interaction (Prolog-only)

**Protocol:** all calls go through `POST /api/v1/query` with body `{"query": "<Prolog text>"}`. The response is `{"success": bool, "solutions": [{"Var": value}], "count": int}`.

### 7.1. Incoming requests: `handle_request/2`

Every agent that should answer others registers `handle_request`:

```python
from fona import register_protocol

register_protocol(agent)  # registers ping/echo/status
```

Or extends it:

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
from fona import register_peers, load_config

CFG = load_config(
    peers=("FONA_PEERS", "peers", {"server": "http://127.0.0.1:8000"}),
    token=("FONA_TOKEN", str, None),
)
register_peers(agent, CFG)
```

→ registers `call_peer/3` and `broadcast_ping/1`.

**Semantics:** returns the **atom** `"ok:<value>"` or `"err:<reason>"`. Errors are strings, not exceptions (P5).

```prolog
run :-
    call_peer(server, 'light(bedroom, X).', Result),
    ui_print(Result).  % → "ok:off"
```

### 7.3. Peer configuration

`FONA_PEERS="name1=url1,name2=url2"` — an env variable. `load_config` parses it into a dict. `CFG.http` automatically adds `X-API-Key` if `token` is set.

---

## 8. Configuration: `load_config`

A declarative env loader.

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

**Principle:** `load_config` is called **once** at import. Immutable (`frozen=True`). No runtime magic (P4).

---

## 9. NL ↔ Prolog: HITL companions

**This is not part of the protocol.** These are ordinary `@agent.action`s that are called from `PROGRAM` **before** and **after** `query_one`.

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

**In `PROGRAM`:**

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

**Key point:** `PROGRAM` does **not parse** the content. It strips the `nl ` prefix and passes the rest to the action. The translation itself happens in Python. `handle_request`/`call_peer` know nothing about NL.

---

## 10. `query_one/1`: an internal bridge to the engine

```python
@agent.action
def query_one(prolog_text):
    sol = agent.query_one(prolog_text)
    return "" if sol is None else str(sol)
```

**Purpose:** execute arbitrary Prolog text from the middle of `PROGRAM`. It is needed because `PROGRAM` cannot "execute text" — it can only unify goals.

**Where it is used:** only in the HITL loop (`on_user_input` → `run_query` → `query_one`). Peers and UI sessions go through other paths:
- **Peer:** `server.py` → `agent.query(q)` directly.
- **UI session:** `QueryOneSession._run` → `agent.query_one(start_query)` once at start.

**Architectural rule:** `query_one/1` is a thin bridge. It does **not process** the query (no parsing, no branching). Any interpretation belongs in `PROGRAM` (via unification) or in a separate action **before** `query_one`.

---

## 11. REST API

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | HTML UI (if `ui=True`) |
| `/api/v1/health` | GET | `{"status": "ok"}` — no token |
| `/api/v1/model` | GET | Model info: `rules_count`, `kb_file`, `actions` |
| `/api/v1/query` | POST | Run a Prolog query: `{"query": "..."}` |
| `/api/v1/query_one` | POST | First solution |
| `/api/v1/stream` | POST | SSE stream of solutions |
| `/api/v1/facts` | POST | `?fact=light(kitchen,on).` |
| `/api/v1/actions` | GET | List of actions |
| `/api/v1/ui/start` | POST | Start a HITL session → `{"session_id": "..."}` |
| `/api/v1/ui/input` | POST | `{"session_id": "...", "text": "...", "ui_values": {}}` |
| `/api/v1/ui/stream` | GET | SSE: `event: output`, `event: state` |
| `/api/v1/ui/stop` | POST | `?session_id=...` |

**`/api/v1/query` is the contract for inter-agent interaction.** Returns `{"success": bool, "solutions": [...], "count": int}`. Errors are `{"success": false, "error": "..."}`.

**`api_lock`:** every REST request against the template model runs under a `threading.RLock`. `Database` is not thread-safe.

---

## 12. HF models

### 12.1. Loading

```python
from fona import Agent

a = Agent.from_hub("user/repo-name", revision="main")
# or
a = Agent.from_hub("/local/path/to/model")
```

**Where it is downloaded:** the global HuggingFace cache:
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

**Prepend:** your `run/0` goes **first**, the HF `run/0` is the fallback. `_ensure_solver()` → merge `PROGRAM` → `_ensure_kb_loaded()`.

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

**Concept:** a project = a folder. Inside: `team.json`, `scripts/` (agent copies), `logs/` (runtime).

**Workflow:**
1. **Create a project** — pick a folder → `scripts/` and `logs/` are created.
2. **Add an agent** — via `gr.File` (copied into `scripts/` with sha256-based deduplication) or a manual path (no copy).
3. **Save / Start** — `team.json` is written into the project folder; `Load and start` launches agents with `autostart=true`.

**Source tracking:** if an agent was copied, `team.json` stores `source`, `source_sha256`, `source_mtime`. The card shows a `⚠ source changed` badge; clicking it calls `update_source` (overwrites the copy and restarts).

**Runtime:** `logs/children.json` — PIDs/ports. `_kill_orphan_children()` runs on project open. Ctrl+C stops the children.

---

## 14. Orchestrator

```bash
python -m fona.orchestrator_app \
  --orchestrator http://127.0.0.1:8000 \
  --port 8010
```

**Three-column UI:**
- **Left:** Goal (card) + input + `Set` + `Open HTML`.
- **Center:** Plan (3 columns: Pending/Active/Done) + Chat.
- **Right:** Logs + Subordinates (list with dots) + Status.

**Communication with the orchestrator:**
- `/api/v1/ui/*` — HITL session (chat).
- `/orch/current_goal`, `/orch/goal`, `/orch/tasks`, `/orch/subordinates` — orchestration state. **These endpoints must be implemented by the orchestrator agent**; `orchestrator_app.py` only reads them.

**Language:** system language (same as `dashboard.py`), no switcher.

---

## 15. Agent template (`template_agent.py`)

**What it covers:**
1. HITL: `ui_print`/`ui_read` + NL ↔ Prolog (companions).
2. Outgoing: `call_peer/3` (from `fona.peers`).
3. Incoming: `handle_request/2` (from `fona.protocol`).
4. Actions: `now_iso`, `read_env` (whitelist), `numbers` (generate).

**Structure:**
```python
CFG = load_config(...)           # configuration
register_peers(agent, CFG)        # transport
register_protocol(agent)          # protocol
# ... domain actions ...
@agent.program PROGRAM = r"""..."""  # pure Prolog, no parsing
agent.run(port=CFG.port, token=CFG.token)
```

---

## 16. Security

- **`FONA_TOKEN`:** if empty — `/api/v1/*` has no authentication. Defaults to `127.0.0.1`. For `0.0.0.0` — always set a token and use a TLS reverse proxy.
- **`trust_remote_code=True`:** required for HF. The model must come from a trusted source.
- **`read_env`:** always use a whitelist. Without it, `read_env("FONA_TOKEN")` returns the token.
- **Tokens are never logged.** `_ensure_kb_loaded` prints `repo_id`, but not the token.

---

## 17. Testing and benchmarks

**Coverage:** ≥ 80% for `fona/*.py`.

**Required tests:** decorators (arity, None→fail, context), build (standalone/HF/prepend), clone, semantics (`_start_query`), integration (TestClient, SSE, HITL).

**Forbidden:** real network in tests (only `fake_llm`), sleep > 100 ms.

**Benchmarks (manual):**
- `import fona` < 500 ms (without transformers).
- `Agent().build()` standalone < 100 ms.
- `query_one('run.')` of the hello agent < 50 ms.

---

## 18. Release process (brief)

1. **Freeze:** `release/vX.Y.Z` from `main`.
2. **Changelog:** `Unreleased` → `[X.Y.Z] — YYYY-MM-DD`.
3. **Tag:** `git tag -s vX.Y.Z`, push → `release.yml` → PyPI (trusted publishing).
4. **Post-release:** merge back into `main`, version becomes `X.Y.Z.dev0`.

**Semver:**
- **major** — breaking changes to the public API/semantics (P2, P5, P6).
- **minor** — new methods/parameters.
- **patch** — fixes.

**Deprecation:** `DeprecationWarning` for **two minor** releases, removal in the next major.

---

## 19. Developer checklist (abridged)

- [ ] Type hints on the public API.
- [ ] Google-style docstrings.
- [ ] No `print()` (use `sys.stderr` / `logging`).
- [ ] No `# noqa` without a reason.
- [ ] Tests: unit + integration (if semantics changed).
- [ ] Coverage ≥ 80%.
- [ ] `CHANGELOG.md` updated.
- [ ] Example in `examples/` (if the feature is user-visible).
- [ ] `_ensure_kb_loaded` after `_ensure_solver` (HF).
- [ ] Prepend preserved.

---

## 20. Known limitations

- **`Database` is not thread-safe** — use `api_lock` or separate clones for HITL.
- **Dashboard:** one project at a time. Multi-project support is an RFC.
- **`_install_script`** does not delete old copies on `renamed` — `scripts/` grows.
- **`orchestrator_app.py`** expects `/orch/*` endpoints that do not exist in `server.py` — they must be implemented by the orchestrator agent.
- **A search of open sources for "pyagentprolog-fona" returned no results** — this guide is based on the provided files, not on external documentation.