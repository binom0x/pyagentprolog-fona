from fona import agent

# База — HF-модель. Её config.program и kb_file загружаются автоматически.
agent.load_hub('user/pyagent-prolog-demo')

@agent.action
def translate(text):
    """Перевод через ваш LLM-клиент (заглушка)."""
    return f"[en] {text}"

agent.program("""
run :- loop.

loop :-
    ui_print('Введите сообщение (или "stop"):'),
    ui_read(Action),
    ( Action = "stop" -> ui_print('Пока!'), !
    ; ui_print(Action),
      loop
    ).
""")

if __name__ == '__main__':
    agent.run()