"""Reusable orchestrator UI scaffold.

An "orchestrator" is an ordinary Fona agent with a Prolog program that
plays the role of a team lead. This module provides a *customizable*
Gradio UI on top of that agent — not a fixed view.

Customization points
--------------------
1. Config — where the agent lives, which endpoints to call.
2. Panels — named read-only views: (title, fetcher, renderer).
3. Actions — named buttons/forms: (title, handler).

By default the UI shows:
    * Chat (HITL)           — always present, talks to /api/v1/ui/*
    * Status                — connection + last error
    * Panels listed in the Config

Replace or extend the defaults; nothing here assumes "goal", "plan",
or "subordinates". Those are just example panels.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape as _esc
from typing import Any, Callable, Optional

import gradio as gr
import httpx


# ============================================================================
# Data model
# ============================================================================
Fetcher = Callable[["OrchestratorClient"], Any]
Renderer = Callable[[Any, str], str]          # (data, lang) -> HTML
ActionHandler = Callable[["OrchestratorClient", dict], Any]


@dataclass
class Panel:
    """A named read-only view: fetch data, render HTML."""
    key: str
    title_en: str
    title_ru: str
    fetcher: Fetcher
    renderer: Renderer
    refresh_sec: float = 1.0


@dataclass
class Action:
    """A named button/form that performs an HTTP call."""
    key: str
    title_en: str
    title_ru: str
    handler: ActionHandler
    # Optional: inputs for the form (empty = no form, just a button)
    inputs: list[dict] = field(default_factory=list)


@dataclass
class OrchestratorConfig:
    """Everything the UI needs to know about the agent."""
    base_url: str
    token: Optional[str] = None
    timeout: float = 5.0
    panels: list[Panel] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)


# ============================================================================
# HTTP client
# ============================================================================
class OrchestratorClient:
    def __init__(self, cfg: OrchestratorConfig):
        self.cfg = cfg
        self.base = cfg.base_url.rstrip("/")
        self.session_id: Optional[str] = None
        headers = {"X-API-Key": cfg.token} if cfg.token else {}
        self.http = httpx.Client(timeout=cfg.timeout, headers=headers)

    # ---- HITL ----
    def health(self) -> bool:
        try:
            return self.http.get(f"{self.base}/api/v1/health").status_code == 200
        except Exception:
            return False

    def start_session(self) -> bool:
        try:
            r = self.http.post(f"{self.base}/api/v1/ui/start")
            r.raise_for_status()
            self.session_id = r.json()["session_id"]
            return True
        except Exception:
            return False

    def stop_session(self):
        if self.session_id:
            try:
                self.http.post(f"{self.base}/api/v1/ui/stop",
                               params={"session_id": self.session_id})
            except Exception:
                pass
        self.session_id = None

    def send(self, text: str, ui_values: Optional[dict] = None) -> bool:
        if not self.session_id:
            return False
        try:
            r = self.http.post(f"{self.base}/api/v1/ui/input", json={
                "session_id": self.session_id,
                "text": text,
                "ui_values": ui_values or {},
            })
            return r.status_code == 200
        except Exception:
            return False

    def poll(self, timeout: float = 0.4) -> list[str]:
        if not self.session_id:
            return []
        msgs: list[str] = []
        try:
            with self.http.stream(
                "GET", f"{self.base}/api/v1/ui/stream",
                params={"session_id": self.session_id},
                timeout=httpx.Timeout(timeout, connect=1.0),
            ) as r:
                if r.status_code != 200:
                    return []
                buf: list[str] = []
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
                                msg = json.loads(evt_data).get("text", "")
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

    # ---- Generic request for custom panels/actions ----
    def get_json(self, path: str) -> Any:
        try:
            r = self.http.get(f"{self.base}{path}")
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def post_json(self, path: str, body: Any) -> Any:
        try:
            r = self.http.post(f"{self.base}{path}", json=body)
            if r.status_code == 200:
                try:
                    return r.json()
                except Exception:
                    return {"status": "ok"}
        except Exception:
            pass
        return None


# ============================================================================
# Default renderers
# ============================================================================
def render_kv(data: Any, lang: str) -> str:
    """Generic key-value renderer: {"key": value} -> card."""
    if not isinstance(data, dict) or not data:
        return _status_box("—")
    rows = "".join(
        f'<div style="display:flex;justify-content:space-between;gap:8px;'
        f'padding:2px 0;font-size:12px;">'
        f'<span style="color:#8b949e">{_esc(str(k))}</span>'
        f'<span style="font-family:ui-monospace,monospace">'
        f'{_esc(str(v))}</span></div>'
        for k, v in data.items()
    )
    return (f'<div class="orch-card">{rows}</div>')


def render_list(data: Any, lang: str) -> str:
    """Generic list renderer: [{title, status}] -> rows with dots."""
    if not isinstance(data, list) or not data:
        return _status_box("—")
    rows = []
    for item in data:
        if isinstance(item, dict):
            name = item.get("name") or item.get("title") or item.get("id") or "?"
            status = str(item.get("status", "")).lower()
            url = item.get("url", "")
            cls = "online" if status in ("online", "ok", "done") else \
                  "warn" if status in ("active", "running", "pending") else \
                  "offline"
            rows.append(
                f'<div class="agent-row">'
                f'<span class="agent-dot {cls}"></span>'
                f'<b>{_esc(str(name))}</b>'
                f'<span style="color:#8b949e;margin-left:auto">'
                f'{_esc(str(url))}</span></div>'
            )
        else:
            rows.append(f'<div class="agent-row">{_esc(str(item))}</div>')
    return f'<div class="agent-list">{"".join(rows)}</div>'


def render_kanban(data: Any, lang: str) -> str:
    """Kanban renderer: [{title, status}] grouped by status."""
    if not isinstance(data, list):
        return _status_box("—")
    groups: dict[str, list] = {}
    for item in data:
        status = str((item or {}).get("status", "pending")).lower()
        groups.setdefault(status, []).append(item)
    order = ["pending", "active", "done", "failed"]
    cols = []
    for key in order:
        items = groups.get(key, [])
        title = key.capitalize()
        body = "".join(
            f'<div class="task-item {key}">'
            f'{_esc(str(x.get("title") or x.get("id") or "?"))}</div>'
            for x in items
        ) or f'<div class="task-empty">—</div>'
        cols.append(f'<div class="task-col"><h4>{title} ({len(items)})</h4>'
                    f'{body}</div>')
    return f'<div class="task-board">{"".join(cols)}</div>'


def _status_box(s: str) -> str:
    return f'<pre class="status-box">{_esc(str(s))}</pre>'


# ============================================================================
# UI builder
# ============================================================================
def build_ui(cfg: OrchestratorConfig, lang: str = "en") -> gr.Blocks:
    """Build a Gradio UI for an orchestrator agent.

    Layout:
        top bar: URL + Connect + Refresh
        left  : chat (HITL) — always present
        right : panels (from cfg.panels) + status

    The user replaces panels/actions in cfg; the UI does not assume
    any domain ("goal", "plan", "subordinates" are just examples).
    """
    client = OrchestratorClient(cfg)
    state = {"client": client, "lang": lang}

    _blocks_kwargs = {"title": "Orchestrator UI"}
    try:
        _blocks_kwargs["css"] = _CSS
        _blocks_kwargs["head"] = _HEAD_DARK
    except Exception:
        pass

    with gr.Blocks(**_blocks_kwargs) as demo:
        # ---------- Top bar ----------
        with gr.Row(equal_height=True):
            gr.HTML('<div class="col-head">\U0001f3af Orchestrator</div>')
            url_box = gr.Textbox(
                value=cfg.base_url, show_label=False, scale=4,
                elem_classes=["compact-tb"],
            )
            connect_btn = gr.Button(
                f"\U0001f517 {_t(lang, 'connect')}", size="sm",
                variant="primary", scale=1,
                elem_classes=["compact-btn"])
            refresh_btn = gr.Button(
                "\U0001f504", size="sm", scale=0, min_width=0,
                elem_classes=["compact-btn"],
                elem_id="orch_refresh_btn")
        status_html = gr.HTML(_status_box(_t(lang, "not_connected")))

        # ---------- Two areas: chat (left) + panels (right) ----------
        with gr.Row(equal_height=False):
            with gr.Column(scale=4, min_width=420):
                gr.HTML(f'<div class="col-head">\U0001f4ac '
                        f'{_t(lang, "chat")}</div>')
                chatbot = gr.Chatbot(
                    height=420, show_label=False,
                    elem_classes=["chat-panel"],
                    **({"type": "messages"}
                       if not _IS_GRADIO6 else {}))
                with gr.Row(equal_height=True):
                    user_msg = gr.Textbox(
                        placeholder=_t(lang, "message_placeholder"),
                        show_label=False, scale=4,
                        elem_classes=["compact-tb"])
                    send_btn = gr.Button(
                        f"\u25b6 {_t(lang, 'send')}", size="sm",
                        variant="primary", scale=1,
                        elem_classes=["compact-btn"])

                # Actions: buttons/forms provided by the user
                if cfg.actions:
                    gr.HTML('<div class="col-head">\u26a1 Actions</div>')
                    with gr.Row(equal_height=True):
                        for action in cfg.actions:
                            gr.Button(
                                _t2(lang, action.title_en, action.title_ru),
                                size="sm", scale=1,
                                elem_classes=["compact-btn"],
                            ).click(
                                _make_action_handler(action),
                                [],
                                [status_html],
                            )

            with gr.Column(scale=5, min_width=480):
                panel_outputs = []
                for panel in cfg.panels:
                    gr.HTML(f'<div class="col-head">{_esc(panel.title_en if lang == "en" else panel.title_ru)}</div>')
                    out = gr.HTML(panel.renderer(panel.fetcher(client), lang))
                    panel_outputs.append(out)

                gr.HTML(f'<div class="col-head">\U0001f4cb '
                        f'{_t(lang, "logs")}</div>')
                logs_out = gr.Textbox(
                    show_label=False, lines=8, interactive=False,
                    elem_classes=["compact-tb"])

        timer = gr.Timer(1.0)

        # ---------- Handlers ----------
        def _connect(url):
            url = (url or "").strip() or cfg.base_url
            client.cfg.base_url = url
            client.base = url.rstrip("/")
            client.stop_session()
            if not client.health():
                return _status_box(
                    f"\u2717 {_t(lang, 'connect_error')}: {url}")
            if not client.start_session():
                return _status_box(
                    f"\u2717 {_t(lang, 'connect_error')}: session start")
            # refresh all panels
            for panel, out in zip(cfg.panels, panel_outputs):
                try:
                    out.value = panel.renderer(panel.fetcher(client), lang)
                except Exception:
                    pass
            return _status_box(f"\u2713 {_t(lang, 'connected')}: {url}")

        connect_btn.click(_connect, [url_box], [status_html])

        def _refresh():
            results = []
            for panel in cfg.panels:
                try:
                    data = panel.fetcher(client)
                except Exception:
                    data = None
                results.append(panel.renderer(data, lang))
            return results

        refresh_btn.click(_refresh, [], panel_outputs)

        def _send(text, history):
            text = (text or "").strip()
            if not text:
                return history, ""
            if client.send(text):
                history = list(history or []) + [
                    {"role": "user", "content": text}]
            return history, ""

        send_btn.click(_send, [user_msg, chatbot], [chatbot, user_msg])
        user_msg.submit(_send, [user_msg, chatbot], [chatbot, user_msg])

        def _poll(history, logs):
            new_msgs = client.poll()
            history = list(history or [])
            for m in new_msgs:
                history.append({"role": "assistant", "content": m})
            base = (logs or "").rstrip("\n")
            if new_msgs:
                base = (base + "\n" + "\n".join(new_msgs))[-8000:]
            return history, base

        timer.tick(_poll, [chatbot, logs_out], [chatbot, logs_out])

        return demo


def _make_action_handler(action: Action):
    def handler():
        client = _current_client()
        if client is None:
            return _status_box("not connected")
        try:
            result = action.handler(client, {})
            return _status_box(str(result) if result is not None else "ok")
        except Exception as e:
            return _status_box(f"error: {e}")
    return handler


# ============================================================================
# Launch
# ============================================================================
def launch(cfg: OrchestratorConfig,
           host: str = "127.0.0.1",
           port: int = 8010,
           lang: str = "en") -> None:
    ui = build_ui(cfg, lang)
    ui.launch(server_name=host, server_port=port, inbrowser=True)


# ============================================================================
# Small helpers
# ============================================================================
def _t(lang: str, key: str) -> str:
    table = {
        "en": {"connect": "Connect", "connected": "Connected",
               "not_connected": "Not connected",
               "connect_error": "Connect error",
               "chat": "Chat", "send": "Send", "logs": "Logs",
               "message_placeholder": "Message..."},
        "ru": {"connect": "Подключиться", "connected": "Подключено",
               "not_connected": "Не подключено",
               "connect_error": "Ошибка подключения",
               "chat": "Диалог", "send": "Отправить", "logs": "Логи",
               "message_placeholder": "Сообщение..."},
    }
    return (table.get(lang) or table["en"]).get(key, key)


def _t2(lang: str, en: str, ru: str) -> str:
    return en if lang == "en" else ru