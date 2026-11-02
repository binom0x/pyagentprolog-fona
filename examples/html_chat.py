"""Чат-бот на Fona + vanilla HTML/JS + SSE."""
import asyncio
import json
import threading
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from fona import Agent
from fona.agent import _clone_model
from prolog.proagent_gradio import (
    AgentGradioSession, get_session, register_session,
    remove_session, send_input_to_agent,
)


# -------------------------------------------------------------------
# Агент и модель
# -------------------------------------------------------------------
chat_agent = Agent()

@chat_agent.program
PROGRAM = """
run :- greeting, loop.

greeting :-
    ui_print('Привет! Я Fona-бот. Напиши "stop" для выхода.').

loop :-
    ui_read(Input),
    handle(Input).

handle("stop") :- !, ui_print('До свидания!').
handle(Text) :-
    echo(Text, Reply),
    ui_print(Reply),
    loop.
"""

@chat_agent.action
def echo(text):
    return f"Ты сказал: {text}"


_MODEL = chat_agent.build(with_ui=True)
_SESSIONS: dict[str, AgentGradioSession] = {}
_LOCK = threading.Lock()


def _new_session() -> str:
    sid = str(uuid.uuid4())
    sess = AgentGradioSession()
    with _LOCK:
        _SESSIONS[sid] = sess
    clone = _clone_model(_MODEL)
    sess.start(clone.agent, query="run.")
    return sid


def _drop(sid: str):
    with _LOCK:
        sess = _SESSIONS.pop(sid, None)
    if sess:
        sess.stop()


# -------------------------------------------------------------------
# FastAPI
# -------------------------------------------------------------------
class _Input(BaseModel):
    session_id: str
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from prolog.arith_numba import warmup_arith_numba
        warmup_arith_numba()
    except Exception:
        pass
    yield


