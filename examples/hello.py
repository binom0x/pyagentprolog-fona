import os
from fona import agent

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
    port = int(os.environ.get("FONA_PORT", "8010"))
    agent.run(port=port)