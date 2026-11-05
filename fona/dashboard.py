"""Fona Dashboard — manage and monitor background agents.

Features:
  * add/remove agents (file picker, drag-drop, or manual path)
  * start/stop/restart, change port with live validation
  * live status cards: uptime, latency, rules, actions, sparkline
  * team save/load (JSON); per-agent `autostart` flag decides who
    starts when the team is loaded via "Load and start"
  * action log of all dashboard operations
  * i18n: English / Russian switchable at runtime
  * Language is auto-detected at startup:
    - FONA_DASHBOARD_LANG  override (en / ru)
    - locale.getlocale()
    - LANG / LC_ALL / LANGUAGE / LC_MESSAGES
    - GetUserDefaultUILanguage() on Windows
    - fallback: en
  * stdout/stderr are written to logs/<agent_id>.{out,err}.log
  * on crash, the real stderr tail is shown in the card (no hiding)
  * the actual uvicorn port is auto-detected from the child's stdout
    and the card self-corrects if the script hardcodes a different port
  * children are tracked in logs/children.json; orphans from a previous
    dashboard run are killed automatically on startup; a graceful
    shutdown (Ctrl+C) kills the ones we started

Run:
    python -m fona.dashboard
    fona-dashboard --port 7861
    FONA_DASHBOARD_LANG=ru python -m fona.dashboard --port 7861
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json as _json
import locale as _locale
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time as _t
import uuid
from dataclasses import dataclass, field
from html import escape as _esc
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import gradio as gr
import httpx

from fastapi import Request
from fastapi.responses import PlainTextResponse

# ============================================================================
# i18n
# ============================================================================
TRANSLATIONS = {
    "en": {
        "title": "Fona Dashboard",
        "agents": "Agents", "summary": "Summary",
        "add_agent": "Add Agent", "action_log": "Action Log",
        "team": "Team", "script": "Script",
        "script_placeholder": "examples/demo_agent.py",
        "select_script": "Script file (drag or click)",
        "manual_path": "or paste absolute path",
        "port": "Port", "port_placeholder": "8000",
        "name_optional": "Name (optional)", "name_placeholder": "my-agent",
        "orch_port_optional": "Orchestrator port (opt)",
        "orch_port_placeholder": "8010",
        "add": "Add",
        "start": "Start", "stop": "Stop", "restart": "Restart", "remove": "Remove",
        "open_ui": "Open UI", "open_orchestrator": "Orchestrator",
        "uptime": "uptime", "latency": "latency", "rules": "rules",
        "actions": "actions", "availability": "availability", "kb": "KB",
        "error": "error", "autostart": "autostart",
        "online": "ONLINE", "offline": "OFFLINE",
        "starting": "STARTING", "stopped": "STOPPED", "error_status": "ERROR",
        "save_load": "Save / Load", "saved_teams": "Saved teams",
        "team_name": "New team name (no extension)",
        "save_as": "Save as", "load": "Load",
        "load_and_start": "Load and start", "delete": "Delete",
        "load_hint": ("Load registers agents only. "
                      "Load and start also launches agents whose "
                      "per-card autostart flag is checked."),
        "empty_state": "No agents. Add a script in the panel on the left.",
        "empty_hint": "Example: examples/demo_agent.py, port 8000",
        "change_port_prompt": "New port for {name} (current {current}):",
        "confirm_remove": "Remove {name}?",
        "not_found": "not found",
        "port_conflict": "Port {port} is already used by {name}",
        "port_busy": "Port {port} is already in use by another process",
        "port_invalid": "Port must be 1..65535",
        "script_missing": "Script not found: {path}",
        "script_copied": "Script copied to agents/ folder",
        "no_script": "No script provided",
        "logs": "Logs",
        "status_total": "total", "status_online": "online",
        "status_offline": "offline", "status_stopped": "stopped",
        "status_starting": "starting",
        "log_added": "Added {name} \u2192 {url}",
        "log_started": "Started {name}",
        "log_adopted": "Adopted running process for {name} on port {port}",
        "log_recovered": "Recovered {name}: process exit was transient, "
                         "port {port} is serving",
        "log_start_failed": "Failed to start {name}: {reason}",
        "log_stopped": "Stopped {name}",
        "log_restarted": "Restarted {name}",
        "log_removed": "Removed {name}",
        "log_port_changed": "Changed port of {name} to {port}",
        "log_team_saved": "Saved team {name}",
        "log_team_loaded": "Loaded team {name} (+{n})",
        "log_team_loaded_started": ("Loaded team {name} (+{n}); "
                                    "started {started} flagged agent(s)"),
        "log_team_deleted": "Deleted team {name}",
        "log_killed_stale": "Killed stale python process {pid} on port {port}",
    },
    "ru": {
        "title": "Дашборд Fona",
        "agents": "Агенты", "summary": "Сводка",
        "add_agent": "Добавить агента", "action_log": "Журнал действий",
        "team": "Команда", "script": "Скрипт",
        "script_placeholder": "examples/demo_agent.py",
        "select_script": "Файл скрипта (перетащите или нажмите)",
        "manual_path": "или вставьте абсолютный путь",
        "port": "Порт", "port_placeholder": "8000",
        "name_optional": "Имя (опционально)", "name_placeholder": "мой-агент",
        "orch_port_optional": "Порт оркестратора (опц)",
        "orch_port_placeholder": "8010",
        "add": "Добавить",
        "start": "Старт", "stop": "Стоп", "restart": "Перезапустить",
        "remove": "Удалить",
        "open_ui": "Открыть UI", "open_orchestrator": "Оркестратор",
        "uptime": "аптайм", "latency": "задержка", "rules": "правил",
        "actions": "действий", "availability": "доступность", "kb": "БЗ",
        "error": "ошибка", "autostart": "автозапуск",
        "online": "ОНЛАЙН", "offline": "ОФЛАЙН",
        "starting": "СТАРТ", "stopped": "СТОП", "error_status": "ОШИБКА",
        "save_load": "Сохранить / Загрузить",
        "saved_teams": "Сохранённые команды",
        "team_name": "Имя новой команды (без расширения)",
        "save_as": "Сохранить как", "load": "Загрузить",
        "load_and_start": "Загрузить и запустить", "delete": "Удалить",
        "load_hint": ("«Загрузить» только регистрирует агентов. "
                      "«Загрузить и запустить» дополнительно запускает "
                      "тех, у кого на карточке отмечен флаг autostart."),
        "empty_state": "Нет агентов. Добавьте скрипт в панели слева.",
        "empty_hint": "Пример: examples/demo_agent.py, порт 8000",
        "change_port_prompt": "Новый порт для {name} (текущий {current}):",
        "confirm_remove": "Удалить {name}?",
        "not_found": "не найден",
        "port_conflict": "Порт {port} уже занят агентом {name}",
        "port_busy": "Порт {port} занят другим процессом на этой машине",
        "port_invalid": "Порт должен быть 1..65535",
        "script_missing": "Скрипт не найден: {path}",
        "script_copied": "Скрипт скопирован в папку agents/",
        "no_script": "Скрипт не указан",
        "logs": "Логи",
        "status_total": "всего", "status_online": "онлайн",
        "status_offline": "офлайн", "status_stopped": "остановлен",
        "status_starting": "стартует",
        "log_added": "Добавлен {name} \u2192 {url}",
        "log_started": "Запущен {name}",
        "log_adopted": "Принят работающий процесс {name} на порту {port}",
        "log_recovered": "Восстановлен {name}: выход процесса был "
                         "кратковременным, порт {port} обслуживается",
        "log_start_failed": "Ошибка запуска {name}: {reason}",
        "log_stopped": "Остановлен {name}",
        "log_restarted": "Перезапущен {name}",
        "log_removed": "Удалён {name}",
        "log_port_changed": "Изменён порт {name} на {port}",
        "log_team_saved": "Сохранена команда {name}",
        "log_team_loaded": "Загружена команда {name} (+{n})",
        "log_team_loaded_started": ("Загружена команда {name} (+{n}); "
                                    "запущено {started} агентов с флагом"),
        "log_team_deleted": "Удалена команда {name}",
        "log_killed_stale": "Убит устаревший python-процесс {pid} на порту {port}",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    table = TRANSLATIONS.get(lang) or TRANSLATIONS["en"]
    template = table.get(key) or TRANSLATIONS["en"].get(key, key)
    return template.format(**kwargs) if kwargs else template


# ============================================================================
# System language detection
# ============================================================================
def _detect_system_lang() -> str:
    override = os.environ.get("FONA_DASHBOARD_LANG", "").strip().lower()
    if override in ("en", "ru"):
        return override

    try:
        loc = (_locale.getlocale()[0] or "").lower()
        if loc.startswith("ru"):
            return "ru"
    except (ValueError, TypeError, AttributeError):
        pass

    for var in ("LANG", "LC_ALL", "LANGUAGE", "LC_MESSAGES"):
        val = os.environ.get(var, "").lower()
        if val.startswith("ru"):
            return "ru"

    if sys.platform == "win32":
        try:
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if (lang_id & 0x3FF) == 0x19:
                return "ru"
        except Exception:
            pass

    return "en"


# ============================================================================
# Gradio 5 / 6 compatibility
# ============================================================================
try:
    _GRADIO_VERSION = tuple(int(x) for x in gr.__version__.split(".")[:2])
except (ValueError, AttributeError):
    _GRADIO_VERSION = (5, 0)
_IS_GRADIO6 = _GRADIO_VERSION >= (6, 0)


# ============================================================================
# PYTHONPATH for children
# ============================================================================
def _python_paths() -> List[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    paths: List[str] = []
    if os.path.isdir(parent):
        paths.append(parent)
    cwd = os.getcwd()
    if os.path.isdir(cwd) and cwd not in paths:
        paths.append(cwd)
    return paths


def _child_env(port: int) -> dict:
    env = os.environ.copy()
    env["FONA_CHILD"] = "1"
    env["FONA_PORT"] = str(port)
    env.pop("WEB_CONCURRENCY", None)
    existing = env.get("PYTHONPATH", "")
    parts = existing.split(os.pathsep) if existing else []
    for p in reversed(_python_paths()):
        if p and p not in parts:
            parts.insert(0, p)
    if parts:
        env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


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
.gradio-container .compact-tb.block,
.gradio-container .compact-tb > .block {
    border: 1px solid #2a313d !important; border-radius: 4px !important;
    background: #0b0d11 !important; box-shadow: none !important;
    padding: 0 !important;
}
.gradio-container .compact-tb .block,
.gradio-container .compact-tb .form,
.gradio-container .compact-tb .wrap,
.gradio-container .compact-tb .secondary-wrap,
.gradio-container .compact-tb .wrap-inner,
.gradio-container .compact-tb .container,
.gradio-container .compact-tb .input-container,
.gradio-container .compact-tb input,
.gradio-container .compact-tb textarea,
.gradio-container .compact-tb select {
    border: 0 !important; background: transparent !important;
    box-shadow: none !important; outline: none !important;
    border-radius: 0 !important;
}
.gradio-container .compact-tb input,
.gradio-container .compact-tb textarea,
.gradio-container .compact-tb select {
    padding: 4px 8px !important; font-size: 12px !important;
    min-height: 28px !important; color: #c7cbd1 !important;
}
.gradio-container .compact-tb > label,
.gradio-container .compact-tb .label-wrap {
    padding: 2px 8px 0 8px !important; font-size: 11px !important;
    color: #8b949e !important;
}
.gradio-container .compact-tb.block:focus-within,
.gradio-container .compact-tb > .block:focus-within {
    border-color: #58a6ff !important;
    box-shadow: 0 0 0 2px rgba(88,166,255,.2) !important;
}
.gradio-container .compact-file,
.gradio-container .compact-file > div,
.gradio-container .compact-file .wrap,
.gradio-container .compact-file .file-preview,
.gradio-container .compact-file .upload-button {
    background: #0b0d11 !important; border-color: #3a4250 !important;
    color: #c7cbd1 !important; font-size: 12px !important;
    border-radius: 4px !important;
}
.gradio-container .compact-file {
    border: 1px dashed #3a4250 !important; min-height: 60px !important;
    padding: 4px !important;
}
.gradio-container .compact-file:hover { border-color: #58a6ff !important; }
.gradio-container .compact-file .file-preview .wrap,
.gradio-container .compact-file .file-preview > span,
.gradio-container .compact-file .file-preview .upload-text,
.gradio-container .compact-file .file-preview .upload-button {
    color: transparent !important; font-size: 0 !important;
    line-height: 0 !important;
}
.gradio-container .compact-file .file-preview {
    display: flex !important; align-items: center; justify-content: center;
    min-height: 64px !important; cursor: pointer; position: relative;
}
.gradio-container .compact-file .file-preview::before {
    content: "\\2B06"; font-size: 22px; color: #4f5866;
    pointer-events: none; user-select: none;
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
    max-height: 120px; overflow: auto;
}
.team-hint {
    font-size: 11px; color: #8b949e; line-height: 1.35;
    padding: 2px 4px; margin: 2px 0 6px 0;
}
*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-thumb { background: #2a313d; border-radius: 5px; }
.dash-grid { display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 12px; padding: 4px; }
.card { background: #0f1115; border: 1px solid #2a313d;
    border-radius: 8px; padding: 12px; display: flex;
    flex-direction: column; gap: 8px;
    transition: border-color .15s, transform .15s; }
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
.kv .v.err { color: #ff7b72; font-family: ui-monospace, monospace;
             font-size: 10px; max-width: 60%; text-align: right;
             overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: auto; }
.card-actions button, .card-actions a { font-size: 11px; padding: 3px 8px; }
.card-actions .open-btn {
    text-decoration: none !important; display: inline-block;
    padding: 3px 10px; background: #238636; color: #fff !important;
    border-radius: 4px; font-size: 11px; border: 1px solid #238636;
}
.card-actions .open-btn:hover { background: #2ea043; }
.card-actions .open-btn.orch { background: #6e40c9; border-color: #6e40c9; }
.card-actions .open-btn.orch:hover { background: #8957e5; }
.card-actions .logs-btn {
    text-decoration: none !important; display: inline-block;
    padding: 3px 8px; background: #21262d; color: #c7cbd1 !important;
    border-radius: 4px; font-size: 11px; border: 1px solid #2a313d;
}
.card-actions .logs-btn:hover { background: #30363d; }
.empty-state { padding: 40px 20px; text-align: center; color: #8b949e;
    border: 1px dashed #2a313d; border-radius: 8px; font-size: 13px; }
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

    window.fonaRefresh = function() {
        var candidates = [
            document.querySelector('#refresh_btn button'),
            document.querySelector('#refresh_btn'),
            document.querySelector('[data-testid="refresh_btn"] button'),
        ];
        for (var i = 0; i < candidates.length; i++) {
            var el = candidates[i];
            if (el && typeof el.click === 'function') {
                el.click();
                return true;
            }
        }
        return false;
    };

    var inflight = {};

    window.dashAction = function(url, opts) {
        opts = opts || {};
        if (opts.confirm && !confirm(opts.confirm)) return;
        if (inflight[url]) return;
        inflight[url] = true;
        var prevCursor = document.body.style.cursor;
        document.body.style.cursor = 'progress';
        fetch(url, {method: 'POST'})
            .then(function(r) {
                if (!r.ok) {
                    return r.text().then(function(body) {
                        throw new Error('HTTP ' + r.status + ': ' +
                            body.slice(0, 200));
                    });
                }
                return r.json().catch(function() { return {}; });
            })
            .then(function(d) {
                if (d && d.error) alert(d.error);
                window.fonaRefresh();
            })
            .catch(function(e) {
                alert('Action failed: ' + e.message);
                window.fonaRefresh();
            })
            .finally(function() {
                delete inflight[url];
                document.body.style.cursor = prevCursor;
            });
    };
})();
</script>
"""


