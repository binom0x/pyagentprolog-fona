# Fona

**Minimalist framework for background AI agents on PyAgentProlog.**

An agent is a Prolog program plus Python actions. It runs as an HTTP server with a chat UI and a REST API, can talk to users and to other agents, and can be launched from a dashboard.

---

## What it looks like

```python
from fona import agent

@agent.action
def now_iso():
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

@agent.program
PROGRAM = r"""
run :-
    ui_print('Hello. Type "time" or "quit".'),
    on_user_input.

on_user_input :-
    ui_read(Input),
    (   Input == quit -> ui_print('Bye.')
    ;   Input == time -> now_iso(T), ui_print(T), on_user_input
    ;   ui_print('Unknown.'), on_user_input
    ).
"""

if __name__ == '__main__':
    agent.run(port=8000)
```

```bash
python hello.py
# open http://127.0.0.1:8000/
```

---

## Install

```bash
pip install pyagentprolog-fona
```

Python 3.10+. `torch` / `sentence-transformers` are optional (`[torch]`, `[semantic]`, `[all]`).

---

## What you get

- **`@agent.program`** — declare the agent's logic in Prolog.
- **`@agent.action` / `@agent.effect` / `@agent.generate`** — expose Python functions as Prolog predicates.
- **`agent.run()`** — serve a chat UI and a REST API (`/api/v1/query`, `/api/v1/ui/*`).
- **Prolog-only inter-agent protocol** — peers call `/api/v1/query` with Prolog text; errors are `"err:..."` atoms, not exceptions.
- **Declarative config** — `load_config(...)` reads env once, returns an immutable object.
- **HF models** — `Agent.from_hub("user/repo")`; the user's `PROGRAM` is prepended to the model's program.
- **Dashboard** — `python -m fona.dashboard`; a project is a folder holding `team.json`, `scripts/`, `logs/`.
- **Orchestrator UI** — `python -m fona.orchestrator_app`; three-column view of goal, plan, chat, subordinates.
- **Natural language ↔ Prolog** — optional `@agent.action` companions to the HITL loop, not part of the protocol.

---

## Documentation

The full guide — architecture, decorators, HITL, inter-agent protocol, `query_one`, REST contract, HF cache, dashboard, orchestrator, security, testing, releases, known limitations — lives in [docs/guide.md](https://github.com/binom0x/pyagentprolog-fona/blob/main/doc/guide.md)

Start there. This README intentionally does not duplicate it.

---

## Examples

| File | Shows |
|---|---|
| `examples/hello.py` | smallest agent: `run/0` + `ui_print` |
| `examples/server_agent.py` | facts server + `handle_request/2` (incoming) |
| `examples/client_agent.py` | `call_peer/3` (outgoing) |
| `examples/template_agent.py` | reference: HITL, peers, protocol, NL ↔ Prolog, `query_one` |
| `examples/with_hf.py` | `Agent.from_hub` + prepended `PROGRAM` |

---

## Protocol in one paragraph

Every agent can answer `POST /api/v1/query` with body `{"query": "<Prolog text>"}`. The response is `{"success": bool, "solutions": [{"Var": value}], "count": int}`. The recommended handler is `handle_request(Kind, Payload) -> str` with `Kind ∈ {ping, echo, status}`, extensible via `register_protocol(agent, extra={...})`. Outgoing calls use `call_peer(Peer, Query) -> "ok:<v>" | "err:<r>"`, registered by `register_peers(agent, CFG)`. Peers are configured via `FONA_PEERS="name=url,..."`. No special language, no special client — just Prolog over HTTP.

---

## Requirements

- Core: `fastapi`, `uvicorn`, `httpx`, `pydantic`, `transformers`, `huggingface_hub`, `pyagentprolog`, `pyagentprolog-hf`.
- Optional: `torch`, `sentence-transformers`.
- For private HF models: `FONA_HF_TOKEN`.
- For non-local bind: `FONA_TOKEN` (REST auth) — see §16 of the guide.

---

## Status

`0.1.0` — in development. The public API and the inter-agent protocol are stable; the dashboard and orchestrator UI may change. Semver applies to `Agent`, `agent`, the decorators, and `load_config` / `register_*`.

---

## License

See `LICENSE`.

---

**One line:** Fona lets you write an agent as a Prolog program plus Python actions, serve it over HTTP with a chat UI, and let it talk to other agents — all through one Prolog-only protocol. For everything else, read [docs/guide.md](https://github.com/binom0x/pyagentprolog-fona/blob/main/doc/guide.md)
