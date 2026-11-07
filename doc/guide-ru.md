## 1. Что такое Fona

Fona — это минималистичный фреймворк для создания **фоновых ИИ-агентов** на базе PyAgentProlog. Агент пишется на Prolog (логика) и Python (действия), запускается как HTTP-сервер с UI и REST API, и может взаимодействовать с пользователем и другими агентами.

**Три пакета:**

| Пакет | Роль |
|---|---|
| `pyagentprolog` | Ядро: интерпретатор Prolog, парсер, агент |
| `pyagentprolog-hf` | Обёртка HuggingFace-моделей как PyAgentProlog-моделей |
| `pyagentprolog-fona` | Публичный пакет Fona: `Agent`, декораторы, сервер, дашборд |

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

Откройте `http://127.0.0.1:8000/` — увидите чат-интерфейс. Агент работает: `ui_print` выводит сообщения в UI.

**Что произошло:**
1. `agent` — синглтон `Agent()`.
2. `agent.program(...)` установил `PROGRAM` — Prolog-программу агента.
3. `agent.run(port=8000)` собрал модель, создал FastAPI-приложение с UI и REST, запустил uvicorn.

---

## 4. Основы

### 4.1. `@agent.program` — логика агента

Три формы записи (все эквивалентны):

```python
# Форма 1: присваивание
agent.program = "run :- ui_print('hi')."

# Форма 2: вызов
agent.program("run :- ui_print('hi').")

# Форма 3: декоратор на функции
@agent.program
def PROGRAM():
    return "run :- ui_print('hi')."
```

Если `PROGRAM` задан несколько раз — они **конкатенируются** (через `\n`).

Для HF-модели (`Agent.from_hub`) `PROGRAM` **prepend**-ится к `config.program` модели: ваши правила срабатывают первыми, HF-ные — как fallback.

### 4.2. `@agent.action` — предикат, возвращающий значение

```python
@agent.action
def add(X, Y):
    return X + Y
```

→ регистрирует `add/3` в Prolog. Вызов `add(2, 3, R)` → `R = 5`.

**Arity выводится из сигнатуры:**
- `def add(X, Y)` → `add/3` (2 входа + 1 выход, `output_arg=2`).
- `def ask(context, prompt)` → `ask/2` (`context` не считается, выход — `prompt`).

**Параметр `context`** — зарезервирован: получает `agent.context` (словарь), не входит в arity, не доступен из Prolog.

**Семантика (P5):**
- Если функция вернула `None` → **fail**.
- Если функция бросила исключение → **fail** (исключение подавляется).

**Параметры декоратора:**
- `name='custom_name'` — имя предиката (по умолчанию — имя функции).
- `arity=4` — общая арность (по умолчанию `len(params) + 1`).
- `output_arg=0` — индекс выходного аргумента (по умолчанию последний).

### 4.3. `@agent.effect` — побочный эффект, всегда успешен

```python
@agent.effect
def log_event(message):
    print(f"[log] {message}")
```

→ `log_event/1`. При успехе — всегда успех. При исключении — fail (но без возврата значения).

### 4.4. `@agent.generate` — генератор решений

```python
@agent.generate
def numbers(limit):
    for i in range(1, limit + 1):
        yield i
```

→ `numbers/2` (вход + выход). `numbers(3, L)` → `L = [1, 2, 3]` (все решения).

---

## 5. Запуск: `agent.run()`

```python
agent.run(
    host='127.0.0.1',     # адрес
    port=8000,            # порт
    ui=True,              # монтировать HTML UI на /
    rest=True,            # включить /api/v1/*
    token=None,           # FONA_TOKEN для REST (None = без аутентификации)
    background=False,     # True = pythonw без окна (Windows)
)
```

**`background=True`** — запускает агента как фоновый процесс без консольного окна (Windows: `pythonw.exe`). Для этого скрипт должен быть `.py`-файлом.

**Если `token` задан** (или `FONA_TOKEN` в env) — все `/api/v1/*` (кроме `/health`) требуют заголовок `X-API-Key: <token>`.

**Если `host != '127.0.0.1'` и `token` пуст** — `create_app` пишет предупреждение в stderr. Это осознанный дизайн: по умолчанию слушаем localhost.

---

## 6. Взаимодействие с пользователем (HITL)

HITL = Human-in-the-Loop. Механизм: `ui_print` (вывод) и `ui_read` (ввод).

**`ui_print/1`** — эффектор, выводит текст в UI-сессию.
**`ui_read/1`** — действие, **блокируется** до ввода пользователя, возвращает текст.

**Паттерн диалога:**

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

**Важно:** `ui_read` блокирует сессию, но не поток сервера. Каждый `POST /api/v1/ui/input` будит сессию. `QueryOneSession._run` вызывает `agent.query_one(start_query)` **один раз** — `run/0` не выполняется повторно.