# ============================================================================
# Action log
# ============================================================================
_action_log: List[Tuple[float, str, dict]] = []
_action_log_lock = threading.RLock()


def _log_action(key: str, **kwargs) -> None:
    with _action_log_lock:
        _action_log.append((_t.time(), key, kwargs))
        del _action_log[:-200]


def _get_action_log(lang: str) -> str:
    with _action_log_lock:
        lines = []
        for ts, key, kwargs in _action_log:
            hhmmss = _dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            try:
                msg = t(lang, key, **kwargs)
            except Exception:
                msg = f"{key} {kwargs}"
            lines.append(f"[{hhmmss}] {msg}")
        return "\n".join(lines)


# ============================================================================
# Log files for subprocess stdout/stderr
# ============================================================================
_UVICORN_PORT_RE = re.compile(
    r"Uvicorn running on https?://[^\s]+?:(\d+)"
)


def _logs_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "logs")
    os.makedirs(path, exist_ok=True)
    return path


def _out_log_path(agent_id: str) -> str:
    return os.path.join(_logs_dir(), f"{agent_id}.out.log")


def _err_log_path(agent_id: str) -> str:
    return os.path.join(_logs_dir(), f"{agent_id}.err.log")


def _read_tail(path: str, n: int = 500) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - n * 4))
            data = f.read()
        return data.decode("utf-8", errors="replace")[-n:].strip()
    except Exception:
        return ""


