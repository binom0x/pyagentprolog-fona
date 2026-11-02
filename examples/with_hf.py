"""HF-модель + собственное действие в чат-петле."""
from fona import agent

# База — HF-модель. Её config.program и kb_file загружаются автоматически.
# Замените на свой репозиторий (или локальную директорию):
agent.load_hub('user/pyagent-prolog-demo')


@agent.action
def translate(text):
    """Демонстрационное действие: префикс [en] к строке."""
    return f"[en] {text}"


agent.program("""
run :- loop.

loop :-
    ui_print('Введите сообщение (или "stop"):'),
    ui_read(Action),
    ( Action = "stop" -> ui_print('Пока!'), !
    ; translate(Action, En),
      format('~w → ~w', [Action, En], Msg),
      ui_print(Msg),
      loop
    ).
""")


if __name__ == '__main__':
    agent.run()