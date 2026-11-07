"""Inter-agent transport. Registered into an Agent once, identical for all.

Public API:
    register_peers(agent, cfg)   -> None
    call_peer(cfg, name, query)  -> str   ("ok:<v>" | "err:<r>")

CFG must come from fona.load_config() and have:
    cfg.peers : dict[str, str]   name -> base URL
    cfg.http  : httpx.Client     shared client (auto X-API-Key)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent import Agent
    from .config import FonaConfig


def call_peer(cfg: Any, peer_name: str, query: str) -> str:
    """Send a Prolog query to a peer. Returns an atom: ok:<v> | err:<r>."""
    url = (cfg.peers or {}).get(peer_name)
    if not url:
        return f"err:unknown peer {peer_name}"
    if cfg.http is None:
        return "err:http client unavailable"
    try:
        r = cfg.http.post(f"{url}/api/v1/query", json={"query": query})
        if r.status_code != 200:
            return f"err:http {r.status_code}"
        data = r.json()
        if not data.get("success"):
            return f"err:{data.get('error', 'query failed')}"
        sols = data.get("solutions") or []
        if not sols:
            return "ok:"
        return f"ok:{next(iter(sols[0].values()), '')}"
    except Exception as e:
        return f"err:{type(e).__name__}: {e}"


def register_peers(agent_obj: "Agent", cfg: Any) -> None:
    """Register call_peer/3 and broadcast_ping/0 on the agent.

    Idempotent: calling twice does not register duplicates.
    """

    if getattr(agent_obj, "_peers_registered", False):
        return

    def _call_peer(peer_name, query):
        return call_peer(cfg, peer_name, query)

    def _broadcast_ping():
        peers = cfg.peers or {}
        if not peers:
            return "err:no peers"
        return "\n".join(
            f"{name}={call_peer(cfg, name, 'handle_request(\"ping\", R).')}"
            for name in peers
        )

    agent_obj.action(_call_peer, name="call_peer", arity=3, output_arg=2)
    agent_obj.action(_broadcast_ping, name="broadcast_ping", arity=1,
                     output_arg=0)
    agent_obj._peers_registered = True