"""Fona Dashboard — manage and monitor background agents (v4.5).

Key changes vs v4.4:
  * FIX T: _walk_team_files + recursive _autodetect_team_files
    (depth<=3, skip .git/node_modules/venv/...). team.json in
    examples/<team>/ is now found on launch.
  * FIX U: _live_scan_any falls back to DEFAULT_PORT_RANGE = (8020, 8099)
    when no team.json exists, so the Adopted tab is populated from
    startup, regardless of whether a project is open.
  * FIX V: _pick_directory_dialog(title) — custom dialog title.
  * FIX W: Project.from_folder(root) — open by folder, autodetect
    team.json in root or up to 3 levels down.
  * FIX X/Y: redesigned Project section:
        [ Open project… ] [ Create project… ] [ Close ]
    No manual name/port_range/path fields. Opening a folder without
    team.json offers to create the project in that folder.
  * FIX Z: demo.load(_refresh, ...) refreshes cards AND Adopted tab
    immediately on page load.
  * FIX AA: _do_close releases adopted agents but does not kill them.
    (Model "processes survive the dashboard" is preserved.)

Previous fixes (A–S) are kept:
  A: Project.open migrates team.json v1/v2/v3 -> v4.
  B: start() kills stale python on the port BEFORE Popen.
  C: poll() is a pure observer; never kills, never clears a.process.
  D: _is_pid_alive (WaitForSingleObject); _kill_pid rc=128 no-op.
  E: orphan cleanup in port_range before adoption.
  F: team_resolver live scan (in fona/team.py).
  G: _allocate_for() allocates both ports; gated by with_orch (M).
  H: pid mismatch signalled only when FONA_STRICT_PID=1 and not adopted.
  I: start() adopt branch clears a.process.
  J: _child_env strips UVICORN_RELOAD and WEB_CONCURRENCY.
  L: "Load and start" force-starts every non-online agent.
  M: Orchestrator button only if template AND port are set.
  N: Project autodetect on launch.
  O: load_team preserves adopted state if process is still serving.
  R: _on_project_open no longer calls stop_all/clear.
  S: _ensure_startup_project logs when >1 team.json is found.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json as _json
import locale as _locale
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
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

from .live_scan import scan_range, LiveAgent


# ============================================================================
# i18n
# ============================================================================
TRANSLATIONS = {
    "en": {
        "title": "Fona Dashboard",
        "agents": "Agents", "summary": "Summary",
        "tab_agents": "Agents",
        "tab_adopted": "Adopted / Live",
        "adopted_agents": "Live agents in port range",
        "no_live_agents": "No live agents in the port range.",
        "team_col": "Team", "name_col": "Name", "port_col": "Port",
        "status_col": "Status", "actions_col": "Actions",
        "kill": "Kill", "adopted_badge": "ADOPTED",
        "project": "Project",
        "project_open_btn": "Open",
        "project_create_btn": "Create",
        "project_close_btn": "Close",
        "project_none": "No project open",
        "project_summary":
            "{name} — {n} agent(s), ports {start}-{end}",
        "project_dialog_open_title":
            "Choose a project folder (with team.json)",
        "project_dialog_create_title":
            "Choose an empty folder to create a new project",
        "project_multi_found":
            "Multiple team.json found under the folder; pick the exact "
            "folder or run with FONA_TEAM_FILE",
        "project_create_exists":
            "Folder already contains team.json — opening it instead",
        "project_create_invalid":
            "Cannot create project: {msg}",
        "project_open_failed": "Open failed: {msg}",
        "project_closed": "Project closed",
        "project_path_required": "Project folder is required",
        "project_name_placeholder": "team name (optional)",
        "port_range_invalid": "Invalid port range",
        "no_project": "No project open. Create or open one first.",
        "no_project_active": "No active project",
        "add_agent": "Add Agent", "action_log": "Action Log",
        "team": "Team", "script": "Script",
        "select_script": "Script file (drag or click)",
        "manual_path": "or paste absolute path",
        "name_optional": "Name (optional)", "name_placeholder": "my-agent",
        "orch_template_optional": "Orchestrator UI template (opt)",
        "orch_template_placeholder": "path/to/orchestrator_template.py",
        "orch_template_missing":
            "orchestrator template not found: {path}",
        "orch_ui": "orch ui",
        "add": "Add",
        "start": "Start", "stop": "Stop", "restart": "Restart", 
        "remove": "Remove", "stop_all": "Stop all",
        "release": "Release",
        "open_ui": "Open UI", "open_orchestrator": "Orchestrator",
        "uptime": "uptime", "latency": "latency", "rules": "rules",
        "actions": "actions", "availability": "availability", "kb": "KB",
        "error": "error", "autostart": "autostart",
        "autostart_hint": "Start automatically when the project is opened",
        "online": "ONLINE", "offline": "OFFLINE",
        "starting": "STARTING", "stopped": "STOPPED",
        "adopted": "ADOPTED", "error_status": "ERROR",
        "save": "Save",
        "load_and_start": "Load and start",
        "empty_state": "No agents. Add a script in the panel on the left.",
        "empty_hint": "Example: examples/demo_agent.py",
        "confirm_remove": "Remove {name}?",
        "no_free_port": "No free port in range {start}..{end}",
        "script_missing": "Script not found: {path}",
        "no_script": "No script provided",
        "logs": "Logs",
        "script_copied": "Copied to project scripts/",
        "script_copied_renamed":
            "Copied as new file (different content, old kept)",
        "script_already_copied":
            "Already in project (identical content, not duplicated)",
        "using_source_in_place":
            "Using file in place (no copy)",
        "source_changed": "source changed",
        "source_missing": "source missing",
        "source_update": "Update",
        "status_total": "total", "status_online": "online",
        "status_offline": "offline", "status_stopped": "stopped",
        "status_starting": "starting",
        "log_added": "Added {name}",
        "log_started": "Started {name} on port {port}",
        "log_adopted": "Adopted {name} on port {port}",
        "log_released": "Released {name} on port {port} (not killed)",
        "log_killed_live": "Killed pid={pid} on port {port}",
        "log_killed_orphan": "Killed orphan pid={pid} on port {port}",
        "log_recovered": "Recovered {name}: process exit was transient, "
                         "port {port} is serving",
        "log_start_failed": "Failed to start {name}: {reason}",
        "log_stopped": "Stopped {name}",
        "log_restarted": "Restarted {name}",
        "log_removed": "Removed {name}",
        "log_team_saved": "Saved team to {path}",
        "log_team_loaded": "Loaded team from {path} (+{n})",
        "log_team_loaded_started": ("Loaded team from {path} (+{n}); "
                                    "started {started} agent(s)"),
        "log_project_created": "Created project at {path}",
        "log_project_opened": "Opened project at {path} (+{n})",
        "log_project_autodetected": "Autodetected project at {path}",
        "log_project_autodetect_ambiguous":
            "Multiple team.json found ({n}); open one manually",
        "log_project_closed": "Closed project",
        "log_script_missing": "Script missing for {name}: {path}",
        "log_source_updated": "Updated {name} from {path}",
        "log_orch_template_missing":
            "Orchestrator template missing for {name}: {path}",
        "log_pid_mismatch":
            "Port {port} serves a different process for {name}",
        "log_child_died":
            "{name} exited immediately after start (rc={rc}): {tail}",
        "log_stop_all": "Stopping all agents",
        "log_migrated_v3": "Migrated team.json v3 -> v4",
        "log_orphans_cleaned": "Killed {n} orphan process(es) in port range",
    },
    "ru": {
        "title": "Дашборд Fona",
        "agents": "Агенты", "summary": "Сводка",
        "tab_agents": "Агенты",
        "tab_adopted": "Усыновлённые / Живые",
        "adopted_agents": "Живые агенты в диапазоне портов",
        "no_live_agents": "Нет живых агентов в диапазоне портов.",
        "team_col": "Команда", "name_col": "Имя", "port_col": "Порт",
        "status_col": "Статус", "actions_col": "Действия",
        "kill": "Убить", "adopted_badge": "УСЫНОВЛЁН",
        "project": "Проект",
        "project_open_btn": "Открыть",
        "project_create_btn": "Создать",
        "project_close_btn": "Закрыть",
        "project_none": "Проект не открыт",
        "project_summary":
            "{name} — агентов: {n}, порты {start}-{end}",
        "project_dialog_open_title":
            "Выберите папку проекта (с team.json)",
        "project_dialog_create_title":
            "Выберите пустую папку для нового проекта",
        "project_multi_found":
            "В папке несколько team.json; укажите конкретную папку или "
            "задайте FONA_TEAM_FILE",
        "project_create_exists":
            "В папке уже есть team.json — открываю её",
        "project_create_invalid":
            "Не удалось создать проект: {msg}",
        "project_open_failed": "Ошибка открытия: {msg}",
        "project_closed": "Проект закрыт",
        "project_path_required": "Укажите папку проекта",
        "project_name_placeholder": "имя команды (опционально)",
        "port_range_invalid": "Неверный диапазон портов",
        "no_project": "Проект не открыт. Создайте или откройте его.",
        "no_project_active": "Проект не открыт",
        "add_agent": "Добавить агента", "action_log": "Журнал действий",
        "team": "Команда", "script": "Скрипт",
        "select_script": "Файл скрипта (перетащите или нажмите)",
        "manual_path": "или вставьте абсолютный путь",
        "name_optional": "Имя (опционально)", "name_placeholder": "мой-агент",
        "orch_template_optional": "Шаблон UI оркестратора (опц)",
        "orch_template_placeholder": "путь/к/orchestrator_template.py",
        "orch_template_missing":
            "шаблон оркестратора не найден: {path}",
        "orch_ui": "UI оркестратора",
        "add": "Добавить",
        "start": "Старт", "stop": "Стоп", "restart": "Перезапустить",
        "remove": "Удалить", "stop_all": "Остановить всё",
        "release": "Отпустить",
        "open_ui": "Открыть UI", "open_orchestrator": "Оркестратор",
        "uptime": "аптайм", "latency": "задержка", "rules": "правил",
        "actions": "действий", "availability": "доступность", "kb": "БЗ",
        "error": "ошибка", "autostart": "автозапуск",
        "autostart_hint": "Запускать автоматически при открытии проекта",
        "online": "ОНЛАЙН", "offline": "ОФЛАЙН",
        "starting": "СТАРТ", "stopped": "СТОП",
        "adopted": "УСЫНОВЛЁН", "error_status": "ОШИБКА",
        "save": "Сохранить",
        "load_and_start": "Загрузить и запустить",
        "empty_state": "Нет агентов. Добавьте скрипт в панели слева.",
        "empty_hint": "Пример: examples/demo_agent.py",
        "confirm_remove": "Удалить {name}?",
        "no_free_port": "Нет свободного порта в диапазоне {start}..{end}",
        "script_missing": "Скрипт не найден: {path}",
        "no_script": "Скрипт не указан",
        "logs": "Логи",
        "script_copied": "Скопирован в scripts/ проекта",
        "script_copied_renamed":
            "Скопирован как новый файл (содержимое отличается, старый сохранён)",
        "script_already_copied":
            "Уже в проекте (идентичное содержимое, дубликат не создан)",
        "using_source_in_place":
            "Используется по месту (без копирования)",
        "source_changed": "исходник изменён",
        "source_missing": "исходник недоступен",
        "source_update": "Обновить",
        "status_total": "всего", "status_online": "онлайн",
        "status_offline": "офлайн", "status_stopped": "остановлен",
        "status_starting": "стартует",
        "log_added": "Добавлен {name}",
        "log_started": "Запущен {name} на порту {port}",
        "log_adopted": "Усыновлён {name} на порту {port}",
        "log_released": "Отпущен {name} на порту {port} (не убит)",
        "log_killed_live": "Убит pid={pid} на порту {port}",
        "log_killed_orphan": "Убит осиротевший pid={pid} на порту {port}",
        "log_recovered": "Восстановлен {name}: выход процесса был "
                         "кратковременным, порт {port} обслуживается",
        "log_start_failed": "Ошибка запуска {name}: {reason}",
        "log_stopped": "Остановлен {name}",
        "log_restarted": "Перезапущен {name}",
        "log_removed": "Удалён {name}",
        "log_team_saved": "Команда сохранена в {path}",
        "log_team_loaded": "Команда загружена из {path} (+{n})",
        "log_team_loaded_started": ("Команда загружена из {path} (+{n}); "
                                    "запущено {started} агент(ов)"),
        "log_project_created": "Создан проект в {path}",
        "log_project_opened": "Открыт проект в {path} (+{n})",
        "log_project_autodetected": "Автоопределён проект в {path}",
        "log_project_autodetect_ambiguous":
            "Найдено несколько team.json ({n}); откройте вручную",
        "log_project_closed": "Проект закрыт",
        "log_script_missing": "Скрипт не найден для {name}: {path}",
        "log_source_updated": "Обновлён {name} из {path}",
        "log_orch_template_missing":
            "Шаблон оркестратора не найден для {name}: {path}",
        "log_pid_mismatch":
            "На порту {port} отвечает другой процесс для {name}",
        "log_child_died":
            "{name} завершился сразу после старта (rc={rc}): {tail}",
        "log_stop_all": "Останавливаю всех агентов",
        "log_migrated_v3": "team.json миграция v3 -> v4",
        "log_orphans_cleaned":
            "Убито {n} осиротевших процесс(ов) в диапазоне портов",
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
# PYTHONPATH / env for children
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


def _child_env(port: int,
               agent_name: Optional[str] = None,
               team_name: Optional[str] = None,
               extra: Optional[Dict[str, str]] = None,
               team_file: Optional[str] = None) -> dict:
    env = os.environ.copy()
    env["FONA_CHILD"] = "1"
    env["FONA_PORT"] = str(port)
    if agent_name:
        env["FONA_AGENT_NAME"] = agent_name
    if team_name:
        env["FONA_TEAM_NAME"] = team_name
    if team_file:
        env["FONA_TEAM_FILE"] = team_file
    env.pop("WEB_CONCURRENCY", None)
    env.pop("UVICORN_RELOAD", None)
    existing = env.get("PYTHONPATH", "")
    parts = existing.split(os.pathsep) if existing else []
    for p in reversed(_python_paths()):
        if p and p not in parts:
            parts.insert(0, p)
    if parts:
        env["PYTHONPATH"] = os.pathsep.join(parts)
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
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
.card.adopted { border-left: 4px solid #58a6ff; }
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
.badge.adopted  { background: #1c2a3a; color: #58a6ff; }
.badge.source-warn { background: #2a1f0f; color: #e3b341; }
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
.card-actions .update-btn {
    text-decoration: none !important; display: inline-block;
    padding: 3px 8px; background: #2a1f0f; color: #e3b341 !important;
    border-radius: 4px; font-size: 11px; border: 1px solid #3a2a10;
}
.card-actions .update-btn:hover { background: #3a2a10; }
.empty-state { padding: 40px 20px; text-align: center; color: #8b949e;
    border: 1px dashed #2a313d; border-radius: 8px; font-size: 13px; }
.sparkline { width: 100%; height: 30px; margin-top: 4px; }

/* Live agents table */
.live-table { display: flex; flex-direction: column;
              border: 1px solid #2a313d; border-radius: 6px;
              overflow: hidden; }
.live-header { display: grid;
               grid-template-columns: 140px 1fr 70px 80px 100px 200px;
               background: #0b0d11; border-bottom: 1px solid #2a313d;
               font-size: 11px; color: #8b949e; font-weight: 600; }
.live-row { display: grid;
            grid-template-columns: 140px 1fr 70px 80px 100px 200px;
            border-bottom: 1px solid #161a20; }
.live-row:last-child { border-bottom: none; }
.live-row.online  { border-left: 3px solid #238636; }
.live-row.error   { border-left: 3px solid #f85149; }
.live-cell { padding: 6px 8px; font-size: 12px;
             display: flex; align-items: center; gap: 6px;
             overflow: hidden; text-overflow: ellipsis;
             white-space: nowrap; }
.live-team, .live-name, .live-port, .live-pid {
    font-family: ui-monospace, monospace; font-size: 11px;
}
.live-team.team-ours { color: #58a6ff; font-weight: 600; }
.live-actions { justify-content: flex-end; }
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
# Constants
# ============================================================================
DEFAULT_PORT_RANGE: Tuple[int, int] = (8020, 8099)
TEAM_VERSION = 4


# ============================================================================
# Project (folder = team)
# ============================================================================
@dataclass
class Project:
    root: str
    name: str
    port_range: Tuple[int, int] = DEFAULT_PORT_RANGE

    @property
    def team_file(self) -> str:
        return os.path.join(self.root, "team.json")

    @property
    def scripts_dir(self) -> str:
        return os.path.join(self.root, "scripts")

    @property
    def logs_dir(self) -> str:
        return os.path.join(self.root, "logs")

    def ensure(self) -> None:
        for d in (self.root, self.scripts_dir, self.logs_dir):
            os.makedirs(d, exist_ok=True)

    @classmethod
    def create(cls, root: str, name: str = "",
               port_range: Tuple[int, int] = DEFAULT_PORT_RANGE) -> "Project":
        root = os.path.abspath(root)
        p = cls(root=root, name=name or os.path.basename(root),
                port_range=port_range)
        p.ensure()
        return p

    @classmethod
    def open(cls, root: str) -> "Project":
        root = os.path.abspath(root)
        team_file = os.path.join(root, "team.json")
        if not os.path.isfile(team_file):
            raise FileNotFoundError(f"team.json not found in {root}")
        name = os.path.basename(root)
        port_range: Tuple[int, int] = DEFAULT_PORT_RANGE
        try:
            with open(team_file, "r", encoding="utf-8") as f:
                payload = _json.load(f)
            name = payload.get("name") or name
            version = int(payload.get("version", 1))

            if version < 4:
                agents = payload.get("agents") or []
                old_ports: List[int] = []
                for a in agents:
                    for key in ("port", "orchestrator_gradio_port"):
                        try:
                            v = int(a.get(key) or 0)
                        except (TypeError, ValueError):
                            v = 0
                        if v:
                            old_ports.append(v)
                        a.pop(key, None)
                    a.pop("port_range", None)
                if old_ports:
                    pr = (min(old_ports), max(old_ports) + 10)
                else:
                    pr = DEFAULT_PORT_RANGE
                payload["version"] = 4
                payload["port_range"] = list(pr)
                payload["agents"] = agents
                with open(team_file, "w", encoding="utf-8") as f:
                    _json.dump(payload, f, indent=2, ensure_ascii=False)
                port_range = pr
                _log_action("log_migrated_v3")
            else:
                pr = payload.get("port_range")
                if isinstance(pr, (list, tuple)) and len(pr) == 2:
                    port_range = (int(pr[0]), int(pr[1]))
        except Exception:
            pass
        p = cls(root=root, name=name, port_range=port_range)
        p.ensure()
        return p

    @classmethod
    def from_folder(cls, root: str) -> "Project":
        """Open root as a project. team.json may be at root or one of
        the next 3 levels. Raise if none or if multiple.

        FIX W: this is the entry point for the "Open project…" button.
        """
        root = os.path.abspath(root)
        if not os.path.isdir(root):
            raise FileNotFoundError(f"not a directory: {root}")
        direct = os.path.join(root, "team.json")
        if os.path.isfile(direct):
            return cls.open(root)
        nested = _walk_team_files(root, max_depth=3)
        if not nested:
            raise FileNotFoundError(f"no team.json under {root}")
        if len(nested) > 1:
            raise ValueError(
                f"multiple team.json under {root}: {len(nested)}")
        return cls.open(os.path.dirname(nested[0]))


_active_project: Optional[Project] = None
_do_not_adopt: set = set()
# FIX EE: cache mtime of team.json to auto-reload on external change.
_team_mtime_cache: Dict[str, float] = {}
_RELOAD_EPS = 0.5  # ignore sub-second mtime jitter on some FS


def _logs_dir() -> str:
    if _active_project is not None:
        path = _active_project.logs_dir
    else:
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


_UVICORN_PORT_RE = re.compile(
    r"Uvicorn running on https?://[^\s]+?:(\d+)"
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
# Project autodetection (FIX N, S, T)
# ============================================================================
_SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv",
              "build", "dist", ".idea", ".vscode", ".mypy_cache",
              ".pytest_cache", ".ruff_cache", "site-packages"}


def _walk_team_files(root: str, max_depth: int = 3) -> List[str]:
    """Recursively find team.json up to max_depth levels under root."""
    found: List[str] = []
    root = os.path.abspath(root)
    base_depth = root.count(os.sep)

    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath.count(os.sep) - base_depth
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS and not d.startswith(".")]
        if depth >= max_depth:
            dirnames[:] = []
            continue
        if "team.json" in filenames:
            found.append(os.path.join(dirpath, "team.json"))
    return found


def _autodetect_team_files() -> List[str]:
    """Find team.json recursively under cwd (up to 3 levels)."""
    cwd = os.getcwd()
    candidates = _walk_team_files(cwd, max_depth=3)
    env_team = (os.environ.get("FONA_TEAM_FILE") or "").strip()
    if env_team and os.path.isfile(env_team) and env_team not in candidates:
        candidates.insert(0, env_team)
    return candidates


def _ensure_startup_project() -> None:
    """Autodetect and open a project on dashboard launch."""
    global _active_project
    if _active_project is not None:
        return
    candidates = _autodetect_team_files()
    if not candidates:
        print("[fona] no team.json found under cwd (depth <= 3)",
              file=sys.stderr, flush=True)
        return
    if len(candidates) > 1:
        _log_action("log_project_autodetect_ambiguous", n=len(candidates))
        print(f"[fona] multiple team.json found ({len(candidates)}):",
              file=sys.stderr, flush=True)
        for c in candidates[:5]:
            print(f"[fona]   {c}", file=sys.stderr, flush=True)
        return
    try:
        project = Project.open(candidates[0])
        _active_project = project
        try:
            load_team(project.team_file, start_flagged=False)
        except Exception as e:
            print(f"[fona] startup load failed: {e}",
                  file=sys.stderr, flush=True)
        # FIX GG: autostart agents come up with the project. This is
        # the only place where the flag actually starts something;
        # auto-reload (_maybe_reload_team) deliberately does NOT.
        try:
            for a in list(_manager.list()):
                if a.autostart and a.status != "online":
                    _manager.start(a.id)
        except Exception as e:
            print(f"[fona] autostart on launch failed: {e}",
                  file=sys.stderr, flush=True)
        _log_action("log_project_autodetected", path=project.root)
        try:
            _team_mtime_cache[project.team_file] = os.path.getmtime(
                project.team_file)
        except OSError:
            pass
        print(f"[fona] autodetected project: {project.root} "
              f"(port_range={project.port_range})",
              file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[fona] autodetect open failed: {e}",
              file=sys.stderr, flush=True)


def _known_port_ranges() -> List[Tuple[int, int]]:
    ranges: List[Tuple[int, int]] = []
    if _active_project is not None:
        ranges.append(_active_project.port_range)
    for path in _autodetect_team_files():
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = _json.load(f)
            pr = payload.get("port_range")
            if isinstance(pr, (list, tuple)) and len(pr) == 2:
                pr = (int(pr[0]), int(pr[1]))
                if pr not in ranges:
                    ranges.append(pr)
        except Exception:
            continue
    return ranges


def _live_scan_any() -> List[LiveAgent]:
    """Scan all known port ranges; fall back to DEFAULT_PORT_RANGE.

    FIX U: Adopted tab must show live agents regardless of whether a
    project is open. If no team.json exists at all, scan the standard
    Fona range — scan_range only returns ports that answer
    /api/v1/model, so it is harmless if nothing is there.
    """
    ranges = _known_port_ranges()
    if not ranges:
        ranges = [DEFAULT_PORT_RANGE]
    start = min(r[0] for r in ranges)
    end = max(r[1] for r in ranges)
    try:
        return scan_range(start, end)
    except Exception:
        return []


# ============================================================================
# Port helpers
# ============================================================================
def _is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.15)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def _is_port_free(port: int) -> bool:
    if _is_port_open(port):
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if sys.platform != "win32":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _health_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        r = httpx.get(f"{url}/api/v1/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _health_pid(url: str, timeout: float = 1.0) -> Optional[int]:
    try:
        r = httpx.get(f"{url}/api/v1/health", timeout=timeout)
        if r.status_code == 200:
            try:
                return int(r.json().get("pid", 0)) or None
            except Exception:
                return None
    except Exception:
        pass
    return None


def _allocate_port(used: set, range_start: int, range_end: int) -> int:
    for port in range(range_start, range_end + 1):
        if port in used:
            continue
        if _is_port_free(port):
            return port
    raise RuntimeError(
        f"no free port in range {range_start}..{range_end}")


# ============================================================================
# PID helpers
# ============================================================================
def _is_pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            SYNCHRONIZE = 0x00100000
            WAIT_TIMEOUT = 0x00000102
            h = ctypes.windll.kernel32.OpenProcess(
                SYNCHRONIZE, False, int(pid))
            if not h:
                return False
            try:
                rc = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
            return rc == WAIT_TIMEOUT
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
            r = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=4)
            if r.returncode not in (0, 128):
                err = (r.stderr or b"").decode(errors="replace")[:200]
                print(f"[fona] taskkill pid={pid} rc={r.returncode}: {err}",
                      file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[fona] taskkill pid={pid} failed: {e}",
                  file=sys.stderr, flush=True)
    else:
        for sig in (15, 9):
            try:
                os.kill(pid, sig)
                _t.sleep(0.3)
                if not _is_pid_alive(pid):
                    return
            except OSError as e:
                print(f"[fona] kill pid={pid} sig={sig} failed: {e}",
                      file=sys.stderr, flush=True)
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
    if image and not image.lower().startswith("python"):
        print(f"[fona] not killing pid={pid} on port {port}: "
              f"image={image!r}", file=sys.stderr, flush=True)
        return None
    print(f"[fona] killing stale pid={pid} on port {port} "
          f"(image={image!r})", file=sys.stderr, flush=True)
    _kill_pid(pid)
    _t.sleep(0.5)
    if _is_pid_alive(pid):
        print(f"[fona] pid={pid} still alive after taskkill; "
              f"may need admin rights", file=sys.stderr, flush=True)
        return None
    return pid


def _kill_orphans_in_range(start: int, end: int,
                           team_name: Optional[str]) -> int:
    killed = 0
    try:
        live = scan_range(start, end)
    except Exception as e:
        print(f"[fona] orphan scan failed: {e}",
              file=sys.stderr, flush=True)
        return 0
    for item in live:
        if team_name and item.team_name == team_name:
            continue
        pid = item.pid
        if not pid or not _is_pid_alive(pid):
            continue
        image = _get_process_image(pid)
        if image and not image.lower().startswith("python"):
            continue
        _kill_pid(pid)
        _t.sleep(0.2)
        if not _is_pid_alive(pid):
            killed += 1
            _log_action("log_killed_orphan", pid=pid, port=item.port)
            print(f"[fona] killed orphan pid={pid} on port {item.port} "
                  f"(team={item.team_name!r}, name={item.name!r})",
                  file=sys.stderr, flush=True)
    return killed


# ============================================================================
# Agent model
# ============================================================================
@dataclass
class AgentEntry:
    id: str
    name: str
    script: str
    port: int = 0
    url: str = ""
    process: Optional[subprocess.Popen] = None
    orchestrator_gradio_port: Optional[int] = None
    orchestrator_process: Optional[subprocess.Popen] = None
    orchestrator_template: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    status: str = "stopped"
    error: str = ""
    started_at: float = 0.0
    first_poll_starting_at: float = 0.0
    rules: int = 0
    actions: int = 0
    kb_file: str = ""
    last_check: float = 0.0
    latency_ms: float = 0.0
    history: List[int] = field(default_factory=list)
    autostart: bool = False
    source: str = ""
    source_sha256: str = ""
    source_mtime: float = 0.0
    adopted: bool = False

    def __post_init__(self):
        if self.port and not self.url:
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


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _install_script(src_path: str) -> Tuple[str, str]:
    dest_dir = _agents_dir()
    basename = os.path.basename(src_path)
    stem, ext = os.path.splitext(basename)
    src_abs = os.path.abspath(src_path)
    dest = os.path.join(dest_dir, basename)

    if os.path.abspath(dest) == src_abs:
        return dest, "same"

    if os.path.exists(dest):
        try:
            if _sha256(src_abs) == _sha256(dest):
                return dest, "same"
        except OSError:
            pass
        short = _sha256(src_abs)[:8]
        dest = os.path.join(dest_dir, f"{stem}_{short}{ext}")

    shutil.copy2(src_abs, dest)
    return dest, ("copied" if dest == os.path.join(dest_dir, basename)
                  else "renamed")


def _agents_dir() -> str:
    if _active_project is not None:
        path = _active_project.scripts_dir
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "agents")
    os.makedirs(path, exist_ok=True)
    return path


def _maybe_reload_team() -> bool:
    """FIX EE: silently reload team.json when its mtime changes.

    Replaces the removed "Load" button. Safe: load_team(start_flagged=
    False) only updates entries by id, adopts live processes, does not
    kill, does not start. Returns True if a reload happened.
    """
    if _active_project is None:
        return False
    path = _active_project.team_file
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return False
    prev = _team_mtime_cache.get(path)
    if prev is not None and abs(mtime - prev) < _RELOAD_EPS:
        return False
    _team_mtime_cache[path] = mtime
    if prev is None:
        # First observation after open: _open_after_load / _ensure_
        # startup_project already ran load_team; nothing to do.
        return False
    try:
        load_team(path, start_flagged=False)
        _log_action("log_team_loaded", path=path,
                    n=len(_manager.list()))
        return True
    except Exception as e:
        print(f"[fona] auto-reload failed: {e}",
              file=sys.stderr, flush=True)
        return False


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


def _pick_directory_dialog(title: str = "") -> str:
    """FIX V: optional dialog title."""
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
        path = filedialog.askdirectory(
            title=title or "Select project folder")
        root.destroy()
        return path or ""
    except Exception:
        return ""


def _source_status(a: AgentEntry) -> str:
    if not a.source:
        return ""
    if not os.path.isfile(a.source):
        return "missing"
    if not a.source_sha256:
        return ""
    try:
        cur = _sha256(a.source)
    except OSError:
        return "missing"
    return "" if cur == a.source_sha256 else "changed"


# ============================================================================
# Agent manager
# ============================================================================
class AgentManager:
    def __init__(self):
        self.agents: Dict[str, AgentEntry] = {}
        self._lock = threading.RLock()

    def _check_port_collisions(self, port: int, orch_port: Optional[int],
                               exclude_id: Optional[str] = None) -> None:
        for a in self.agents.values():
            if exclude_id is not None and a.id == exclude_id:
                continue
            if a.port == int(port):
                raise ValueError(f"port {port} already used by {a.name}")
            if (orch_port is not None
                    and a.orchestrator_gradio_port == int(orch_port)):
                raise ValueError(
                    f"orchestrator port {orch_port} already used by {a.name}")

    def add(self, script: str, name: str,
            orch_template: Optional[str] = None,
            env: Optional[Dict[str, str]] = None) -> AgentEntry:
        with self._lock:
            entry = AgentEntry(
                id=str(uuid.uuid4())[:8],
                name=name or Path(script).stem,
                script=script,
                orchestrator_template=orch_template or None,
                env=dict(env or {}),
            )
            self.agents[entry.id] = entry
            return entry

    def remove(self, agent_id: str) -> Optional[AgentEntry]:
        with self._lock:
            a = self.agents.pop(agent_id, None)
        if a is not None:
            self._stop_process(a)
        return a

    def get(self, agent_id: str) -> Optional[AgentEntry]:
        with self._lock:
            return self.agents.get(agent_id)

    def list(self) -> List[AgentEntry]:
        with self._lock:
            return list(self.agents.values())

    def set_autostart(self, agent_id: str, value: bool) -> None:
        a = self.get(agent_id)
        if a is not None:
            a.autostart = bool(value)

    def set_orchestrator_template(self, agent_id: str,
                                  path: Optional[str]) -> None:
        a = self.get(agent_id)
        if a is not None:
            a.orchestrator_template = path or None

    def _allocate_for(self, exclude_id: Optional[str] = None,
                      with_orch: bool = True) -> Tuple[int, int]:
        if _active_project is None:
            raise RuntimeError("no active project")
        used: set = set()
        for a in self.list():
            if exclude_id is not None and a.id == exclude_id:
                continue
            if a.port:
                used.add(a.port)
            if a.orchestrator_gradio_port:
                used.add(a.orchestrator_gradio_port)
        start, end = _active_project.port_range
        agent_port = _allocate_port(used, start, end)
        used.add(agent_port)
        orch_port = 0
        if with_orch:
            try:
                orch_port = _allocate_port(used, start, end)
            except RuntimeError:
                orch_port = 0
        return agent_port, orch_port

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
            _log_action("log_start_failed", name=a.name, reason=msg)
            return
        if a.process is not None and a.process.poll() is None:
            return

        if a.port and _health_ok(a.url, timeout=0.8):
            adopted_pid = _find_pid_by_port(a.port) or 0
            a.status = "online"
            a.adopted = True
            a.process = None
            a.started_at = _t.time()
            a.first_poll_starting_at = 0.0
            a.error = ""
            a.history = [1]
            _log_action("log_adopted", name=a.name, port=a.port)
            print(f"[fona] {a.name}: adopted existing process on "
                  f"port {a.port} (pid={adopted_pid})",
                  file=sys.stderr, flush=True)
            return

        with_orch = bool(a.orchestrator_template)
        try:
            agent_port, orch_port = self._allocate_for(
                exclude_id=a.id, with_orch=with_orch)
        except Exception as e:
            a.status = "error"
            a.error = str(e)
            _log_action("log_start_failed", name=a.name, reason=a.error)
            return

        for _attempt in range(3):
            stale = _find_pid_by_port(agent_port)
            if not stale:
                break
            _kill_python_on_port(agent_port)
            _t.sleep(0.3)
        if not _is_port_free(agent_port):
            try:
                used = {x.port for x in self.list()
                        if x.id != a.id and x.port}
                used.add(agent_port)
                start_r, end_r = _active_project.port_range
                agent_port = _allocate_port(used, start_r, end_r)
                _kill_python_on_port(agent_port)
                _t.sleep(0.2)
            except Exception as e:
                a.status = "error"
                a.error = f"port busy: {e}"
                _log_action("log_start_failed", name=a.name,
                            reason=a.error)
                return

        a.port = agent_port
        a.url = f"http://127.0.0.1:{agent_port}"
        a.orchestrator_gradio_port = orch_port or None

        team_name = (_active_project.name
                     if _active_project is not None else None)
        team_file = (_active_project.team_file
                     if _active_project is not None else None)
        env = _child_env(
            a.port,
            agent_name=a.name,
            team_name=team_name,
            extra=a.env,
            team_file=team_file,
        )
        if a.orchestrator_gradio_port:
            env["FONA_ORCHESTRATOR_PORT"] = str(a.orchestrator_gradio_port)

        out_path = _out_log_path(a.id)
        err_path = _err_log_path(a.id)
        for p in (out_path, err_path):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass

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
            a.adopted = False
            a.error = ""
            a.history = []
            print(f"[fona] started {a.name} pid={a.process.pid} "
                  f"port={a.port} orch_port={a.orchestrator_gradio_port} "
                  f"script={a.script}",
                  file=sys.stderr, flush=True)
        except Exception as e:
            a.status = "error"
            a.error = f"{type(e).__name__}: {e}"
            _log_action("log_start_failed", name=a.name, reason=a.error)
            return

        for delay in (0.3, 0.7, 1.0):
            _t.sleep(delay)
            if a.process is None:
                break
            if a.process.poll() is not None:
                rc = a.process.returncode
                out_tail, err_tail = _read_both_logs(a.id, 400)
                compact = (err_tail or out_tail or "").strip()[:300]
                a.status = "error"
                a.error = f"child exited immediately rc={rc}: {compact}"
                _log_action("log_child_died",
                            name=a.name, rc=rc, tail=compact)
                return

    def stop(self, agent_id: str) -> None:
        a = self.get(agent_id)
        if a is None:
            return
        if a.adopted:
            _do_not_adopt.add(a.id)
            pid = _find_pid_by_port(a.port) or 0
            a.adopted = False
            a.process = None
            a.status = "stopped"
            a.started_at = 0.0
            a.first_poll_starting_at = 0.0
            _log_action("log_released", name=a.name, port=a.port)
            print(f"[fona] {a.name}: released adopted pid={pid} on port "
                  f"{a.port} (not killed)", file=sys.stderr, flush=True)
            return
        self._stop_process(a)
        a.status = "stopped"
        a.started_at = 0.0
        a.first_poll_starting_at = 0.0

    def kill(self, agent_id: str) -> None:
        a = self.get(agent_id)
        if a is None:
            return
        pid = _find_pid_by_port(a.port) or 0
        if pid and _is_pid_alive(pid):
            image = _get_process_image(pid)
            if not image or image.lower().startswith("python"):
                _kill_pid(pid)
        a.process = None
        a.adopted = False
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

        if a.process is not None and a.process.poll() is not None:
            rc = a.process.returncode
            a.process = None
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
                a.history.append(0)
                a.history = a.history[-40:]
                return a

        if not a.port:
            return a

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

        if ok:
            if (a.process is not None
                    and not a.adopted
                    and os.environ.get("FONA_STRICT_PID") == "1"):
                serving_pid = _health_pid(a.url)
                if (serving_pid is not None
                        and serving_pid != a.process.pid):
                    ok = False
                    a.status = "error"
                    a.error = (f"port {a.port} serves pid={serving_pid}, "
                               f"expected {a.process.pid}; "
                               f"press Start to retry")
                    _log_action("log_pid_mismatch", name=a.name,
                                port=a.port)
                    a.first_poll_starting_at = 0.0
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
                if a.first_poll_starting_at == 0.0:
                    a.first_poll_starting_at = _t.time()
                if _t.time() - a.first_poll_starting_at > 25.0:
                    a.status = "error"
                    a.error = "no response > 25s"

        a.history.append(1 if ok else 0)
        a.history = a.history[-40:]
        return a


_manager = AgentManager()


# ============================================================================
# Team save/load (v4)
# ============================================================================
def _agent_to_dict(a: AgentEntry, base_dir: str) -> dict:
    def rel(p: str) -> str:
        if not p:
            return ""
        try:
            return os.path.relpath(p, base_dir)
        except ValueError:
            return p

    d = {
        "id": a.id, "name": a.name,
        "script": rel(a.script),
        "autostart": a.autostart,
    }
    if a.source:
        d["source"] = rel(a.source)
        d["source_sha256"] = a.source_sha256
        d["source_mtime"] = a.source_mtime
    if a.orchestrator_template:
        d["orchestrator_template"] = rel(a.orchestrator_template)
    if a.env:
        d["env"] = dict(a.env)
    return d


def _dict_to_agent(d: dict, base_dir: str) -> AgentEntry:
    def abspath_or_rel(p: str) -> str:
        if not p:
            return p
        return p if os.path.isabs(p) else os.path.normpath(
            os.path.join(base_dir, p))

    script = abspath_or_rel(d.get("script", ""))
    source = abspath_or_rel(d.get("source", "")) if d.get("source") else ""
    orch_template = (
        abspath_or_rel(d["orchestrator_template"])
        if d.get("orchestrator_template") else None)
    env = d.get("env")
    if not isinstance(env, dict):
        env = {}
    return AgentEntry(
        id=d.get("id") or str(uuid.uuid4())[:8],
        name=d.get("name") or Path(script).stem,
        script=script,
        autostart=bool(d.get("autostart", False)),
        source=source,
        source_sha256=d.get("source_sha256", ""),
        source_mtime=float(d.get("source_mtime") or 0.0),
        orchestrator_template=orch_template,
        env={str(k): str(v) for k, v in env.items()},
    )


def save_team(_unused_name: str = "") -> str:
    if _active_project is None:
        raise RuntimeError("no active project")
    project = _active_project
    project.ensure()
    payload = {
        "version": TEAM_VERSION,
        "name": project.name,
        "port_range": list(project.port_range),
        "saved_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "agents": [_agent_to_dict(a, project.root)
                   for a in _manager.list()],
    }
    with open(project.team_file, "w", encoding="utf-8") as f:
        _json.dump(payload, f, indent=2, ensure_ascii=False)
    return project.team_file


def _scan_and_adopt(project: Project,
                    known: Dict[str, dict]) -> Dict[str, AgentEntry]:
    adopted: Dict[str, AgentEntry] = {}
    try:
        live = scan_range(*project.port_range)
    except Exception:
        live = []
    for item in live:
        name = item.name
        team = item.team_name
        if team != project.name:
            continue
        if not name or name not in known:
            continue
        if name in adopted:
            print(f"[fona] adoption: duplicate name {name!r} on port "
                  f"{item.port}; already adopted on "
                  f"{adopted[name].port}; skipping",
                  file=sys.stderr, flush=True)
            continue
        if known[name].get("id") in _do_not_adopt:
            continue
        adopted[name] = AgentEntry(
            id=known[name].get("id") or str(uuid.uuid4())[:8],
            name=name,
            script=known[name]["script"],
            port=item.port, url=item.url,
            status="online",
            adopted=True,
            autostart=bool(known[name].get("autostart")),
            orchestrator_template=known[name].get("orchestrator_template"),
            env=dict(known[name].get("env") or {}),
            source=known[name].get("source", ""),
            source_sha256=known[name].get("source_sha256", ""),
            source_mtime=float(known[name].get("source_mtime") or 0.0),
        )
        print(f"[fona] adoption: {name!r} (team={team!r}) on port "
              f"{item.port}", file=sys.stderr, flush=True)
    return adopted


def load_team(path: str, *, start_flagged: bool = False,
              force_start: bool = False) -> Tuple[int, int]:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        payload = _json.load(f)
    version = payload.get("version")
    if version not in (1, 2, 3, 4):
        raise ValueError(f"unsupported team version: {version}")

    base_dir = os.path.dirname(path)
    loaded = 0
    flagged_ids: List[str] = []
    known: Dict[str, dict] = {}

    with _manager._lock:
        for d in payload.get("agents", []):
            try:
                entry = _dict_to_agent(d, base_dir)
            except Exception:
                continue
            if not os.path.isfile(entry.script):
                _log_action("log_script_missing",
                            name=entry.name, path=entry.script)
                continue
            known[entry.name] = {
                "id": entry.id,
                "script": entry.script,
                "autostart": entry.autostart,
                "orchestrator_template": entry.orchestrator_template,
                "env": entry.env,
                "source": entry.source,
                "source_sha256": entry.source_sha256,
                "source_mtime": entry.source_mtime,
            }
            existing = _manager.agents.get(entry.id)
            if existing is not None:
                was_adopted = existing.adopted
                was_port = existing.port
                existing.name = entry.name
                existing.script = entry.script
                existing.autostart = entry.autostart
                existing.orchestrator_template = \
                    entry.orchestrator_template
                existing.env = dict(entry.env)
                existing.source = entry.source
                existing.source_sha256 = entry.source_sha256
                existing.source_mtime = entry.source_mtime
                if was_adopted:
                    if was_port and _health_ok(
                            f"http://127.0.0.1:{was_port}", timeout=0.6):
                        existing.adopted = True
                        existing.process = None
                        existing.status = "online"
                        existing.port = was_port
                        existing.url = f"http://127.0.0.1:{was_port}"
                    else:
                        existing.adopted = False
                        existing.process = None
                        existing.status = "stopped"
                        existing.error = ""
                        existing.started_at = 0.0
                        existing.first_poll_starting_at = 0.0
                else:
                    existing.adopted = False
            else:
                _manager.agents[entry.id] = entry
                loaded += 1
            if entry.autostart:
                flagged_ids.append(entry.id)

    if _active_project is not None:
        adopted = _scan_and_adopt(_active_project, known)
        for name, entry in adopted.items():
            existing = _manager.agents.get(entry.id)
            if existing is not None:
                existing.port = entry.port
                existing.url = entry.url
                existing.status = "online"
                existing.adopted = True
                existing.process = None
                existing.started_at = _t.time()
                existing.error = ""
                existing.history = [1]
            else:
                _manager.agents[entry.id] = entry
                loaded += 1

    started = 0
    if start_flagged:
        if force_start:
            to_start = [a.id for a in _manager.list()]
        else:
            to_start = list(flagged_ids)
        for aid in to_start:
            a = _manager.get(aid)
            if a is None or (a.status == "online" and a.adopted):
                continue
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
    card_class = a.status
    if a.adopted:
        card_class = "adopted"
        badge_text = t(lang, "adopted_badge")

    open_html = (
        f'<a class="open-btn" href="{_esc(a.url)}" target="_blank" '
        f'rel="noopener">{t(lang, "open_ui")} \u2197</a>'
        if a.status == "online" else
        f'<button class="compact-btn" disabled '
        f'style="opacity:.4">{t(lang, "open_ui")}</button>'
    )
    orch_html = ""
    if a.orchestrator_template and a.orchestrator_gradio_port:
        orch_html = (
            f'<a class="open-btn orch" '
            f'href="http://127.0.0.1:{a.orchestrator_gradio_port}" '
            f'target="_blank" rel="noopener">'
            f'{t(lang, "open_orchestrator")} \u2197</a>'
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
    source_html = ""
    if a.source:
        src_status = _source_status(a)
        src_name = os.path.basename(a.source)
        src_extra = (f' <span class="badge source-warn">'
                     f'{_esc(t(lang, "source_changed" if src_status == "changed"
                               else "source_missing"))}</span>'
                     if src_status else "")
        update_link = (
            f' <a class="update-btn" '
            f'href="javascript:dashAction('
            f"'/dashboard/update_source?id={a.id}')"
            f'">{t(lang, "source_update")}</a>'
            if src_status == "changed" else ""
        )
        source_html = (
            f'<div class="kv"><span class="k">source</span>'
            f'<span class="v" title="{_esc(a.source)}">'
            f'{_esc(src_name)}{src_extra}{update_link}</span></div>'
        )
    orch_tpl_html = ""
    if a.orchestrator_template:
        orch_tpl_html = (
            f'<div class="kv"><span class="k">{t(lang, "orch_ui")}</span>'
            f'<span class="v" title="{_esc(a.orchestrator_template)}">'
            f'{_esc(os.path.basename(a.orchestrator_template))}</span></div>'
        )
    ratio = (f"{sum(a.history[-20:])}/{len(a.history[-20:])}"
             if a.history else "\u2014")
    autostart_checked = "checked" if a.autostart else ""
    confirm_text = t(lang, "confirm_remove", name=a.name)

    return f"""