def _read_both_logs(agent_id: str, n: int = 500) -> Tuple[str, str]:
    return (
        _read_tail(_out_log_path(agent_id), n),
        _read_tail(_err_log_path(agent_id), n),
    )


def _detect_uvicorn_port_from_logs(agent_id: str) -> Optional[int]:
    for path in (_out_log_path(agent_id), _err_log_path(agent_id)):
        data = _read_tail(path, 4000)
        m = _UVICORN_PORT_RE.search(data)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


# ============================================================================
# PID/port tracking for child processes
# ============================================================================
def _pid_file() -> str:
    return os.path.join(_logs_dir(), "children.json")


def _load_pid_map() -> Dict[str, Dict[str, int]]:
    try:
        with open(_pid_file(), "r", encoding="utf-8") as f:
            data = _json.load(f)
    except Exception:
        return {}

    result: Dict[str, Dict[str, int]] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            result[str(k)] = {
                "pid": int(v.get("pid", 0) or 0),
                "port": int(v.get("port", 0) or 0),
            }
        else:
            try:
                result[str(k)] = {"pid": int(v), "port": 0}
            except (TypeError, ValueError):
                pass
    return result


def _save_pid_map(m: Dict[str, Dict[str, int]]) -> None:
    try:
        with open(_pid_file(), "w", encoding="utf-8") as f:
            _json.dump(m, f, indent=2)
    except OSError:
        pass


def _is_pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _get_process_image(pid: int) -> str:
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not h:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                        h, 0, buf, ctypes.byref(size)):
                    return os.path.basename(buf.value).lower()
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        else:
            with open(f"/proc/{pid}/comm", "r") as f:
                return f.read().strip().lower()
    except Exception:
        pass
    return ""


def _kill_pid(pid: int) -> None:
    if not pid:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=4)
        except Exception:
            pass
    else:
        for sig in (15, 9):
            try:
                os.kill(pid, sig)
                _t.sleep(0.3)
                if not _is_pid_alive(pid):
                    return
            except OSError:
                return


def _find_pid_by_port(port: int) -> Optional[int]:
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "TCP"],
                timeout=4, text=True, errors="replace")
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3] == "LISTENING":
                    local = parts[1]
                    if local.endswith(f":{port}"):
                        try:
                            return int(parts[4])
                        except ValueError:
                            continue
        else:
            try:
                out = subprocess.check_output(
                    ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-t"],
                    timeout=4, text=True)
            except FileNotFoundError:
                out = subprocess.check_output(
                    ["ss", "-tlnp", f"sport = :{port}"],
                    timeout=4, text=True)
                m = re.search(r"pid=(\d+)", out)
                return int(m.group(1)) if m else None
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    return int(line)
    except Exception:
        pass
    return None


def _kill_python_on_port(port: int) -> Optional[int]:
    if not port:
        return None
    pid = _find_pid_by_port(port)
    if not pid or not _is_pid_alive(pid):
        return None
    image = _get_process_image(pid)
    if image and not image.startswith("python"):
        return None
    print(f"[fona] killing stale pid={pid} on port {port}",
          file=sys.stderr, flush=True)
    _kill_pid(pid)
    return pid


