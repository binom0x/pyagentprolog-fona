"""FastAPI + SSE + HITL-сессии."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time as _time
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from prolog.proagent_gradio import (
    AgentGradioSession, get_session, register_session,
    remove_session, send_input_to_agent,
)

from .agent import _clone_model
from .ui import HTML

if TYPE_CHECKING:
    from pyagentprolog_hf import PyAgentPrologModel


# =====================================================================
# Сессия с семантикой query_one (только первое решение run.)
# =====================================================================
class QueryOneSession(AgentGradioSession):
    """HITL-сессия: вызывает query_one вместо query.

    Это правильно для «один агент = один жизненный цикл»:
    если в программе переопределён run/0, HF-ный run/0 не будет
    выполняться вдогонку.
    """

    def _run(self, agent, query):
        try:
            if agent.context is None:
                agent.context = {}
            agent.context['agent_session'] = self
            result = agent.query_one(query)
            if result is None:
                self.add_output("Агент завершил выполнение без решений.")
            elif result.get('__success__'):
                self.add_output("Агент завершил выполнение.")
            else:
                self.add_output(f"Результат: {result}")
        except Exception as e:
            self.add_output(f"Ошибка: {type(e).__name__}: {e}")
        finally:
            self.running = False
            self.thread = None


def _create_query_one_session() -> str:
    sid = str(uuid.uuid4())
    register_session(sid, QueryOneSession())
    return sid


# =====================================================================
# Схемы
# =====================================================================
class _InputRequest(BaseModel):
    session_id: str
    text: str
    ui_values: dict[str, Any] = {}


class _QueryRequest(BaseModel):
    query: str
    with_explanation: Optional[bool] = None


# =====================================================================
# FastAPI
# =====================================================================
def create_app(
    model: Any,
    *,
    start_query: str = 'run.',
    with_ui: bool = True,
    with_rest: bool = True,
    token: Optional[str] = None,
) -> FastAPI:
    """Собрать FastAPI-приложение с UI и/или REST.

    Database не потокобезопасна (interpreter.py мутирует rules,
    _cut_counter, tracer). Все REST-запросы к шаблонной модели идут
    под api_lock. HITL-сессии изолированы: своя модель = свой Database.
    """
    api_lock = threading.RLock()

    def check_token(key: Optional[str]):
        if token and key != token:
            raise HTTPException(401, "invalid API token")

    @asynccontextmanager
    async def lifespan(app):
        if os.getenv('FONA_WARMUP') == '1':
            try:
                from prolog.arith_numba import warmup_arith_numba
                t0 = _time.time()
                warmup_arith_numba()
                print(f"[fona] numba warmup: {_time.time()-t0:.2f}s",
                      file=sys.stderr, flush=True)
            except Exception:
                pass
        yield

    app = FastAPI(title="Fona Agent", version="0.1.0", lifespan=lifespan)

    # ---------------- UI ----------------
    if with_ui:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def index():
            return HTML

        @app.post("/api/v1/ui/start")
        async def ui_start():
            sid = _create_query_one_session()
            sess = get_session(sid)
            clone = _clone_model(model)
            sess.start(clone.agent, query=start_query)
            return {"session_id": sid}

        @app.post("/api/v1/ui/input")
        async def ui_input(req: _InputRequest):
            sess = get_session(req.session_id)
            if not sess:
                raise HTTPException(404, "session not found")
            if not sess.running:
                raise HTTPException(409, "agent not running")
            for k, v in req.ui_values.items():
                sess.set_ui_value(k, v)
            send_input_to_agent(req.session_id, req.text)
            return {"status": "ok"}

        @app.post("/api/v1/ui/stop")
        async def ui_stop(session_id: str):
            sess = get_session(session_id)
            if sess:
                sess.stop()
                remove_session(session_id)
            return {"status": "ok"}

        @app.get("/api/v1/ui/stream")
        async def ui_stream(session_id: str):
            if not get_session(session_id):
                raise HTTPException(404, "session not found")

            async def gen():
                sess = get_session(session_id)
                if sess is None:
                    yield 'event: state\ndata: {"running": false, "removed": true}\n\n'
                    return
                yield (f'event: state\n'
                       f'data: {json.dumps({"running": sess.running})}\n\n')
                while True:
                    sess = get_session(session_id)
                    if sess is None:
                        yield ('event: state\n'
                               'data: {"running": false, "removed": true}\n\n')
                        return
                    for msg in sess.get_output():
                        yield (f'event: output\n'
                               f'data: {json.dumps({"text": str(msg)}, ensure_ascii=False)}\n\n')
                    if not sess.running:
                        for msg in sess.get_output():
                            yield (f'event: output\n'
                                   f'data: {json.dumps({"text": str(msg)}, ensure_ascii=False)}\n\n')
                        yield ('event: state\n'
                               'data: {"running": false, "finished": true}\n\n')
                        return
                    await asyncio.sleep(0.2)

            return StreamingResponse(
                gen(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache",
                         "X-Accel-Buffering": "no"},
            )

    # ---------------- REST ----------------
    if with_rest:
        @app.get("/api/v1/health")
        def health():
            return {"status": "ok"}

        @app.get("/api/v1/model")
        def model_info_endpoint(x_api_key: Optional[str] = Header(default=None)):
            check_token(x_api_key)
            cfg = model.config
            return {
                'name_or_path': getattr(model, 'name_or_path', None),
                'rules_count': len(model.agent.solver.database.rules),
                'kb_file': getattr(cfg, 'kb_file', None),
                'kb_format': getattr(cfg, 'kb_format', 'auto'),
                'semantic_enabled': bool(getattr(cfg, 'semantic_enabled', False)),
                'default_main': getattr(cfg, 'default_main', None),
                'max_solutions': getattr(cfg, 'max_solutions', 0),
                'actions': model.agent.list_actions(),
            }

        @app.post("/api/v1/query")
        def query_endpoint(req: _QueryRequest,
                           x_api_key: Optional[str] = Header(default=None)):
            check_token(x_api_key)
            with api_lock:
                raw = model.agent.query(req.query)

            if not isinstance(raw, dict):
                return {"success": False, "query": req.query,
                        "error": f"unexpected result: {type(raw).__name__}"}
            if 'error' in raw:
                return {"success": False, "query": req.query,
                        "error": f"{raw.get('type', 'error')}: "
                                 f"{raw.get('detail', raw['error'])}"}

            sol = raw.get('solution')
            success = sol is not None and sol is not False
            return {
                "success": success,
                "query": req.query,
                "solutions": sol if success else [],
                "count": raw.get('count', 0),
            }

        @app.post("/api/v1/query_one")
        def query_one_endpoint(req: _QueryRequest,
                               x_api_key: Optional[str] = Header(default=None)):
            check_token(x_api_key)
            with api_lock:
                sol = model.agent.query_one(req.query)
            return {"success": sol is not None, "solution": sol,
                    "query": req.query}

        @app.post("/api/v1/stream")
        def stream_endpoint(req: _QueryRequest,
                            x_api_key: Optional[str] = Header(default=None)):
            check_token(x_api_key)

            def gen():
                with api_lock:
                    for sol in model.agent.stream(req.query):
                        yield (f"data: "
                               f"{json.dumps(sol, default=str, ensure_ascii=False)}"
                               f"\n\n")
                yield "event: done\ndata: {}\n\n"

            return StreamingResponse(gen(),
                                     media_type="text/event-stream")

        @app.post("/api/v1/facts")
        def facts_endpoint(fact: str,
                           x_api_key: Optional[str] = Header(default=None)):
            check_token(x_api_key)
            with api_lock:
                model.add_facts(fact)
            return {"status": "ok"}

        @app.get("/api/v1/actions")
        def actions_endpoint(x_api_key: Optional[str] = Header(default=None)):
            check_token(x_api_key)
            return {"actions": model.agent.list_actions()}

    return app


def run_uvicorn(app, host: str = '127.0.0.1', port: int = 8000):
    uvicorn.run(app, host=host, port=port, log_level="info")