---

## 7. Меж-агентное взаимодействие (Prolog-only)

**Протокол:** все вызовы идут через `POST /api/v1/query` с телом `{"query": "<Prolog text>"}`. Ответ: `{"success": bool, "solutions": [{"Var": value}], "count": int}`.

### 7.1. Входящие запросы: `handle_request/2`

Каждый агент, который должен отвечать другим, регистрирует `handle_request`:

```python
from fona import register_protocol

register_protocol(agent)  # регистрирует ping/echo/status
```

Или расширяет:

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
from fona import register_peers, load_config

CFG = load_config(
    peers=("FONA_PEERS", "peers", {"server": "http://127.0.0.1:8000"}),
    token=("FONA_TOKEN", str, None),
)
register_peers(agent, CFG)
```

→ регистрирует `call_peer/3` и `broadcast_ping/1`.

**Семантика:** возвращает **атом** `"ok:<value>"` или `"err:<reason>"`. Ошибки — строкой, не исключением (P5).

```prolog
run :-
    call_peer(server, 'light(bedroom, X).', Result),
    ui_print(Result).  % → "ok:off"
```

### 7.3. Конфигурация пиров

`FONA_PEERS="name1=url1,name2=url2"` — env-переменная. `load_config` парсит её в словарь. `CFG.http` автоматически добавляет `X-API-Key`, если `token` задан.

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

**Принцип:** `load_config` вызывается **один раз** при импорте. Immutable (`frozen=True`). Никакой магии в runtime (P4).

---

## 9. NL ↔ Prolog: спутники HITL

**Это не часть протокола.** Это обычные `@agent.action`, которые вызываются из `PROGRAM` **до** и **после** `query_one`.

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

**В `PROGRAM`:**

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

**Ключевое:** `PROGRAM` **не парсит** содержимое. Он отрезает префикс `nl ` и передаёт остаток в действие. Само преобразование — в Python. `handle_request`/`call_peer` про NL ничего не знают.

---

## 10. `query_one/1`: внутренний мост к движку

```python
@agent.action
def query_one(prolog_text):
    sol = agent.query_one(prolog_text)
    return "" if sol is None else str(sol)
```

**Назначение:** выполнить произвольный Prolog-текст из середины `PROGRAM`. Нужен, потому что `PROGRAM` не умеет «выполнить текст» — только унифицировать цели.

**Где используется:** только HITL-цикл (`on_user_input` → `run_query` → `query_one`). Пир и UI-сессия идут другими путями:
- **Пир:** `server.py` → `agent.query(q)` напрямую.
- **UI-сессия:** `QueryOneSession._run` → `agent.query_one(start_query)` один раз при старте.

**Архитектурное правило:** `query_one/1` — тонкий мост. Он **не обрабатывает** запрос (не парсит, не выбирает ветки). Любая интерпретация — в `PROGRAM` (через унификацию) или в отдельном действии **до** `query_one`.

---

## 11. REST API

| Эндпоинт | Метод | Назначение |
|---|---|---|
| `/` | GET | HTML UI (если `ui=True`) |
| `/api/v1/health` | GET | `{"status": "ok"}` — без токена |
| `/api/v1/model` | GET | Инфо о модели: `rules_count`, `kb_file`, `actions` |
| `/api/v1/query` | POST | Выполнить Prolog-запрос: `{"query": "..."}` |
| `/api/v1/query_one` | POST | Первое решение |
| `/api/v1/stream` | POST | SSE-поток решений |
| `/api/v1/facts` | POST | `?fact=light(kitchen,on).` |
| `/api/v1/actions` | GET | Список действий |
| `/api/v1/ui/start` | POST | Начать HITL-сессию → `{"session_id": "..."}` |
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

**Куда скачивается:** глобальный кэш HuggingFace:
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

**Prepend:** ваш `run/0` **первый**, HF-ный — fallback. `_ensure_solver()` → merge `PROGRAM` → `_ensure_kb_loaded()`.

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

**Концепция:** проект = папка. Внутри: `team.json`, `scripts/` (копии агентов), `logs/` (runtime).

**Порядок работы:**
1. **Создать проект** — выбрать папку → создаётся `scripts/`, `logs/`.
2. **Добавить агента** — через `gr.File` (копируется в `scripts/` с дедупликацией по sha256) или ручной путь (без копии).
3. **Сохранить / Запустить** — `team.json` пишется в папку проекта; `Load and start` запускает агентов с `autostart=true`.

**Отслеживание источника:** если агент скопирован, `team.json` хранит `source`, `source_sha256`, `source_mtime`. На карточке — бейдж `⚠ source changed`, клик → `update_source` (перезаписывает копию и рестартит).

**Runtime:** `logs/children.json` — PID/порты. `_kill_orphan_children()` при открытии проекта. Ctrl+C останавливает детей.

---

## 14. Оркестратор

```bash
python -m fona.orchestrator_app \
  --orchestrator http://127.0.0.1:8000 \
  --port 8010
