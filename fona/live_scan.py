"""Scan port range for live Fona agents.

A "live" agent is any process listening on a port in the range whose
GET /api/v1/model returns 200. It may or may not be in team.json.

The scan uses ONE netstat/lsof call for the whole range and then
parallel HTTP requests to /api/v1/model. This keeps the 2s UI tick
cheap even for large ranges.
"""
from __future__ import annotations

import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx


@dataclass
class LiveAgent:
    port: int
    url: str
    name: Optional[str] = None
    team_name: Optional[str] = None
    pid: Optional[int] = None
    rules_count: int = 0
    actions_count: int = 0
    kb_file: str = ""
    error: str = ""


def _listening_pids(start: int, end: int) -> Dict[int, int]:
    """Return {port: pid} for all LISTENING ports in [start, end]."""
    result: Dict[int, int] = {}
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "TCP"],
                timeout=4, text=True, errors="replace")
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3] == "LISTENING":
                    local = parts[1]
                    m = re.search(r":(\d+)$", local)
                    if not m:
                        continue
                    port = int(m.group(1))
                    if start <= port <= end:
                        try:
                            result[port] = int(parts[4])
                        except ValueError:
                            pass
        else:
            try:
                out = subprocess.check_output(
                    ["lsof", "-i", f":{start}-{end}", "-sTCP:LISTEN",
                     "-P", "-n", "-Fpn"],
                    timeout=4, text=True)
                cur_pid = 0
                for line in out.splitlines():
                    if line.startswith("p"):
                        cur_pid = int(line[1:])
                    elif line.startswith("n"):
                        m = re.search(r":(\d+)$", line[1:])
                        if m:
                            result[int(m.group(1))] = cur_pid
            except FileNotFoundError:
                out = subprocess.check_output(
                    ["ss", "-tlnp", f"sport >= :{start} and sport <= :{end}"],
                    timeout=4, text=True)
                for line in out.splitlines():
                    m = re.search(r":(\d+).*pid=(\d+)", line)
                    if m:
                        result[int(m.group(1))] = int(m.group(2))
    except Exception:
        pass
    return result


def scan_range(start: int, end: int, timeout: float = 0.5,
               workers: int = 32) -> List[LiveAgent]:
    """Return LiveAgent for every port in [start, end] that answers."""
    pids = _listening_pids(start, end)
    if not pids:
        return []

    def _one(port: int) -> Optional[LiveAgent]:
        pid = pids.get(port)
        url = f"http://127.0.0.1:{port}"
        try:
            r = httpx.get(f"{url}/api/v1/model", timeout=timeout)
        except Exception as e:
            return LiveAgent(port=port, url=url, pid=pid,
                             error=f"{type(e).__name__}: {e}")
        if r.status_code != 200:
            return LiveAgent(port=port, url=url, pid=pid,
                             error=f"HTTP {r.status_code}")
        try:
            data = r.json()
        except Exception:
            return LiveAgent(port=port, url=url, pid=pid,
                             error="invalid JSON")
        return LiveAgent(
            port=port, url=url,
            name=data.get("agent_name"),
            team_name=data.get("team_name"),
            pid=pid,
            rules_count=int(data.get("rules_count", 0) or 0),
            actions_count=len(data.get("actions", []) or []),
            kb_file=data.get("kb_file") or "",
        )

    result: List[LiveAgent] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_one, p) for p in pids.keys()]
        for fut in as_completed(futures):
            try:
                item = fut.result()
            except Exception:
                continue
            if item is not None:
                result.append(item)
    result.sort(key=lambda x: x.port)
    return result