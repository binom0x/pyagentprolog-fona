"""Orders agent — creates orders by asking the warehouse.

Role in the team:
  * Calls warehouse via call_peer/3 (check + reserve), with R as
    the output argument:  handle_request("check", "lamp 1", R).
  * Answers peers via handle_request/3:
      - ping / echo / status      (standard)
      - place <item> <qty>        -> "ok:<order_id>" | "err:<reason>"
      - orders                    -> "ok:<id>=<item>x<qty>;..."
  * HITL: user can type "place lamp 1" in the UI.

Run:
    FONA_PEERS="warehouse=http://127.0.0.1:8000" \
        python examples/warehouse_team/orders_agent.py
    FONA_PORT=8001 FONA_PEERS="warehouse=http://127.0.0.1:8000" \
        python examples/warehouse_team/orders_agent.py
"""
import os
import sys
import time
import uuid

from fona import (
    agent, load_config, register_peers, register_protocol,
)

CFG = load_config(
    port=("FONA_PORT", int, 8001),
    token=("FONA_TOKEN", str, None),
    peers=("FONA_PEERS", "peers",
           {"warehouse": "http://127.0.0.1:8000"}),
    timeout=("FONA_HTTP_TIMEOUT", float, 10.0),
    peers_headers=True,
)

from fona import team_resolver
register_peers(agent, CFG, resolver=team_resolver)


# =====================================================================
# In-memory order log
# =====================================================================
_orders: dict[str, dict] = {}


def _place(item: str, qty: str) -> str:
    try:
        want = int(qty)
    except ValueError:
        return f"err:bad qty {qty!r}"
    if want <= 0:
        return "err:qty must be positive"
    # 1) check — handle_request/3: Kind, Payload, Result
    check = call_peer("warehouse",
                      f'handle_request("check", "{item} {want}", R).')
    if check.startswith("err:"):
        return check
    # 2) reserve
    reserve = call_peer("warehouse",
                        f'handle_request("reserve", "{item} {want}", R).')
    if reserve.startswith("err:"):
        return reserve
    # 3) record
    oid = str(uuid.uuid4())[:8]
    _orders[oid] = {"item": item, "qty": want,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}] order {oid}: {item} x{want}",
          file=sys.stderr, flush=True)
    return f"ok:{oid}"


def _list_orders() -> str:
    if not _orders:
        return "ok:"
    return "ok:" + ";".join(
        f"{oid}={o['item']}x{o['qty']}" for oid, o in _orders.items())


register_protocol(agent, extra={
    "place": lambda p: (lambda a, b: _place(a, b) if a else
                        "err:usage place <item> <qty>")(*_split_payload(p)),
    "orders": lambda _p: _list_orders(),
})


def _split_payload(payload: str):
    parts = payload.split(None, 1)
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]


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
    if t == "quit":
        return "quit."
    if t == "orders":
        return "ui_print('(use REST /api/v1/query to list orders)')."
    if t.startswith("place "):
        rest = t[6:].strip()
        return (f'call_peer(orders, '
                f'\'handle_request("place", "{rest}", R).\', R2), '
                f'ui_print(R2).')
    return t if t.endswith(".") else t + "."


# =====================================================================
# PROGRAM
# =====================================================================
agent.program = r"""
run :-
    log_event('orders agent started'),
    ui_print('Orders agent ready.'),
    ui_print('Type: place <item> <qty> | quit.'),
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


if __name__ == "__main__":
    agent.run(port=CFG.port, token=CFG.token)