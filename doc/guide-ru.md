# Руководство по Fona

## 1. Что такое Fona

Fona — минималистичный фреймворк для создания **фоновых ИИ-агентов** на базе PyAgentProlog. Агент пишется на Prolog (логика) и Python (действия), запускается как HTTP-сервер с UI и REST API, может взаимодействовать с пользователем и другими агентами. Дашборд — опциональная надстройка для управления командой.

**Три пакета:**

| Пакет | Роль |
|---|---|
| `pyagentprolog` | Ядро: интерпретатор Prolog, парсер, агент |
| `pyagentprolog-hf` | Обёртка HuggingFace-моделей как PyAgentProlog-моделей |
| `pyagentprolog-fona` | Публичный пакет: `Agent`, декораторы, сервер, дашборд |

---

## 2. Установка

```bash
pip install pyagentprolog-fona
```

**Зависимости core:** `fastapi`, `uvicorn`, `httpx`, `pydantic`, `transformers`, `huggingface_hub`, `pyagentprolog`, `pyagentprolog-hf`. `torch` и `sentence-transformers` — опционально (`pip install pyagentprolog-fona[torch]`).

**Python 3.10+.**

---

## 3. Быстрый старт: первый агент

Создайте `hello.py`:

```python
from fona import agent

agent.program("""
run :-
    ui_print('Привет! Я агент Fona.'),
    ui_print('Напишите что-нибудь.').
""")

if __name__ == '__main__':
    agent.run(port=8000)
```

Запустите:

```bash
python hello.py
```

Откройте `http://127.0.0.1:8000/` — увидите чат-интерфейс.

**Что произошло:**
1. `agent` — синглтон `Agent()`.
2. `agent.program(...)` установил `PROGRAM` — Prolog-программу агента.
3. `agent.run(port=8000)` собрал модель, создал FastAPI-приложение с UI и REST, запустил uvicorn в текущем процессе.

**Дашборд не нужен.** Это полноценный агент. Дашборд (§13) — только удобная обёртка для команды из нескольких агентов.

---

## 4. Основы

### 4.1. `@agent.program` — логика агента

Три эквивалентные формы:

```python
# Форма 1: присваивание
agent.program = "run :- ui_print('hi')."

# Форма 2: вызов
agent.program("run :- ui_print('hi').")

# Форма 3: декоратор
@agent.program
def PROGRAM():
    return "run :- ui_print('hi')."
```

Несколько вызовов **конкатенируются** через `\n`.

Для HF-модели (`Agent.from_hub`) `PROGRAM` **prepend**-ится к `config.program` модели: ваши правила срабатывают первыми, HF-ные — как fallback.

### 4.2. `@agent.action` — предикат, возвращающий значение

```python
@agent.action
def add(X, Y):
    return X + Y
```

→ `add/3` (2 входа + 1 выход, `output_arg=2`). `add(2, 3, R)` → `R = 5`.

**Arity из сигнатуры:**
- `def add(X, Y)` → `add/3`.
- `def ask(prompt, context)` → `ask/2` (`context` не считается, выход — `prompt`).

**`context`** — зарезервирован: получает `agent.context` (dict), не входит в arity, не доступен из Prolog.

**Семантика (P5):**
- `None` → **fail**.
- Исключение → **fail** (подавляется).

**Параметры декоратора:**
- `name='custom'` — имя предиката (по умолчанию — имя функции).
- `arity=4` — общая арность (по умолчанию `len(params) + 1`).
- `output_arg=0` — индекс выхода (по умолчанию последний).

### 4.3. `@agent.effect` — побочный эффект, всегда успешен

```python
@agent.effect
def log_event(message):
    print(f"[log] {message}")
```

→ `log_event/1`. При успехе — успех. При исключении — fail.

### 4.4. `@agent.generate` — генератор решений

```python
@agent.generate
def numbers(limit):
    for i in range(1, limit + 1):
        yield i
```

→ `numbers/2`. `numbers(3, L)` → `L = [1, 2, 3]` (все решения).

---

## 5. Запуск: `agent.run()`

```python
agent.run(
    host='127.0.0.1',     # адрес
    port=8000,            # порт
    ui=True,              # монтировать HTML UI на /
    rest=True,            # включить /api/v1/*
    token=None,           # FONA_TOKEN (None = без аутентификации)
    background=False,     # True = pythonw без окна (Windows)
)
```

**`background=True`** — запуск как фоновый процесс без консоли (Windows: `pythonw.exe`). Требует `.py`-файл как `__main__`.

**`token`** — если задан, все `/api/v1/*` (кроме `/health`) требуют `X-API-Key: <token>`.

**`host != '127.0.0.1'` + пустой `token`** → предупреждение в stderr. По умолчанию слушаем localhost.

---

