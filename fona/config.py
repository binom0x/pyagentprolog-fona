"""Declarative config loader for Fona agents.

Single entry point: load_config(**spec) reads environment variables,
parses them by the given type (or a named parser), and returns a
frozen object. No side effects beyond reading os.environ.

Spec format:
    name = (env_var, type_or_parser, default)
where type_or_parser is:
    * a builtin type: int, float, str, bool
    * a string name from _PARSERS: "peers", "csv", "json", "list"
    * a callable: (raw: str) -> Any

Example:
    CFG = load_config(
        port=("FONA_PORT", int, 8000),
        token=("FONA_TOKEN", str, None),
        peers=("FONA_PEERS", "peers", {}),
        timeout=("FONA_HTTP_TIMEOUT", float, 10.0),
        peers_headers=True,
    )
    CFG.port, CFG.peers, CFG.http
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _parse_peers(raw: str) -> dict[str, str]:
    """'a=http://x,b=http://y' -> {'a': 'http://x', 'b': 'http://y'}"""
    out: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, url = item.split("=", 1)
        out[name.strip()] = url.strip().rstrip("/")
    return out


def _parse_csv(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


_PARSERS: dict[str, Callable[[str], Any]] = {
    "bool": _parse_bool,
    "peers": _parse_peers,
    "csv": _parse_csv,
    "json": json.loads,
}


@dataclass(frozen=True)
class FonaConfig:
    """Frozen view of resolved configuration."""
    _values: dict = field(repr=False, default_factory=dict)
    http: Any = None

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def as_dict(self) -> dict:
        return dict(self._values)


def load_config(**spec: Any) -> FonaConfig:
    """Build a FonaConfig from env vars according to spec.

    Recognised kwargs:
        <name>            : (env_var, parser, default)
        peers_headers     : bool, default True — add X-API-Key: token
                            to CFG.http if token is set
        http_timeout_from : str, default "timeout" — which spec name
                            is used as HTTP timeout
    """
    peers_headers = bool(spec.pop("peers_headers", True))
    http_timeout_from = spec.pop("http_timeout_from", "timeout")

    values: dict[str, Any] = {}
    for name, trio in spec.items():
        if (not isinstance(trio, tuple)) or len(trio) != 3:
            raise TypeError(
                f"config spec for {name!r} must be "
                f"(env_var, parser, default), got {trio!r}")
        env_var, parser, default = trio
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            values[name] = default
            continue
        if isinstance(parser, str):
            fn = _PARSERS.get(parser)
            if fn is None:
                raise ValueError(
                    f"unknown parser {parser!r} for {name!r}")
            values[name] = fn(raw)
        elif callable(parser):
            values[name] = parser(raw)
        else:
            raise TypeError(
                f"parser for {name!r} must be str or callable, "
                f"got {type(parser).__name__}")

    # Build shared HTTP client if httpx is available.
    http = None
    try:
        import httpx
        timeout = values.get(http_timeout_from, 10.0)
        token = values.get("token")
        headers = {"X-API-Key": token} if (token and peers_headers) else {}
        http = httpx.Client(timeout=float(timeout), headers=headers)
    except ImportError:
        pass

    return FonaConfig(_values=values, http=http)