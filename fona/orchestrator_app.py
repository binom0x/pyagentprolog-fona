"""Fona Orchestrator — extended Gradio UI for an orchestrator agent.

Runs as a separate process, talks to the orchestrator's HTML UI via:
  * /api/v1/ui/*        — chat (HITL session)
  * /orch/*             — orchestration state (goal, tasks, subordinates)

Three-column layout (same as fona/dashboard.py):
  * left   (scale=2): Goal + input + Open HTML
  * center (scale=5): Plan (3 task columns) + Chat
  * right  (scale=2): Logs + Subordinates + connection status

System-language detection, no manual switcher.

Run:
    python -m fona.orchestrator_app --orchestrator http://127.0.0.1:8000 \
                                    --port 8010
    FONA_DASHBOARD_LANG=ru python -m fona.orchestrator_app \
        --orchestrator http://127.0.0.1:8000 --port 8010
"""
from __future__ import annotations

import argparse
import json
import locale as _locale
import os
import sys
import time as _t
from html import escape as _esc
from typing import List, Optional

import gradio as gr
import httpx


# ============================================================================
# i18n
# ============================================================================
TRANSLATIONS = {
    "en": {
        "title": "Fona Orchestrator",
        "orchestrator": "Orchestrator",
        "connect": "Connect",
        "open_html": "Open HTML",
        "goal": "Goal",
        "no_goal": "No goal set. Enter below.",
        "goal_placeholder": "Describe the task for the orchestrator...",
        "set_goal": "Set",
        "plan": "Plan",
        "subordinates": "Subordinates",
        "chat": "Chat with orchestrator",
        "message_placeholder": "Message to orchestrator...",
        "send": "Send",
        "logs": "Logs",
        "status": "Status",
        "not_connected": "Not connected",
        "connected": "Connected",
        "pending": "Pending",
        "active": "Active",
        "done": "Done",
        "failed": "Failed",
        "empty_col": "empty",
        "errors": "Errors",
        "no_subordinates": "No subordinates configured.",
        "goal_set": "Goal set",
        "connect_error": "Connect error",
        "url_placeholder": "http://127.0.0.1:8000",
        "refresh": "Refresh",
        "env_hint": (
            "Orchestrator URL from --orchestrator / FONA_ORCHESTRATOR. "
            "Click Connect to open a HITL session."),
    },
    "ru": {
        "title": "Оркестратор Fona",
        "orchestrator": "Оркестратор",
        "connect": "Подключиться",
        "open_html": "Открыть HTML",
        "goal": "Цель",
        "no_goal": "Цель не задана. Введите ниже.",
        "goal_placeholder": "Опишите задачу для оркестратора...",
        "set_goal": "Установить",
        "plan": "План",
        "subordinates": "Подчинённые",
        "chat": "Диалог с оркестратором",
        "message_placeholder": "Сообщение оркестратору...",
        "send": "Отправить",
        "logs": "Логи",
        "status": "Состояние",
        "not_connected": "Не подключено",
        "connected": "Подключено",
        "pending": "Ожидает",
        "active": "В работе",
        "done": "Готово",
        "failed": "Ошибка",
        "empty_col": "пусто",
        "errors": "Ошибок",
        "no_subordinates": "Подчинённые не заданы.",
        "goal_set": "Цель установлена",
        "connect_error": "Ошибка подключения",
        "url_placeholder": "http://127.0.0.1:8000",
        "refresh": "Обновить",
        "env_hint": (
            "URL оркестратора берётся из --orchestrator / FONA_ORCHESTRATOR. "
            "Нажмите «Подключиться», чтобы открыть HITL-сессию."),
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    table = TRANSLATIONS.get(lang) or TRANSLATIONS["en"]
    template = table.get(key) or TRANSLATIONS["en"].get(key, key)
    return template.format(**kwargs) if kwargs else template


# ============================================================================
# System language detection (same logic as fona/dashboard.py)
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

_CHATBOT_KWARGS = {
    "height": 380, "show_label": False,
    "elem_classes": ["chat-panel"],
}
if not _IS_GRADIO6:
    _CHATBOT_KWARGS["type"] = "messages"


# ============================================================================
# CSS — same palette and control classes as fona/dashboard.py
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
.env-hint {
    font-size: 11px; color: #8b949e; line-height: 1.35;
    padding: 2px 4px; margin: 2px 0 6px 0;
}
.chat-panel { background: #0b0d11 !important;
              border: 1px solid #2a313d !important;
              border-radius: 4px !important; }
*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-thumb { background: #2a313d; border-radius: 5px; }

.goal-card {
    padding: 10px; background: #0f1115;
    border: 1px solid #2a313d; border-radius: 6px;
    font-size: 13px; color: #c7cbd1;
}
.goal-card .goal-label { color: #8b949e; font-size: 11px;
                          margin-bottom: 4px; }

.task-board { display: grid; grid-template-columns: repeat(3, 1fr);
              gap: 8px; margin: 4px 0; }
.task-col { background: #0f1115; border: 1px solid #2a313d;
            border-radius: 6px; padding: 8px; min-height: 160px; }
.task-col h4 { margin: 0 0 6px 0; font-size: 12px;
               color: #8b949e; font-weight: 600;
               text-transform: uppercase; letter-spacing: .5px; }
.task-item { background: #161a20; border: 1px solid #2a313d;
             border-radius: 4px; padding: 6px 8px; margin-bottom: 4px;
             font-size: 12px; color: #c7cbd1; }
.task-item.done   { border-left: 3px solid #238636; }
.task-item.active { border-left: 3px solid #d29922; }
.task-item.failed { border-left: 3px solid #d73a49; }
.task-empty { color: #484f58; font-size: 11px;
              text-align: center; padding: 8px; }

.agent-list { background: #0f1115; border: 1px solid #2a313d;
              border-radius: 6px; padding: 4px 0; }
.agent-row { display: flex; align-items: center; gap: 8px;
             padding: 4px 8px; border-bottom: 1px solid #161a20;
             font-size: 12px; color: #c7cbd1; }
.agent-row:last-child { border-bottom: none; }
.agent-dot { width: 8px; height: 8px; border-radius: 50%; }
.agent-dot.online { background: #238636; }
.agent-dot.offline { background: #d73a49; }
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
# Orchestrator client
# ============================================================================
class OrchestratorClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.session_id: Optional[str] = None

    def health(self) -> bool:
        try:
            r = httpx.get(f"{self.base}/api/v1/health", timeout=0.8)
            return r.status_code == 200
        except Exception:
            return False

    def start(self) -> bool:
        try:
            r = httpx.post(f"{self.base}/api/v1/ui/start", timeout=5.0)
            r.raise_for_status()
            self.session_id = r.json()["session_id"]
            return True
        except Exception:
            return False

    def stop(self):
        if self.session_id:
            try:
                httpx.post(f"{self.base}/api/v1/ui/stop",
                           params={"session_id": self.session_id},
                           timeout=3.0)
            except Exception:
                pass
        self.session_id = None

    def send(self, text: str) -> bool:
        if not self.session_id:
            return False
        try:
            r = httpx.post(f"{self.base}/api/v1/ui/input",
                           json={"session_id": self.session_id,
                                 "text": text, "ui_values": {}},
                           timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    def poll(self, timeout: float = 0.4) -> List[str]:
        if not self.session_id:
            return []
        msgs: List[str] = []
        try:
            with httpx.stream(
                "GET", f"{self.base}/api/v1/ui/stream",
                params={"session_id": self.session_id},
                timeout=httpx.Timeout(timeout, connect=1.0),
            ) as r:
                if r.status_code != 200:
                    return []
                buf: List[str] = []
                for line in r.iter_lines():
                    buf.append(line)
                    if line == "":
                        evt_type, evt_data = "message", ""
                        for l in buf:
                            if l.startswith("event: "):
                                evt_type = l[7:].strip()
                            elif l.startswith("data: "):
                                evt_data += l[6:]
                        buf = []
                        if evt_type == "output":
                            try:
                                d = json.loads(evt_data)
                                msg = d.get("text", "")
                                if msg and not msg.startswith(
                                        "Agent finished execution"):
                                    msgs.append(msg)
                            except Exception:
                                pass
        except (httpx.TimeoutException, httpx.ReadTimeout):
            pass
        except Exception:
            pass
        return msgs

    def get_goal(self) -> str:
        try:
            r = httpx.get(f"{self.base}/orch/current_goal", timeout=1.0)
            if r.status_code == 200:
                return r.json().get("goal", "")
        except Exception:
            pass
        return ""

    def set_goal(self, goal: str) -> bool:
        try:
            r = httpx.post(f"{self.base}/orch/goal",
                           json={"goal": goal}, timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def get_tasks(self) -> List[dict]:
        try:
            r = httpx.get(f"{self.base}/orch/tasks", timeout=1.0)
            if r.status_code == 200:
                return r.json().get("tasks", [])
        except Exception:
            pass
        return []

    def get_subordinates(self) -> List[dict]:
        try:
            r = httpx.get(f"{self.base}/orch/subordinates", timeout=1.0)
            if r.status_code == 200:
                return r.json().get("agents", [])
        except Exception:
            pass
        return []


_state = {"client": None}


# ============================================================================
# Rendering
# ============================================================================
def _status_html(s: str) -> str:
    return f'<pre class="status-box">{_esc(str(s))}</pre>'


def _render_goal(lang: str) -> str:
    client: Optional[OrchestratorClient] = _state["client"]
    goal = client.get_goal() if client else ""
    if not goal:
        return _status_html(t(lang, "no_goal"))
    return (
        f'<div class="goal-card">'
        f'<div class="goal-label">\U0001f3af {_esc(t(lang, "goal"))}</div>'
        f'<div>{_esc(goal)}</div>'
        f'</div>'
    )


def _render_tasks(lang: str) -> str:
    client: Optional[OrchestratorClient] = _state["client"]
    tasks = client.get_tasks() if client else []
    groups = {"pending": [], "active": [], "done": [], "failed": []}
    for task in tasks:
        status = (task.get("status") or "pending").lower()
        if status in ("done", "completed"):
            groups["done"].append(task)
        elif status in ("failed", "error"):
            groups["failed"].append(task)
        elif status in ("active", "in_progress", "running"):
            groups["active"].append(task)
        else:
            groups["pending"].append(task)

    def col(title: str, items: list, cls: str) -> str:
        body = "".join(
            f'<div class="task-item {cls}">'
            f'{_esc(x.get("title") or x.get("id") or "?")}'
            f'</div>'
            for x in items
        ) or f'<div class="task-empty">{t(lang, "empty_col")}</div>'
        return (f'<div class="task-col"><h4>{title} ({len(items)})</h4>'
                f'{body}</div>')

    html = (
        '<div class="task-board">'
        + col(f'\u23f3 {t(lang, "pending")}', groups["pending"], "active")
        + col(f'\u2699 {t(lang, "active")}', groups["active"], "active")
        + col(f'\u2705 {t(lang, "done")}', groups["done"], "done")
        + "</div>"
    )
    if groups["failed"]:
        html += (
            f'<div style="color:#ff7b72;font-size:11px;margin-top:4px">'
            f'\u26a0 {t(lang, "errors")}: {len(groups["failed"])}</div>'
        )
    return html


def _render_subordinates(lang: str) -> str:
    client: Optional[OrchestratorClient] = _state["client"]
    subs = client.get_subordinates() if client else []
    if not subs:
        return _status_html(t(lang, "no_subordinates"))
    rows = []
    for a in subs:
        status = a.get("status", "unknown")
        cls = "online" if status == "online" else "offline"
        rows.append(
            f'<div class="agent-row">'
            f'<span class="agent-dot {cls}"></span>'
            f'<b>{_esc(a.get("name", "?"))}</b>'
            f'<span style="color:#8b949e;margin-left:auto">'
            f'{_esc(a.get("url", ""))}</span>'
            f'</div>'
        )
    return f'<div class="agent-list">{"".join(rows)}</div>'


# ============================================================================
# UI
# ============================================================================
def build_ui() -> gr.Blocks:
    lang = _detect_system_lang()
    print(f"[fona] orchestrator language: {lang} "
          f"(override: FONA_DASHBOARD_LANG=en|ru)",
          file=sys.stderr, flush=True)

    _blocks_kwargs = {"title": t(lang, "title")}
    if not _IS_GRADIO6:
        _blocks_kwargs["css"] = _GLOBAL_CSS
        _blocks_kwargs["head"] = _HEAD_DARK

    with gr.Blocks(**_blocks_kwargs) as demo:

        # ---------- Top bar: URL + Connect + Refresh ----------
        with gr.Row(equal_height=True):
            gr.HTML(f'<div class="col-head">\U0001f3af '
                    f'{t(lang, "orchestrator")}</div>')
            orch_url = gr.Textbox(
                value=os.getenv("FONA_ORCHESTRATOR",
                                "http://127.0.0.1:8000"),
                placeholder=t(lang, "url_placeholder"),
                show_label=False, scale=4,
                elem_classes=["compact-tb"],
            )
            connect_btn = gr.Button(
                f"\U0001f517 {t(lang, 'connect')}", size="sm",
                variant="primary", scale=1,
                elem_classes=["compact-btn"])
            refresh_btn = gr.Button(
                "\U0001f504", size="sm", scale=0, min_width=0,
                elem_classes=["compact-btn"],
                elem_id="orch_refresh_btn")
        gr.HTML(f'<div class="env-hint">{t(lang, "env_hint")}</div>')

        # ---------- Three columns ----------
        with gr.Row(equal_height=False):

            # -------- Left: Goal + input + Open HTML --------
            with gr.Column(scale=2, min_width=340):
                gr.HTML(f'<div class="col-head">\U0001f3af '
                        f'{t(lang, "goal")}</div>')
                goal_html = gr.HTML(_render_goal(lang))

                with gr.Row(equal_height=True):
                    goal_input = gr.Textbox(
                        placeholder=t(lang, "goal_placeholder"),
                        show_label=False, lines=2, scale=4,
                        elem_classes=["compact-tb"])
                    set_goal_btn = gr.Button(
                        f"{t(lang, 'set_goal')}", size="sm",
                        variant="primary", scale=1,
                        elem_classes=["compact-btn"])

                with gr.Row(equal_height=True):
                    html_btn = gr.Button(
                        f"{t(lang, 'open_html')} \u2197", size="sm",
                        scale=1, elem_classes=["compact-btn"])

            # -------- Center: Plan + Chat --------
            with gr.Column(scale=5, min_width=520):
                gr.HTML(f'<div class="col-head">\U0001f4cb '
                        f'{t(lang, "plan")}</div>')
                tasks_html = gr.HTML(_render_tasks(lang))

                gr.HTML(f'<div class="col-head">\U0001f4ac '
                        f'{t(lang, "chat")}</div>')
                chatbot = gr.Chatbot(**_CHATBOT_KWARGS)

                with gr.Row(equal_height=True):
                    user_msg = gr.Textbox(
                        placeholder=t(lang, "message_placeholder"),
                        show_label=False, scale=4,
                        elem_classes=["compact-tb"])
                    send_btn = gr.Button(
                        f"\u25b6 {t(lang, 'send')}", size="sm",
                        variant="primary", scale=1,
                        elem_classes=["compact-btn"])

            # -------- Right: Logs + Subordinates + Status --------
            with gr.Column(scale=2, min_width=300):
                gr.HTML(f'<div class="col-head">\U0001f4cb '
                        f'{t(lang, "logs")}</div>')
                logs_out = gr.Textbox(
                    show_label=False, lines=12, interactive=False,
                    elem_classes=["compact-tb"])

                gr.HTML(f'<div class="col-head">\U0001f916 '
                        f'{t(lang, "subordinates")}</div>')
                subs_html = gr.HTML(_render_subordinates(lang))

                gr.HTML(f'<div class="col-head">\U0001f4a1 '
                        f'{t(lang, "status")}</div>')
                status_html = gr.HTML(
                    _status_html(t(lang, "not_connected")))

        timer = gr.Timer(0.6)

        # ============================================================
        # Connect
        # ============================================================
        def _connect(url):
            url = (url or "").strip()
            if _state["client"] is not None:
                _state["client"].stop()
                _state["client"] = None
            client = OrchestratorClient(url)
            if not client.health():
                return (
                    _status_html(
                        f"\u2717 {t(lang, 'connect_error')}: {url}"),
                    _render_goal(lang),
                    _render_tasks(lang),
                    _render_subordinates(lang),
                )
            if not client.start():
                return (
                    _status_html(
                        f"\u2717 {t(lang, 'connect_error')}: session start"),
                    _render_goal(lang),
                    _render_tasks(lang),
                    _render_subordinates(lang),
                )
            _state["client"] = client
            return (
                _status_html(f"\u2713 {t(lang, 'connected')}: {url}"),
                _render_goal(lang),
                _render_tasks(lang),
                _render_subordinates(lang),
            )

        connect_btn.click(
            _connect, [orch_url],
            [status_html, goal_html, tasks_html, subs_html])

        # ============================================================
        # Open HTML
        # ============================================================
        def _open_html(url):
            url = (url or "").strip() or "http://127.0.0.1:8000"
            return f'<script>window.open("{_esc(url)}", "_blank");</script>'

        html_btn.click(_open_html, [orch_url], [status_html])

        # ============================================================
        # Refresh
        # ============================================================
        def _refresh():
            return (
                _render_goal(lang),
                _render_tasks(lang),
                _render_subordinates(lang),
            )

        refresh_btn.click(
            _refresh, [],
            [goal_html, tasks_html, subs_html])

        # ============================================================
        # Set goal
        # ============================================================
        def _set_goal(goal):
            client: Optional[OrchestratorClient] = _state["client"]
            if client is None:
                return (_render_goal(lang),
                        _status_html(t(lang, "not_connected")))
            ok = client.set_goal(goal or "")
            return (
                _render_goal(lang),
                _status_html(f"\u2713 {t(lang, 'goal_set')}"
                             if ok else "\u2717"),
            )

        set_goal_btn.click(
            _set_goal, [goal_input],
            [goal_html, status_html])

        # ============================================================
        # Chat
        # ============================================================
        def _send(text, history):
            text = (text or "").strip()
            client: Optional[OrchestratorClient] = _state["client"]
            if not text or client is None:
                return history, ""
            if client.send(text):
                history = list(history or []) + [
                    {"role": "user", "content": text}]
            return history, ""

        send_btn.click(
            _send, [user_msg, chatbot],
            [chatbot, user_msg])
        user_msg.submit(
            _send, [user_msg, chatbot],
            [chatbot, user_msg])

        # ============================================================
        # Polling
        # ============================================================
        def _poll(history, logs):
            client: Optional[OrchestratorClient] = _state["client"]
            if client is None:
                return history, logs, _render_tasks(lang)
            new_msgs = client.poll()
            history = list(history or [])
            for m in new_msgs:
                history.append({"role": "assistant", "content": m})
            base = (logs or "").rstrip("\n")
            if new_msgs:
                base = (base + "\n" + "\n".join(new_msgs))[-8000:]
            return history, base, _render_tasks(lang)

        timer.tick(
            _poll, [chatbot, logs_out],
            [chatbot, logs_out, tasks_html])

        return demo


# ============================================================================
# Launch
# ============================================================================
def launch(host: str = "127.0.0.1",
           port: int = 8010,
           inbrowser: bool = True,
           share: bool = False,
           **kwargs) -> None:
    ui = build_ui()
    launch_kwargs = dict(
        server_name=host, server_port=port,
        inbrowser=False, share=share,
    )
    if _IS_GRADIO6:
        launch_kwargs["css"] = _GLOBAL_CSS
        launch_kwargs["head"] = _HEAD_DARK
    launch_kwargs.update(kwargs)
    if "inbrowser" in kwargs:
        launch_kwargs["inbrowser"] = False
    ui.launch(**launch_kwargs)

    if inbrowser:
        try:
            import webbrowser
            webbrowser.open(f"http://{host}:{port}/")
        except Exception:
            pass


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="fona-orchestrator")
    parser.add_argument("--orchestrator", default="http://127.0.0.1:8000")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--share", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    os.environ.setdefault("FONA_ORCHESTRATOR", args.orchestrator)
    launch(host=args.host, port=args.port,
           share=args.share, inbrowser=not args.no_browser)


if __name__ == "__main__":
    main()