## 6. Взаимодействие с пользователем (HITL)

**`ui_print/1`** — эффектор, выводит текст в UI-сессию.
**`ui_read/1`** — действие, **блокируется** до ввода пользователя, возвращает текст.

```prolog
run :-
    ui_print('Как вас зовут?'),
    ui_read(Name),
    format(atom(Msg), 'Привет, ~w!', [Name]),
    ui_print(Msg).
```

**Цикл:**

```prolog
run :- ui_print('Готов.'), on_user_input.

on_user_input :-
    ui_read(Input),
    dispatch(Input).

dispatch(quit) :- !, ui_print('Пока.').
dispatch(Input) :-
    format(atom(Msg), 'Вы сказали: ~w', [Input]),
    ui_print(Msg),
    on_user_input.
```

`ui_read` блокирует сессию, но не поток сервера. Каждый `POST /api/v1/ui/input` будит сессию. `QueryOneSession._run` вызывает `agent.query_one(start_query)` **один раз** — `run/0` не выполняется повторно.

---

## 7. Меж-агентное взаимодействие

Все вызовы идут через `POST /api/v1/query` с телом `{"query": "<Prolog text>"}`. Ответ: `{"success": bool, "solutions": [{"Var": value}], "count": int}`.

### 7.1. Входящие запросы: `handle_request/3`

```python
from fona import register_protocol

register_protocol(agent)  # ping/echo/status
```

Или с расширением:

```python
register_protocol(agent, extra={
    "echo": lambda p: p,
    "facts": lambda _: f"ok facts={len(agent.build().agent.solver.database.facts)}",
})
```

Пир вызывает:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "handle_request(\"ping\", R)."}'
# → {"success": true, "solutions": [{"R": "pong"}], ...}
```

### 7.2. Исходящие запросы: `call_peer/3`

```python
from fona import register_peers, load_config, team_resolver

CFG = load_config(
    peers=("FONA_PEERS", "peers", {}),
    token=("FONA_TOKEN", str, None),
)
register_peers(agent, CFG, resolver=team_resolver)
```

→ регистрирует `call_peer/3` и `broadcast_ping/0`.

**Семантика:** возвращает **атом** `"ok:<value>"` или `"err:<reason>"`. Ошибки — строкой, не исключением.

```prolog
run :-
    call_peer(warehouse, 'handle_request("check", "lamp 2", R).', Result),
    ui_print(Result).  % → "ok:10"
```

**`call_peer` внутри `peers.py`:**

```python
url = resolver(peer_name) if resolver else None      # team_resolver → live scan
if not url:
    url = (cfg.peers or {}).get(peer_name)           # fallback: FONA_PEERS
if not url:
    return f"err:unknown peer {peer_name}"
```

### 7.3. Как агент узнаёт порты других агентов

Порты **не** хранятся в `team.json` (v4). Они назначаются при `Start` (дашбордом или вручную через `FONA_PORT`). Узнать «кто на каком порту» можно только через `team_resolver`.

**Механизм `team_resolver(name)` (в `fona/team.py`):**

1. **Self** — если `name == FONA_AGENT_NAME`, вернуть `http://127.0.0.1:$FONA_PORT`. Скан не нужен.
2. **Static** — если в `team.json` у пира есть `port` (v2/v3), использовать его. В v4 этого поля нет.
3. **Live scan** — `scan_range(*port_range)` → на каждом порту `GET /api/v1/model` → сопоставить `agent_name` → `port` → URL. Результат кешируется на **2 секунды** (`_CACHE_TTL`).

Если ничего не дало URL — `team_resolver` возвращает `None`, `call_peer` уходит в `cfg.peers` (`FONA_PEERS`). Если и там нет — `"err:unknown peer <name>"`.

**Три env, которые дашборд прокидывает автоматически:**

| Env | Значение | Кто ставит |
|---|---|---|
| `FONA_TEAM_FILE` | абсолютный путь к `team.json` | дашборд при `Start` |
| `FONA_AGENT_NAME` | имя агента в `team.json` (`WH`, `ORDERS`, `CHAT`) | дашборд |
| `FONA_PORT` | фактический порт | дашборд |

**Критично:** `name` в `call_peer(name, …)` должен **совпадать** с полем `name` в `team.json`. Если в `team.json` записано `"WH"`, а в `chat_agent.py` вызывается `call_peer("warehouse", …)`, `team_resolver` вернёт `None` и `call_peer` уйдёт в `FONA_PEERS` (если задан) или `err:unknown peer`.

**Кеш и перезапуски.** Если пир умер и перезапустился на новом порту, первые 2 с после перезапуска `call_peer` может получить `err:unknown peer`. Через `_CACHE_TTL` кеш обновится, пир найдётся. Если пир был в кеше, но стал недоступен — `call_peer` вернёт `err:http …`, через 2 с `_live_scan` его выкинет.

