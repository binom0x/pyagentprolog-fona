import os
from fona import agent

agent.program("""
light(kitchen, on).
light(bedroom, off).
light(living_room, on).

run :- ui_print('Сервер фактов готов.').
""")

if __name__ == '__main__':
    port = int(os.environ.get("FONA_PORT", "8000"))
    agent.run(port=port)