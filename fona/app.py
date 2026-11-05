"""Трёхколоночный чат-интерфейс для Fona-агента.

Колонки:
  1) 📁 Данные: файл + текст → ui_values['data'] агента
  2) 💬 Диалог: чат с агентом (вопрос/ответ/уточнения)
  3) 📋 Логи + 🔬 Состояние сессии

Тёмная тема в стиле PrologIDE / KnowledgeGraph Editor.
Совместимо с Gradio 5 и Gradio 6.

Запуск:
    python -m fona.app
    python -m fona.app --port 7860 --no-browser
    fona-chat                         # если установлен console_scripts
    fona-chat --port 7860

Программный запуск:
    from fona.app import launch
    launch(port=7860, inbrowser=True)

Замените блок `_agent.program = \"\"\"...\"\"\"` на логику своего агента.
"""
from __future__ import annotations

import argparse
import os
import queue
import uuid
from html import escape as _esc
from pathlib import Path
from typing import List, Optional

import gradio as gr

from fona import Agent
from fona.agent import _clone_model
from prolog.proagent_gradio import (
    AgentGradioSession,
    get_session,
    register_session,
    remove_session,
)


# =====================================================================
# Gradio: определение версии и параметров (5 vs 6)
# =====================================================================
try:
    _GRADIO_VERSION = tuple(int(x) for x in gr.__version__.split('.')[:2])
except (ValueError, AttributeError):
    _GRADIO_VERSION = (5, 0)

_IS_GRADIO6 = _GRADIO_VERSION >= (6, 0)

# gr.Chatbot в Gradio 5 требует type="messages", в 6 — параметр удалён
_CHATBOT_KWARGS = {
    "height": 560,
    "show_label": False,
    "elem_classes": ["chat-panel"],
}
if not _IS_GRADIO6:
    _CHATBOT_KWARGS["type"] = "messages"


# =====================================================================
# Favicon — как в PrologIDE / KnowledgeGraph Editor
# =====================================================================
_DEFAULT_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="12" fill="#4f46e5"/>'
    '<text x="32" y="46" font-family="ui-sans-serif,system-ui,sans-serif" '
    'font-size="40" font-weight="700" fill="#ffffff" '
    'text-anchor="middle" dominant-baseline="middle">F</text>'
    '</svg>'
)