**Self-resolver.** Если агент вызывает `call_peer(своё_имя, …)` — `team_resolver` вернёт свой URL без сканирования (из `FONA_AGENT_NAME` + `FONA_PORT`). Полезно для broadcast.

### 7.4. Работа без дашборда

`team_resolver` работает и без дашборда — если заданы `FONA_TEAM_FILE`, `FONA_AGENT_NAME`, `FONA_PORT`. Без `team.json` остаётся только `FONA_PEERS` (статический список URL).

```bash
# Три терминала
FONA_AGENT_NAME=WH FONA_TEAM_NAME=test1 \
FONA_TEAM_FILE=/path/to/team.json FONA_PORT=8020 \
python warehouse_agent.py

FONA_AGENT_NAME=ORDERS FONA_TEAM_NAME=test1 \
FONA_TEAM_FILE=/path/to/team.json FONA_PORT=8021 \
python orders_agent.py

FONA_AGENT_NAME=CHAT FONA_TEAM_NAME=test1 \
FONA_TEAM_FILE=/path/to/team.json FONA_PORT=8022 \
python chat_agent.py
```

Каждый агент — обычный процесс. `team_resolver` при `call_peer("WH", …)` найдёт WH через `scan_range([8020, 8099])` из `team.json`.

---

## 8. Конфигурация: `load_config`

Декларативный загрузчик env-переменных.

```python
from fona import load_config

CFG = load_config(
    port=("FONA_PORT", int, 8000),
    token=("FONA_TOKEN", str, None),
    peers=("FONA_PEERS", "peers", {}),
    timeout=("FONA_HTTP_TIMEOUT", float, 10.0),
    peers_headers=True,  # X-API-Key для CFG.http
)
```

**Спецификация:** `name = (env_var, parser, default)`.

**Парсеры:** `int`, `float`, `str`, `bool`, `"peers"`, `"csv"`, `"json"`, callable.

**Результат:** `CFG.port`, `CFG.peers`, `CFG.http` (общий `httpx.Client`), `CFG.as_dict()`.

**Принцип:** `load_config` вызывается **один раз** при импорте. Immutable (`frozen=True`).

---

## 9. NL ↔ Prolog: спутники HITL

**Это не часть протокола.** Обычные `@agent.action`, вызываемые из `PROGRAM` **до** и **после** `query_one`.

```python
@agent.action
def nl_to_prolog(text):
    # Заглушка. Замените на вызов HF/LLM:
    # from transformers import AutoModel
    # model = AutoModel.from_pretrained("user/pyagent-prolog-nl",
    #                                   trust_remote_code=True)
    # return model.generate(texts=[text]).results[0]["answers"][0]["Answer"]
    return f"err:nl_to_prolog not configured ({text!r})"

@agent.action
def prolog_to_nl(term):
    return f"err:prolog_to_nl not configured ({term!r})"
```

В `PROGRAM`:

```prolog
on_user_input :-
    ui_read(Text),
    (   Text == quit -> ui_print('Пока.')
    ;   sub_atom(Text, 0, 3, _, 'nl ')
    ->  sub_atom(Text, 3, _, 0, NL),
        nl_to_prolog(NL, Prolog),
        run_query(Prolog)
    ;   run_query(Text)
    ).

run_query(Query) :-
    query_one(Query, Result),
    (   Result == '' -> ui_print('Нет решения.')
    ;   prolog_to_nl(Result, NL),
        (   sub_atom(NL, 0, 4, _, 'err:') -> ui_print(Result)
        ;   ui_print(NL)
        )
    ),
    on_user_input.
```

`PROGRAM` **не парсит** содержимое. Отрезает префикс `nl ` и передаёт остаток в действие. Преобразование — в Python.

---

## 10. `query_one/1`: внутренний мост к движку

```python
@agent.action
def query_one(prolog_text):
    sol = agent.query_one(prolog_text)
    return "" if sol is None else str(sol)
```

**Назначение:** выполнить произвольный Prolog-текст из середины `PROGRAM`. `PROGRAM` не умеет «выполнить текст» — только унифицировать цели.

**Где используется:** только HITL-цикл. Пир и UI-сессия идут другими путями:
- **Пир:** `server.py` → `agent.query(q)` напрямую.
- **UI-сессия:** `QueryOneSession._run` → `agent.query_one(start_query)` один раз при старте.

**Архитектурное правило:** `query_one/1` — тонкий мост. Не обрабатывает запрос. Любая интерпретация — в `PROGRAM` или в отдельном действии **до** `query_one`.

---

## 11. REST API

