# Fona

**Минималистичный фреймворк для фоновых ИИ-агентов на PyAgentProlog.**

Агент — это Prolog-программа плюс Python-действия. Он запускается как HTTP-сервер с чат-интерфейсом и REST API, умеет общаться с пользователем и другими агентами, и может быть запущен из дашборда.

---

## Как это выглядит

```python
from fona import agent

@agent.action
def now_iso():
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

@agent.program
PROGRAM = r"""
run :-
    ui_print('Привет. Напишите "time" или "quit".'),
    on_user_input.

on_user_input :-
    ui_read(Input),
    (   Input == quit -> ui_print('Пока.')
    ;   Input == time -> now_iso(T), ui_print(T), on_user_input
    ;   ui_print('Не понял.'), on_user_input
    ).
"""

if __name__ == '__main__':
    agent.run(port=8000)
```

```bash
python hello.py
# открыть http://127.0.0.1:8000/
```

---

## Установка

```bash
pip install pyagentprolog-fona
```

Python 3.10+. `torch` / `sentence-transformers` — опционально (`[torch]`, `[semantic]`, `[all]`).

---

## Что вы получаете

- **`@agent.program`** — декларация логики агента на Prolog.
- **`@agent.action` / `@agent.effect` / `@agent.generate`** — публикация Python-функций как Prolog-предикатов.
- **`agent.run()`** — чат-UI и REST API (`/api/v1/query`, `/api/v1/ui/*`).
- **Меж-агентный протокол — только Prolog** — пиры шлют на `/api/v1/query` Prolog-текст; ошибки — атомы `"err:..."`, не исключения.
- **Декларативный конфиг** — `load_config(...)` читает env один раз, возвращает immutable-объект.
- **HF-модели** — `Agent.from_hub("user/repo")`; пользовательский `PROGRAM` **prepend**-ится к программе модели.
- **Дашборд** — `python -m fona.dashboard`; проект = папка с `team.json`, `scripts/`, `logs/`.
- **Оркестратор** — `python -m fona.orchestrator_app`; трёхколоночный UI: цель, план, чат, подчинённые.
- **Естественный язык ↔ Prolog** — опциональные `@agent.action`-спутники HITL-цикла, не часть протокола.

---

## Документация

Полное руководство — архитектура, декораторы, HITL, меж-агентный протокол, `query_one`, контракт REST, кэш HF, дашборд, оркестратор, безопасность, тестирование, релизы, известные ограничения — в [`docs/guide-ru.md`](docs/guide.md).

Начните с него. Этот README намеренно не дублирует руководство.

---

## Примеры

| Файл | Что показывает |
|---|---|
| `examples/hello.py` | минимальный агент: `run/0` + `ui_print` |
| `examples/server_agent.py` | сервер фактов + `handle_request/2` (входящие) |
| `examples/client_agent.py` | `call_peer/3` (исходящие) |
| `examples/template_agent.py` | эталон: HITL, пиры, протокол, NL ↔ Prolog, `query_one` |
| `examples/with_hf.py` | `Agent.from_hub` + prepend `PROGRAM` |

---

## Протокол в одном абзаце

Любой агент отвечает на `POST /api/v1/query` с телом `{"query": "<Prolog text>"}`. Ответ — `{"success": bool, "solutions": [{"Var": value}], "count": int}`. Рекомендуемый обработчик — `handle_request(Kind, Payload) -> str` с `Kind ∈ {ping, echo, status}`, расширяется через `register_protocol(agent, extra={...})`. Исходящие вызовы — `call_peer(Peer, Query) -> "ok:<v>" | "err:<r>"`, регистрируется через `register_peers(agent, CFG)`. Пиры конфигурируются через `FONA_PEERS="name=url,..."`. Никакого специального языка, никакого специального клиента — только Prolog поверх HTTP.

---

## Требования

- Core: `fastapi`, `uvicorn`, `httpx`, `pydantic`, `transformers`, `huggingface_hub`, `pyagentprolog`, `pyagentprolog-hf`.
- Опционально: `torch`, `sentence-transformers`.
- Для приватных HF-моделей: `FONA_HF_TOKEN`.
- Для bind не на localhost: `FONA_TOKEN` (REST-аутентификация) — см. §16 руководства.

---

## Статус

`0.1.0` — в разработке. Публичный API и меж-агентный протокол стабильны; дашборд и оркестратор могут меняться. Semver применяется к `Agent`, `agent`, декораторам, `load_config` / `register_*`.

---

## Лицензия

См. `LICENSE`.

---

**Одной строкой:** Fona позволяет описать агента как Prolog-программу плюс Python-действия, поднять его по HTTP с чат-UI и научить говорить с другими агентами — всё через один Prolog-only протокол. За остальным — в [`docs/guide-ru.md`](docs/guide.md).