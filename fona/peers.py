"""Inter-agent transport. Registered into an Agent once, identical for all.

Public API:
    register_peers(agent, cfg, resolver=None) -> None
    call_peer(cfg, name, query, resolver=None) -> str

Resolver: callable(name: str) -> Optional[str] returning a base URL.
If resolver is given and returns a URL, it wins over cfg.peers.
If cfg.peers has the name, it is used as fallback.
If neither, "err:unknown peer <name>".
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from .agent import Agent
    from .config import FonaConfig


Resolver = Callable[[str], Optional[str]]


def call_peer(cfg: Any, peer_name: str, query: str,
              resolver: Optional[Resolver] = None) -> str:
    """Send a Prolog query to a peer. Returns an atom: ok:<v> | err:<r>."""
    url = None
    if resolver is not None:
        try:
            url = resolver(peer_name)
        except Exception:
            url = None
    if not url:
        url = (cfg.peers or {}).get(peer_name)
    if not url:
        return f"err:unknown peer {peer_name}"
    if cfg.http is None:
        return "err:http client unavailable"
    try:
        r = cfg.http.post(f"{url.rstrip('/')}/api/v1/query",
                          json={"query": query})
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


def register_peers(agent_obj: "Agent", cfg: Any,
                   resolver: Optional[Resolver] = None) -> None:
    """Register call_peer/3 and broadcast_ping/0 on the agent.

    Idempotent. If resolver is given, it is consulted first; cfg.peers
    is the fallback. If neither yields a URL, "err:unknown peer".
    """
    if getattr(agent_obj, "_peers_registered", False):
        return

    def _call_peer(peer_name, query):
        return call_peer(cfg, peer_name, query, resolver)

    def _broadcast_ping():
        names = set((cfg.peers or {}).keys())
        if resolver is not None:
            # best effort: only names from cfg.peers can be enumerated;
            # the resolver is name-based, not enumerable.
            pass
        if not names:
            return "err:no peers"
        return "\n".join(
            f"{name}={call_peer(cfg, name, 'handle_request(\"ping\", R).', resolver)}"
            for name in names
        )

    agent_obj.action(_call_peer, name="call_peer", arity=3, output_arg=2)
    agent_obj.action(_broadcast_ping, name="broadcast_ping", arity=1,
                     output_arg=0)
    agent_obj._peers_registered = True