app = FastAPI(title="Fona Chat", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    return CHAT_HTML


@app.post("/api/chat/start")
async def chat_start():
    return {"session_id": _new_session()}


@app.post("/api/chat/input")
async def chat_input(req: _Input):
    with _LOCK:
        sess = _SESSIONS.get(req.session_id)
    if not sess:
        raise HTTPException(404, "session not found")
    if not sess.running:
        raise HTTPException(409, "session ended")
    send_input_to_agent(req.session_id, req.text)
    return {"status": "ok"}


@app.post("/api/chat/stop")
async def chat_stop(session_id: str):
    _drop(session_id)
    return {"status": "ok"}


@app.get("/api/chat/stream")
async def chat_stream(session_id: str):
    with _LOCK:
        if session_id not in _SESSIONS:
            raise HTTPException(404, "session not found")

    async def gen():
        yield 'event: state\ndata: {"running": true}\n\n'
        while True:
            with _LOCK:
                sess = _SESSIONS.get(session_id)
            if sess is None:
                yield 'event: state\ndata: {"running": false, "removed": true}\n\n'
                return

            for msg in sess.get_output():
                text = str(msg)
                if text.startswith("Agent finished execution"):
                    continue
                yield (f'event: message\n'
                       f'data: {json.dumps({"text": text}, ensure_ascii=False)}\n\n')

            if not sess.running:
                for msg in sess.get_output():
                    text = str(msg)
                    if text.startswith("Agent finished execution"):
                        continue
                    yield (f'event: message\n'
                           f'data: {json.dumps({"text": text}, ensure_ascii=False)}\n\n')
                yield 'event: state\ndata: {"running": false, "finished": true}\n\n'
                return

            await asyncio.sleep(0.15)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -------------------------------------------------------------------
# HTML
# -------------------------------------------------------------------
CHAT_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fona Chat</title>
<style>
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: #f6f7f9; color: #111;
    display: flex; justify-content: center;
  }
  .app {
    width: 100%; max-width: 720px; height: 100vh;
    display: flex; flex-direction: column; background: #fff;
  }
  .header {
    padding: .9rem 1rem; border-bottom: 1px solid #e5e7eb;
    display: flex; justify-content: space-between; align-items: center;
  }
  .header h1 { margin: 0; font-size: 1.1rem; font-weight: 600; }
  .header .actions { display: flex; gap: .5rem; align-items: center; }
  .badge {
    font-size: .78rem; padding: .18rem .5rem; border-radius: 999px;
    background: #fde2e1; color: #b3261e;
  }
  .badge.on { background: #e6f4ea; color: #137333; }
  .messages {
    flex: 1; overflow-y: auto; padding: 1rem;
    display: flex; flex-direction: column; gap: .55rem;
  }
  .msg {
    max-width: 78%; padding: .6rem .85rem;
    border-radius: 14px; line-height: 1.4;
    font-size: .96rem; white-space: pre-wrap; word-wrap: break-word;
  }
  .msg.user      { align-self: flex-end;   background: #2c7be5; color: #fff;
                   border-bottom-right-radius: 4px; }
  .msg.assistant { align-self: flex-start; background: #f0f1f3; color: #111;
                   border-bottom-left-radius: 4px; }
  .msg.system    { align-self: center; background: transparent;
                   color: #9aa0a6; font-size: .82rem; font-style: italic; }
  .composer {
    padding: .75rem; border-top: 1px solid #e5e7eb;
    display: flex; gap: .5rem;
  }
  .composer input {
    flex: 1; padding: .65rem .85rem;
    border: 1px solid #d0d5dd; border-radius: 10px;
    font-size: 1rem; outline: none;
  }
  .composer input:focus { border-color: #2c7be5; }
  .composer button {
    padding: .65rem 1rem; border: 0; border-radius: 10px;
    background: #2c7be5; color: #fff; font-size: 1rem; cursor: pointer;
  }
  .composer button:disabled,
  .composer input:disabled { opacity: .5; cursor: not-allowed; }
  .header button {
    padding: .35rem .7rem; font-size: .82rem;
    border: 1px solid #d0d5dd; background: #fff; border-radius: 8px;
    cursor: pointer;
  }
  .header button:disabled { opacity: .5; cursor: not-allowed; }
</style>
</head>
<body>
<div class="app">
  <div class="header">
    <h1>Fona Chat</h1>
    <div class="actions">
      <span class="badge" id="status">офлайн</span>
      <button id="restart" disabled>Новый диалог</button>
    </div>
  </div>
  <div class="messages" id="messages"></div>
  <form class="composer" id="composer" autocomplete="off">
    <input type="text" id="input" placeholder="Введите сообщение..." disabled>
    <button type="submit" id="send" disabled>Отправить</button>
  </form>
</div>

<script>
(() => {
  const $ = id => document.getElementById(id);
  const messages = $('messages');
  const input = $('input');
  const send = $('send');
  const restart = $('restart');
  const status = $('status');

  let sid = null;
  let es = null;

  function append(text, role) {
    const el = document.createElement('div');
    el.className = 'msg ' + role;
    el.textContent = text;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
  }

  function setRunning(on) {
    status.textContent = on ? 'онлайн' : 'офлайн';
    status.classList.toggle('on', on);
    input.disabled = !on;
    send.disabled = !on;
    restart.disabled = !on;
    if (!on) input.value = '';
  }

  async function start() {
    messages.innerHTML = '';
    setRunning(false);
    try {
      const r = await fetch('/api/chat/start', { method: 'POST' });
      if (!r.ok) { append('Ошибка: ' + await r.text(), 'system'); return; }
      sid = (await r.json()).session_id;
      setRunning(true);
      openStream();
      input.focus();
    } catch (e) {
      append('Сеть: ' + e.message, 'system');
    }
  }

  async function stop() {
    if (!sid) return;
    try {
      await fetch('/api/chat/stop?session_id=' + encodeURIComponent(sid),
                  { method: 'POST' });
    } catch (_) {}
    closeStream();
    sid = null;
    setRunning(false);
    append('— диалог завершён —', 'system');
  }

  async function sendText(text) {
    text = text.trim();
    if (!text || !sid) return;
    append(text, 'user');
    input.value = '';
    try {
      const r = await fetch('/api/chat/input', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid, text }),
      });
      if (!r.ok) append('Ошибка отправки: ' + await r.text(), 'system');
    } catch (e) {
      append('Сеть: ' + e.message, 'system');
    }
  }

  function openStream() {
    closeStream();
    es = new EventSource('/api/chat/stream?session_id=' + encodeURIComponent(sid));
    es.addEventListener('message', e => {
      try { append(JSON.parse(e.data).text, 'assistant'); } catch (_) {}
    });
    es.addEventListener('state', e => {
      try {
        const d = JSON.parse(e.data);
        if (d.finished || d.removed) {
          setRunning(false);
          closeStream();
          if (d.finished) append('— сессия завершена —', 'system');
        } else if (typeof d.running === 'boolean') {
          setRunning(d.running);
        }
      } catch (_) {}
    });
  }

  function closeStream() { if (es) { es.close(); es = null; } }

  $('composer').addEventListener('submit', e => {
    e.preventDefault();
    sendText(input.value);
  });

  restart.addEventListener('click', start);

  window.addEventListener('beforeunload', () => {
    if (sid) navigator.sendBeacon(
      '/api/chat/stop?session_id=' + encodeURIComponent(sid));
  });

  start();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")