| Эндпоинт | Метод | Назначение |
|---|---|---|
| `/` | GET | HTML UI (если `ui=True`) |
| `/api/v1/health` | GET | `{"status": "ok", "pid": N}` — без токена |
| `/api/v1/model` | GET | `rules_count`, `kb_file`, `actions`, `agent_name`, `team_name` |
| `/api/v1/query` | POST | Prolog-запрос `{"query": "..."}` |
| `/api/v1/query_one` | POST | Первое решение |
| `/api/v1/stream` | POST | SSE-поток решений |
| `/api/v1/facts` | POST | `?fact=light(kitchen,on).` |
| `/api/v1/actions` | GET | Список действий |
| `/api/v1/ui/start` | POST | HITL-сессия → `{"session_id": "..."}` |
| `/api/v1/ui/input` | POST | `{"session_id": "...", "text": "...", "ui_values": {}}` |
| `/api/v1/ui/stream` | GET | SSE: `event: output`, `event: state` |
| `/api/v1/ui/stop` | POST | `?session_id=...` |

**`/api/v1/query` — контракт для меж-агентного взаимодействия.** Возвращает `{"success": bool, "solutions": [...], "count": int}`. Ошибки — `{"success": false, "error": "..."}`.

**`api_lock`:** все REST-запросы к шаблонной модели идут под `threading.RLock`. `Database` не потокобезопасна.

---

## 12. HF-модели

### 12.1. Загрузка

```python
from fona import Agent

a = Agent.from_hub("user/repo-name", revision="main")
# или
a = Agent.from_hub("/local/path/to/model")
```

**Куда скачивается:** глобальный кэш HuggingFace.
- Linux/macOS: `~/.cache/huggingface/hub/`
- Windows: `C:\Users\<user>\.cache\huggingface\hub\`

**Переопределение:** `HF_HOME=/path` или `HF_HUB_CACHE=/path`.

### 12.2. Merge с `PROGRAM`

```python
a = Agent.from_hub("user/repo")
@a.program
PROGRAM = "run :- ui_print('my rule')."
a.run()
```

**Prepend:** ваш `run/0` **первый**, HF-ный — fallback. Порядок: `_ensure_solver()` → merge `PROGRAM` → `_ensure_kb_loaded()`.

### 12.3. Режимы

- **`FONA_LOCAL_ONLY=1`** — только локальный кэш, без сети.
- **`FONA_HF_TOKEN`** — токен для приватных моделей. Не логируется.

---

## 13. Дашборд

```bash
python -m fona.dashboard --port 7861
# или
fona-dashboard --port 7861
```

**Концепция:** проект = папка. Внутри: `team.json` (описание команды), `scripts/` (копии скриптов), `logs/` (runtime-логи). Дашборд — единый UI для управления командой: запуск, мониторинг, перезапуск, остановка, «усыновление» уже работающих агентов.

### 13.1. Запуск и автоопределение проекта

При старте `fona-dashboard` пытается найти проект:

1. Если задан `FONA_TEAM_FILE` и файл существует — используется он.
2. Иначе — рекурсивный поиск `team.json` в `cwd` и до **3 уровней вглубь**, с пропуском `.git`, `node_modules`, `venv`, `build`, `dist`, `.idea`, `.vscode`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `site-packages`.

Возможные исходы:

- **Ровно один** `team.json` — открывается автоматически (`autodetected project: <path>` в stderr), агенты загружаются, `autostart`-агенты запускаются.
- **Ни одного** — проект не открыт, карточки пусты. Вкладка `Adopted / Live` всё равно заполняется: `_live_scan_any()` сканирует стандартный диапазон Fona `[8020, 8099]`.
- **Несколько** — автооткрытие **не** происходит. В stderr — список найденных путей; пользователь открывает проект явно.

### 13.2. Блок «Проект»

Три кнопки в один ряд: `Открыть` / `Создать` / `Закрыть`. Без ручных полей пути, имени проекта или диапазона портов.

- **Открыть** → диалог выбора папки. `Project.from_folder(root)`:
  1. Если в папке есть `team.json` — открывает.
  2. Иначе ищет `team.json` до 3 уровней вглубь. Если ровно один — открывает; если несколько — `gr.Warning`, отказ; если ни одного — **предлагает создать** проект в этой папке.
- **Создать** → диалог выбора **пустой** папки. Создаёт `team.json` c `port_range: [8020, 8099]` и именем = имя папки. Если `team.json` уже есть — открывает существующий (не перезаписывает).
- **Закрыть** → `_active_project = None`, adopted-агенты **отпускаются** (не убиваются, §13.6). Карточки очищаются, вкладка `Adopted` продолжает работать.

**Статус-бар** под кнопками: `✓ <name> — N агентов, порты START-END` + полный путь к папке проекта.

**Автоподхват `team.json`:** при внешнем изменении файла (руками, `git pull`) дашборд перечитывает его автоматически. `_maybe_reload_team()` в каждом 2-секундном тике сравнивает `mtime` с кэшем. Reload **не** убивает adopted, **не** запускает никого — только обновляет карточки по `id`. Своё сохранение через «Сохранить» обновляет кэш `mtime`, поэтому не вызывает двойной reload.

### 13.3. Блок «Команда»

Две кнопки: `Сохранить` / `Загрузить и запустить`.

- **Сохранить** — пишет `team.json` из текущего состояния `_manager`. Ничего не запускает, `Adopted` не трогает.
- **Загрузить и запустить** — перечитывает `team.json` и запускает **всех**, кто не `online`/`adopted`. Явное действие пользователя, поэтому запускает всех, не только `autostart`.

### 13.4. Карточки агентов

Каждая карточка показывает статус (`ONLINE` / `OFFLINE` / `STARTING` / `STOPPED` / `ERROR` / `ADOPTED`), адрес, `uptime`, `latency`, число правил и действий, KB-файл, `source` (если агент добавлен из файла), шаблон оркестратора (если задан), долю успешных health-проверок, error-строку (если есть), sparkline.

Кнопки на карточке:

- **Open UI** — `http://127.0.0.1:<port>/` агента (когда `status == online`).
- **Orchestrator** — UI оркестратора, если у агента задан `orchestrator_template` и ему выделен второй порт из `port_range`.
- **Logs** — `/dashboard/logs?id=<id>&kind=err`.
- **Start / Stop / Restart / Remove** — обычные операции.
- **Autostart** — чекбокс, §13.7.

