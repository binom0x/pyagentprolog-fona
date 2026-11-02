"""Чат-бот на Fona + Gradio."""
import gradio as gr

from fona import Agent
from fona.agent import _clone_model
from prolog.proagent_gradio import (
    create_agent_session, get_session, remove_session,
    send_input_to_agent, get_agent_outputs,
)


# -------------------------------------------------------------------
# Агент собирается один раз; клонируется под каждую сессию
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


_MODEL = chat_agent.build(with_ui=True)   # ui_print, ui_read, gradio_*


# -------------------------------------------------------------------
# Операции над сессией
# -------------------------------------------------------------------
def _new_session(old_sid):
    """Останавливает старую сессию (если была) и создаёт новую."""
    if old_sid:
        old = get_session(old_sid)
        if old:
            old.stop()                # None в input_queue → разблокирует ui_read
            remove_session(old_sid)

    sid = create_agent_session()
    sess = get_session(sid)
    clone = _clone_model(_MODEL)
    sess.start(clone.agent, query="run.")
    return sid, []


def _send(sid, text, history):
    if not sid or not text.strip():
        return history, ""
    history = history + [{"role": "user", "content": text.strip()}]
    send_input_to_agent(sid, text.strip())
    return history, ""


def _poll(sid, history):
    if not sid:
        return history
    for out in get_agent_outputs(sid):
        text = str(out)
        # AgentGradioSession._run добавляет финальный маркер — в чат не пускаем
        if text.startswith("Agent finished execution"):
            continue
        history = history + [{"role": "assistant", "content": text}]
    return history


def _stop(sid):
    if sid:
        sess = get_session(sid)
        if sess:
            sess.stop()
        remove_session(sid)
    return None


# -------------------------------------------------------------------
# UI
# -------------------------------------------------------------------
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Fona Chat") as demo:
        gr.Markdown("# Fona Chat")

        chatbot = gr.Chatbot(type="messages", height=520, label="Диалог")

        with gr.Row():
            msg = gr.Textbox(
                placeholder="Введите сообщение...",
                scale=4, show_label=False, container=False, autofocus=True,
            )
            send = gr.Button("Отправить", variant="primary", scale=1)

        with gr.Row():
            restart = gr.Button("Новый диалог", size="sm", variant="secondary")
            stop_btn = gr.Button("Завершить", size="sm", variant="stop")

        sid = gr.State(None)
        timer = gr.Timer(0.5)   # опрос output_queue

        demo.load(_new_session, inputs=[sid], outputs=[sid, chatbot])

        send.click(_send, [sid, msg, chatbot], [chatbot, msg])
        msg.submit(_send, [sid, msg, chatbot], [chatbot, msg])

        restart.click(_new_session, inputs=[sid], outputs=[sid, chatbot])
        stop_btn.click(_stop, [sid], [sid])

        timer.tick(_poll, [sid, chatbot], [chatbot])

    return demo


if __name__ == "__main__":
    build_ui().launch(inbrowser=True)