"""Агент-клиент, вызывающий другой агент по HTTP."""
from fona import agent

@agent.action
def ask_remote(url, query):
    import httpx
    r = httpx.post(url, json={'query': query}, timeout=10)
    r.raise_for_status()
    return r.json().get('solutions')

@agent.program
PROGRAM = """
run :-
    ask_remote('http://127.0.0.1:8000/api/v1/query',
               'light(kitchen, X).',
               Solutions),
    format('Получено: ~w', [Solutions], Msg),
    ui_print(Msg).
"""

if __name__ == '__main__':
    # Слушаем на другом порту — агент-клиент это тоже сервер
    agent.run(port=8001)