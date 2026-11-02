# pyagentprolog-fona

Минималистичный фреймворк для фоновых ИИ-агентов на PyAgentProlog.
Пользователь пишет **Prolog** и **Python-функции**, а всё остальное —
FastAPI, SSE-UI, REST для других агентов, фоновый запуск на Windows —
прячется за декораторами.

```python
from fona import agent

agent.program("""
run :-
    ui_print('Введите имя:'),
    ui_read(Name),
    format('Привет, ~w!', [Name], Msg),
    ui_print(Msg).
""")

agent.run()
```

После запуска:

- `http://127.0.0.1:8000/` — готовый UI с логом, вводом и кнопками.
- `http://127.0.0.1:8000/docs` — интерактивная OpenAPI-документация.
- `http://127.0.0.1:8000/api/v1/query` — REST для других агентов.

Запуск занимает ~2 секунды для standalone-агента: `transformers`
и `torch` **не** импортируются, пока не запрошена HF-модель.

---

## Содержание

- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Декораторы](#декораторы)
  - [`@agent.program` — три формы](#agentprogram--три-формы)
  - [`@agent.action`](#agentaction)
  - [`@agent.effect`](#agenteffect)
  - [`@agent.generate`](#agentgenerate)
- [Запуск](#запуск)
- [HF-модели](#hf-модели)
- [Программный доступ](#программный-доступ)
- [REST API](#rest-api)
- [HITL и UI](#hitl-и-ui)
- [Мультиагентное взаимодействие](#мультиагентное-взаимодействие)
- [Фоновый режим](#фоновый-режим)
- [Служба Windows (NSSM)](#служба-windows-nssm)
- [Переменные окружения](#переменные-окружения)
- [Архитектура](#архитектура)
- [Производительность](#производительность)
- [Ограничения и подводные камни](#ограничения-и-подводные-камни)
- [Лицензия](#лицензия)

---

## Установка

Базовый вариант (standalone-агенты, без torch):

```bash
pip install pyagentprolog-fona
```

С поддержкой HF Hub, torch и эмбеддингов:

```bash
pip install "pyagentprolog-fona[all]"
```

Только HF Hub (без sentence-transformers):

```bash
pip install "pyagentprolog-fona[torch]"
```

Только семантика (без torch-моделей HF):

```bash
pip install "pyagentprolog-fona[semantic]"
```

Требования: Python 3.10+, PyAgentProlog ≥ 5.9.1, PyAgentProlog-HF ≥ 0.2.0.

---

## Быстрый старт

`hello.py`:

```python
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
    agent.run()
    # agent.run(background=True)
```

```bash
python hello.py
```

Терминал покажет:

```
[fona] build(): 0.00s (standalone)
INFO:     Uvicorn running on http://127.0.0.1:8000
```

Откройте `http://127.0.0.1:8000/` и **нажмите «Запустить»**. Предикат
`run.` выполняется по клику, а не при старте uvicorn: иначе каждая
открытая вкладка держала бы поток, заблокированный на `ui_read`.

Встроенные предикаты, доступные в любом агенте с UI:

| Предикат | Описание |
|---|---|
| `ui_print(+Text)` | Вывести текст в лог UI |
| `ui_read(-Text)` | Дождаться ввода из UI |
| `ui_get_value(+Name, -Value)` | Прочитать значение UI-компонента |
| `gradio_print/1`, `gradio_read_input/1`, `gradio_get_ui_value/2` | Алиасы для совместимости |
| `format(+Fmt, +Args, -Text)` | Форматирование строки |

---

## Декораторы

### `@agent.program` — три формы

**Важно:** в Python декоратор нельзя применить к присваиванию.
Запись

```python
@agent.program
PROGRAM = """..."""      # ← SyntaxError
```

**невалидна**, интерпретатор падает ещё до вызова декоратора. Fona
поддерживает три корректные формы:

#### Форма 1 — прямой вызов

```python
from fona import agent

agent.program("""
parent(ivan, alexey).
parent(alexey, peter).

run :-
    parent(ivan, X),
    format('Ребёнок Ивана: ~w', [X], Msg),
    ui_print(Msg).
""")
```

Самая простая, работает всегда.

#### Форма 2 — декоратор на функции

```python
from fona import agent

@agent.program
def _program():
    return """
    parent(ivan, alexey).
    parent(alexey, peter).
    run :- parent(ivan, X), ui_print(X).
    """
```

Работает, потому что `@agent.program` вызывает функцию и берёт строку.
Имя функции сохраняется — можно распечатать исходник через
`print(_program())`.

#### Форма 3 — присваивание

```python
from fona import agent

agent.program = """
parent(ivan, alexey).
run :- parent(ivan, X), ui_print(X).
"""
```

Работает через дескриптор `_ProgramDescriptor`. Визуально похоже на
исходную (невалидную) запись, но без `@`.

#### Семантика накопления

Несколько вызовов `agent.program(...)` **накапливают** текст:

```python
agent.program("fact1(1).")
agent.program("fact2(2).")
# В базе: fact1/1 и fact2/1
```

С HF-моделью текст **дополняет** `config.program` модели (prepend —
ваши правила идут первыми; см. [HF-модели](#hf-модели)).

### `@agent.action`

Предикат, **возвращающий значение**. Арность и позиция выходного
аргумента выводятся из сигнатуры.

```python
@agent.action
def ask_llm(prompt):
    return llm_client.generate(prompt)
# → предикат ask_llm/2, output_arg=1

@agent.action(name='ask_llm', arity=2, output_arg=1)
def ask(prompt):
    return llm_client.generate(prompt)
```

Правила вывода:

- Имя предиката = имя Python-функции (или `name=`).
- Арность = число параметров + 1 (для output).
- Выходной аргумент — последний.
- `context` не считается параметром, но доступен:

```python
@agent.action
def ask(prompt, context):
    return context['llm'].generate(prompt)
```

- Если функция содержит `yield`, автоматически оборачивается как
  генератор — каждый `yield` даёт отдельное решение.
- Возврат `None` → **провал** (backtracking).

### `@agent.effect`

Побочный эффект без возврата. Все аргументы входные. **Всегда
успешно**, если не было исключения.

```python
@agent.effect
def log_to_file(text):
    with open('agent.log', 'a') as f:
        f.write(text + '\n')
# → предикат log_to_file/1
```

### `@agent.generate`

Явное объявление генератора.

```python
@agent.generate
def rooms():
    yield "kitchen"
    yield "bedroom"
    yield "living_room"
# → предикат rooms/1
```

В Prolog:

```prolog
all_rooms :-
    rooms(R),
    ui_print(R),
    fail.
all_rooms.
```

### Таблица соответствия

| Декоратор | Возврат | При неудаче | Пример |
|---|---|---|---|
| `@agent.action` | значение → в output_arg | `None` → fail | LLM-запрос, вычисление, сенсор |
| `@agent.effect` | нет | исключение → fail | запись в лог, отправка команды |
| `@agent.generate` | `yield` → решения | пустой генератор → fail | перебор комнат, вариантов |

---

## Запуск

```python
agent.run()                       # foreground, 127.0.0.1:8000
agent.run(port=9000)              # другой порт
agent.run(host='0.0.0.0')         # по сети (см. token)
agent.run(ui=False)               # только REST
agent.run(rest=False)             # только UI
agent.run(token='secret')         # REST под токеном
agent.run(background=True)        # скрытый процесс (pythonw)
```

`agent.run()` — блокирующий вызов. `background=True` возвращает
управление сразу, запустив дочерний `pythonw.exe`.

### Что доступно после запуска

| URL | Назначение |
|---|---|
| `/` | HTML UI с логом и вводом |
| `/docs` | Swagger / OpenAPI |
| `/api/v1/health` | Health-check |
| `/api/v1/model` | Информация о загруженной модели |
| `/api/v1/query` | REST: выполнить Prolog-запрос |
| `/api/v1/query_one` | REST: первый ответ |
| `/api/v1/stream` | SSE-стрим решений |
| `/api/v1/facts` | Добавить факт(ы) |
| `/api/v1/actions` | Список зарегистрированных действий |
| `/api/v1/ui/start` · `input` · `stop` · `stream` | HITL-сессии |

### Автостарт HITL

По умолчанию `run.` стартует по клику **Запустить**. Чтобы диалог
начинался сразу при открытии страницы, добавьте `start();` в конец
`<script>` в `fona/ui.py` (или своём HTML — см. [HITL и UI](#hitl-и-ui)).

---

## HF-модели

Fona умеет загружать `PyAgentPrologModel` с Hugging Face Hub (или из
локальной директории) как **базу** для агента.

### Простейший вариант

```python
from fona import agent

agent.load_hub('user/pyagent-prolog-demo')
agent.run()
```

Модель загружается через `PyAgentPrologModel.from_pretrained(...,
trust_remote_code=True)`. Её `config.program`, `config.kb_file` и
семантические директивы подхватываются автоматически.

### С расширениями

```python
from fona import agent

agent.load_hub('user/pyagent-prolog-demo')

@agent.action
def translate(text):
    return my_llm(f'Translate to English: {text}')

agent.program = """
run :-
    ui_print('Текст:'),
    ui_read(Text),
    translate(Text, En),
    ui_print(En).
"""

agent.run()
```

`agent.program` **дополняет** `config.program` HF-модели (prepend), а
`translate/2` регистрируется в том же `Database` — HF-программа может
его вызывать.

### Через `Agent.from_hub`

```python
from fona import Agent

a = Agent.from_hub('user/repo', revision='main')
a.run()
```

### KB из Hub

Если в `config.json` модели есть `kb_file`, но файл не найден
локально, Fona автоматически вызывает `hf_hub_download` и загружает
KB в `Database`. Это обходит ограничение обёртки
`pyagentprolog-hf`: `_resolve_kb_path` не работает для `hf:user/repo`.

### Приватные модели

```bash
export FONA_HF_TOKEN=hf_xxxxxxxxxxxxxxxx
python agent.py
```

Локально без сети:

```bash
export FONA_LOCAL_ONLY=1
python agent.py
```

### Overrides после загрузки

```python
agent.load_hub('user/repo')

agent.configure(
    semantic_enabled=True,
    semantic_threshold=0.82,
    semantic_model='intfloat/multilingual-e5-small',
    semantic_backend='st',
    max_solutions=50,
    default_main='handle_request',
)
```

Работает только для HF-модели: применяется **после** загрузки и
`_ensure_solver()`.

---

## Программный доступ

Если сервер не нужен, Fona даёт прямой доступ к модели:

```python
from fona import Agent

a = Agent.from_hub('user/repo')

result = a.query('light(kitchen, X).')
print(result['solution'])       # [{'X': 'on'}]

sol = a.query_one('light(kitchen, X).')
print(sol)                       # {'X': 'on'} или None

for sol in a.stream('light(Room, State).'):
    print(sol)

result = a('light(kitchen, X).')
```

Тот же объект потом можно поднять как сервер: `a.run()`.

### Терминальный режим без сервера

Если браузер не нужен, объявите свои `print`/`input`-действия и
вызовите `query` напрямую:

```python
from fona import agent

@agent.effect
def say(text):
    print(f'[Агент]: {text}', flush=True)

@agent.action
def ask():
    return input('>> ').strip()

agent.program = """
run :- loop.
loop :-
    say('Введите сообщение (или "stop"):'),
    ask(Action),
    ( Action = "stop" -> say('Пока!'), !
    ; say(Action), loop
    ).
"""

if __name__ == '__main__':
    agent.build()          # без with_ui=True
    agent.query('run.')    # без HTTP
```

---

## REST API

Все эндпоинты, кроме `/health`, требуют `X-API-Key`, если при запуске
был передан `token=` (или задан `FONA_TOKEN`).

```http
POST /api/v1/query
Content-Type: application/json
X-API-Key: your-token-here

{"query": "light(kitchen, X)."}
```

Ответ:

```json
{
  "success": true,
  "query": "light(kitchen, X).",
  "solutions": [{"X": "on"}],
  "count": 1
}
```

Провал:

```json
{"success": false, "query": "light(garage, X).", "solutions": [], "count": 0}
```

Ошибка разбора или выполнения:

```json
{"success": false, "query": "broken(", "error": "Query parse error: ..."}
```

Пример:

```python
import httpx

r = httpx.post(
    'http://127.0.0.1:8000/api/v1/query',
    json={'query': 'light(Room, State).'},
    headers={'X-API-Key': 'secret-token'},
    timeout=10.0,
)
print(r.json())
```

### Добавление фактов

```python
httpx.post(
    'http://127.0.0.1:8000/api/v1/facts',
    params={'fact': 'light(garage, off). light(garden, on).'},
    headers={'X-API-Key': 'secret-token'},
)
```

### SSE-стрим

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/stream \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret-token" \
  -d '{"query": "light(Room, State)."}'
```

События:

```
data: {"Room": "kitchen", "State": "on"}

data: {"Room": "bedroom", "State": "off"}

event: done
data: {}
```

---

## HITL и UI

HITL в Fona — естественное продолжение агента. В Prolog вы пишете
`ui_read/1`, а JS-фронтенд разблокирует поле ввода. Состояние живёт в
`Database`, а не в чекпоинтах.

### Как устроена сессия

Каждый клик **Запустить** → `POST /api/v1/ui/start` → создаётся:

1. **Клон модели** (`_clone_model`) — независимый `Database` и
   `tracer`. Пользовательские `@agent.action` и стандартные
   `gradio_*`/`ui_*` копируются.
2. **`QueryOneSession`** — наследник `AgentGradioSession`, вызывает
   `query_one('run.')` вместо `query('run.')`. Это важно для
   HF-моделей: если ваш `PROGRAM` переопределяет `run/0`, HF-ный
   `run/0` не будет выполняться вдогонку.
3. **SSE-канал** `/api/v1/ui/stream?session_id=...` — стримит вывод
   (`event: output`) и состояние (`event: state`).

### Ввод из UI

JS читает значения компонентов и передаёт их в `POST
/api/v1/ui/input`. Значения попадают в `session.set_ui_value`,
доступны из Prolog через `ui_get_value/2` или
`gradio_get_ui_value/2`.

```prolog
run :-
    ui_get_value('mode_select', Mode),
    format('Режим: ~w', [Mode], Msg),
    ui_print(Msg),
    ui_read(Text),
    ...
```

### Автостарт

Одна строка в конце `<script>` в `fona/ui.py`:

```javascript
start();
```

Этого достаточно, чтобы диалог стартовал при открытии страницы. Для
production добавьте очистку сессий по таймауту.

### Полная замена HTML

HTML-шаблон — это строка `HTML` в `fona/ui.py`. Чтобы заменить его на
свой (например, чат-бот в стиле bubbles), передайте `html=` в
`create_app` и добавьте параметр в `run()`:

```python
# fona/server.py
def create_app(model, *, html=None, **kwargs):
    ...
    page = html or HTML
    @app.get("/", response_class=HTMLResponse)
    async def index(): return page
```

---

## Мультиагентное взаимодействие

Агенты общаются по HTTP. Один агент — REST-сервер; другой вызывает
его как обычное действие.

`server_agent.py`:

```python
from fona import agent

agent.program = """
light(kitchen, on).
light(bedroom, off).

run :- ui_print('Сервер фактов готов.').
"""

agent.run(port=8000, ui=False, token='secret')
```

`client_agent.py`:

```python
from fona import agent

@agent.action
def ask_remote(url, query, context):
    import httpx
    headers = {}
    token = context.get('api_token') if context else None
    if token:
        headers['X-API-Key'] = token
    with httpx.Client(timeout=10.0) as c:
        r = c.post(url, json={'query': query}, headers=headers)
        r.raise_for_status()
        return r.json().get('solutions')

agent.program = """
run :-
    ask_remote('http://127.0.0.1:8000/api/v1/query',
               'light(kitchen, X).',
               Solutions),
    format('Получено: ~w', [Solutions], Msg),
    ui_print(Msg).
"""

agent.run(port=8001)
```

### Проверка

```bash
# терминал A
python server_agent.py

# терминал B — убедиться, что сервер жив
curl -X POST http://127.0.0.1:8000/api/v1/query \
     -H "Content-Type: application/json" \
     -H "X-API-Key: secret" \
     -d '{"query": "light(kitchen, X)."}'

# терминал C
python client_agent.py
# открыть http://127.0.0.1:8001/, нажать «Запустить»
```

В логе клиента должно появиться `Получено: [{'X': 'on'}]`. Если сервер
не запущен — в stderr клиента будет `httpx.ConnectError`, а в UI —
«Агент завершил выполнение без решений».

### Общая память

Три подхода:

1. **Общая KB через файл.** Два агента читают/пишут один `kb.pl`, но
   `Database` у каждого свой.
2. **REST `/api/v1/facts`.** Один агент — «владелец» KB, остальные
   пишут через API.
3. **`context` с общим клиентом.** Передайте в `agent.build()` объект
   БД/очереди, доступный всем действиям.

### Маршрутизация через Prolog

```prolog
route(Task, Agent) :-
    task_type(Task, Type),
    agent_capability(Agent, Type),
    agent_available(Agent).

agent_capability('http://agent-a:8000', light).
agent_capability('http://agent-b:8000', temperature).
```

Диспетчер — обычный `Agent` с правилами `route/2` и действием
`ask_remote/3`. Всё аудируется через ProofTracer при
`with_explanation=True`.

---

## Фоновый режим

### `agent.run(background=True)`

Запускает дочерний `pythonw.exe` (Windows) или `python` (Unix) в
фоне. Родительский процесс возвращает управление сразу.

```python
agent.run(background=True)
print('Агент работает в фоне')
```

Что происходит под капотом:

1. `sys.modules['__main__'].__file__` — путь к скрипту.
2. `sys.executable` заменяется на `pythonw.exe`, если найден.
3. `Popen` с `FONA_CHILD=1`.
4. Дочерний процесс видит `FONA_CHILD=1` и не спавнится снова.

### Ограничение

Если скрипт — REPL или `python -c "..."`, `_spawn_background` не
найдёт `.py`-файл и запустит foreground.

---

## Служба Windows (NSSM)

Для production на Windows — служба через [NSSM](https://nssm.cc/).
Даёт автозапуск при загрузке ОС и перезапуск при сбоях, независимо
от входа пользователя.

```cmd
nssm install FonaAgent "C:\Python311\python.exe" "C:\agents\agent.py"
nssm set FonaAgent AppDirectory C:\agents
nssm set FonaAgent AppStdout C:\agents\logs\agent.out.log
nssm set FonaAgent AppStderr C:\agents\logs\agent.err.log
nssm set FonaAgent AppRotateFiles 1
nssm set FonaAgent AppRotateBytes 10485760
nssm set FonaAgent AppEnvironmentExtra ^
  "FONA_TOKEN=secret-token" ^
  "FONA_HF_TOKEN=hf_xxxxxxxxxxxxxxxx"
nssm set FonaAgent Start SERVICE_AUTO_START
nssm start FonaAgent
```

Важно:

- `python.exe`, а не `pythonw.exe` — NSSM перенаправляет
  stdout/stderr в файлы.
- `AppDirectory` обязателен, иначе не найдутся модули.
- `AppRotateBytes` + `AppRotateFiles=1` — ротация логов.
- `AppEnvironmentExtra` — переменные окружения.

Управление:

```cmd
nssm stop FonaAgent
nssm restart FonaAgent
nssm remove FonaAgent confirm
```

---

## Переменные окружения

Fona:

| Переменная | Значение | Описание |
|---|---|---|
| `FONA_HF_TOKEN` | `hf_xxx...` | Токен HF Hub для приватных моделей |
| `FONA_LOCAL_ONLY` | `1` | Не обращаться к сети, использовать кэш HF Hub |
| `FONA_TOKEN` | `secret` | Токен REST API (по умолчанию — без аутентификации) |
| `FONA_WARMUP` | `1` | Прогреть Numba JIT при старте (для арифметически-тяжёлых агентов) |
| `FONA_CHILD` | `1` | Внутренний маркер дочернего процесса при `background=True` |

PyAgentProlog:

| Переменная | Описание |
|---|---|
| `PROLOG_NUMBA_DISABLE=1` | Отключить Numba-ускорение арифметики |
| `PROLOG_ST_VERBOSE=1` | Показывать прогресс-бары sentence-transformers |
| `HF_HUB_DISABLE_PROGRESS_BARS=1` | Отключить полосы загрузки HF Hub |

---

## Архитектура

```
Fona Agent
│
├── Agent (fona.agent)
│   ├── _program      — Prolog-текст
│   ├── _actions      — Python-предикаты (@action/@effect/@generate)
│   ├── _hub_source   — (repo, revision), если load_hub()
│   ├── _overrides    — configure()
│   └── build() → PyAgentPrologModel | _StandaloneModel
│
├── PyAgentPrologModel (pyagentprolog-hf)   ← только для HF-пути
│   ├── config        — PyAgentPrologConfig
│   ├── agent         — Agent из PyAgentProlog
│   └── _ensure_solver
│
├── _StandaloneModel (fona.agent)           ← HF-путь не нужен
│   ├── config        — SimpleNamespace (минимум полей)
│   ├── agent         — Agent из PyAgentProlog
│   └── _ensure_solver (no-op)
│
└── FastAPI (fona.server)
    ├── /                       — HTML (fona.ui)
    ├── /api/v1/ui/*            — HITL-сессии (QueryOneSession)
    ├── /api/v1/query           — REST
    ├── /api/v1/query_one       — REST
    ├── /api/v1/stream          — SSE
    ├── /api/v1/facts           — добавить факты
    ├── /api/v1/actions         — список действий
    └── /api/v1/model           — информация о модели
```

### Поток `agent.run()` для standalone

```
agent.run(background=False)
│
├── build(with_ui=True)
│   ├── _StandaloneModel(_program, overrides)
│   │   └── prolog.agent.Agent(program)      ← без torch, без transformers
│   ├── register _actions
│   └── _install_ui_actions → ui_print/1, ui_read/1, gradio_*
│
├── _start_query(model) → "run."
│
└── create_app(model, start_query, ...)
    └── uvicorn.run(app)        ← ~2 c, torch не импортирован
```

### Поток `agent.run()` для HF

```
agent.run(background=False)
│
├── build(with_ui=True)
│   ├── _import_hf() → from pyagentprolog_hf import ...  ← здесь transformers/torch
│   ├── PyAgentPrologModel.from_pretrained(repo, trust_remote_code=True)
│   ├── _ensure_solver()
│   ├── _ensure_kb_loaded (hf_hub_download, если kb_file задан)
│   ├── prepend @agent.program rules (at_beginning=True)
│   ├── register _actions
│   └── _install_ui_actions
│
└── create_app(model, ...) → uvicorn.run(app)   ← ~7 c
```

### Поток HITL-запроса

```
Браузер                   Сервер
   │                        │
   ├─ POST /ui/start ──────►│  _clone_model(model)
   │                        │  _create_query_one_session()
   │                        │  sess.start(clone.agent, 'run.')
   │  ◄──── session_id ─────│
   │                        │
   ├─ GET /ui/stream ──────►│  StreamingResponse:
   │  ◄──── event: state ───│    yield 'running'
   │  ◄──── event: output ──│    session.get_output()
   │                        │    await asyncio.sleep(0.2)
   │                        │
   ├─ POST /ui/input ──────►│  session.set_ui_value(...)
   │                        │  session.send_input(text)
   │                        │
   │                        │  QueryOneSession._run:
   │                        │    agent.query_one('run.')
   │                        │    ui_read/1 блокируется на input_queue.get()
   │                        │
   │                        │  Prolog продолжается:
   │                        │    ui_print(Result) → output_queue
   │                        │    running=False
   │                        │
   │  ◄──── event: output ──│  последние сообщения
   │  ◄──── event: state ───│  finished=true
```

---

## Производительность

Замеры на Windows 11 / Python 3.12 / CPU:

| Этап | Standalone | HF |
|---|---|---|
| `from fona import agent` | 0.4 с | 7.4 с |
| `agent.build()` | 0.2 с | 0.3 с |
| `create_app` + `uvicorn.run` | 1.5 с | 1.5 с |
| `warmup_arith_numba` (опционально) | 0 с | 12 с |
| **Итого при старте** | **~2 с** | **~9 с** |

Что помогает:

- **Standalone-путь без torch/transformers.** `_import_hf()` вызывается
  только при `load_hub()` / `from_hub()`. Обычный `agent.run()` не
  тянет `transformers`/`torch`.
- **`FONA_WARMUP=1`** — opt-in для Numba JIT. Чат-ботам без арифметики
  он не нужен.
- **`PROLOG_NUMBA_DISABLE=1`** — отключить numba полностью, если JIT
  не нужен.
- **CPU-only torch** (`pip install torch --index-url
  https://download.pytorch.org/whl/cpu`) — импортируется быстрее.

Проверить, что torch не загрузился в standalone:

```python
import sys
assert 'torch' not in sys.modules
```

---

## Ограничения и подводные камни

### `Database` не потокобезопасна

`interpreter.py` мутирует `rules`, `rule_index`, `_cut_counter`,
`tracer`. Поэтому:

- **REST-запросы** к шаблонной модели идут под `threading.RLock` (в
  `create_app`).
- **HITL-сессии** изолированы: каждая со своей копией модели.
- **Программный `agent.query()`** без сервера **не потокобезопасен**.
  Из нескольких потоков — оборачивайте в свой лок.

### `semantic_on` — глобальное состояние

`_current_unifier` в `prolog.embedding_unify` — один на процесс. Если
включите семантику через `configure(semantic_enabled=True)`, она
повлияет на HF-модель и HITL-сессии. Это ожидаемо.

### `remote_query` под `API_LOCK`

Если `ask_remote/3` вызывает другой агент, шаблонная модель держит
лок на всё время HTTP-запроса. Для цепочек: короткий `timeout`
(5–10 с), лучше вызывать `ask_remote` из клиентского агента снаружи.

### `kb_file` не перезагружается динамически

`configure(kb_file=...)` не перезагружает KB: обёртка не
предоставляет публичного API. Workaround:

```python
agent.build()._load_kb_file('/path/to/new.pl', 'text')
```

Это внутренний API, но работает. Для продакшна лучше перезапустить
процесс.

### `PROGRAM` только дополняет HF-модель

Через `@agent.program` нельзя **удалить** правила из
`config.program` HF-модели. Ваши правила prepend-ятся, HF-ные
остаются. Полное переопределение — используйте Fona без
`load_hub()`.

### `@agent.program` на присваивании — SyntaxError

Запись `@agent.program\nPROGRAM = ...` **невалидна**. Используйте
одну из трёх форм: `agent.program(...)`, `@agent.program def ...`,
`agent.program = ...`. См. [`@agent.program` — три
формы](#agentprogram--три-формы).

### `None` в `@agent.action` → fail

Возврат `None` означает провал предиката (backtracking). Если нужен
«всегда успешный» эффект — `@agent.effect`.

### `output_arg` по умолчанию — последний

`@agent.action` делает **последний** аргумент выходным. Если функция
принимает `(prompt, temp=0.7)`, предикат будет `ask/3` с
`output_arg=2`, а `temp` станет вторым аргументом. Используйте
`@agent.action(output_arg=N)` или `arity=`.

### HITL-старт по клику, а не при загрузке uvicorn

По умолчанию `run.` выполняется после нажатия **Запустить**. Если
хотите автостарт — добавьте `start();` в `<script>` шаблона (см.
[HITL и UI](#hitl-и-ui)).

### `from_pretrained` в HITL-клонах

`_clone_model` использует `PyAgentPrologConfig.from_pretrained(...,
local_files_only=True)` для HF-моделей. Если кэш HF Hub пуст (модель
загружалась без кэширования), клон упадёт. Решение —
`FONA_LOCAL_ONLY=1` или явный прогрев кэша.

---

## Лицензия

MIT. См. `LICENSE`.

---

## Авторы

- Andrey Vorfolomeev — PyAgentProlog, PyAgentProlog-HF, Fona