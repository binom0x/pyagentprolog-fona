"""Fona Dashboard — manage and monitor background agents.

Features:
  * add/remove agents (script + port + optional orchestrator Gradio port)
  * start/stop/restart, change port with live validation
  * live status cards: uptime, latency, rules, actions, sparkline
  * team save/load (JSON), autostart flag per agent
  * i18n: English / Russian switchable at runtime

Run:
    python -m fona.dashboard
    fona-dashboard --port 7861
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json as _json
import os
import re
import socket
import subprocess
import sys
import threading
import time as _t
import uuid
from dataclasses import dataclass, field
from html import escape as _esc
from pathlib import Path
from typing import Dict, List, Optional

import gradio as gr
import httpx


# ============================================================================
# i18n
# ============================================================================
TRANSLATIONS = {
    "en": {
        "title": "Fona Dashboard",
        "agents": "Agents",
        "summary": "Summary",
        "add_agent": "Add Agent",
        "action_log": "Action Log",
        "script": "Script",
        "script_placeholder": "examples/demo_agent.py",
        "port": "Port",
        "port_placeholder": "8000",
        "name_optional": "Name (optional)",
        "name_placeholder": "my-agent",
        "orch_port_optional": "Orchestrator Gradio port (optional)",
        "orch_port_placeholder": "8010",
        "add": "Add",
        "start": "Start",
        "stop": "Stop",
        "restart": "Restart",
        "remove": "Remove",
        "open_ui": "Open UI",
        "open_orchestrator": "Orchestrator",
        "uptime": "uptime",
        "latency": "latency",
        "rules": "rules",
        "actions": "actions",
        "availability": "availability",
        "kb": "KB",
        "error": "error",
        "autostart": "autostart",
        "online": "ONLINE",
        "offline": "OFFLINE",
        "starting": "STARTING",
        "stopped": "STOPPED",
        "error_status": "ERROR",
        "team": "Team - save / load",
        "saved_teams": "Saved teams",
        "team_name": "New team name (no extension)",
        "save_as": "Save as",
        "load": "Load",
        "load_and_start": "Load and start",
        "delete": "Delete",
        "autostart_all": "Start all on load (autostart flag)",
        "empty_state": "No agents. Add a script in the panel on the right.",
        "empty_hint": "Example: examples/demo_agent.py, port 8000",
        "change_port_prompt": "New port for {name} (current {current}):",
        "confirm_remove": "Remove {name}?",
        "not_found": "not found",
        "port_conflict": "Port {port} is already used by {name}",
        "port_busy": "Port {port} is already in use by another process",
        "port_invalid": "Port must be 1..65535",
        "script_missing": "Script not found: {path}",
        "status_total": "total",
        "status_online": "online",
        "status_offline": "offline",
        "status_stopped": "stopped",
        "status_starting": "starting",
    },
    "ru": {
        "title": "Дашборд Fona",
        "agents": "Агенты",
        "summary": "Сводка",
        "add_agent": "Добавить агента",
        "action_log": "Журнал действий",
        "script": "Скрипт",
        "script_placeholder": "examples/demo_agent.py",
        "port": "Порт",
        "port_placeholder": "8000",
        "name_optional": "Имя (опционально)",
        "name_placeholder": "мой-агент",
        "orch_port_optional": "Порт Gradio оркестратора (опционально)",
        "orch_port_placeholder": "8010",
        "add": "Добавить",
        "start": "Старт",
        "stop": "Стоп",
        "restart": "Перезапустить",
        "remove": "Удалить",
        "open_ui": "Открыть UI",
        "open_orchestrator": "Оркестратор",
        "uptime": "аптайм",
        "latency": "задержка",
        "rules": "правил",
        "actions": "действий",
        "availability": "доступность",
        "kb": "БЗ",
        "error": "ошибка",
        "autostart": "автозапуск",
        "online": "ОНЛАЙН",
        "offline": "ОФЛАЙН",
        "starting": "СТАРТ",
        "stopped": "СТОП",
        "error_status": "ОШИБКА",
        "team": "Команда — сохранить / загрузить",
        "saved_teams": "Сохранённые команды",
        "team_name": "Имя новой команды (без расширения)",
        "save_as": "Сохранить как",
        "load": "Загрузить",
        "load_and_start": "Загрузить и запустить",
        "delete": "Удалить",
        "autostart_all": "Запускать всех при загрузке (флаг autostart)",
        "empty_state": "Нет агентов. Добавьте скрипт в панели справа.",
        "empty_hint": "Пример: examples/demo_agent.py, порт 8000",
        "change_port_prompt": "Новый порт для {name} (текущий {current}):",
        "confirm_remove": "Удалить {name}?",
        "not_found": "не найден",
        "port_conflict": "Порт {port} уже занят агентом {name}",
        "port_busy": "Порт {port} занят другим процессом на этой машине",
        "port_invalid": "Порт должен быть 1..65535",
        "script_missing": "Скрипт не найден: {path}",
        "status_total": "всего",
        "status_online": "онлайн",
        "status_offline": "офлайн",
        "status_stopped": "остановлен",
        "status_starting": "стартует",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    """Get translation for key in given language."""
    table = TRANSLATIONS.get(lang) or TRANSLATIONS["en"]
    template = table.get(key) or TRANSLATIONS["en"].get(key, key)
    return template.format(**kwargs) if kwargs else template


# ============================================================================
# Gradio 5 / 6 compatibility
# ============================================================================
try:
    _GRADIO_VERSION = tuple(int(x) for x in gr.__version__.split(".")[:2])
except (ValueError, AttributeError):
    _GRADIO_VERSION = (5, 0)
_IS_GRADIO6 = _GRADIO_VERSION >= (6, 0)


# ============================================================================
# Favicon
# ============================================================================
_DEFAULT_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="12" fill="#4f46e5"/>'
    '<text x="32" y="46" font-family="ui-sans-serif,system-ui,sans-serif" '
    'font-size="40" font-weight="700" fill="#ffffff" '
    'text-anchor="middle" dominant-baseline="middle">F</text>'
    '</svg>'
)


def _ensure_favicon() -> Optional[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    for subdir in ("", "assets"):
        for name in ("favicon.png", "favicon.ico", "favicon.svg"):
            path = (os.path.join(here, subdir, name)
                    if subdir else os.path.join(here, name))
            if os.path.isfile(path):
                return path
    try:
        path = os.path.join(here, "favicon.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_DEFAULT_FAVICON_SVG)
        return path
    except OSError:
        return None


# ============================================================================
# CSS
# ============================================================================
_GLOBAL_CSS = """
.gradio-container { max-width: 1900px !important; padding: 6px 8px !important;
                    background: #0b0d11 !important; color: #c7cbd1 !important; }
footer { display: none !important; }
button.compact-btn, .compact-btn button {
    min-height: 26px !important; padding: 2px 8px !important;
    font-size: 12px !important; line-height: 1.2 !important;
    background: #21262d !important; border: 1px solid #2a313d !important;
    color: #c7cbd1 !important;
}
button.compact-btn:hover, .compact-btn button:hover {
    background: #30363d !important; border-color: #3a4250 !important;
}
.compact-tb input, .compact-tb textarea {
    padding: 4px 8px !important; font-size: 12px !important;
    min-height: 28px !important; background: #0b0d11 !important;
    color: #c7cbd1 !important; border: 1px solid #2a313d !important;
    border-radius: 4px !important;
}
.compact-tb input:focus, .compact-tb textarea:focus {
    border-color: #58a6ff !important;
    box-shadow: 0 0 0 2px rgba(88,166,255,.2) !important;
    outline: none !important;
}
.compact-lbl label {
    font-size: 11px !important; margin-bottom: 1px !important;
    color: #8b949e !important;
}
.col-head {
    font-size: 14px !important; font-weight: 600;
    margin: 2px 0 6px 0 !important; color: #c7cbd1;
}
pre.status-box {
    margin: 0 !important;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11px; line-height: 1.35;
    padding: 4px 8px; background: #0b0d11;
    border: 1px solid #2a313d; border-radius: 4px;
    color: #c7cbd1; white-space: pre-wrap;
    max-height: 100px; overflow: auto;
}
*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-track { background: transparent; }
*::-webkit-scrollbar-thumb { background: #2a313d; border-radius: 5px; }

.dash-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 12px;
    padding: 4px;
}
.card {
    background: #0f1115; border: 1px solid #2a313d;
    border-radius: 8px; padding: 12px;
    display: flex; flex-direction: column; gap: 8px;
    transition: border-color .15s, transform .15s;
}
.card:hover { border-color: #3a4250; transform: translateY(-1px); }
.card.online  { border-left: 4px solid #238636; }
.card.offline { border-left: 4px solid #d73a49; }
.card.starting{ border-left: 4px solid #d29922; }
.card.stopped { border-left: 4px solid #484f58; }
.card.error   { border-left: 4px solid #f85149; }

.card-head { display: flex; justify-content: space-between;
             align-items: center; gap: 8px; }
.card-title { font-weight: 600; font-size: 13px; color: #c7cbd1; }
.card-sub { font-size: 11px; color: #8b949e;
            font-family: ui-monospace, monospace; }
.badge { font-size: 10px; padding: 2px 8px; border-radius: 10px;
         font-weight: 600; letter-spacing: .3px; text-transform: uppercase; }
.badge.online   { background: #0f2a1a; color: #7ee787; }
.badge.offline  { background: #2a0f12; color: #ff7b72; }
.badge.starting { background: #2a1f0f; color: #e3b341; }
.badge.stopped  { background: #21262d; color: #8b949e; }
.badge.error    { background: #2a0f12; color: #ff7b72; }

.card-body { display: flex; flex-direction: column; gap: 4px;
             font-size: 12px; color: #c7cbd1; }
.kv { display: flex; justify-content: space-between; gap: 8px; }
.kv .k { color: #8b949e; font-size: 11px; }
.kv .v { color: #c7cbd1; font-family: ui-monospace, monospace; font-size: 11px; }

.card-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: auto; }
.card-actions button { font-size: 11px; padding: 3px 8px; }
.card-actions .open-btn {
    text-decoration: none !important; display: inline-block;
    padding: 3px 10px; background: #238636; color: #fff !important;
    border-radius: 4px; font-size: 11px; border: 1px solid #238636;
}
.card-actions .open-btn:hover { background: #2ea043; }
.card-actions .open-btn.orch { background: #6e40c9; border-color: #6e40c9; }
.card-actions .open-btn.orch:hover { background: #8957e5; }

.empty-state {
    padding: 40px 20px; text-align: center; color: #8b949e;
    border: 1px dashed #2a313d; border-radius: 8px; font-size: 13px;
}
.sparkline { width: 100%; height: 30px; margin-top: 4px; }
"""

_HEAD_DARK = """
<script>
(function(){
    const force = () => {
        document.documentElement.classList.add('dark');
        if (document.body) document.body.classList.add('dark');
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', force);
    } else { force(); }
    new MutationObserver(() => {
        if (!document.documentElement.classList.contains('dark')) {
            document.documentElement.classList.add('dark');
        }
    }).observe(document.documentElement, {attributes: true, attributeFilter: ['class']});
})();
</script>
"""


# ============================================================================
# Agent model
# ============================================================================
@dataclass
class AgentEntry:
    id: str
    name: str
    script: str
    port: int
    url: str = ""
    process: Optional[subprocess.Popen] = None
    orchestrator_gradio_port: Optional[int] = None
    orchestrator_process: Optional[subprocess.Popen] = None
    status: str = "stopped"
    error: str = ""
    started_at: float = 0.0
    rules: int = 0
    actions: int = 0
    kb_file: str = ""
    last_check: float = 0.0
    latency_ms: float = 0.0
    history: List[int] = field(default_factory=list)
    autostart: bool = False

    def __post_init__(self):
        if not self.url:
            self.url = f"http://127.0.0.1:{self.port}"

    def uptime_seconds(self) -> float:
        if not self.started_at or self.status == "stopped":
            return 0.0
        return max(0.0, _t.time() - self.started_at)

    def is_alive(self) -> bool:
        return self.status in ("online", "starting", "offline")


# ============================================================================
# Utilities
# ============================================================================
def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _status_html(s: str) -> str:
    return f'<pre class="status-box">{_esc(str(s))}</pre>'


# ============================================================================
# Agent manager
# ============================================================================
class AgentManager:
    def __init__(self):
        self.agents: Dict[str, AgentEntry] = {}
        self._lock = threading.RLock()

    def add(self, script: str, name: str, port: int,
            orch_port: Optional[int] = None) -> AgentEntry:
        if not (1 <= int(port) <= 65535):
            raise ValueError(f"port must be 1..65535 (got {port})")
        if orch_port is not None and not (1 <= int(orch_port) <= 65535):
            raise ValueError(f"orchestrator port must be 1..65535")

        with self._lock:
            for a in self.agents.values():
                if a.port == int(port):
                    raise ValueError(
                        f"port {port} already used by {a.name}")
                if (orch_port is not None
                        and a.orchestrator_gradio_port == int(orch_port)):
                    raise ValueError(
                        f"orchestrator port {orch_port} already used by {a.name}")
            if not _is_port_free(int(port)):
                raise ValueError(f"port {port} is in use")

            entry = AgentEntry(
                id=str(uuid.uuid4())[:8],
                name=name or Path(script).stem,
                script=script,
                port=int(port),
                orchestrator_gradio_port=(
                    int(orch_port) if orch_port else None),
            )
            self.agents[entry.id] = entry
            return entry

    def remove(self, agent_id: str) -> None:
        with self._lock:
            a = self.agents.pop(agent_id, None)
        if a is not None:
            self._stop_process(a)

    def get(self, agent_id: str) -> Optional[AgentEntry]:
        with self._lock:
            return self.agents.get(agent_id)

    def list(self) -> List[AgentEntry]:
        with self._lock:
            return list(self.agents.values())

    def change_port(self, agent_id: str, new_port: int) -> None:
        if not (1 <= int(new_port) <= 65535):
            raise ValueError("port must be 1..65535")
        a = self.get(agent_id)
        if a is None or int(new_port) == a.port:
            return
        with self._lock:
            for other in self.agents.values():
                if other.id != agent_id and other.port == int(new_port):
                    raise ValueError(
                        f"port {new_port} already used by {other.name}")
        if not _is_port_free(int(new_port)):
            raise ValueError(f"port {new_port} is in use")

        was_running = a.is_alive()
        if was_running:
            self._stop_process(a)
        a.port = int(new_port)
        a.url = f"http://127.0.0.1:{a.port}"
        a.status = "stopped"
        a.error = ""
        a.history = []
        a.started_at = 0.0
        if was_running:
            self.start(agent_id)

    def set_autostart(self, agent_id: str, value: bool) -> None:
        a = self.get(agent_id)
        if a is not None:
            a.autostart = bool(value)

    # ------------------------------------------------------------------
    # Process control
    # ------------------------------------------------------------------
    def start(self, agent_id: str) -> None:
        a = self.get(agent_id)
        if a is None or not os.path.isfile(a.script):
            if a is not None:
                a.status = "error"
                a.error = f"script not found: {a.script}"
            return
        if a.process is not None and a.process.poll() is None:
            return

        env = os.environ.copy()
        env["FONA_CHILD"] = "1"
        env["FONA_PORT"] = str(a.port)

        try:
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000)
            a.process = subprocess.Popen(
                [sys.executable, a.script],
                cwd=os.path.dirname(os.path.abspath(a.script)) or None,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **kwargs,
            )
            a.started_at = _t.time()
            a.status = "starting"
            a.error = ""
            a.history = []
        except Exception as e:
            a.status = "error"
            a.error = f"{type(e).__name__}: {e}"
            return

        # Spawn orchestrator Gradio app if configured
        if a.orchestrator_gradio_port and a.orchestrator_process is None:
            try:
                okwargs = {"stdout": subprocess.PIPE,
                           "stderr": subprocess.PIPE}
                if sys.platform == "win32":
                    okwargs["creationflags"] = 0x08000000
                a.orchestrator_process = subprocess.Popen(
                    [sys.executable, "-m", "fona.orchestrator_app",
                     "--orchestrator", a.url,
                     "--port", str(a.orchestrator_gradio_port),
                     "--no-browser"],
                    env={**os.environ, "FONA_CHILD": "1"},
                    **okwargs,
                )
            except Exception as e:
                a.error = f"orchestrator spawn failed: {e}"

    def stop(self, agent_id: str) -> None:
        a = self.get(agent_id)
        if a is None:
            return
        self._stop_process(a)
        a.status = "stopped"
        a.started_at = 0.0

    def restart(self, agent_id: str) -> None:
        self.stop(agent_id)
        _t.sleep(0.5)
        self.start(agent_id)

    @staticmethod
    def _stop_process(a: AgentEntry) -> None:
        for field_name in ("process", "orchestrator_process"):
            p = getattr(a, field_name, None)
            if p is None:
                continue
            if p.poll() is not None:
                setattr(a, field_name, None)
                continue
            try:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=2)
            except Exception:
                pass
            finally:
                setattr(a, field_name, None)

    # ------------------------------------------------------------------
    # Status polling
    # ------------------------------------------------------------------
    def poll(self, agent_id: str) -> Optional[AgentEntry]:
        a = self.get(agent_id)
        if a is None:
            return None

        if a.process is not None and a.process.poll() is not None:
            rc = a.process.returncode
            a.process = None
            a.status = "error" if rc not in (0, None) else "stopped"
            if rc not in (0, None):
                a.error = f"process exited with code {rc}"

        t0 = _t.time()
        try:
            r = httpx.get(f"{a.url}/api/v1/health", timeout=0.6)
            ok = r.status_code == 200
        except Exception as e:
            ok = False
            if a.status != "starting":
                a.error = str(e)[:120]
        a.last_check = _t.time()
        a.latency_ms = (a.last_check - t0) * 1000.0

        if ok:
            a.status = "online"
            a.error = ""
            try:
                mr = httpx.get(f"{a.url}/api/v1/model", timeout=0.6)
                if mr.status_code == 200:
                    m = mr.json()
                    a.rules = int(m.get("rules_count", 0))
                    a.actions = len(m.get("actions", []))
                    a.kb_file = m.get("kb_file") or ""
            except Exception:
                pass
        else:
            if a.status == "online":
                a.status = "offline"
            elif a.status == "starting" and _t.time() - a.started_at > 15:
                a.status = "error"
                a.error = "no response > 15 s"

        a.history.append(1 if ok else 0)
        a.history = a.history[-40:]
        return a


_manager = AgentManager()


# ============================================================================
# Team save / load
# ============================================================================
TEAM_VERSION = 1
TEAM_DIR = "teams"


def _teams_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, TEAM_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _team_path(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-]+", "_", (name or "").strip())
    safe = safe.strip("_") or str(uuid.uuid4())[:8]
    return os.path.join(_teams_dir(), f"{safe}.json")


def _list_teams() -> List[str]:
    d = _teams_dir()
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(d) if f.endswith(".json")
    )


def _agent_to_dict(a: AgentEntry, base_dir: str) -> dict:
    try:
        rel = os.path.relpath(a.script, base_dir)
    except ValueError:
        rel = a.script
    return {
        "id": a.id,
        "name": a.name,
        "script": rel,
        "port": a.port,
        "autostart": a.autostart,
        "orchestrator_gradio_port": a.orchestrator_gradio_port,
    }


def _dict_to_agent(d: dict, base_dir: str) -> AgentEntry:
    script = d.get("script", "")
    if script and not os.path.isabs(script):
        script = os.path.normpath(os.path.join(base_dir, script))
    return AgentEntry(
        id=d.get("id") or str(uuid.uuid4())[:8],
        name=d.get("name") or Path(script).stem,
        script=script,
        port=int(d.get("port") or 8000),
        autostart=bool(d.get("autostart", False)),
        orchestrator_gradio_port=(
            int(d["orchestrator_gradio_port"])
            if d.get("orchestrator_gradio_port") else None),
    )


def save_team(name: str) -> str:
    path = _team_path(name)
    base_dir = os.path.dirname(path)
    payload = {
        "version": TEAM_VERSION,
        "name": name or os.path.basename(path),
        "saved_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "agents": [_agent_to_dict(a, base_dir) for a in _manager.list()],
    }
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def load_team(name: str, *, autostart: bool = False) -> int:
    path = _team_path(name)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        payload = _json.load(f)
    if payload.get("version") != TEAM_VERSION:
        raise ValueError(
            f"unsupported team version: {payload.get('version')}")

    base_dir = os.path.dirname(path)
    loaded = 0
    to_start: List[str] = []

    with _manager._lock:
        for d in payload.get("agents", []):
            try:
                entry = _dict_to_agent(d, base_dir)
            except Exception:
                continue
            existing = _manager.agents.get(entry.id)
            if existing is not None:
                existing.name = entry.name
                existing.script = entry.script
                existing.autostart = entry.autostart
                existing.orchestrator_gradio_port = entry.orchestrator_gradio_port
                if existing.port != entry.port and _is_port_free(entry.port):
                    if existing.is_alive():
                        _manager._stop_process(existing)
                    existing.port = entry.port
                    existing.url = f"http://127.0.0.1:{entry.port}"
                    existing.status = "stopped"
            else:
                _manager.agents[entry.id] = entry
                loaded += 1
            if entry.autostart:
                to_start.append(entry.id)

    if autostart:
        for aid in to_start:
            _manager.start(aid)
    return loaded


# ============================================================================
# Rendering helpers
# ============================================================================
def _fmt_uptime(sec: float) -> str:
    if sec <= 0:
        return "—"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _sparkline(history: List[int]) -> str:
    if not history:
        return ""
    w = max(60, len(history) * 4)
    h = 22
    pad = 2
    step = (w - 2 * pad) / max(1, len(history) - 1)
    pts = [
        f"{pad + i * step:.1f},{h - pad - v * (h - 2 * pad):.1f}"
        for i, v in enumerate(history)
    ]
    color = "#238636" if history[-1] == 1 else "#d73a49"
    return (
        f'<svg class="sparkline" viewBox="0 0 {w} {h}" '
        f'preserveAspectRatio="none">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" '
        f'points="{" ".join(pts)}"/></svg>'
    )


def _card_html(a: AgentEntry, lang: str) -> str:
    status_key = {
        "online": "online",
        "offline": "offline",
        "starting": "starting",
        "stopped": "stopped",
        "error": "error_status",
    }.get(a.status, "stopped")
    badge_text = t(lang, status_key)

    open_html = (
        f'<a class="open-btn" href="{_esc(a.url)}" target="_blank" '
        f'rel="noopener">{t(lang, "open_ui")} ↗</a>'
        if a.status == "online" else
        f'<button class="compact-btn" disabled '
        f'style="opacity:.4">{t(lang, "open_ui")}</button>'
    )

    orch_html = ""
    if a.orchestrator_gradio_port and a.status == "online":
        orch_url = f"http://127.0.0.1:{a.orchestrator_gradio_port}/"
        orch_html = (
            f'<a class="open-btn orch" href="{_esc(orch_url)}" '
            f'target="_blank" rel="noopener">'
            f'🎛 {t(lang, "open_orchestrator")} ↗</a>'
        )

    error_html = (
        f'<div class="kv"><span class="k">{t(lang, "error")}</span>'
        f'<span class="v" style="color:#ff7b72">{_esc(a.error)}</span></div>'
        if a.error else ""
    )
    kb_html = (
        f'<div class="kv"><span class="k">{t(lang, "kb")}</span>'
        f'<span class="v">{_esc(a.kb_file)}</span></div>'
        if a.kb_file else ""
    )
    ratio = (
        f"{sum(a.history[-20:])}/{len(a.history[-20:])}"
        if a.history else "—"
    )
    autostart_checked = "checked" if a.autostart else ""

    prompt_text = t(
        lang, "change_port_prompt", name=a.name, current=a.port)
    confirm_text = t(lang, "confirm_remove", name=a.name)

    return f"""
<div class="card {a.status}">
  <div class="card-head">
    <div>
      <div class="card-title">{_esc(a.name)}</div>
      <div class="card-sub">{_esc(a.url)}</div>
    </div>
    <span class="badge {a.status}">{badge_text}</span>
  </div>
  <div class="card-body">
    <div class="kv"><span class="k">{t(lang, "uptime")}</span>
      <span class="v">{_fmt_uptime(a.uptime_seconds())}</span></div>
    <div class="kv"><span class="k">{t(lang, "latency")}</span>
      <span class="v">{a.latency_ms:.0f} ms</span></div>
    <div class="kv"><span class="k">{t(lang, "rules")}</span>
      <span class="v">{a.rules}</span></div>
    <div class="kv"><span class="k">{t(lang, "actions")}</span>
      <span class="v">{a.actions}</span></div>
    {kb_html}
    <div class="kv"><span class="k">{t(lang, "availability")}</span>
      <span class="v">{ratio}</span></div>
    {error_html}
    {_sparkline(a.history)}
  </div>
  <div class="card-actions">
    {open_html}
    {orch_html}
    <button class="compact-btn"
            onclick="fetch('/dashboard/start?id={a.id}',{{method:'POST'}}).then(()=>location.reload())">
      ▶ {t(lang, "start")}
    </button>
    <button class="compact-btn"
            onclick="fetch('/dashboard/stop?id={a.id}',{{method:'POST'}}).then(()=>location.reload())">
      ⏹ {t(lang, "stop")}
    </button>
    <button class="compact-btn"
            onclick="fetch('/dashboard/restart?id={a.id}',{{method:'POST'}}).then(()=>location.reload())">
      ↻
    </button>
    <button class="compact-btn"
            onclick="var p=prompt(&quot;{_esc(prompt_text)}&quot;,&quot;{a.port}&quot;); if(!p) return; fetch('/dashboard/change_port?id={a.id}&port='+encodeURIComponent(p.trim()),{{method:'POST'}}).then(r=>r.json()).then(d=>{{if(d.status!=='ok')alert(d.error||'?'); location.reload();}});">
      ⚙ {a.port}
    </button>
    <button class="compact-btn"
            onclick="if(confirm(&quot;{_esc(confirm_text)}&quot;)) fetch('/dashboard/remove?id={a.id}',{{method:'POST'}}).then(()=>location.reload())">
      🗑
    </button>
    <label class="compact-lbl" style="display:flex;align-items:center;gap:4px;">
      <input type="checkbox" {autostart_checked}
             onchange="fetch('/dashboard/autostart?id={a.id}&value='+(this.checked?1:0),{{method:'POST'}})">
      {t(lang, "autostart")}
    </label>
  </div>
</div>
"""


def _render_cards(lang: str) -> str:
    agents = _manager.list()
    if not agents:
        return (
            f'<div class="empty-state">'
            f'{t(lang, "empty_state")}<br><br>'
            f'{t(lang, "empty_hint")}'
            f'</div>'
        )
    return (
        '<div class="dash-grid">'
        + "".join(_card_html(a, lang) for a in agents)
        + '</div>'
    )


def _render_summary_chart(lang: str) -> str:
    agents = _manager.list()
    total = len(agents) or 1
    counts = {
        "online": sum(1 for a in agents if a.status == "online"),
        "starting": sum(1 for a in agents if a.status == "starting"),
        "offline": sum(1 for a in agents if a.status in ("offline", "error")),
        "stopped": sum(1 for a in agents if a.status == "stopped"),
    }
    colors = {
        "online": "#238636",
        "starting": "#d29922",
        "offline": "#d73a49",
        "stopped": "#484f58",
    }
    rows = []
    for key in ("online", "starting", "offline", "stopped"):
        pct = counts[key] / total * 100
        rows.append(
            f'<div style="display:flex;gap:8px;align-items:center;'
            f'margin:4px 0;font-size:12px;">'
            f'<span style="width:110px;color:#8b949e">'
            f'{t(lang, key)}</span>'
            f'<div style="flex:1;height:6px;background:#21262d;'
            f'border-radius:3px;overflow:hidden;">'
            f'<div style="width:{pct:.1f}%;height:100%;'
            f'background:{colors[key]}"></div></div>'
            f'<span style="width:32px;text-align:right;color:#c7cbd1">'
            f'{counts[key]}</span></div>'
        )
    return (
        '<div style="padding:8px;background:#0f1115;'
        'border:1px solid #2a313d;border-radius:6px;">'
        + "".join(rows)
        + "</div>"
    )


def _status_dict(lang: str) -> dict:
    agents = _manager.list()
    return {
        t(lang, "status_total"): len(agents),
        t(lang, "status_online"): sum(
            1 for a in agents if a.status == "online"),
        t(lang, "status_offline"): sum(
            1 for a in agents if a.status in ("offline", "error")),
        t(lang, "status_stopped"): sum(
            1 for a in agents if a.status == "stopped"),
    }


# ============================================================================
# HTTP endpoints
# ============================================================================
def _attach_dashboard_routes(app):
    from fastapi import Request

    @app.post("/dashboard/start")
    async def dash_start(request: Request):
        _manager.start(request.query_params.get("id"))
        return {"status": "ok"}

    @app.post("/dashboard/stop")
    async def dash_stop(request: Request):
        _manager.stop(request.query_params.get("id"))
        return {"status": "ok"}

    @app.post("/dashboard/restart")
    async def dash_restart(request: Request):
        _manager.restart(request.query_params.get("id"))
        return {"status": "ok"}

    @app.post("/dashboard/remove")
    async def dash_remove(request: Request):
        _manager.remove(request.query_params.get("id"))
        return {"status": "ok"}

    @app.post("/dashboard/change_port")
    async def dash_change_port(request: Request):
        try:
            _manager.change_port(
                request.query_params.get("id"),
                int(request.query_params.get("port")))
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @app.post("/dashboard/autostart")
    async def dash_autostart(request: Request):
        val = request.query_params.get("value") in ("1", "true", "True")
        _manager.set_autostart(request.query_params.get("id"), val)
        return {"status": "ok"}

    @app.get("/dashboard/teams")
    async def dash_teams():
        return {"teams": _list_teams()}

    @app.post("/dashboard/teams/save")
    async def dash_team_save(request: Request):
        body = await request.json()
        try:
            path = save_team(body.get("name") or "")
            return {"status": "ok", "path": path}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @app.post("/dashboard/teams/load")
    async def dash_team_load(request: Request):
        body = await request.json()
        try:
            n = load_team(body.get("name") or "",
                          autostart=bool(body.get("autostart", False)))
            return {"status": "ok", "loaded": n}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @app.post("/dashboard/teams/delete")
    async def dash_team_delete(request: Request):
        body = await request.json()
        try:
            path = _team_path(body.get("name") or "")
            if os.path.isfile(path):
                os.remove(path)
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "error": str(e)}


# ============================================================================
# UI
# ============================================================================
def build_ui() -> gr.Blocks:
    _blocks_kwargs = {"title": "Fona Dashboard"}
    if not _IS_GRADIO6:
        _blocks_kwargs["css"] = _GLOBAL_CSS
        _blocks_kwargs["head"] = _HEAD_DARK

    with gr.Blocks(**_blocks_kwargs) as demo:
        lang_state = gr.State("en")
        selected_id = gr.State(None)

        # ---------- Language switcher ----------
        with gr.Row(equal_height=True):
            lang_dropdown = gr.Dropdown(
                choices=[("English", "en"), ("Русский", "ru")],
                value="en",
                label="🌐",
                scale=0, min_width=130,
            )
            gr.HTML('<div style="flex:1"></div>')

        # ---------- Team ----------
        with gr.Accordion("👥 Team - save / load", open=False) as team_acc:
            with gr.Row(equal_height=True):
                team_dropdown = gr.Dropdown(
                    choices=_list_teams(),
                    label="Saved teams",
                    scale=4, allow_custom_value=True,
                    elem_classes=["compact-tb"],
                )
                team_refresh = gr.Button(
                    "🔄", size="sm", scale=0, min_width=0,
                    elem_classes=["compact-btn"])
                team_name_input = gr.Textbox(
                    placeholder="New team name (no extension)",
                    show_label=False, scale=3,
                    elem_classes=["compact-tb"],
                )
                team_save_btn = gr.Button(
                    "💾 Save as", size="sm", variant="primary", scale=1,
                    elem_classes=["compact-btn"])
            with gr.Row(equal_height=True):
                team_autostart = gr.Checkbox(
                    label="Start all on load (autostart flag)",
                    value=False, scale=3,
                    elem_classes=["compact-lbl"])
                team_load_btn = gr.Button(
                    "📂 Load", size="sm", scale=1,
                    elem_classes=["compact-btn"])
                team_load_start_btn = gr.Button(
                    "▶ Load and start", size="sm", variant="primary", scale=2,
                    elem_classes=["compact-btn"])
                team_delete_btn = gr.Button(
                    "🗑 Delete", size="sm", scale=1,
                    elem_classes=["compact-btn"])
            team_status = gr.HTML(_status_html(""))

        # ---------- Main two-column layout ----------
        with gr.Row(equal_height=False):
            with gr.Column(scale=4):
                with gr.Row(equal_height=True):
                    agents_header = gr.HTML(
                        '<div class="col-head">📊 Agents</div>')
                    refresh_btn = gr.Button(
                        "🔄", size="sm", scale=0, min_width=0,
                        elem_classes=["compact-btn"])

                summary_json = gr.JSON(show_label=False, value={})
                cards_html = gr.HTML(_render_cards("en"))

                with gr.Accordion("➕ Add Agent", open=False) as add_acc:
                    with gr.Row():
                        new_script = gr.Textbox(
                            placeholder="examples/demo_agent.py",
                            label="Script", scale=4,
                            elem_classes=["compact-tb"])
                        new_port = gr.Number(
                            value=8000, label="Port",
                            precision=0, scale=1)
                        new_orch_port = gr.Number(
                            value=None, label="Orchestrator port (optional)",
                            precision=0, scale=1)
                    with gr.Row():
                        new_name = gr.Textbox(
                            placeholder="Name (optional)",
                            label="Name", scale=3,
                            elem_classes=["compact-tb"])
                        add_btn = gr.Button(
                            "➕ Add", size="sm", variant="primary",
                            scale=1, elem_classes=["compact-btn"])
                    add_status = gr.HTML(_status_html(""))

            with gr.Column(scale=2):
                summary_head = gr.HTML('<div class="col-head">📈 Summary</div>')
                summary_chart = gr.HTML(_render_summary_chart("en"))

                log_head = gr.HTML('<div class="col-head">📋 Action Log</div>')
                action_log = gr.Textbox(
                    show_label=False, lines=20, interactive=False,
                    elem_classes=["compact-tb"])

        # ============================================================
        # Timer
        # ============================================================
        timer = gr.Timer(2.0)

        # ============================================================
        # Language change handler
        # ============================================================
        def _on_lang_change(choice: str):
            lang = choice or "en"
            return (
                lang,
                gr.update(label=t(lang, "saved_teams")),
                gr.update(placeholder=t(lang, "team_name")),
                gr.update(value=f"💾 {t(lang, 'save_as')}"),
                gr.update(label=t(lang, "autostart_all")),
                gr.update(value=f"📂 {t(lang, 'load')}"),
                gr.update(value=f"▶ {t(lang, 'load_and_start')}"),
                gr.update(value=f"🗑 {t(lang, 'delete')}"),
                gr.update(value=f'<div class="col-head">'
                                f'📊 {t(lang, "agents")}</div>'),
                gr.update(label=f"➕ {t(lang, 'add_agent')}"),
                gr.update(label=t(lang, "script"),
                          placeholder=t(lang, "script_placeholder")),
                gr.update(label=t(lang, "port")),
                gr.update(label=t(lang, "orch_port_optional")),
                gr.update(label=t(lang, "name_optional"),
                          placeholder=t(lang, "name_placeholder")),
                gr.update(value=f"➕ {t(lang, 'add')}"),
                gr.update(value=f'<div class="col-head">'
                                f'📈 {t(lang, "summary")}</div>'),
                gr.update(value=f'<div class="col-head">'
                                f'📋 {t(lang, "action_log")}</div>'),
                _render_cards(lang),
                _render_summary_chart(lang),
                _status_dict(lang),
            )

        lang_dropdown.change(
            _on_lang_change,
            [lang_dropdown],
            [lang_state,
             team_dropdown, team_name_input, team_save_btn,
             team_autostart, team_load_btn, team_load_start_btn,
             team_delete_btn,
             agents_header, add_acc, new_script, new_port,
             new_orch_port, new_name, add_btn,
             summary_head, log_head,
             cards_html, summary_chart, summary_json],
        )

        # ============================================================
        # Refresh handler
        # ============================================================
        def _refresh(lang):
            for a in _manager.list():
                _manager.poll(a.id)
            return (
                _render_cards(lang),
                _status_dict(lang),
                _render_summary_chart(lang),
            )

        timer.tick(
            _refresh, [lang_state],
            [cards_html, summary_json, summary_chart])
        refresh_btn.click(
            _refresh, [lang_state],
            [cards_html, summary_json, summary_chart])

        # ============================================================
        # Add agent
        # ============================================================
        def _add(lang, script, port, orch_port, name):
            try:
                script = (script or "").strip()
                if not script:
                    return _status_html("✗ " + t(lang, "script"))
                if not os.path.isfile(script):
                    return _status_html(
                        f"✗ {t(lang, 'script_missing', path=script)}")
                entry = _manager.add(
                    script, name or "",
                    int(port) if port else 8000,
                    int(orch_port) if orch_port else None,
                )
                return _status_html(
                    f"✓ {entry.name} → {entry.url}")
            except Exception as e:
                return _status_html(f"✗ {e}")

        add_btn.click(
            _add, [lang_state, new_script, new_port, new_orch_port, new_name],
            [add_status],
        ).then(
            _refresh, [lang_state],
            [cards_html, summary_json, summary_chart],
        )

        # ============================================================
        # Team handlers
        # ============================================================
        def _refresh_teams():
            names = _list_teams()
            return gr.update(choices=names,
                             value=names[0] if names else None)

        team_refresh.click(_refresh_teams, [], [team_dropdown])

        def _do_save(lang, name):
            try:
                path = save_team(name or "")
                return (_status_html(
                    f"✓ {os.path.basename(path)}: "
                    f"{len(_manager.list())} agents"),
                    _refresh_teams())
            except Exception as e:
                return _status_html(f"✗ {e}"), _refresh_teams()

        team_save_btn.click(
            _do_save, [lang_state, team_name_input],
            [team_status, team_dropdown])

        def _do_load(lang, name, do_start):
            try:
                n = load_team(name or "", autostart=bool(do_start))
                return (
                    _status_html(f"✓ {name}: +{n}"),
                    _render_cards(lang),
                    _status_dict(lang),
                )
            except Exception as e:
                return (_status_html(f"✗ {e}"),
                        _render_cards(lang),
                        _status_dict(lang))

        team_load_btn.click(
            _do_load, [lang_state, team_dropdown, team_autostart],
            [team_status, cards_html, summary_json])

        team_load_start_btn.click(
            lambda lang, name: _do_load(lang, name, True),
            [lang_state, team_dropdown],
            [team_status, cards_html, summary_json])

        def _do_delete(lang, name):
            try:
                path = _team_path(name or "")
                if os.path.isfile(path):
                    os.remove(path)
                return _status_html(f"✓ {name}"), _refresh_teams()
            except Exception as e:
                return _status_html(f"✗ {e}"), _refresh_teams()

        team_delete_btn.click(
            _do_delete, [lang_state, team_dropdown],
            [team_status, team_dropdown])

        return demo


# ============================================================================
# Launch
# ============================================================================
def launch(host: str = "127.0.0.1",
           port: int = 7861,
           inbrowser: bool = True,
           share: bool = False,
           **kwargs) -> None:
    ui = build_ui()

    launch_kwargs = dict(
        server_name=host, server_port=port,
        inbrowser=inbrowser, share=share,
    )

    favicon = _ensure_favicon()
    if favicon:
        launch_kwargs["favicon_path"] = favicon

    if _IS_GRADIO6:
        head = _HEAD_DARK
        if favicon:
            head += f'<link rel="icon" href="/favicon.ico?v={int(_t.time())}">'
        launch_kwargs["css"] = _GLOBAL_CSS
        launch_kwargs["head"] = head

    launch_kwargs.update(kwargs)
    app = ui.launch(**launch_kwargs, prevent_thread_lock=True)
    if hasattr(app, "routes"):
        _attach_dashboard_routes(app)

    try:
        while True:
            _t.sleep(1)
    except KeyboardInterrupt:
        pass


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="fona-dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--share", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    launch(host=args.host, port=args.port,
           share=args.share, inbrowser=not args.no_browser)


if __name__ == "__main__":
    main()