def _kill_orphan_children() -> List[int]:
    pid_map = _load_pid_map()
    if not pid_map:
        return []

    killed: List[int] = []
    seen: set = set()
    for agent_id, info in pid_map.items():
        pid = info.get("pid") or 0
        port = info.get("port") or 0

        if pid and _is_pid_alive(pid) and pid not in seen:
            image = _get_process_image(pid)
            if not image or image.startswith("python"):
                print(f"[fona] killing orphan pid={pid} (agent {agent_id})",
                      file=sys.stderr, flush=True)
                _kill_pid(pid)
                killed.append(pid)
                seen.add(pid)

        if port:
            port_pid = _kill_python_on_port(port)
            if port_pid and port_pid not in seen:
                killed.append(port_pid)
                seen.add(port_pid)

    try:
        os.remove(_pid_file())
    except OSError:
        pass
    return killed


# ============================================================================
# Port detection helpers
# ============================================================================
def _is_port_free(port: int) -> bool:
    """True if we could bind to 127.0.0.1:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if sys.platform != "win32":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.15)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def _health_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        r = httpx.get(f"{url}/api/v1/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


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
    # Time the poll loop first observed the agent in the "starting"
    # state. The "no response > N s" timeout is measured from this
    # moment, NOT from started_at (spawn time). Otherwise a slow
    # sequential "Load and start" of many agents makes the first
    # agents hit the timeout before poll() has even had a chance to
    # check them.
    first_poll_starting_at: float = 0.0
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
def _status_html(s: str) -> str:
    return f'<pre class="status-box">{_esc(str(s))}</pre>'


def _agents_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "agents")
    os.makedirs(path, exist_ok=True)
    return path


def _install_script(src_path: str) -> str:
    dest_dir = _agents_dir()
    basename = os.path.basename(src_path)
    dest = os.path.join(dest_dir, basename)
    counter = 1
    while (os.path.exists(dest)
           and os.path.abspath(src_path) != os.path.abspath(dest)):
        stem, ext = os.path.splitext(basename)
        dest = os.path.join(dest_dir, f"{stem}_{counter}{ext}")
        counter += 1
    if os.path.abspath(src_path) != os.path.abspath(dest):
        shutil.copy2(src_path, dest)
    return dest


def _file_to_path(f) -> Optional[str]:
    if f is None:
        return None
    if isinstance(f, str):
        return f
    if hasattr(f, "name"):
        return f.name
    return None


def _pick_script_dialog() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return ""
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        path = filedialog.askopenfilename(
            title="Select agent script",
            filetypes=[("Python", "*.py"), ("All files", "*.*")],
        )
        root.destroy()
        return path or ""
    except Exception:
        return ""


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
                    raise ValueError(f"port {port} already used by {a.name}")
                if (orch_port is not None
                        and a.orchestrator_gradio_port == int(orch_port)):
                    raise ValueError(
                        f"orchestrator port {orch_port} already used by {a.name}")
            if _is_port_open(int(port)):
                raise ValueError(f"port {port} is in use")
            entry = AgentEntry(
                id=str(uuid.uuid4())[:8],
                name=name or Path(script).stem,
                script=script, port=int(port),
                orchestrator_gradio_port=(
                    int(orch_port) if orch_port else None),
            )
            self.agents[entry.id] = entry
            return entry

    def remove(self, agent_id: str) -> Optional[AgentEntry]:
        with self._lock:
            a = self.agents.pop(agent_id, None)
        if a is not None:
            self._stop_process(a)
            pid_map = _load_pid_map()
            pid_map.pop(agent_id, None)
            _save_pid_map(pid_map)
        return a

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
        if _is_port_open(int(new_port)):
            raise ValueError(f"port {new_port} is in use")
        was_running = a.is_alive()
        if was_running:
            self._stop_process(a)
        a.port = int(new_port)
        a.url = f"http://127.0.0.1:{a.port}"
        a.status = "stopped"; a.error = ""; a.history = []
        a.started_at = 0.0
        a.first_poll_starting_at = 0.0
        if was_running:
            self.start(agent_id)

    def set_autostart(self, agent_id: str, value: bool) -> None:
        a = self.get(agent_id)
        if a is not None:
            a.autostart = bool(value)

    def start(self, agent_id: str) -> None:
        a = self.get(agent_id)
        if a is None:
            print(f"[fona] start: agent {agent_id} not found",
                  file=sys.stderr, flush=True)
            return
        if not os.path.isfile(a.script):
            msg = f"script not found: {a.script}"
            a.status = "error"
            a.error = msg
            print(f"[fona] start failed for {a.name}: {msg}",
                  file=sys.stderr, flush=True)
            _log_action("log_start_failed", name=a.name, reason=msg)
            return
        if a.process is not None and a.process.poll() is None:
            return

        # ---- 1. Adopt or clear the port ----
        deadline = _t.time() + 5.0
        while _t.time() < deadline:
            if _is_port_free(a.port):
                break
            if _health_ok(a.url, timeout=0.8):
                adopted_pid = _find_pid_by_port(a.port) or 0
                a.status = "online"
                a.started_at = _t.time()
                a.first_poll_starting_at = 0.0
                a.error = ""
                a.history = [1]
                if adopted_pid:
                    m = _load_pid_map()
                    m[a.id] = {"pid": adopted_pid, "port": a.port}
                    _save_pid_map(m)
                print(f"[fona] {a.name}: adopted existing process on "
                      f"port {a.port} (pid={adopted_pid})",
                      file=sys.stderr, flush=True)
                _log_action("log_adopted", name=a.name, port=a.port)
                return
            _t.sleep(0.5)

        if not _is_port_free(a.port):
            killed = _kill_python_on_port(a.port)
            if killed:
                _log_action("log_killed_stale", pid=killed, port=a.port)
            for _ in range(20):
                if _is_port_free(a.port):
                    break
                _t.sleep(0.1)

        if not _is_port_free(a.port):
            msg = (f"port {a.port} is still in use after cleanup "
                   f"(waited ~5s)")
            a.status = "error"
            a.error = msg
            print(f"[fona] start failed for {a.name}: {msg}",
                  file=sys.stderr, flush=True)
            _log_action("log_start_failed", name=a.name, reason=msg)
            return

        # ---- 2. Spawn a fresh child ----
        env = _child_env(a.port)
        out_path = _out_log_path(a.id)
        err_path = _err_log_path(a.id)
        for p in (out_path, err_path):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError as e:
                print(f"[fona] cannot remove {p}: {e}",
                      file=sys.stderr, flush=True)

        exe = sys.executable
        if exe.lower().endswith("pythonw.exe"):
            py = exe[:-len("pythonw.exe")] + "python.exe"
            if os.path.exists(py):
                exe = py

        try:
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000)

            outf = open(out_path, "wb")
            errf = open(err_path, "wb")
            try:
                a.process = subprocess.Popen(
                    [exe, "-u", a.script],
                    cwd=os.path.dirname(os.path.abspath(a.script)) or None,
                    env=env,
                    stdout=outf,
                    stderr=errf,
                    **kwargs,
                )
            finally:
                outf.close()
                errf.close()
            a.started_at = _t.time()
            a.first_poll_starting_at = 0.0
            a.status = "starting"
            a.error = ""
            a.history = []
            pid_map = _load_pid_map()
            pid_map[a.id] = {"pid": a.process.pid, "port": a.port}
            _save_pid_map(pid_map)
            print(f"[fona] started {a.name} pid={a.process.pid} "
                  f"port={a.port} script={a.script} "
                  f"PYTHONPATH={env.get('PYTHONPATH', '')}",
                  file=sys.stderr, flush=True)
        except Exception as e:
            a.status = "error"
            a.error = f"{type(e).__name__}: {e}"
            print(f"[fona] Popen failed for {a.name}: {a.error}",
                  file=sys.stderr, flush=True)
            _log_action("log_start_failed", name=a.name, reason=a.error)
            return

        if a.orchestrator_gradio_port and a.orchestrator_process is None:
            try:
                okwargs = {}
                if sys.platform == "win32":
                    okwargs["creationflags"] = 0x08000000
                o_out = open(
                    os.path.join(_logs_dir(), f"{a.id}.orch.out.log"), "wb")
                o_err = open(
                    os.path.join(_logs_dir(), f"{a.id}.orch.err.log"), "wb")
                try:
                    a.orchestrator_process = subprocess.Popen(
                        [exe, "-u", "-m", "fona.orchestrator_app",
                         "--orchestrator", a.url,
                         "--port", str(a.orchestrator_gradio_port),
                         "--no-browser"],
                        env={**os.environ, "FONA_CHILD": "1"},
                        stdout=o_out, stderr=o_err, **okwargs,
                    )
                finally:
                    o_out.close()
                    o_err.close()
            except Exception as e:
                a.error = f"orchestrator spawn failed: {e}"
                print(f"[fona] orchestrator spawn failed for {a.name}: {e}",
                      file=sys.stderr, flush=True)

    def stop(self, agent_id: str) -> None:
        a = self.get(agent_id)
        if a is None:
            return

        if a.process is not None:
            self._stop_process(a)
        else:
            pid_map = _load_pid_map()
            info = pid_map.get(agent_id) or {}
            pid = info.get("pid") or 0
            if not pid:
                pid = _find_pid_by_port(a.port) or 0
            if pid and _is_pid_alive(pid):
                image = _get_process_image(pid)
                if not image or image.startswith("python"):
                    print(f"[fona] stopping adopted pid={pid} "
                          f"(agent {agent_id})",
                          file=sys.stderr, flush=True)
                    _kill_pid(pid)

        for _ in range(20):
            if _is_port_free(a.port):
                break
            _kill_python_on_port(a.port)
            _t.sleep(0.1)

        pid_map = _load_pid_map()
        pid_map.pop(agent_id, None)
        _save_pid_map(pid_map)

        a.status = "stopped"
        a.started_at = 0.0
        a.first_poll_starting_at = 0.0

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
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                        capture_output=True, timeout=4)
                    try:
                        p.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        try:
                            p.kill()
                        except Exception:
                            pass
                else:
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

    def stop_all(self) -> None:
        for a in self.list():
            try:
                self.stop(a.id)
            except Exception:
                pass

    def poll(self, agent_id: str) -> Optional[AgentEntry]:
        a = self.get(agent_id)
        if a is None:
            return None

        # ---- Direct child exited ----
        if a.process is not None and a.process.poll() is not None:
            rc = a.process.returncode
            a.process = None

            # Give the port a moment: uvicorn may be delegated to a
            # worker, or a healthy orphan may already be serving.
            # Retry health for up to ~2s before flagging an error.
            deadline = _t.time() + 2.0
            while _t.time() < deadline:
                if _health_ok(a.url, timeout=0.5):
                    adopted_pid = _find_pid_by_port(a.port) or 0
                    a.status = "online"
                    a.started_at = _t.time()
                    a.first_poll_starting_at = 0.0
                    a.error = ""
                    if adopted_pid:
                        m = _load_pid_map()
                        m[a.id] = {"pid": adopted_pid, "port": a.port}
                        _save_pid_map(m)
                    print(f"[fona] {a.name}: child exited rc={rc} but "
                          f"port {a.port} is serving (pid={adopted_pid}); "
                          f"adopted", file=sys.stderr, flush=True)
                    _log_action("log_recovered", name=a.name, port=a.port)
                    a.history.append(1)
                    a.history = a.history[-40:]
                    return a
                _t.sleep(0.2)

            if rc not in (0, None):
                out_tail, err_tail = _read_both_logs(a.id, 800)
                combined = (err_tail or out_tail or "").strip()
                compact = " | ".join(
                    line.strip() for line in combined.splitlines()
                    if line.strip()
                ) if combined else ""
                a.status = "error"
                a.error = (f"exit {rc}: {compact[:400]}" if compact
                           else f"process exited with code {rc}")
                print(f"[fona] {a.name} exited rc={rc}: "
                      f"{compact[:300]}", file=sys.stderr, flush=True)
                a.history.append(0)
                a.history = a.history[-40:]
                return a
            # rc == 0: fall through to normal health path.

        # ---- Health check ----
        t0 = _t.time()
        ok = _health_ok(a.url, timeout=1.0)
        a.latency_ms = (_t.time() - t0) * 1000.0

        if not ok and a.status in ("starting", "offline", "error"):
            detected = _detect_uvicorn_port_from_logs(a.id)
            if detected is not None and detected != a.port:
                old_port = a.port
                a.port = detected
                a.url = f"http://127.0.0.1:{detected}"
                if _health_ok(a.url, timeout=1.0):
                    ok = True
                    a.error = (f"port auto-corrected: {old_port} \u2192 "
                               f"{detected} (script ignores FONA_PORT)")
                    print(f"[fona] {a.name}: port auto-corrected "
                          f"{old_port} -> {detected}",
                          file=sys.stderr, flush=True)

        if ok:
            a.status = "online"
            a.first_poll_starting_at = 0.0
            if not a.error.startswith("port auto-corrected"):
                a.error = ""
            try:
                mr = httpx.get(f"{a.url}/api/v1/model", timeout=1.0)
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
                a.first_poll_starting_at = 0.0
            elif a.status == "starting":
                # Timeout counts from the first poll that saw this
                # agent in "starting", NOT from spawn time. This makes
                # sequential "Load and start" of many agents immune
                # to the first agents hitting the timeout before
                # poll() has had a chance to check them.
                if a.first_poll_starting_at == 0.0:
                    a.first_poll_starting_at = _t.time()
                elapsed = _t.time() - a.first_poll_starting_at
                if elapsed > 25.0:
                    a.status = "error"
                    # Diagnostics: child alive? listener present?
                    child_alive = (a.process is not None
                                   and a.process.poll() is None)
                    listener_pid = _find_pid_by_port(a.port) or 0
                    out_tail, err_tail = _read_both_logs(a.id, 400)
                    combined = (err_tail or out_tail or "").strip()
                    compact = " | ".join(
                        line.strip() for line in combined.splitlines()
                        if line.strip()
                    ) if combined else ""
                    diag = (f"child_alive={child_alive}, "
                            f"listener_pid={listener_pid}")
                    a.error = (f"no response > 25s ({diag}): "
                               f"{compact[:300]}" if compact
                               else f"no response > 25s ({diag})")
                    print(f"[fona] {a.name}: {a.error}",
                          file=sys.stderr, flush=True)

        a.history.append(1 if ok else 0)
        a.history = a.history[-40:]
        return a


_manager = AgentManager()


# ============================================================================
# Team save/load
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
    return sorted(os.path.splitext(f)[0]
                  for f in os.listdir(d) if f.endswith(".json"))


def _agent_to_dict(a: AgentEntry, base_dir: str) -> dict:
    try:
        rel = os.path.relpath(a.script, base_dir)
    except ValueError:
        rel = a.script
    return {
        "id": a.id, "name": a.name, "script": rel,
        "port": a.port, "autostart": a.autostart,
        "orchestrator_gradio_port": a.orchestrator_gradio_port,
    }


def _dict_to_agent(d: dict, base_dir: str) -> AgentEntry:
    script = d.get("script", "")
    if script and not os.path.isabs(script):
        script = os.path.normpath(os.path.join(base_dir, script))
    return AgentEntry(
        id=d.get("id") or str(uuid.uuid4())[:8],
        name=d.get("name") or Path(script).stem,
        script=script, port=int(d.get("port") or 8000),
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


def load_team(name: str, *, start_flagged: bool = False) -> Tuple[int, int]:
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
    flagged_ids: List[str] = []

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
                    existing.first_poll_starting_at = 0.0
            else:
                _manager.agents[entry.id] = entry
                loaded += 1
            if entry.autostart:
                flagged_ids.append(entry.id)

    started = 0
    if start_flagged:
        for aid in flagged_ids:
            _manager.start(aid)
            started += 1
    return loaded, started


# ============================================================================
# Rendering
# ============================================================================
def _fmt_uptime(sec: float) -> str:
    if sec <= 0:
        return "\u2014"
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
    w = max(60, len(history) * 4); h = 22; pad = 2
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
        "online": "online", "offline": "offline",
        "starting": "starting", "stopped": "stopped",
        "error": "error_status",
    }.get(a.status, "stopped")
    badge_text = t(lang, status_key)
    open_html = (
        f'<a class="open-btn" href="{_esc(a.url)}" target="_blank" '
        f'rel="noopener">{t(lang, "open_ui")} \u2197</a>'
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
            f'\U0001f39b {t(lang, "open_orchestrator")} \u2197</a>'
        )
    logs_html = (
        f'<a class="logs-btn" href="/dashboard/logs?id={a.id}&kind=err" '
        f'target="_blank" rel="noopener" title="stderr log">'
        f'\U0001f4c4 {t(lang, "logs")}</a>'
    )
    error_html = (
        f'<div class="kv"><span class="k">{t(lang, "error")}</span>'
        f'<span class="v err" title="{_esc(a.error)}">{_esc(a.error)}</span>'
        f'</div>'
        if a.error else ""
    )
    kb_html = (
        f'<div class="kv"><span class="k">{t(lang, "kb")}</span>'
        f'<span class="v">{_esc(a.kb_file)}</span></div>'
        if a.kb_file else ""
    )
    ratio = (f"{sum(a.history[-20:])}/{len(a.history[-20:])}"
             if a.history else "\u2014")
    autostart_checked = "checked" if a.autostart else ""
    prompt_text = t(lang, "change_port_prompt",
                    name=a.name, current=a.port)
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
    {logs_html}
    <button class="compact-btn"
            onclick="dashAction('/dashboard/start?id={a.id}')">
      \u25b6 {t(lang, "start")}
    </button>
    <button class="compact-btn"
            onclick="dashAction('/dashboard/stop?id={a.id}')">
      \u23f9 {t(lang, "stop")}
    </button>
    <button class="compact-btn"
            onclick="dashAction('/dashboard/restart?id={a.id}')">
      \u21bb
    </button>
    <button class="compact-btn"
            onclick="var p=prompt(&quot;{_esc(prompt_text)}&quot;,&quot;{a.port}&quot;); if(!p) return; dashAction('/dashboard/change_port?id={a.id}&port='+encodeURIComponent(p.trim()));">
      \u2699 {a.port}
    </button>
    <button class="compact-btn"
            onclick="dashAction('/dashboard/remove?id={a.id}', {{confirm: &quot;{_esc(confirm_text)}&quot;}})">
      \U0001f5d1
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
    return ('<div class="dash-grid">'
            + "".join(_card_html(a, lang) for a in agents)
            + '</div>')


def _render_summary_chart(lang: str) -> str:
    agents = _manager.list()
    total = len(agents) or 1
    counts = {
        "online": sum(1 for a in agents if a.status == "online"),
        "starting": sum(1 for a in agents if a.status == "starting"),
        "offline": sum(1 for a in agents if a.status in ("offline", "error")),
        "stopped": sum(1 for a in agents if a.status == "stopped"),
    }
    colors = {"online": "#238636", "starting": "#d29922",
              "offline": "#d73a49", "stopped": "#484f58"}
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
    return ('<div style="padding:8px;background:#0f1115;'
            'border:1px solid #2a313d;border-radius:6px;">'
            + "".join(rows) + "</div>")


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

    @app.post("/dashboard/start")
    async def dash_start(request: Request):
        aid = request.query_params.get("id")
        _manager.start(aid)
        a = _manager.get(aid)
        if a is not None and a.status != "error":
            _log_action("log_started", name=a.name)
        elif a is not None:
            _log_action("log_start_failed", name=a.name, reason=a.error)
        return {"status": "ok",
                "status_after": a.status if a else None,
                "error": a.error if a else None}

    @app.post("/dashboard/stop")
    async def dash_stop(request: Request):
        aid = request.query_params.get("id")
        a = _manager.get(aid)
        _manager.stop(aid)
        if a is not None:
            _log_action("log_stopped", name=a.name)
        return {"status": "ok"}

    @app.post("/dashboard/restart")
    async def dash_restart(request: Request):
        aid = request.query_params.get("id")
        a = _manager.get(aid)
        _manager.restart(aid)
        if a is not None:
            _log_action("log_restarted", name=a.name)
        return {"status": "ok"}

    @app.post("/dashboard/remove")
    async def dash_remove(request: Request):
        aid = request.query_params.get("id")
        a = _manager.remove(aid)
        if a is not None:
            _log_action("log_removed", name=a.name)
        return {"status": "ok"}

    @app.post("/dashboard/change_port")
    async def dash_change_port(request: Request):
        try:
            aid = request.query_params.get("id")
            new_port = int(request.query_params.get("port"))
            a = _manager.get(aid)
            _manager.change_port(aid, new_port)
            if a is not None:
                _log_action("log_port_changed", name=a.name, port=new_port)
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @app.post("/dashboard/autostart")
    async def dash_autostart(request: Request):
        val = request.query_params.get("value") in ("1", "true", "True")
        _manager.set_autostart(request.query_params.get("id"), val)
        return {"status": "ok"}

    @app.get("/dashboard/logs")
    async def dash_logs(id: str, kind: str = "err", tail: int = 20000):
        path = _out_log_path(id) if kind == "out" else _err_log_path(id)
        text = _read_tail(path, tail)
        if not text:
            text = f"(empty log file)\n{path}"
        return PlainTextResponse(text)

    @app.get("/dashboard/env")
    async def dash_env():
        return {
            "sys_executable": sys.executable,
            "cwd": os.getcwd(),
            "python_paths": _python_paths(),
            "pythonpath": os.environ.get("PYTHONPATH", ""),
            "logs_dir": _logs_dir(),
            "agents_dir": _agents_dir(),
            "teams_dir": _teams_dir(),
            "pid_file": _pid_file(),
            "children": _load_pid_map(),
            "web_concurrency": os.environ.get("WEB_CONCURRENCY"),
        }

    @app.get("/dashboard/teams")
    async def dash_teams():
        return {"teams": _list_teams()}

    @app.post("/dashboard/teams/save")
    async def dash_team_save(request: Request):
        body = await request.json()
        try:
            name = body.get("name") or ""
            path = save_team(name)
            _log_action("log_team_saved",
                        name=name or os.path.basename(path))
            return {"status": "ok", "path": path}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @app.post("/dashboard/teams/load")
    async def dash_team_load(request: Request):
        body = await request.json()
        try:
            name = body.get("name") or ""
            start_flagged = bool(body.get(
                "start_flagged", body.get("autostart", False)))
            loaded, started = load_team(name, start_flagged=start_flagged)
            if start_flagged:
                _log_action("log_team_loaded_started",
                            name=name, n=loaded, started=started)
            else:
                _log_action("log_team_loaded", name=name, n=loaded)
            return {"status": "ok",
                    "loaded": loaded,
                    "started": started}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @app.post("/dashboard/teams/delete")
    async def dash_team_delete(request: Request):
        body = await request.json()
        try:
            name = body.get("name") or ""
            path = _team_path(name)
            if os.path.isfile(path):
                os.remove(path)
            _log_action("log_team_deleted", name=name)
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "error": str(e)}


# ============================================================================
# UI
# ============================================================================
def build_ui() -> gr.Blocks:
    lang = _detect_system_lang()
    print(f"[fona] dashboard language: {lang} "
          f"(override: FONA_DASHBOARD_LANG=en|ru)",
          file=sys.stderr, flush=True)
    print(f"[fona] logs dir: {_logs_dir()}", file=sys.stderr, flush=True)
    print(f"[fona] python paths for children: {_python_paths()}",
          file=sys.stderr, flush=True)

    killed = _kill_orphan_children()
    if killed:
        print(f"[fona] cleaned up {len(killed)} orphan child process(es)",
              file=sys.stderr, flush=True)

    _blocks_kwargs = {"title": t(lang, "title")}
    if not _IS_GRADIO6:
        _blocks_kwargs["css"] = _GLOBAL_CSS
        _blocks_kwargs["head"] = _HEAD_DARK

    with gr.Blocks(**_blocks_kwargs) as demo:
        lang_state = gr.State(lang)

        with gr.Row(equal_height=False):

            with gr.Column(scale=2, min_width=340):
                gr.HTML(f'<div class="col-head">\U0001f4c1 '
                        f'{t(lang, "team")}</div>')

                with gr.Accordion(
                        f"\u2795 {t(lang, 'add_agent')}",
                        open=True) as add_acc:
                    new_script_file = gr.File(
                        label=t(lang, "select_script"),
                        file_types=[".py"],
                        file_count="single",
                        type="filepath",
                        elem_classes=["compact-file"])
                    with gr.Row(equal_height=True):
                        new_script_manual = gr.Textbox(
                            placeholder=t(lang, "manual_path"),
                            show_label=False, scale=4,
                            elem_classes=["compact-tb"])
                        new_script_browse = gr.Button(
                            "\U0001f4c2", size="sm",
                            scale=0, min_width=0,
                            elem_classes=["compact-btn"])
                    with gr.Row(equal_height=True):
                        new_port = gr.Number(
                            value=8000, label=t(lang, "port"),
                            precision=0, scale=2,
                            elem_classes=["compact-tb"])
                        new_orch_port = gr.Number(
                            value=None,
                            label=t(lang, "orch_port_optional"),
                            precision=0, scale=3,
                            elem_classes=["compact-tb"])
                    new_name = gr.Textbox(
                        placeholder=t(lang, "name_placeholder"),
                        label=t(lang, "name_optional"),
                        elem_classes=["compact-tb"])
                    add_btn = gr.Button(
                        f"\u2795 {t(lang, 'add')}",
                        size="sm", variant="primary",
                        elem_classes=["compact-btn"])
                    add_status = gr.HTML(_status_html(""))

                with gr.Accordion(
                        f"\U0001f4be {t(lang, 'save_load')}",
                        open=False) as team_acc:
                    team_dropdown = gr.Dropdown(
                        choices=_list_teams(),
                        label=t(lang, "saved_teams"),
                        allow_custom_value=True,
                        elem_classes=["compact-tb"])
                    with gr.Row(equal_height=True):
                        team_refresh = gr.Button(
                            "\U0001f504", size="sm",
                            scale=0, min_width=0,
                            elem_classes=["compact-btn"])
                        team_name_input = gr.Textbox(
                            placeholder=t(lang, "team_name"),
                            show_label=False, scale=4,
                            elem_classes=["compact-tb"])
                    with gr.Row(equal_height=True):
                        team_save_btn = gr.Button(
                            f"\U0001f4be {t(lang, 'save_as')}",
                            size="sm", variant="primary", scale=1,
                            elem_classes=["compact-btn"])
                        team_delete_btn = gr.Button(
                            f"\U0001f5d1 {t(lang, 'delete')}",
                            size="sm", scale=1,
                            elem_classes=["compact-btn"])
                    with gr.Row(equal_height=True):
                        team_load_btn = gr.Button(
                            f"\U0001f4c2 {t(lang, 'load')}",
                            size="sm", scale=1,
                            elem_classes=["compact-btn"])
                        team_load_start_btn = gr.Button(
                            f"\u25b6 {t(lang, 'load_and_start')}",
                            size="sm", variant="primary", scale=2,
                            elem_classes=["compact-btn"])
                    team_hint = gr.HTML(
                        f'<div class="team-hint">'
                        f'{t(lang, "load_hint")}</div>')
                    team_status = gr.HTML(_status_html(""))

            with gr.Column(scale=5, min_width=520):
                with gr.Row(equal_height=True):
                    gr.HTML(f'<div class="col-head">\U0001f4ca '
                            f'{t(lang, "agents")}</div>')
                    refresh_btn = gr.Button(
                        "\U0001f504", size="sm", scale=0, min_width=0,
                        elem_classes=["compact-btn"],
                        elem_id="refresh_btn")
                cards_html = gr.HTML(_render_cards(lang))
                summary_json = gr.JSON(show_label=False,
                                       value=_status_dict(lang))

            with gr.Column(scale=2, min_width=300):
                gr.HTML(f'<div class="col-head">\U0001f4c8 '
                        f'{t(lang, "summary")}</div>')
                summary_chart = gr.HTML(_render_summary_chart(lang))
                gr.HTML(f'<div class="col-head">\U0001f4cb '
                        f'{t(lang, "action_log")}</div>')
                action_log = gr.Textbox(
                    show_label=False, lines=24, interactive=False,
                    elem_classes=["compact-tb"])

        timer = gr.Timer(2.0)

        def _refresh(lang_code):
            for a in _manager.list():
                _manager.poll(a.id)
            return (
                _render_cards(lang_code),
                _status_dict(lang_code),
                _render_summary_chart(lang_code),
                _get_action_log(lang_code),
            )

        timer.tick(_refresh, [lang_state],
                   [cards_html, summary_json, summary_chart, action_log])
        refresh_btn.click(_refresh, [lang_state],
                          [cards_html, summary_json,
                           summary_chart, action_log])

        new_script_browse.click(
            _pick_script_dialog, [], [new_script_manual])

        def _add(lang_code, file_obj, manual_path, port, orch_port, name):
            try:
                script_path = None
                notes: List[str] = []
                manual = (manual_path or "").strip()
                if manual and os.path.isfile(manual):
                    script_path = manual
                if script_path is None:
                    uploaded = _file_to_path(file_obj)
                    if uploaded and os.path.isfile(uploaded):
                        import tempfile
                        tmp = tempfile.gettempdir()
                        is_temp = os.path.abspath(uploaded).startswith(
                            os.path.abspath(tmp) + os.sep)
                        if is_temp:
                            script_path = _install_script(uploaded)
                            notes.append(t(lang_code, "script_copied"))
                        else:
                            script_path = uploaded
                if script_path is None:
                    return _status_html(
                        f"\u2717 {t(lang_code, 'no_script')}")
                entry = _manager.add(
                    script_path, name or "",
                    int(port) if port else 8000,
                    int(orch_port) if orch_port else None,
                )
                _log_action("log_added", name=entry.name, url=entry.url)
                msg = f"\u2713 {entry.name} \u2192 {entry.url}"
                if notes:
                    msg += "\n  " + "\n  ".join(notes)
                return _status_html(msg)
            except Exception as e:
                return _status_html(f"\u2717 {e}")

        add_btn.click(
            _add,
            [lang_state, new_script_file, new_script_manual,
             new_port, new_orch_port, new_name],
            [add_status],
        ).then(
            _refresh, [lang_state],
            [cards_html, summary_json, summary_chart, action_log],
        )

        def _refresh_teams():
            names = _list_teams()
            return gr.update(choices=names,
                             value=names[0] if names else None)

        team_refresh.click(_refresh_teams, [], [team_dropdown])

        def _do_save(lang_code, name):
            try:
                name = (name or "").strip()
                path = save_team(name)
                _log_action("log_team_saved",
                            name=name or os.path.basename(path))
                return (_status_html(
                    f"\u2713 {os.path.basename(path)}: "
                    f"{len(_manager.list())} agents"),
                    _refresh_teams(),
                    _get_action_log(lang_code))
            except Exception as e:
                return (_status_html(f"\u2717 {e}"),
                        _refresh_teams(),
                        _get_action_log(lang_code))

        team_save_btn.click(
            _do_save, [lang_state, team_name_input],
            [team_status, team_dropdown, action_log])

        def _do_load(lang_code, name, start_flagged):
            try:
                loaded, started = load_team(
                    name or "", start_flagged=bool(start_flagged))
                if start_flagged:
                    _log_action("log_team_loaded_started",
                                name=name or "", n=loaded,
                                started=started)
                else:
                    _log_action("log_team_loaded",
                                name=name or "", n=loaded)
                msg = f"\u2713 {name}: +{loaded}"
                if start_flagged:
                    msg += f", started {started}"
                return (_status_html(msg),
                        _render_cards(lang_code),
                        _status_dict(lang_code),
                        _get_action_log(lang_code))
            except Exception as e:
                return (_status_html(f"\u2717 {e}"),
                        _render_cards(lang_code),
                        _status_dict(lang_code),
                        _get_action_log(lang_code))

        team_load_btn.click(
            lambda lang_code, name: _do_load(lang_code, name, False),
            [lang_state, team_dropdown],
            [team_status, cards_html, summary_json, action_log])

        team_load_start_btn.click(
            lambda lang_code, name: _do_load(lang_code, name, True),
            [lang_state, team_dropdown],
            [team_status, cards_html, summary_json, action_log])

        def _do_delete(lang_code, name):
            try:
                name = (name or "").strip()
                path = _team_path(name)
                if os.path.isfile(path):
                    os.remove(path)
                _log_action("log_team_deleted", name=name)
                return (_status_html(f"\u2713 {name}"),
                        _refresh_teams(),
                        _get_action_log(lang_code))
            except Exception as e:
                return (_status_html(f"\u2717 {e}"),
                        _refresh_teams(),
                        _get_action_log(lang_code))

        team_delete_btn.click(
            _do_delete, [lang_state, team_dropdown],
            [team_status, team_dropdown, action_log])

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
        inbrowser=False,
        share=share)

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
    if "inbrowser" in kwargs:
        launch_kwargs["inbrowser"] = False

    result = ui.launch(**launch_kwargs, prevent_thread_lock=True)

    print(f"[fona] launch() returned {type(result).__name__}",
          file=sys.stderr, flush=True)

    fastapi_app = None
    if isinstance(result, tuple):
        for item in result:
            if hasattr(item, "routes"):
                fastapi_app = item
                break
    elif hasattr(result, "routes"):
        fastapi_app = result

    if fastapi_app is None:
        for attr in ("server_app", "_server_app", "app", "fastapi_app"):
            candidate = getattr(ui, attr, None)
            if candidate is not None and hasattr(candidate, "routes"):
                fastapi_app = candidate
                break

    if fastapi_app is not None:
        _attach_dashboard_routes(fastapi_app)
        print(f"[fona] dashboard routes attached. "
              f"Self-test: http://{host}:{port}/dashboard/env",
              file=sys.stderr, flush=True)
    else:
        print(
            "[fona] ERROR: could not attach /dashboard/* routes. "
            f"launch() returned {type(result).__name__}. "
            "Buttons and log viewer will return 404. "
            "Please report this with your gradio version "
            f"({gr.__version__}).",
            file=sys.stderr, flush=True)

    if inbrowser:
        try:
            import webbrowser
            webbrowser.open(f"http://{host}:{port}/")
        except Exception:
            pass

    try:
        while True:
            _t.sleep(1)
    except KeyboardInterrupt:
        print("[fona] dashboard shutting down, stopping child agents…",
              file=sys.stderr, flush=True)
        _manager.stop_all()
        try:
            os.remove(_pid_file())
        except OSError:
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