### 13.5. Вкладка «Adopted / Live»

Показывает **все** живые агенты в известных диапазонах портов — **независимо** от того, открыт ли проект. Таблица: `Team / Name / Port / PID / Status / Actions (Open UI, Kill)`.

Источники «известных диапазонов»:

1. `_active_project.port_range`, если проект открыт.
2. `port_range` из **всех** `team.json`, найденных рекурсивно под `cwd` (до 3 уровней).
3. Если ничего не найдено — fallback `[8020, 8099]`.

`scan_range` возвращает только порты, ответившие `GET /api/v1/model`, поэтому чужие python-процессы, не являющиеся Fona-агентами, отфильтрованы. Вкладка заполняется **при загрузке страницы** (`demo.load`) и далее каждые 2 с. Принадлежность к текущему проекту подсвечивается (`team-ours`, синим): если `team_name` из `/api/v1/model` совпадает с `_active_project.name`.

**Kill** во вкладке — `POST /dashboard/kill_live?port=<port>`, убивает python-listener на этом порту. Для adopted-агента это «убить по-настоящему» (в отличие от `Stop`, §13.6).

### 13.6. Модель «процессы переживают дашборд»

Ctrl+C в дашборде **не убивает** детей. Только явные команды:

| Действие | Adopted-агент | Свой агент |
|---|---|---|
| **Stop** | **Release** — `adopted=False`, `process=None`, `status=stopped`, процесс **живёт** | `taskkill /F /T` + sweep, процесс умирает |
| **Restart** | Release + Start (может снова adopt'ить) | Stop + Start |
| **Remove** | Release + удаление из `_manager` | Stop + удаление |
| **Kill (Adopted)** | `taskkill /F` по PID | — |
| **Close project** | Release всех adopted, `_manager.agents.clear()` | Stop всех, `clear()` |
| **Ctrl+C** | Ничего не делает, процессы живы | Ничего не делает, процессы живы |

«Adopted» = агент, которого дашборд **не** запускал (он был жив на момент `Project.open` / `_ensure_startup_project` / `Start`). Дашборд знает про него из `/api/v1/model`, но **не владеет** его PID: `process = None`, `pid` берётся из `netstat`/`lsof` по порту.

### 13.7. Autostart

Флаг `autostart` в `team.json` (`"autostart": true|false`) — «запускать автоматически при открытии проекта».

**Где срабатывает:**
- Автооткрытие при запуске дашборда (`_ensure_startup_project`).
- Кнопка «Открыть» (`_open_after_load`).

Для каждого агента с `autostart=True` и `status != "online"` вызывается `_manager.start()`. Если процесс уже жив на порту, `start()` вместо запуска **адоптирует** его.

**Где не срабатывает:**
- Авто-подхват `team.json` (`_maybe_reload_team`) — только читает, никого не запускает.
- «Загрузить и запустить» — запускает **всех** не-online.
- «Сохранить» — только пишет файл.
- Ручной `Start` на карточке — запускает конкретного агента.

Чекбокс на карточке — `POST /dashboard/autostart?id=<id>&value=1|0`; после ответа вызывается `window.fonaRefresh()`.

### 13.8. Добавление агента

Аккордеон «Add Agent» **свёрнут по умолчанию**. Содержимое:

- **Файл скрипта** (`gr.File`, `.py`) — копируется в `<project>/scripts/` с дедупликацией по `sha256`. `team.json` запоминает `source`, `source_sha256`, `source_mtime`. При внешнем изменении источника — бейдж `⚠ source changed` и кнопка `Update` → `POST /dashboard/update_source` (перезаписывает копию, рестартит).
- **Или абсолютный путь** — «по месту», без копирования.
- **Шаблон оркестратора** — опционально, копируется как обычный скрипт.
- **Имя** — опционально; по умолчанию `Path(script).stem`.

Кнопка `Add` создаёт запись в `_manager`, но **не** пишет `team.json` — это делает «Сохранить».

### 13.9. Порты

- `port_range` задаётся в `team.json` на уровне проекта. В UI поля нет — это осознанно: диапазон — свойство проекта.
- `_allocate_for()` выделяет **два** свободных порта из `port_range`: первый — агенту, второй — оркестратору. Второй выделяется **только** если задан `orchestrator_template`; иначе `orchestrator_gradio_port=None`, кнопка Orchestrator не рисуется.
- Порт **не** хранится в `team.json`: при `Start` назначается заново. После `Stop`/`Start` агент может получить другой порт, если старый занят. `Open UI` всегда использует актуальный `a.port`.
- Свободный порт гарантируется до `Popen`: `start()` вызывает `_kill_python_on_port(agent_port)` **до** спавна. Если порт всё ещё занят (race), аллоцируется следующий.

### 13.10. Как поменять диапазон портов

`port_range` хранится в `team.json` (поле верхнего уровня). Меняется правкой файла. В UI поля нет.

**Формат:**

```json
{
  "version": 4,
  "name": "warehouse_team",
  "port_range": [8020, 8099],
  "agents": [ ... ]
}
```

**Пошагово:**

1. **Закрыть проект** в дашборде (кнопка `Закрыть`). Это отпустит adopted-агентов, но **не** убьёт их.
2. **Остановить всех агентов команды**, если они запущены дашбордом: на каждой карточке `Stop`, либо просто закройте дашборд. Если агенты работают под старыми портами, а вы меняете диапазон на **пересекающийся**, старые процессы займут часть новых — `_allocate_port` увидит и выдаст следующие свободные.
3. **Открыть `team.json`** в редакторе и заменить `"port_range": [START, END]`. Ограничения:
   - `1 <= START <= END <= 65535`.
   - Диапазон должен содержать **как минимум** `2 * N_orch + N_agents + 1` портов, где `N_orch` — число агентов с `orchestrator_template`. Если оркестраторов нет, хватит `N_agents + 1`.
   - Не пересекайте с системными/чужими сервисами. Стандарт Fona — `8020–8099`.
4. **Сохранить файл.** Дашборд подхватит изменение автоматически в течение 2 с (`_maybe_reload_team`). Если дашборд был закрыт — при следующем `fona-dashboard` (или после `Открыть`) новый диапазон применится сразу.
5. **Нажать «Загрузить и запустить»**, если нужно сразу поднять всю команду на новых портах. Или жать `Start` на карточках.

**Важно:**

- Порт **не** привязан к агенту. При следующем `Start` каждый агент получит **первый свободный** порт из нового `port_range` в порядке аллокации. Если хотите «прибить» агента к конкретному порту — задайте `env: {"FONA_PORT": "8123"}` в записи агента. `_child_env` объединяет `extra=a.env`, и `FONA_PORT` из `env` переопределит дефолт, который передаёт дашборд.
- Смена `port_range` **не** мигрирует уже запущенные процессы. Adopted-процессы на старых портах останутся на старых портах; `_scan_and_adopt` будет искать их по `team_name`+`agent_name` в **новом** диапазоне и **не найдёт**. Чтобы дашборд снова «увидел» adopted, проще всего остановить старые процессы вручную (`Kill` во вкладке `Adopted` или `taskkill`), затем запустить команду на новых портах.
- Если несколько `team.json` под `cwd` имеют **пересекающиеся** диапазоны, `_live_scan_any()` берёт `min(START)` и `max(END)` — сканирует объединение. Безопасно (лишние порты не ответят), но создаёт нагрузку на `netstat`/HTTP при большом объединении.

**Пример: с 8020–8099 на 9000–9099 для команды из 3 агентов без оркестратора.**

```json
{
  "version": 4,
  "name": "warehouse_team",
  "port_range": [9000, 9099],
  "agents": [
    { "id": "e48fdec6", "name": "WH",     "script": "scripts/warehouse_agent.py", "autostart": false },
    { "id": "21b0c058", "name": "ORDERS", "script": "scripts/orders_agent.py",    "autostart": false },
    { "id": "2c87ef27", "name": "CHAT",   "script": "scripts/chat_agent.py",      "autostart": false }
  ]
}
```

Сохранили → дашборд подхватил → «Загрузить и запустить» → три агента на портах 9000, 9001, 9002 (первый свободный в порядке аллокации).

**Пример: с оркестратором у одного агента.**

```json
{
  "version": 4,
  "name": "warehouse_team",
  "port_range": [9000, 9099],
  "agents": [
    { "id": "a1", "name": "WH",     "script": "scripts/warehouse_agent.py", "autostart": false },
    { "id": "a2", "name": "ORDERS", "script": "scripts/orders_agent.py",    "autostart": false,
      "orchestrator_template": "scripts/orchestrator_template.py" },
    { "id": "a3", "name": "CHAT",   "script": "scripts/chat_agent.py",      "autostart": false }
  ]
}
```

`Start` для ORDERS выделит **два** порта (agent + orchestrator); для WH и CHAT — по одному. Итого 5 портов из `[9000, 9099]`.

### 13.11. HTTP-эндпоинты дашборда

Все `/dashboard/*` монтируются в FastAPI-приложение Gradio. Токен не проверяется — дашборд слушает `127.0.0.1` по умолчанию.

| Эндпоинт | Метод | Назначение |
|---|---|---|
| `/dashboard/project` | GET | Текущий проект (JSON) |
| `/dashboard/project/open` | POST | `{"root": "..."}` → `Project.from_folder` + `load_team` + autostart |
| `/dashboard/project/create` | POST | `{"root", "name", "port_range"}` → создать |
| `/dashboard/project/close` | POST | Отпустить всех, очистить `_manager` |
| `/dashboard/start`, `/stop`, `/restart`, `/remove` | POST | Управление агентом по `id` |
| `/dashboard/release` | POST | Отпустить adopted (без kill) |
| `/dashboard/kill_live` | POST | `?port=<n>` — убить python-listener |
| `/dashboard/autostart` | POST | `?id=<id>&value=1|0` |
| `/dashboard/update_source` | POST | `?id=<id>` — перезаписать копию из `source` |
| `/dashboard/logs` | GET | `?id=<id>&kind=out|err&tail=<n>` — tail лога |
| `/dashboard/env` | GET | Диагностика: `sys_executable`, `PYTHONPATH`, `uvicorn_reload`, `strict_pid`, `project`, `autodetected_teams` |
| `/dashboard/teams/save` | POST | Записать `team.json` |
| `/dashboard/teams/load` | POST | `{"start_flagged": bool, "force_start": bool}` |

### 13.12. Runtime

- `logs/<agent_id>.out.log` / `logs/<agent_id>.err.log` — stdout/stderr каждого ребёнка (кнопка `Logs`).
- Ctrl+C: дашборд пишет `dashboard shutting down (children left running)` и завершается; дети продолжают работать.

### 13.13. Известные ограничения

- **Один проект за раз.** Мультипроектность — RFC.
- **`port_range` не редактируется в UI.** Только через `team.json` (§13.10).
- **Orphan-cleanup только при «Открыть».** `_ensure_startup_project` не убивает «чужих» (`team_name != project.name`), чтобы случайно не убить ручной запуск. Явное убийство — `Kill` во вкладке `Adopted`.
- **`autostart` не срабатывает на авто-подхват `team.json`** — только на «Открыть» и старт дашборда (§13.7).
- **`_install_script` не удаляет старые версии** при `renamed` — `scripts/` постепенно растёт.
- **`/dashboard/*` без токена.** Для `0.0.0.0` нужен reverse proxy с TLS (§16).
- **`orchestrator_gradio_port` без запуска оркестратора.** Порт выделяется, кнопка рисуется, но сам процесс оркестратора дашборд не стартует — ответственность агента (§14).

---

## 14. Оркестратор

```bash
python -m fona.orchestrator_app \
  --orchestrator http://127.0.0.1:8000 \
  --port 8010
```

**UI:** панель URL + Connect + Refresh, слева — Chat (HITL), справа — панели из `cfg.panels`, снизу — Logs.

**Кастомизация** через `OrchestratorConfig`:

```python
from fona.orchestrator_ui import OrchestratorConfig, Panel, Action

def fetch_status(client):
    return client.get_json("/api/v1/model")

def render_status(data, lang):
    return f"<pre>{data}</pre>"

cfg = OrchestratorConfig(
    base_url="http://127.0.0.1:8000",
    panels=[
        Panel(key="status", title_en="Status", title_ru="Статус",
              fetcher=fetch_status, renderer=render_status),
    ],
    actions=[
        Action(key="ping", title_en="Ping", title_ru="Пинг",
               handler=lambda client, _: client.post_json(
                   "/api/v1/query", {"query": "handle_request(\"ping\", R)."})),
    ],
)
```

Связь с оркестратором:
- `/api/v1/ui/*` — HITL-сессия (чат).
- Произвольные эндпоинты — через `client.get_json(path)` / `client.post_json(path, body)`.

Дашборд **не** запускает процесс оркестратора: `FONA_ORCHESTRATOR_PORT` прокидывается в env ребёнка, но интерпретировать его — ответственность скрипта (например, `orchestrator_app.main()` может прочитать env и использовать как `--port`).

---

## 15. Шаблон агента

```python
from fona import (
    agent, load_config, register_peers, register_protocol,
    team_resolver,
)

CFG = load_config(
    port=("FONA_PORT", int, 8000),
    token=("FONA_TOKEN", str, None),
    peers=("FONA_PEERS", "peers", {}),
    timeout=("FONA_HTTP_TIMEOUT", float, 10.0),
    peers_headers=True,
)
register_peers(agent, CFG, resolver=team_resolver)
register_protocol(agent)

@agent.program
PROGRAM = """
run :- ui_print('ready'), on_user_input.
on_user_input :-
    ui_read(T),
    (T == quit -> ui_print('bye')
    ; ui_print(T), on_user_input).
"""

if __name__ == "__main__":
    agent.run(port=CFG.port, token=CFG.token)
```

**Что покрывает:**
1. HITL: `ui_print`/`ui_read`.
2. Исходящие: `call_peer/3` через `team_resolver`.
3. Входящие: `handle_request/3` (ping/echo/status).
4. Запуск: `agent.run()` — без дашборда; или дашборд сам запустит.

---

## 16. Безопасность

- **`FONA_TOKEN`:** если пуст — `/api/v1/*` без аутентификации. По умолчанию `127.0.0.1`. Для `0.0.0.0` — обязательно токен и TLS-прокси.
- **`trust_remote_code=True`:** обязателен для HF. Модель из доверенного источника.
- **`read_env`:** всегда whitelist. Иначе `read_env("FONA_TOKEN")` вернёт токен.
- **Токены не логируются.** `_ensure_kb_loaded` выводит `repo_id`, но не токен.

---

## 17. Тестирование и бенчмарки

**Coverage:** ≥ 80% для `fona/*.py`.

**Обязательные тесты:** декораторы (arity, None→fail, context), build (standalone/HF/prepend), clone, semantics (`_start_query`), integration (TestClient, SSE, HITL).

**Запрещено:** реальная сеть в тестах (`fake_llm`), `sleep > 100ms`.

**Бенчмарки (ручные):**
- `import fona` < 500ms (без transformers).
- `Agent().build()` standalone < 100ms.
- `query_one('run.')` hello-агента < 50ms.

---

## 18. Релизный процесс (кратко)

1. **Freeze:** `release/vX.Y.Z` от `main`.
2. **Changelog:** `Unreleased` → `[X.Y.Z] — YYYY-MM-DD`.
3. **Tag:** `git tag -s vX.Y.Z`, push → `release.yml` → PyPI (trusted publishing).
4. **Post-release:** merge в `main`, версия `X.Y.Z.dev0`.

**Semver:**
- **major** — ломающие изменения публичного API/семантики (P2, P5, P6).
- **minor** — новые методы/параметры.
- **patch** — исправления.

**Deprecation:** `DeprecationWarning` два minor, удаление в следующем major.

---

## 19. Чеклист разработчика (сокращённо)

- [ ] Type hints на публичном API.
- [ ] Docstring Google style.
- [ ] Нет `print()` (только `sys.stderr` / `logging`).
- [ ] Нет `# noqa` без причины.
- [ ] Тесты: unit + integration.
- [ ] Coverage ≥ 80%.
- [ ] `CHANGELOG.md` обновлён.
- [ ] Пример в `examples/` (если фича видна пользователю).
- [ ] `_ensure_kb_loaded` после `_ensure_solver` (HF).
- [ ] Prepend соблюдён.

---

## 20. Известные ограничения

- **`Database` не потокобезопасна** — только `api_lock` или отдельные клоны для HITL.
- **Дашборд:** один проект за раз. Мультипроектность — RFC.
- **`port_range` не редактируется в UI** — только через `team.json`.
- **`_install_script` не удаляет старые версии** при `renamed` — `scripts/` растёт.
- **`orchestrator_app.py`** ожидает `/orch/*` эндпоинты, которых нет в `server.py` — их должен реализовать агент-оркестратор (или кастомные `Panel.fetcher`).
- **Имена в `call_peer` должны совпадать с `name` в `team.json`** — иначе `team_resolver` вернёт `None`.
- **Смена `port_range` не мигрирует adopted-процессы** — старые останутся на старых портах, `_scan_and_adopt` их не найдёт (§13.10).