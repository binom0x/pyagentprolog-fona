from fona import agent

# База — HF-модель. Её config.program и kb_file загружаются автоматически.
agent.load_hub('user/pyagent-prolog-demo')

@agent.action
def translate(text):
    """Перевод через ваш LLM-клиент (заглушка)."""
    return f"[en] {text}"

@agent.program
PROGRAM = """
run :- loop.

loop :-
    ui_print('Сообщение (или "stop"):'),
    ui_read(Text),
    ( Text = "stop" -> ui_print('Пока!'), !
    ; translate(Text, En),
      ui_print(En),
      loop
    ).
"""

if __name__ == '__main__':
    agent.run()