import os
from fona import agent

@agent.action
def ask_remote(url, query):
    import httpx
    r = httpx.post(url, json={'query': query}, timeout=10)
    r.raise_for_status()
    return r.json().get('solutions')

# Remote target — fixed to the server agent's URL.
# Change if the server is not on 8000.
REMOTE_URL = os.environ.get(
    "FONA_REMOTE_URL", "http://127.0.0.1:8000/api/v1/query")

agent.program(f"""
run :-
    ask_remote('{REMOTE_URL}',
               'light(bedroom, X).',
               Solutions),
    format('Получено: ~w', [Solutions], Msg),
    ui_print(Msg).
""")

if __name__ == '__main__':
    port = int(os.environ.get("FONA_PORT", "8001"))
    agent.run(port=port)