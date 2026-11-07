"""Incoming peer protocol. Default branches ping/echo/status.

Public API:
    register_protocol(agent, extra=None) -> None
    extra : dict[str, Callable[[str], str]]  kind -> handler(payload)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from .agent import Agent


def _default_status(agent_obj: "Agent", _payload: str) -> str:
    db = agent_obj.build().agent.solver.database
    return f"ok facts={len(db.facts)} rules={len(db.rules)}"


def register_protocol(
    agent_obj: "Agent",
    extra: Optional[dict[str, Callable[[str], str]]] = None,
) -> None:
    """Register handle_request/2 with default + extra branches.

    Idempotent: calling twice does not register duplicates.
    """
    if getattr(agent_obj, "_protocol_registered", False):
        return

    handlers: dict[str, Callable[[str], str]] = {
        "ping": lambda _p: "pong",
        "echo": lambda p: p,
        "status": lambda _p: _default_status(agent_obj, _p),
    }
    if extra:
        handlers.update(extra)

    def _handle_request(kind, payload):
        fn = handlers.get(kind)
        if fn is None:
            return f"unknown:{kind}"
        return fn(payload)

    agent_obj.action(_handle_request, name="handle_request", arity=3,
                     output_arg=2)
    agent_obj._protocol_registered = True