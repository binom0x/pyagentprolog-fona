"""Read the project's team.json to resolve peer names to URLs.

The dashboard sets FONA_TEAM_FILE for every child it spawns. Agents
that call register_peers(..., resolver=team_resolver) then get a
working call_peer("name", ...) without any manual FONA_PEERS.

Format (team.json v2/v3/v4):
    {"version": 4, "name": "...", "port_range": [8020, 8099],
     "agents": [{"name": "...", ...}]}

In v4 agents no longer carry `port`. When the dashboard spawns a child
it injects FONA_PORT, so the child knows its actual port. team_resolver
in v4 does a LIVE lookup:
  1. If the peer name == FONA_AGENT_NAME -> use FONA_PORT (self).
  2. Otherwise -> scan the project's port_range with live_scan.scan_range
     and match agent_name; result is cached for TTL seconds.

Fallback (no port_range, no live_scan) -> None, and call_peer falls back
to cfg.peers (FONA_PEERS).
"""
from __future__ import annotations

import json as _json
import os
import sys
import time as _time
from typing import Dict, Optional

# cache: {"loaded_at": float, "peers": {name: url}, "port_range": tuple|None}
_cache: Optional[Dict] = None
_CACHE_TTL = 2.0   # seconds; matches dashboard poll interval


def _load_team_file() -> Dict:
    """Parse team.json -> {peers, port_range, name} (no live scan)."""
    path = os.environ.get("FONA_TEAM_FILE", "").strip()
    if not path or not os.path.isfile(path):
        return {"peers": {}, "port_range": None, "name": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = _json.load(f)
    except Exception as e:
        print(f"[fona] team.py: cannot read {path}: {e}",
              file=sys.stderr, flush=True)
        return {"peers": {}, "port_range": None, "name": None}

    peers: Dict[str, str] = {}
    for a in payload.get("agents", []):
        try:
            name = str(a.get("name") or "").strip()
            port = int(a.get("port") or 0)
        except Exception:
            continue
        # v2/v3: static port present -> use it directly
        if name and port:
            peers[name] = f"http://127.0.0.1:{port}"

    pr = payload.get("port_range")
    port_range = None
    if isinstance(pr, (list, tuple)) and len(pr) == 2:
        try:
            port_range = (int(pr[0]), int(pr[1]))
        except Exception:
            port_range = None

    return {"peers": peers, "port_range": port_range,
            "name": payload.get("name")}


def _live_scan(port_range: tuple) -> Dict[str, str]:
    """Scan port_range and return {agent_name: url}."""
    try:
        from .live_scan import scan_range
    except Exception:
        return {}
    try:
        live = scan_range(port_range[0], port_range[1])
    except Exception:
        return {}
    result: Dict[str, str] = {}
    for item in live:
        if item.name and item.url:
            # first-wins; duplicates unlikely in a healthy team
            result.setdefault(item.name, item.url)
    return result


def _refresh_cache() -> Dict:
    global _cache
    now = _time.time()
    if _cache is not None and (now - _cache["loaded_at"]) < _CACHE_TTL:
        return _cache

    info = _load_team_file()
    peers: Dict[str, str] = dict(info["peers"])  # static (v2/v3) first
    pr = info["port_range"]
    if pr is not None:
        # v4: live scan overrides static
        for name, url in _live_scan(pr).items():
            peers[name] = url

    _cache = {
        "loaded_at": now,
        "peers": peers,
        "port_range": pr,
        "name": info["name"],
    }
    return _cache


def team_resolver(name: str) -> Optional[str]:
    """Return base URL for a peer by its agent name, or None.

    Resolution order:
      1. self: name == FONA_AGENT_NAME -> http://127.0.0.1:$FONA_PORT
      2. static port from team.json v2/v3
      3. live scan over team.json v4 port_range (cached _CACHE_TTL s)

    Returns None if the peer cannot be found; call_peer then falls back
    to cfg.peers (FONA_PEERS).
    """
    name = (name or "").strip()
    if not name:
        return None

    # 1. self, no scan needed
    if name == (os.environ.get("FONA_AGENT_NAME") or "").strip():
        port = os.environ.get("FONA_PORT")
        if port:
            return f"http://127.0.0.1:{port}"

    cache = _refresh_cache()

    # 2/3. static peers, then live scan result
    url = cache["peers"].get(name)
    if url:
        return url

    # edge case: cache populated before peer started; force one rescan
    if cache["port_range"] is not None:
        global _cache
        _cache = None
        cache = _refresh_cache()
        return cache["peers"].get(name)

    return None


def invalidate_cache() -> None:
    """Drop the resolver cache (useful for tests)."""
    global _cache
    _cache = None