def _ensure_favicon() -> Optional[str]:
    """Ищет favicon.{png,ico,svg} в fona/ и fona/assets/. Иначе создаёт дефолтный."""
    here = os.path.dirname(os.path.abspath(__file__))
    for subdir in ("", "assets"):
        for name in ("favicon.png", "favicon.ico", "favicon.svg"):
            path = (os.path.join(here, subdir, name)
                    if subdir else os.path.join(here, name))
            if os.path.isfile(path):
                return path
    # ничего нет — создаём дефолтный SVG
    try:
        path = os.path.join(here, "favicon.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_DEFAULT_FAVICON_SVG)
        return path
    except OSError:
        return None


# =====================================================================
# CSS — тёмная палитра PrologIDE / KnowledgeGraph Editor
# =====================================================================
_GLOBAL_CSS = """
.gradio-container { max-width: 1900px !important; padding: 6px 8px !important;
                    background: #0b0d11 !important; color: #c7cbd1 !important; }
footer { display: none !important; }

button.compact-btn, .compact-btn button {
    min-height: 26px !important;
    padding: 2px 8px !important;
    font-size: 12px !important;
    line-height: 1.2 !important;
    background: #21262d !important;
    border: 1px solid #2a313d !important;
    color: #c7cbd1 !important;
}
button.compact-btn:hover, .compact-btn button:hover {
    background: #30363d !important;
    border-color: #3a4250 !important;
}

.compact-tb input, .compact-tb textarea {
    padding: 4px 8px !important;
    font-size: 12px !important;
    min-height: 28px !important;
    background: #0b0d11 !important;
    color: #c7cbd1 !important;
    border: 1px solid #2a313d !important;
    border-radius: 4px !important;
}
.compact-tb input:focus, .compact-tb textarea:focus {
    border-color: #58a6ff !important;
    box-shadow: 0 0 0 2px rgba(88,166,255,.2) !important;
    outline: none !important;
}

.compact-lbl label {
    font-size: 11px !important;
    margin-bottom: 1px !important;
    color: #8b949e !important;
}

.compact-file .file-preview {
    background: #0b0d11 !important;
    border: 1px dashed #3a4250 !important;
    color: #8b949e !important;
    font-size: 12px !important;
}
.compact-file .file-preview:hover {
    border-color: #58a6ff !important;
    background: #161a20 !important;
}

.col-head {
    font-size: 14px !important; font-weight: 600;
    margin: 2px 0 6px 0 !important; color: #c7cbd1;
}

pre.status-box {
    margin: 0 !important;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11px; line-height: 1.35;
    padding: 4px 8px;
    background: #0b0d11; border: 1px solid #2a313d;
    border-radius: 4px; color: #c7cbd1;
    white-space: pre-wrap; max-height: 100px; overflow: auto;
}

.proj-info {
    font-size: 11px; line-height: 1.35; color: #8b949e;
    padding: 4px 8px; background: #0b0d11;
    border: 1px solid #2a313d; border-radius: 4px;
    word-break: break-all;
}
.proj-info b { color: #c7cbd1; }
.proj-info code { color: #79c0ff; background: transparent !important; }

*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-track { background: transparent; }
*::-webkit-scrollbar-thumb { background: #2a313d; border-radius: 5px; }
*::-webkit-scrollbar-thumb:hover { background: #3a4250; }

.md code, .prose code { background: #1c212a !important; color: #e6e6e6 !important; }

.chat-panel {
    background: #0b0d11 !important;
    border: 1px solid #2a313d !important;
    border-radius: 4px !important;
}
.gradio-container .message.user { background: #1c2a3a !important; color: #c7cbd1 !important; }
.gradio-container .message.bot  { background: #161a20 !important; color: #c7cbd1 !important; }

.gradio-container .accordion {
    border: 1px solid #2a313d !important;
    border-radius: 4px;
    background: #0b0d11 !important;
}
.gradio-container .accordion button.label-wrap,
.gradio-container .accordion .label-wrap {
    background: #0f1115 !important;
    color: #c7cbd1 !important;
}

.gradio-container .json-holder,
.gradio-container .json-viewer,
.gradio-container .json-container {
    background: #0b0d11 !important;
    color: #c7cbd1 !important;
    border: 1px solid #2a313d !important;
    border-radius: 4px;
}
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


# =====================================================================
# Сессия с двумя каналами: чат (кол. 2) и логи (кол. 3)
# =====================================================================
class ChatLogSession(AgentGradioSession):
    """Session с отдельными очередями для чата и логов."""

    def __init__(self):
        super().__init__()
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.model = None  # reference на клонированную модель

    def add_log(self, text) -> None:
        self.log_queue.put(str(text))

    def get_logs(self) -> List[str]:
        msgs = []
        while not self.log_queue.empty():
            try:
                msgs.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        return msgs


# =====================================================================
# Агент
# =====================================================================
_agent = Agent()

# ==== ЗАМЕНИТЕ эту программу на свою ====
# Контракт:
#   * run/0            — стартовая точка
#   * ui_print/1       — сообщение в чат (колонка 2)
#   * ui_read/1        — ожидание ввода пользователя
#   * ui_log_msg/1     — строка в лог-панель (колонка 3), определён ниже
#   * gradio_get_ui_value/2 — доступ к ui_values (данные из колонки 1)
_agent.program = """
run :- greeting, loop.

greeting :-
    ui_print('Привет! Загрузите данные в колонке «📁 Данные» и задайте вопрос.'),
    ui_log_msg('session started').

loop :-
    ui_read(Input),
    handle(Input).

handle("stop") :- !,
    ui_print('До свидания!'),
    ui_log_msg('session stopped').

handle("") :- loop.

handle(Text) :-
    ui_log_msg(Text),
    gradio_get_ui_value('data', Data),
    ( Data = [] ->
        echo(Text, Reply),
        ui_print(Reply)
    ;
        count_words(Data, WC),
        format('Данные: ~w слов. Вы написали: ~w', [WC, Text], Reply),
        ui_print(Reply)
    ),
    loop.
"""


@_agent.action
def echo(text):
    return f"Эхо: {text}"


@_agent.action
def count_words(text):
    return len(str(text).split())


@_agent.effect
def ui_log_msg(text, context):
    """Пишет в лог-панель колонки 3."""
    session = context.get('agent_session')
    if session is not None and hasattr(session, 'add_log'):
        session.add_log(text)


_MODEL = _agent.build(with_ui=True)


# =====================================================================
# Извлечение текста из файла
# =====================================================================
def _extract_text_from_file(path: str) -> str:
    ext = Path(path).suffix.lower()
    try:
        if ext in ('.txt', '.md', '.log', '.pl'):
            return Path(path).read_text(encoding='utf-8', errors='ignore')
        if ext == '.pdf':
            try:
                import PyPDF2
                with open(path, 'rb') as f:
                    return '\n'.join(
                        p.extract_text() or '' for p in PyPDF2.PdfReader(f).pages
                    )
            except ImportError:
                return '❌ Установите: pip install PyPDF2'
        if ext == '.docx':
            try:
                import docx
                return '\n'.join(p.text for p in docx.Document(path).paragraphs)
            except ImportError:
                return '❌ Установите: pip install python-docx'
        if ext == '.fb2':
            import xml.etree.ElementTree as ET
            tree = ET.parse(path)
            ns = {'fb': 'http://www.gribuser.ru/xml/fictionbook/2.0'}
            parts = [p.text for p in tree.getroot().findall('.//fb:p', ns)
                     if p.text]
            return '\n'.join(parts)
        return f'❌ Неподдерживаемый формат: {ext}'
    except Exception as e:
        return f'❌ Ошибка чтения: {e}'


# =====================================================================
# Утилиты
# =====================================================================
def _status_html(s: str) -> str:
    return f'<pre class="status-box">{_esc(str(s))}</pre>'


def _stats_html(sid: Optional[str]) -> str:
    sess = get_session(sid) if sid else None
    if sess is None:
        return '<div class="proj-info">Сессия не активна</div>'
    state = 'запущена' if sess.running else 'остановлена'
    color = '#7ee787' if sess.running else '#ff7b72'
    return (
        '<div class="proj-info">'
        f'<b>Статус:</b> <span style="color:{color}">{state}</span>'
        '</div>'
    )


# =====================================================================
# Хэндлеры: сессия
# =====================================================================
def _new_session(old_sid: Optional[str]) -> str:
    if old_sid:
        old = get_session(old_sid)
        if old is not None:
            old.stop()
            remove_session(old_sid)

    sid = str(uuid.uuid4())
    sess = ChatLogSession()
    register_session(sid, sess)
    clone = _clone_model(_MODEL)
    sess.model = clone
    sess.start(clone.agent, query="run.")
    return sid


def _stop_session(sid: Optional[str]):
    if not sid:
        return None
    sess = get_session(sid)
    if sess is not None:
        sess.stop()
        remove_session(sid)
    return None


# =====================================================================
# Хэндлеры: данные (колонка 1)
# =====================================================================
def _load_data(sid: Optional[str], file, text: str):
    sess = get_session(sid) if sid else None
    if sess is None:
        return _status_html("✗ Сессия не найдена"), ""

    parts: List[str] = []

    if file is not None:
        path = file.name if hasattr(file, "name") else str(file)
        extracted = _extract_text_from_file(path)
        if extracted.startswith('❌'):
            return _status_html(extracted), ""
        parts.append(extracted)

    if text and text.strip():
        parts.append(text.strip())

    if not parts:
        return _status_html("✗ Нет данных для загрузки"), ""

    combined = "\n\n".join(parts)
    # Prolog-атом: экранируем двойные кавычки
    combined_safe = combined.replace('"', "'")

    sess.set_ui_value('data', combined_safe)
    if sess.model is not None:
        sess.model.agent.context['data'] = combined_safe

    preview = combined[:500] + ('…' if len(combined) > 500 else '')
    return (
        _status_html(f"✓ Загружено {len(combined)} символов"),
        preview,
    )


def _clear_data(sid: Optional[str]):
    sess = get_session(sid) if sid else None
    if sess is not None:
        sess.set_ui_value('data', None)
        if sess.model is not None:
            sess.model.agent.context.pop('data', None)
    return _status_html("Данные очищены"), ""


# =====================================================================
# Хэндлеры: чат (колонка 2)
# =====================================================================
def _send(sid: Optional[str], text: str, history: list):
    text = (text or "").strip()
    if not text:
        return history, ""
    sess = get_session(sid) if sid else None
    if sess is None:
        return list(history or []) + [
            {"role": "system", "content": "Сессия не найдена — нажмите 🔄 Новую."}
        ], ""
    if not sess.running:
        return list(history or []) + [
            {"role": "system", "content": "Агент остановлен — нажмите 🔄 Новую."}
        ], ""

    history = list(history or []) + [{"role": "user", "content": text}]
    sess.send_input(text)
    return history, ""


def _poll_chat(sid: Optional[str], history: list):
    sess = get_session(sid) if sid else None
    if sess is None:
        return history
    history = list(history or [])
    for out in sess.get_output():
        text = str(out)
        if text.startswith("Agent finished execution"):
            continue
        if text.startswith("Error in agent:"):
            history = history + [{"role": "system", "content": text}]
            continue
        history = history + [{"role": "assistant", "content": text}]
    return history


# =====================================================================
# Хэндлеры: логи и состояние (колонка 3)
# =====================================================================
def _poll_logs(sid: Optional[str], current: str) -> str:
    sess = get_session(sid) if sid else None
    if sess is None or not hasattr(sess, 'get_logs'):
        return current
    new = sess.get_logs()
    if not new:
        return current
    base = (current or "").rstrip("\n")
    for item in new:
        base = (base + "\n" + item) if base else item
    if len(base) > 8000:
        base = "…(log trimmed)…\n" + base[-8000:]
    return base


def _state_json(sid: Optional[str]) -> dict:
    sess = get_session(sid) if sid else None
    if sess is None:
        return {"error": "no session"}
    return {
        "running": sess.running,
        "has_thread": sess.thread is not None,
        "ui_values_keys": list(sess.ui_values.keys()),
        "history_len": len(sess.history),
        "model_attached": sess.model is not None,
        "rules_count": (
            len(sess.model.agent.solver.database.rules)
            if sess.model is not None else 0
        ),
    }


# =====================================================================
# UI
# =====================================================================
def build_ui() -> gr.Blocks:
    _blocks_kwargs = {"title": "Fona Agent Chat"}
    if not _IS_GRADIO6:
        _blocks_kwargs["css"] = _GLOBAL_CSS
        _blocks_kwargs["head"] = _HEAD_DARK

    with gr.Blocks(**_blocks_kwargs) as demo:
        sid_state = gr.State(None)

        with gr.Row(equal_height=False):

            # ============================================================
            # КОЛОНКА 1 — Данные для обработки
            # ============================================================
            with gr.Column(scale=2, min_width=300):
                gr.HTML('<div class="col-head">📁 Данные для обработки</div>')

                data_file = gr.File(
                    label="Файл (txt, md, pdf, docx, fb2)",
                    file_types=[".txt", ".md", ".log", ".pdf", ".docx", ".fb2"],
                    show_label=True,
                    elem_classes=["compact-file"],
                )
                data_text = gr.Textbox(
                    placeholder="Вставьте текст сюда (альтернатива или дополнение к файлу)…",
                    lines=8,
                    show_label=False,
                    elem_classes=["compact-tb"],
                )
                with gr.Row(equal_height=True):
                    load_btn = gr.Button(
                        "📥 Загрузить", size="sm", variant="primary",
                        elem_classes=["compact-btn"], scale=2,
                    )
                    clear_btn = gr.Button(
                        "🗑️ Очистить", size="sm",
                        elem_classes=["compact-btn"], scale=2,
                    )

                data_status = gr.HTML(_status_html("Данные не загружены"))
                data_preview = gr.Textbox(
                    label="Превью (первые 500 символов)",
                    lines=5, interactive=False,
                    elem_classes=["compact-tb"],
                )

                with gr.Accordion("ℹ️ О сессии", open=False):
                    session_stats = gr.HTML(
                        '<div class="proj-info">Сессия не активна</div>'
                    )
                    refresh_stats_btn = gr.Button(
                        "🔄 Обновить", size="sm",
                        elem_classes=["compact-btn"],
                    )

            # ============================================================
            # КОЛОНКА 2 — Диалог с агентом
            # ============================================================
            with gr.Column(scale=5, min_width=500):
                gr.HTML('<div class="col-head">💬 Диалог с агентом</div>')

                chatbot = gr.Chatbot(**_CHATBOT_KWARGS)

                with gr.Row(equal_height=True):
                    user_msg = gr.Textbox(
                        placeholder="Введите сообщение…",
                        show_label=False, scale=4,
                        elem_classes=["compact-tb"],
                        autofocus=True,
                    )
                    send_btn = gr.Button(
                        "Отправить", size="sm", scale=1,
                        variant="primary",
                        elem_classes=["compact-btn"],
                    )

                with gr.Row(equal_height=True):
                    yes_btn = gr.Button(
                        "✅ Да", size="sm", scale=1,
                        elem_classes=["compact-btn"],
                    )
                    no_btn = gr.Button(
                        "❌ Нет", size="sm", scale=1,
                        elem_classes=["compact-btn"],
                    )
                    restart_btn = gr.Button(
                        "🔄 Новая сессия", size="sm", scale=2,
                        elem_classes=["compact-btn"],
                    )
                    stop_btn = gr.Button(
                        "⏹ Завершить", size="sm", scale=1,
                        elem_classes=["compact-btn"],
                    )

                session_status = gr.HTML(
                    _status_html("Сессия не создана — перезагрузите страницу.")
                )

            # ============================================================
            # КОЛОНКА 3 — Логи и состояние
            # ============================================================
            with gr.Column(scale=3, min_width=320):
                gr.HTML('<div class="col-head">📋 Логи</div>')

                logs_out = gr.Textbox(
                    show_label=False, lines=16, interactive=False,
                    value="", max_lines=16,
                    elem_classes=["compact-tb"],
                )
                with gr.Row(equal_height=True):
                    clear_logs_btn = gr.Button(
                        "🗑️ Очистить лог", size="sm",
                        elem_classes=["compact-btn"],
                    )

                gr.HTML('<div class="col-head">🔬 Состояние</div>')
                state_json = gr.JSON(show_label=False)
                with gr.Row(equal_height=True):
                    refresh_state_btn = gr.Button(
                        "🔄 Обновить", size="sm",
                        elem_classes=["compact-btn"],
                    )

        # ============================================================
        # Timer для поллинга
        # ============================================================
        timer = gr.Timer(0.5)

        # ============================================================
        # Wiring
        # ============================================================
        def on_load(old_sid):
            sid = _new_session(old_sid)
            return sid, _stats_html(sid), _status_html("Сессия активна")

        demo.load(
            on_load, [sid_state],
            [sid_state, session_stats, session_status],
        )

        # --- Данные ---
        load_btn.click(
            _load_data, [sid_state, data_file, data_text],
            [data_status, data_preview],
        ).then(_stats_html, [sid_state], [session_stats])

        clear_btn.click(
            _clear_data, [sid_state],
            [data_status, data_preview],
        )

        # --- Чат ---
        send_btn.click(
            _send, [sid_state, user_msg, chatbot],
            [chatbot, user_msg],
        )
        user_msg.submit(
            _send, [sid_state, user_msg, chatbot],
            [chatbot, user_msg],
        )

        yes_btn.click(
            lambda sid, h: _send(sid, "да", h),
            [sid_state, chatbot], [chatbot, user_msg],
        )
        no_btn.click(
            lambda sid, h: _send(sid, "нет", h),
            [sid_state, chatbot], [chatbot, user_msg],
        )

        # --- Новая сессия ---
        def on_restart(old_sid):
            sid = _new_session(old_sid)
            return (
                sid,
                [],
                "",
                _stats_html(sid),
                _status_html("Новая сессия создана"),
                _status_html("Данные не загружены"),
            )

        restart_btn.click(
            on_restart, [sid_state],
            [sid_state, chatbot, logs_out, session_stats,
             session_status, data_status],
        )

        # --- Завершение ---
        stop_btn.click(
            lambda sid: (_stop_session(sid),
                         _status_html("Сессия остановлена")),
            [sid_state], [sid_state, session_status],
        )

        # --- Логи ---
        clear_logs_btn.click(lambda: "", [], [logs_out])

        # --- Поллинг ---
        timer.tick(_poll_chat, [sid_state, chatbot], [chatbot])
        timer.tick(_poll_logs, [sid_state, logs_out], [logs_out])

        # --- Обновления состояния ---
        refresh_stats_btn.click(_stats_html, [sid_state], [session_stats])
        refresh_state_btn.click(_state_json, [sid_state], [state_json])

        return demo


# =====================================================================
# Launch — как в примерах
# =====================================================================
def launch(host: str = "127.0.0.1",
           port: int = 7860,
           inbrowser: bool = True,
           share: bool = False,
           **kwargs) -> None:
    import time as _t

    ui = build_ui()

    launch_kwargs = dict(
        server_name=host,
        server_port=port,
        inbrowser=inbrowser,
        share=share,
    )

    favicon = _ensure_favicon()
    if favicon:
        launch_kwargs["favicon_path"] = favicon

    # Gradio 6: css и head передаются только в launch().
    # В head добавляем <link rel="icon"> с версией — это работает,
    # даже когда Gradio игнорирует favicon_path или кэш браузера застрял.
    if _IS_GRADIO6:
        head = _HEAD_DARK
        if favicon:
            head += (
                f'<link rel="icon" href="/favicon.ico?v={int(_t.time())}">'
            )
        launch_kwargs["css"] = _GLOBAL_CSS
        launch_kwargs["head"] = head

    launch_kwargs.update(kwargs)
    ui.launch(**launch_kwargs)


# =====================================================================
# CLI
# =====================================================================
def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="fona-chat",
        description="Fona Agent Chat — трёхколоночный UI для Fona-агента.",
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="Адрес (по умолчанию 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7860,
                        help="Порт (по умолчанию 7860)")
    parser.add_argument("--share", action="store_true",
                        help="Публичная ссылка Gradio")
    parser.add_argument("--no-browser", action="store_true",
                        help="Не открывать браузер")
    args = parser.parse_args(argv)

    launch(
        host=args.host,
        port=args.port,
        share=args.share,
        inbrowser=not args.no_browser,
    )


if __name__ == "__main__":
    main()