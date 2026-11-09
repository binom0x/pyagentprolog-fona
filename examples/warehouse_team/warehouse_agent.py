"""Warehouse agent — facts server with HITL and the standard peer protocol.

Role in the team:
  * Holds the product catalog (facts).
  * Answers peers via handle_request/3 (Kind, Payload, Result):
      - ping / echo / status      (standard)
      - check   <item> <qty>      -> "ok:<stock>" | "err:<reason>"
      - reserve <item> <qty>      -> "ok:reserved" | "err:<reason>"
  * HITL: user can type "check lamp 2" in the UI; the agent parses it
    via a Python helper and runs the Prolog query locally.

Run:
    python examples/warehouse_team/warehouse_agent.py
    FONA_PORT=8000 python examples/warehouse_team/warehouse_agent.py
"""
import os
import sys
import time

from fona import (
    agent, load_config, register_protocol, register_peers,
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


# =====================================================================
# Catalog
# =====================================================================
agent.program = r"""
item(lamp, 10).
item(chair, 4).
item(table, 2).
item(desk, 3).

run :-
    ui_print('Warehouse ready.'),
    ui_print('Type: check <item> <qty> | reserve <item> <qty> | quit.'),
    on_user_input.

on_user_input :-
    ui_read(Text),
    (   Text == quit
    ->  ui_print('Bye.')
    ;   parse_command(Text, Query),
        (   Query == 'fail.'
        ->  ui_print('Empty input.'),
            on_user_input
        ;   query_one(Query, Result),
            (   Result == ''
            ->  ui_print('(no output)')
            ;   ui_print(Result)
            ),
            on_user_input
        )
    ).
"""


# =====================================================================
# Helpers
# =====================================================================
@agent.effect
def log_event(message):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", file=sys.stderr, flush=True)


@agent.action
def query_one(prolog_text):
    """Run a Prolog query locally; return the first solution as str."""
    try:
        sol = agent.query_one(prolog_text)
    except Exception as e:
        return f"err:{type(e).__name__}: {e}"
    return "" if sol is None else str(sol)


@agent.action
def parse_command(text):
    """Turn a UI command into a Prolog query (ordinary action)."""
    t = (text or "").strip()
    if not t:
        return "fail."
    if t.startswith("?"):
        q = t[1:].strip()
        return q if q.endswith(".") else q + "."
    if t == "quit":
        return "quit."
    if t.startswith("check "):
        rest = t[6:].strip()
        return (f'call_peer(warehouse, '
                f'\'handle_request("check", "{rest}", R).\', R2), '
                f'ui_print(R2).')
    if t.startswith("reserve "):
        rest = t[8:].strip()
        return (f'call_peer(warehouse, '
                f'\'handle_request("reserve", "{rest}", R).\', R2), '
                f'ui_print(R2).')
    return t if t.endswith(".") else t + "."


# =====================================================================
# Incoming peer protocol — handle_request/3 (Kind, Payload, Result)
# =====================================================================
def _check(item: str, qty: str) -> str:
    try:
        want = int(qty)
    except ValueError:
        return f"err:bad qty {qty!r}"
    db = agent.build().agent.solver.database
    stock = 0
    for rule in db.rules:
        head = getattr(rule, "head", None)
        if head is None:
            continue
        try:
            if (head.name == "item" and len(head.arguments) == 2
                    and str(head.arguments[0]) == item):
                stock = int(head.arguments[1])
                break
        except Exception:
            continue
    if want <= stock:
        return f"ok:{stock}"
    return f"err:insufficient (stock={stock}, want={want})"


def _reserve(item: str, qty: str) -> str:
    try:
        want = int(qty)
    except ValueError:
        return f"err:bad qty {qty!r}"
    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}] reserve {item} x{want}", file=sys.stderr, flush=True)
    return "ok:reserved"


def _split_payload(payload: str):
    parts = payload.split(None, 1)
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]


register_protocol(agent, extra={
    "check": lambda p: (lambda a, b: _check(a, b) if a else
                        "err:usage check <item> <qty>")(*_split_payload(p)),
    "reserve": lambda p: (lambda a, b: _reserve(a, b) if a else
                          "err:usage reserve <item> <qty>")(*_split_payload(p)),
})


if __name__ == "__main__":
    agent.run(port=CFG.port, token=CFG.token)