"""Chat agent — user-facing dialogue that drives the team.

Role in the team:
  * HITL: ui_print / ui_read.
  * Calls warehouse and orders via call_peer/3, with R as the output
    argument:  handle_request("check", "lamp 2", R).
  * Answers peers via handle_request/3 (standard ping/echo/status).

Commands:
    ?<prolog>              — run raw Prolog locally
    check <item> <qty>     — ask warehouse
    order <item> <qty>     — ask orders to place an order
    orders                 — list orders
    help                   — show this help
    quit                   — exit

Run:
    FONA_PEERS="warehouse=http://127.0.0.1:8000,orders=http://127.0.0.1:8001" \
        python examples/warehouse_team/chat_agent.py
"""
import os
import sys
import time

from fona import (
    agent, load_config, register_peers, register_protocol,
)

CFG = load_config(
    port=("FONA_PORT", int, 8002),
    token=("FONA_TOKEN", str, None),
    peers=("FONA_PEERS", "peers", {
        "warehouse": "http://127.0.0.1:8000",
        "orders": "http://127.0.0.1:8001",
    }),
    timeout=("FONA_HTTP_TIMEOUT", float, 10.0),
    peers_headers=True,
)

from fona import team_resolver
register_peers(agent, CFG, resolver=team_resolver)
register_protocol(agent)

# =====================================================================
# Helpers
# =====================================================================
@agent.effect
def log_event(message):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", file=sys.stderr, flush=True)


@agent.action
def query_one(prolog_text):
    try:
        sol = agent.query_one(prolog_text)
    except Exception as e:
        return f"err:{type(e).__name__}: {e}"
    return "" if sol is None else str(sol)


@agent.action
def parse_command(text):
    t = (text or "").strip()
    if not t:
        return "fail."
    if t.startswith("?"):
        q = t[1:].strip()
        return q if q.endswith(".") else q + "."
    if t == "help":
        return ("ui_print('Commands: check <item> <qty> | "
                "order <item> <qty> | orders | help | quit').")
    if t == "orders":
        return ("call_peer(orders, "
                "'handle_request(\"orders\", \"\", R).', R2), "
                "ui_print(R2).")
    if t.startswith("check "):
        rest = t[6:].strip()
        return (f'call_peer(warehouse, '
                f'\'handle_request("check", "{rest}", R).\', R2), '
                f'ui_print(R2).')
    if t.startswith("order "):
        rest = t[6:].strip()
        return (f'call_peer(orders, '
                f'\'handle_request("place", "{rest}", R).\', R2), '
                f'ui_print(R2).')
    if t == "quit":
        return "quit."
    return f"ui_print('unknown command: {t.replace(chr(39), '')}')."


# =====================================================================
# Program
# =====================================================================
agent.program = r"""
run :-
    log_event('chat agent started'),
    ui_print('Team chat. Type help for commands.'),
    on_user_input.

on_user_input :-
    ui_read(Text),
    (   Text == quit
    ->  ui_print('Bye.'),
        log_event('user said quit')
    ;   parse_command(Text, Query),
        (   Query == 'quit.'
        ->  ui_print('Bye.')
        ;   Query == 'fail.'
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


if __name__ == "__main__":
    agent.run(port=CFG.port, token=CFG.token)