<div class="card {card_class}">
  <div class="card-head">
    <div>
      <div class="card-title">{_esc(a.name)}</div>
      <div class="card-sub">{_esc(a.url or '—')}</div>
    </div>
    <span class="badge {card_class}">{badge_text}</span>
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
    {source_html}
    {orch_tpl_html}
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
            onclick="dashAction('/dashboard/remove?id={a.id}', {{confirm: &quot;{_esc(confirm_text)}&quot;}})">
      \U0001f5d1
    </button>
    <label class="compact-lbl" style="display:flex;align-items:center;gap:4px;"
           title="{t(lang, 'autostart_hint')}">
      <input type="checkbox" {autostart_checked}
             onchange="fetch('/dashboard/autostart?id={a.id}&value='+(this.checked?1:0),{{method:'POST'}}).then(function(){{window.fonaRefresh();}})">
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


def _render_live_tab(live: List[LiveAgent], lang: str) -> str:
    if not live:
        return (
            f'<div class="empty-state">'
            f'{t(lang, "no_live_agents")}</div>'
        )
    current_team = (_active_project.name
                    if _active_project is not None else None)
    rows = []
    for item in live:
        if item.error and not item.name:
            status = "error"
            status_label = t(lang, "error_status")
            name = "?"
            team = item.team_name or "—"
        else:
            status = "online"
            status_label = t(lang, "online")
            name = item.name or "?"
            team = item.team_name or "—"
        team_cls = (" team-ours" if (current_team and
                                     item.team_name == current_team) else "")
        pid = item.pid or 0
        rows.append(f"""
<div class="live-row {status}">
  <div class="live-cell live-team{team_cls}">{_esc(team)}</div>
  <div class="live-cell live-name"><b>{_esc(name)}</b></div>
  <div class="live-cell live-port">{item.port}</div>
  <div class="live-cell live-pid">{pid}</div>
  <div class="live-cell live-status">
    <span class="badge {status}">{status_label}</span>
  </div>
  <div class="live-cell live-actions">
    <a class="open-btn" href="{_esc(item.url)}" target="_blank"
       rel="noopener">{t(lang, "open_ui")} \u2197</a>
    <button class="compact-btn"
            onclick="dashAction('/dashboard/kill_live?port={item.port}',
                     {{confirm: 'Kill pid {pid} on port {item.port}?'}})">
      \U0001f5d1 {t(lang, "kill")}
    </button>
  </div>
</div>
""")
    header = (
        f'<div class="live-header">'
        f'<div class="live-cell live-team">{t(lang, "team_col")}</div>'
        f'<div class="live-cell live-name">{t(lang, "name_col")}</div>'
        f'<div class="live-cell live-port">{t(lang, "port_col")}</div>'
        f'<div class="live-cell live-pid">PID</div>'
        f'<div class="live-cell live-status">{t(lang, "status_col")}</div>'
        f'<div class="live-cell live-actions">{t(lang, "actions_col")}</div>'
        f'</div>'
    )
    return f'<div class="live-table">{header}{"".join(rows)}</div>'