```

**Трёхколоночный UI:**
- **Левая:** Goal (карточка) + ввод + `Set` + `Open HTML`.
- **Центр:** Plan (3 колонки: Pending/Active/Done) + Chat.
- **Правая:** Logs + Subordinates (список с точками) + Status.

**Связь с оркестратором:**
- `/api/v1/ui/*` — HITL-сессия (чат).
- `/orch/current_goal`, `/orch/goal`, `/orch/tasks`, `/orch/subordinates` — состояние оркестрации. **Эти эндпоинты должен реализовать агент-оркестратор**; `orchestrator_app.py` их только читает.

**Язык:** системный (как в `dashboard.py`), без переключателя.

---

## 15. Шаблон агента (`template_agent.py`)

**Что покрывает:**
1. HITL: `ui_print`/`ui_read` + NL ↔ Prolog (спутники).
2. Исходящие: `call_peer/3` (из `fona.peers`).
3. Входящие: `handle_request/2` (из `fona.protocol`).
4. Действия: `now_iso`, `read_env` (whitelist), `numbers` (generate).

**Структура:**
```python
CFG = load_config(...)           # конфиг
register_peers(agent, CFG)        # транспорт
register_protocol(agent)          # протокол
# ... domain actions ...
@agent.program PROGRAM = r"""..."""  # чистый Prolog, без парсинга
agent.run(port=CFG.port, token=CFG.token)
```

---

## 16. Безопасность

- **`FONA_TOKEN`:** если пуст — `/api/v1/*` без аутентификации. По умолчанию `127.0.0.1`. Для `0.0.0.0` — обязательно установите токен и TLS-прокси.
- **`trust_remote_code=True`:** обязателен для HF. Модель должна быть из доверенного источника.
- **`read_env`:** всегда используйте whitelist. Без него `read_env("FONA_TOKEN")` вернёт токен.
- **Токены не логируются.** `_ensure_kb_loaded` выводит `repo_id`, но не токен.

---

## 17. Тестирование и бенчмарки

**Coverage:** ≥ 80% для `fona/*.py`.

**Обязательные тесты:** декораторы (arity, None→fail, context), build (standalone/HF/prepend), clone, semantics (`_start_query`), integration (TestClient, SSE, HITL).

**Запрещено:** реальная сеть в тестах (только `fake_llm`), sleep > 100ms.

**Бенчмарки (ручные):**
- `import fona` < 500ms (без transformers).
- `Agent().build()` standalone < 100ms.
- `query_one('run.')` hello-агента < 50ms.

---

## 18. Релизный процесс (кратко)

1. **Freeze:** `release/vX.Y.Z` от `main`.
2. **Changelog:** `Unreleased` → `[X.Y.Z] — YYYY-MM-DD`.
3. **Tag:** `git tag -s vX.Y.Z`, push → `release.yml` → PyPI (trusted publishing).
4. **Post-release:** merge обратно в `main`, версия `X.Y.Z.dev0`.

**Semver:**
- **major** — ломающие изменения публичного API/семантики (P2, P5, P6).
- **minor** — новые методы/параметры.
- **patch** — исправления.

**Deprecation:** `DeprecationWarning` в течение **двух minor**, удаление в следующем major.

---

## 19. Чеклист разработчика (сокращённо)

- [ ] Type hints на публичном API.
- [ ] Docstring Google style.
- [ ] Нет `print()` (только `sys.stderr` / `logging`).
- [ ] Нет `# noqa` без причины.
- [ ] Тесты: unit + integration (если семантика).
- [ ] Coverage ≥ 80%.
- [ ] `CHANGELOG.md` обновлён.
- [ ] Пример в `examples/` (если фича видна пользователю).
- [ ] `_ensure_kb_loaded` после `_ensure_solver` (HF).
- [ ] Prepend соблюдён.

---

## 20. Известные ограничения

- **`Database` не потокобезопасна** — только `api_lock` или отдельные клоны для HITL.
- **Дашборд:** один проект за раз. Мультипроектность — RFC.
- **`_install_script`** не удаляет старые версии при `renamed` — `scripts/` растёт.
- **`orchestrator_app.py`** ожидает `/orch/*` эндпоинты, которых нет в `server.py` — их должен реализовать агент-оркестратор.
- **Поиск в открытых источниках по «pyagentprolog-fona» не дал результатов** — это руководство основано на предоставленных файлах, а не на внешней документации.