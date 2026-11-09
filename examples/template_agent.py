"""Fona background agent — reference template (variant A).

Interaction model
-----------------
* PROGRAM is pure Prolog: domain facts/rules + run/0 + on_user_input/0.
  It does NOT parse strings. It receives a Prolog query and runs it.
* Inter-agent protocol (handle_request/2, call_peer/3) lives in
  fona.protocol / fona.peers and is registered in one line each.
* NL <-> Prolog are ordinary @agent.action functions that accompany
  the HITL loop:
      nl_to_prolog/1  — user text -> Prolog query (before query_one)
      prolog_to_nl/1  — Prolog solution -> user text (after query_one)
  They are not part of the protocol, not referenced by PROGRAM, and
  can be removed without breaking anything.
* HITL loop is: read -> maybe translate NL->Prolog -> query_one ->
  maybe translate Prolog->NL -> print. That composition lives in
  PROGRAM as on_user_input/0 using ordinary predicates.

Run:
    python examples/template_agent.py
    FONA_PEERS="server=http://127.0.0.1:8000" \
        python examples/template_agent.py
    FONA_TOKEN=secret python examples/template_agent.py
"""
from __future__ import annotations

import os
import sys
import time

from fona import agent, load_config, register_peers, register_protocol


# =====================================================================
# Configuration — declarative, one place
# =====================================================================
CFG = load_config(
    port=("FONA_PORT", int, 8002),
    token=("FONA_TOKEN", str, None),
    peers=("FONA_PEERS", "peers", {}),
    timeout=("FONA_HTTP_TIMEOUT", float, 10.0),
)

ALLOWED_ENV = {"PATH", "HOME", "USER", "LANG", "FONA_PORT"}


# =====================================================================
# Transport + default protocol — one line each, identical for all agents
# =====================================================================
from fona import team_resolver
register_peers(agent, CFG, resolver=team_resolver)
register_protocol(agent)


# =====================================================================
# Domain actions (ordinary predicates)
# =====================================================================
@agent.effect
def log_event(message):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", file=sys.stderr, flush=True)


@agent.action
def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@agent.action
def read_env(name):
    return os.getenv(name, "") if name in ALLOWED_ENV else ""


@agent.generate
def numbers(limit):
    for i in range(1, int(limit) + 1):
        yield i


# =====================================================================
# Local query runner (ordinary action)
# =====================================================================
@agent.action
def query_one(prolog_text):
    """Run a Prolog query locally; return first solution or "" on fail."""
    try:
        sol = agent.query_one(prolog_text)
    except Exception as e:
        return f"err:{type(e).__name__}: {e}"
    return "" if sol is None else str(sol)


# =====================================================================
# HITL companions: NL <-> Prolog (ordinary actions, stubs)
# =====================================================================
# These accompany the HITL loop; they are not part of the protocol
# and not referenced by handle_request/2. Replace the bodies with
# real HF/LLM calls to enable natural-language input/output.

@agent.action
def nl_to_prolog(text):
    """User text -> Prolog query string. Stub."""
    return f"err:nl_to_prolog not configured ({text!r})"


@agent.action
def prolog_to_nl(term):
    """Prolog solution -> user-facing text. Stub."""
    return f"err:prolog_to_nl not configured ({term!r})"


# =====================================================================
# PROGRAM — pure Prolog, no string parsing
# =====================================================================
@agent.program
PROGRAM = r"""
% ---------- Domain ----------
light(kitchen, on).
light(bedroom, off).
light(living_room, on).

% ---------- Start ----------
run :-
    log_event('agent started'),
    ui_print('Ready.'),
    ui_print('Send a Prolog query, e.g.  light(bedroom, X).'),
    ui_print('Or prefix with nl:  nl find the bedroom light'),
    ui_print('Type quit to stop.'),
    on_user_input.

% ---------- HITL loop ----------
% Input is either:
%   * a Prolog query (runs as-is)
%   * "nl <text>" — NL is translated to Prolog first
% The translation is done by nl_to_prolog/1, an ordinary action.
% The result is optionally translated back by prolog_to_nl/1.
on_user_input :-
    ui_read(Text),
    (   Text == quit
    ->  ui_print('Bye.'),
        log_event('user said quit')
    ;   sub_atom(Text, 0, 3, _, 'nl ')
    ->  sub_atom(Text, 3, _, 0, NL),
        nl_to_prolog(NL, Prolog),
        (   sub_atom(Prolog, 0, 4, _, 'err:')
        ->  ui_print(Prolog),
            on_user_input
        ;   run_query(Prolog)
        )
    ;   run_query(Text)
    ).

% Run a Prolog query and print the solution. If prolog_to_nl/1
% is configured, its output is used; otherwise the raw solution
% is printed.
run_query(Query) :-
    query_one(Query, Result),
    (   Result == ''
    ->  ui_print('No solution.')
    ;   prolog_to_nl(Result, NL),
        (   sub_atom(NL, 0, 4, _, 'err:')
        ->  ui_print(Result)
        ;   ui_print(NL)
        )
    ),
    on_user_input.
"""


# =====================================================================
# Entry point
# =====================================================================
if __name__ == "__main__":
    agent.run(
        host="127.0.0.1",
        port=CFG.port,
        ui=True,
        rest=True,
        token=CFG.token,
    )