# ============================================================================
# HTTP endpoints
# ============================================================================
def _attach_dashboard_routes(app):

    @app.get("/dashboard/project")
    async def dash_project_get():
        if _active_project is None:
            return {"active": False}
        return {
            "active": True,
            "root": _active_project.root,
            "name": _active_project.name,
            "team_file": _active_project.team_file,
            "port_range": list(_active_project.port_range),
            "agents_count": len(_manager.list()),
        }

    @app.post("/dashboard/project/create")
    async def dash_project_create(request: Request):
        body = await request.json()
        root = (body.get("root") or "").strip()
        name = (body.get("name") or "").strip()
        pr = body.get("port_range")
        if not root:
            return {"status": "error", "error": "root is required"}
        try:
            if isinstance(pr, (list, tuple)) and len(pr) == 2:
                port_range = (int(pr[0]), int(pr[1]))
            else:
                port_range = DEFAULT_PORT_RANGE
        except Exception:
            port_range = DEFAULT_PORT_RANGE
        try:
            global _active_project
            _manager.stop_all()
            _manager.agents.clear()
            _do_not_adopt.clear()
            _active_project = Project.create(root, name, port_range)
            _log_action("log_project_created", path=_active_project.root)
            return {"status": "ok", "root": _active_project.root,
                    "name": _active_project.name,
                    "port_range": list(_active_project.port_range)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @app.post("/dashboard/project/open")
    async def dash_project_open(request: Request):
        body = await request.json()
        root = (body.get("root") or "").strip()
        try:
            global _active_project
            project = Project.from_folder(root)
            _active_project = project
            try:
                killed = _kill_orphans_in_range(
                    project.port_range[0], project.port_range[1],
                    team_name=project.name)
                if killed:
                    _log_action("log_orphans_cleaned", n=killed)
            except Exception as e:
                print(f"[fona] orphan cleanup failed: {e}",
                      file=sys.stderr, flush=True)

            loaded, _ = load_team(project.team_file, start_flagged=False)
            _log_action("log_project_opened",
                        path=project.root, n=loaded)
            return {"status": "ok", "root": project.root,
                    "name": project.name, "loaded": loaded,
                    "port_range": list(project.port_range)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @app.post("/dashboard/project/close")
    async def dash_project_close():
        global _active_project
        _manager.stop_all()
        _manager.agents.clear()
        _active_project = None
        _do_not_adopt.clear()
        return {"status": "ok"}

    @app.post("/dashboard/start")
    async def dash_start(request: Request):
        aid = request.query_params.get("id")
        _manager.start(aid)
        a = _manager.get(aid)
        if a is not None and a.status != "error":
            _log_action("log_started", name=a.name, port=a.port)
        elif a is not None:
            _log_action("log_start_failed", name=a.name, reason=a.error)
        return {"status": "ok",
                "status_after": a.status if a else None,
                "port": a.port if a else None,
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

    @app.post("/dashboard/release")
    async def dash_release(request: Request):
        aid = request.query_params.get("id")
        a = _manager.get(aid)
        if a is None:
            return {"status": "error", "error": "not found"}
        _do_not_adopt.add(aid)
        a.adopted = False
        a.process = None
        a.status = "stopped"
        a.started_at = 0.0
        a.first_poll_starting_at = 0.0
        return {"status": "ok"}

    @app.post("/dashboard/kill_live")
    async def dash_kill_live(request: Request):
        try:
            port = int(request.query_params.get("port"))
        except (TypeError, ValueError):
            return {"status": "error", "error": "port required"}
        pid = _find_pid_by_port(port)
        if not pid:
            return {"status": "error", "error": "no listener"}
        image = _get_process_image(pid)
        if image and not image.lower().startswith("python"):
            return {"status": "error",
                    "error": f"not a python process: {image}"}
        _kill_pid(pid)
        _log_action("log_killed_live", pid=pid, port=port)
        return {"status": "ok", "pid": pid, "port": port}

    @app.post("/dashboard/autostart")
    async def dash_autostart(request: Request):
        val = request.query_params.get("value") in ("1", "true", "True")
        _manager.set_autostart(request.query_params.get("id"), val)
        return {"status": "ok"}

    @app.post("/dashboard/orchestrator_template")
    async def dash_orch_template(request: Request):
        aid = request.query_params.get("id")
        path = (request.query_params.get("path") or "").strip() or None
        _manager.set_orchestrator_template(aid, path)
        return {"status": "ok"}

    @app.post("/dashboard/update_source")
    async def dash_update_source(request: Request):
        aid = request.query_params.get("id")
        a = _manager.get(aid)
        if a is None or not a.source:
            return {"status": "error", "error": "no source"}
        if not os.path.isfile(a.source):
            return {"status": "error", "error": "source missing"}
        try:
            dest, status = _install_script(a.source)
            a.script = dest
            a.source_sha256 = _sha256(a.source)
            a.source_mtime = os.path.getmtime(a.source)
            if a.status in ("online", "starting"):
                _manager.restart(aid)
            _log_action("log_source_updated", name=a.name, path=dest)
            return {"status": "ok", "script": dest,
                    "sha": a.source_sha256, "copy_status": status}
        except Exception as e:
            return {"status": "error", "error": str(e)}

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
            "scripts_dir": _agents_dir(),
            "web_concurrency": os.environ.get("WEB_CONCURRENCY"),
            "uvicorn_reload": os.environ.get("UVICORN_RELOAD"),
            "strict_pid": os.environ.get("FONA_STRICT_PID"),
            "project": (
                {"root": _active_project.root,
                 "name": _active_project.name,
                 "team_file": _active_project.team_file,
                 "port_range": list(_active_project.port_range)}
                if _active_project is not None else None),
            "autodetected_teams": _autodetect_team_files(),
        }

    @app.post("/dashboard/teams/save")
    async def dash_team_save(request: Request):
        if _active_project is None:
            return {"status": "error",
                    "error": "no active project; create or open one first"}
        try:
            path = save_team("")
            _log_action("log_team_saved", path=path)
            return {"status": "ok", "path": path}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @app.post("/dashboard/teams/load")
    async def dash_team_load(request: Request):
        body = await request.json()
        if _active_project is None:
            return {"status": "error",
                    "error": "no active project; create or open one first"}
        try:
            start_flagged = bool(body.get(
                "start_flagged", body.get("autostart", False)))
            force_start = bool(body.get("force_start", start_flagged))
            path = _active_project.team_file
            loaded, started = load_team(
                path, start_flagged=start_flagged,
                force_start=force_start)
            if start_flagged:
                _log_action("log_team_loaded_started",
                            path=path, n=loaded, started=started)
            else:
                _log_action("log_team_loaded", path=path, n=loaded)
            return {"status": "ok",
                    "loaded": loaded,
                    "started": started}
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

    _blocks_kwargs = {"title": t(lang, "title")}
    if not _IS_GRADIO6:
        _blocks_kwargs["css"] = _GLOBAL_CSS
        _blocks_kwargs["head"] = _HEAD_DARK

    with gr.Blocks(**_blocks_kwargs) as demo:
        lang_state = gr.State(lang)

        with gr.Row(equal_height=False):

            with gr.Column(scale=2, min_width=340):
                # ---------------- Project (FIX X/Y) ----------------
                gr.HTML(f'<div class="col-head">\U0001f4c1 '
                        f'{t(lang, "project")}</div>')
                # FIX DD: three equal-width buttons in one row.
                # equal_height=False disables the flex-wrap that Gradio 5
                # applies to the inner .flex of a Row when equal_height
                # is True — that wrap is what pushed "Close" onto a new
                # line. min_width=0 lets the three buttons share width
                # equally (scale=1 each).
                with gr.Row(equal_height=False):
                    project_open_btn = gr.Button(
                        f"\U0001f4c2 {t(lang, 'project_open_btn')}",
                        size="sm", variant="primary",
                        scale=1, min_width=0,
                        elem_classes=["compact-btn"])
                    project_create_btn = gr.Button(
                        f"\u2795 {t(lang, 'project_create_btn')}",
                        size="sm",
                        scale=1, min_width=0,
                        elem_classes=["compact-btn"])
                    project_close_btn = gr.Button(
                        f"\u2716 {t(lang, 'project_close_btn')}",
                        size="sm",
                        scale=1, min_width=0,
                        elem_classes=["compact-btn"])
                project_status = gr.HTML(
                    _status_html(t(lang, "project_none")))

                # ---------------- Add agent ----------------
                # FIX CC: collapsed by default to keep the panel compact.
                with gr.Accordion(
                        f"\u2795 {t(lang, 'add_agent')}",
                        open=False):
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
                        new_orch_template_file = gr.File(
                            label=t(lang, "orch_template_optional"),
                            file_types=[".py"],
                            file_count="single",
                            type="filepath",
                            elem_classes=["compact-file"])
                    with gr.Row(equal_height=True):
                        new_orch_template = gr.Textbox(
                            placeholder=t(lang, "orch_template_placeholder"),
                            show_label=False, scale=4,
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

                # ---------------- Team save/load ----------------
                # FIX EE: "Load" (reload-only) removed. Reload-on-change
                # is now automatic in _refresh (see _maybe_reload_team);
                # "Load and start" covers the manual reload+start case.
                with gr.Row(equal_height=False):
                    team_save_btn = gr.Button(
                        f"\U0001f4be {t(lang, 'save')}",
                        size="sm", variant="primary", scale=1,
                        min_width=0,
                        elem_classes=["compact-btn"])
                    team_load_start_btn = gr.Button(
                        f"\u25b6 {t(lang, 'load_and_start')}",
                        size="sm", variant="primary", scale=1,
                        min_width=0,
                        elem_classes=["compact-btn"])
                team_status = gr.HTML(_status_html(""))

            with gr.Column(scale=5, min_width=520):
                with gr.Tabs():
                    with gr.Tab(t(lang, "tab_agents")):
                        with gr.Row(equal_height=True):
                            gr.HTML(f'<div class="col-head">\U0001f4ca '
                                    f'{t(lang, "agents")}</div>')
                            refresh_btn = gr.Button(
                                "\U0001f504", size="sm", scale=0,
                                min_width=0,
                                elem_classes=["compact-btn"],
                                elem_id="refresh_btn")
                        cards_html = gr.HTML(_render_cards(lang))
                        summary_json = gr.JSON(
                            show_label=False,
                            value=_status_dict(lang))
                    with gr.Tab(t(lang, "tab_adopted")):
                        with gr.Row(equal_height=True):
                            gr.HTML(f'<div class="col-head">\U0001f4e1 '
                                    f'{t(lang, "adopted_agents")}</div>')
                        live_html = gr.HTML(_render_live_tab([], lang))

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
            _maybe_reload_team()   # FIX EE: auto-pick up team.json edits
            for a in _manager.list():
                _manager.poll(a.id)
            live = _live_scan_any()
            return (
                _render_cards(lang_code),
                _status_dict(lang_code),
                _render_summary_chart(lang_code),
                _get_action_log(lang_code),
                _render_live_tab(live, lang_code),
            )

        demo.load(_refresh, [lang_state],
                  [cards_html, summary_json, summary_chart,
                   action_log, live_html])
        timer.tick(_refresh, [lang_state],
                   [cards_html, summary_json, summary_chart,
                    action_log, live_html])
        refresh_btn.click(_refresh, [lang_state],
                          [cards_html, summary_json, summary_chart,
                           action_log, live_html])

        # ------------------------------------------------------------------
        # Project actions: one-click open/create/close
        # ------------------------------------------------------------------
        def _status_project(lang_code: str) -> str:
            if _active_project is None:
                return _status_html(t(lang_code, "project_none"))
            n = len(_manager.list())
            rng = _active_project.port_range
            return _status_html(
                f"\u2713 {t(lang_code, 'project_summary', name=_active_project.name, n=n, start=rng[0], end=rng[1])}\n"
                f"{_active_project.root}")

        _project_outs = [project_status, cards_html, summary_json,
                         action_log, live_html]

        def _empty_project_view(lang_code):
            return (_status_project(lang_code),
                    _render_cards(lang_code),
                    _status_dict(lang_code),
                    _get_action_log(lang_code),
                    _render_live_tab(_live_scan_any(), lang_code))

        def _open_after_load(lang_code, project):
            global _active_project
            _active_project = project
            try:
                _kill_orphans_in_range(
                    project.port_range[0], project.port_range[1],
                    team_name=project.name)
            except Exception:
                pass
            try:
                load_team(project.team_file, start_flagged=False)
            except Exception as e:
                print(f"[fona] load after open failed: {e}",
                      file=sys.stderr, flush=True)
            # FIX GG: honor autostart on explicit project open.
            try:
                for a in list(_manager.list()):
                    if a.autostart and a.status != "online":
                        _manager.start(a.id)
            except Exception as e:
                print(f"[fona] autostart on open failed: {e}",
                      file=sys.stderr, flush=True)
            # FIX EE: remember mtime so _maybe_reload_team does not
            # fire immediately on the next 2s tick.
            try:
                _team_mtime_cache[project.team_file] = os.path.getmtime(
                    project.team_file)
            except OSError:
                _team_mtime_cache.pop(project.team_file, None)
            _log_action("log_project_opened",
                        path=project.root, n=len(_manager.list()))
            return _empty_project_view(lang_code)

        def _do_open_from_folder(lang_code, folder):
            try:
                project = Project.from_folder(folder)
            except FileNotFoundError:
                # No team.json in folder/subfolders: offer to create
                return _do_create_in_folder(lang_code, folder)
            except ValueError:
                gr.Warning(t(lang_code, "project_multi_found"))
                return _empty_project_view(lang_code)
            except Exception as e:
                gr.Warning(t(lang_code, "project_open_failed", msg=str(e)))
                return _empty_project_view(lang_code)
            return _open_after_load(lang_code, project)

        def _do_open_from_dialog(lang_code):
            folder = _pick_directory_dialog(
                t(lang_code, "project_dialog_open_title"))
            if not folder:
                return _empty_project_view(lang_code)
            return _do_open_from_folder(lang_code, folder)

        def _do_create_in_folder(lang_code, folder):
            try:
                global _active_project
                if not folder or not os.path.isdir(folder):
                    gr.Warning(t(lang_code, "project_path_required"))
                    return _empty_project_view(lang_code)
                if os.path.isfile(os.path.join(folder, "team.json")):
                    gr.Warning(t(lang_code, "project_create_exists"))
                    return _do_open_from_folder(lang_code, folder)
                project = Project.create(
                    folder, os.path.basename(folder), DEFAULT_PORT_RANGE)
                # FIX FF: save_team() requires _active_project; set it
                # first, then persist. The old code called save_team()
                # before assigning _active_project — that raised
                # RuntimeError("no active project") and the project was
                # never written to disk.
                _active_project = project
                save_team("")
                _log_action("log_project_created", path=project.root)
                return _empty_project_view(lang_code)
            except Exception as e:
                gr.Warning(t(lang_code, "project_create_invalid",
                             msg=str(e)))
                return _empty_project_view(lang_code)

        def _do_create_from_dialog(lang_code):
            folder = _pick_directory_dialog(
                t(lang_code, "project_dialog_create_title"))
            if not folder:
                return _empty_project_view(lang_code)
            return _do_create_in_folder(lang_code, folder)

        def _do_close(lang_code):
            global _active_project
            # FIX AA: release adopted but do not kill them
            for a in list(_manager.list()):
                if a.adopted:
                    _do_not_adopt.add(a.id)
                    a.adopted = False
                    a.process = None
                    a.status = "stopped"
                    a.started_at = 0.0
                    a.first_poll_starting_at = 0.0
            _manager.agents.clear()
            _active_project = None
            _team_mtime_cache.clear()
            _log_action("log_project_closed")
            return _empty_project_view(lang_code)

        project_open_btn.click(
            _do_open_from_dialog, [lang_state], _project_outs)
        project_create_btn.click(
            _do_create_from_dialog, [lang_state], _project_outs)
        project_close_btn.click(
            _do_close, [lang_state], _project_outs)

        new_script_browse.click(
            _pick_script_dialog, [], [new_script_manual])

        def _add(lang_code, file_obj, manual_path,
                 orch_tpl_file, orch_tpl_manual, name):
            try:
                if _active_project is None:
                    return _status_html(
                        f"\u2717 {t(lang_code, 'no_project')}")
                script_path = None
                source_path = ""
                source_sha = ""
                source_mtime = 0.0
                notes: List[str] = []

                manual = (manual_path or "").strip()
                if manual and os.path.isfile(manual):
                    script_path = manual
                    notes.append(t(lang_code, "using_source_in_place"))
                else:
                    uploaded = _file_to_path(file_obj)
                    if uploaded and os.path.isfile(uploaded):
                        tmp = os.path.abspath(tempfile.gettempdir())
                        is_temp = os.path.abspath(uploaded).startswith(
                            tmp + os.sep)
                        if is_temp:
                            dest, status = _install_script(uploaded)
                            script_path = dest
                            source_path = uploaded
                            source_sha = _sha256(uploaded)
                            source_mtime = os.path.getmtime(uploaded)
                            if status == "same":
                                notes.append(
                                    t(lang_code, "script_already_copied"))
                            elif status == "renamed":
                                notes.append(
                                    t(lang_code, "script_copied_renamed"))
                            else:
                                notes.append(
                                    t(lang_code, "script_copied"))
                        else:
                            script_path = uploaded
                            notes.append(
                                t(lang_code, "using_source_in_place"))

                if script_path is None:
                    return _status_html(
                        f"\u2717 {t(lang_code, 'no_script')}")

                orch_template = None
                manual_tpl = (orch_tpl_manual or "").strip()
                if manual_tpl and os.path.isfile(manual_tpl):
                    orch_template = manual_tpl
                else:
                    tpl_uploaded = _file_to_path(orch_tpl_file)
                    if tpl_uploaded and os.path.isfile(tpl_uploaded):
                        tmp = os.path.abspath(tempfile.gettempdir())
                        is_temp = os.path.abspath(tpl_uploaded).startswith(
                            tmp + os.sep)
                        if is_temp:
                            tpl_dest, _ = _install_script(tpl_uploaded)
                            orch_template = tpl_dest
                        else:
                            orch_template = tpl_uploaded

                entry = _manager.add(
                    script_path, name or "",
                    orch_template,
                )
                entry.source = source_path
                entry.source_sha256 = source_sha
                entry.source_mtime = source_mtime
                _log_action("log_added", name=entry.name)

                msg = f"\u2713 {entry.name}"
                if notes:
                    msg += "\n  " + "\n  ".join(notes)
                return _status_html(msg)
            except Exception as e:
                return _status_html(f"\u2717 {e}")

        add_btn.click(
            _add,
            [lang_state, new_script_file, new_script_manual,
             new_orch_template_file, new_orch_template, new_name],
            [add_status],
        ).then(
            _refresh, [lang_state],
            [cards_html, summary_json, summary_chart,
             action_log, live_html],
        )

        def _do_save(lang_code):
            try:
                if _active_project is None:
                    return (_status_html(
                                f"\u2717 {t(lang_code, 'no_project')}"),
                            _get_action_log(lang_code))
                path = save_team("")
                try:
                    _team_mtime_cache[path] = os.path.getmtime(path)
                except OSError:
                    _team_mtime_cache.pop(path, None)
                _log_action("log_team_saved", path=path)
                return (_status_html(
                            f"\u2713 {os.path.basename(path)}: "
                            f"{len(_manager.list())} agents"),
                        _get_action_log(lang_code))
            except Exception as e:
                return (_status_html(f"\u2717 {e}"),
                        _get_action_log(lang_code))

        team_save_btn.click(_do_save, [lang_state],
                            [team_status, action_log])

        def _do_load(lang_code, start_flagged):
            try:
                if _active_project is None:
                    return (_status_html(
                                f"\u2717 {t(lang_code, 'no_project')}"),
                            _render_cards(lang_code),
                            _status_dict(lang_code),
                            _get_action_log(lang_code),
                            _render_live_tab(_live_scan_any(), lang_code))
                path = _active_project.team_file
                loaded, started = load_team(
                    path, start_flagged=bool(start_flagged),
                    force_start=bool(start_flagged))
                if start_flagged:
                    _log_action("log_team_loaded_started",
                                path=path, n=loaded, started=started)
                else:
                    _log_action("log_team_loaded", path=path, n=loaded)
                live = _live_scan_any()
                msg = f"\u2713 +{loaded}"
                if start_flagged:
                    msg += f", started {started}"
                return (_status_html(msg),
                        _render_cards(lang_code),
                        _status_dict(lang_code),
                        _get_action_log(lang_code),
                        _render_live_tab(live, lang_code))
            except Exception as e:
                return (_status_html(f"\u2717 {e}"),
                        _render_cards(lang_code),
                        _status_dict(lang_code),
                        _get_action_log(lang_code),
                        _render_live_tab(_live_scan_any(), lang_code))

        team_load_start_btn.click(
            lambda lang_code: _do_load(lang_code, True),
            [lang_state],
            [team_status, cards_html, summary_json,
             action_log, live_html])

        return demo


# ============================================================================
# Launch
# ============================================================================
def launch(host: str = "127.0.0.1",
           port: int = 7861,
           inbrowser: bool = True,
           share: bool = False,
           **kwargs) -> None:
    _ensure_startup_project()
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
            head += (f'<link rel="icon" href="/favicon.ico'
                     f'?v={int(_t.time())}">')
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
        print("[fona] dashboard shutting down (children left running)",
              file=sys.stderr, flush=True)


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