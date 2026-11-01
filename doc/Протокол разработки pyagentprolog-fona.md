# Протокол разработки pyagentprolog-fona

Документ для maintainers и контрибьюторов. Фиксирует принципы, правила и процедуры, чтобы API оставался предсказуемым, а изменения — проверяемыми.

---

## 1. Назначение и границы

**Что покрывает:** разработку самого пакета `pyagentprolog-fona` — API, семантику, тесты, релизы, безопасность.

**Что не покрывает:** разработку `pyagentprolog` и `pyagentprolog-hf` (это отдельные репозитории, у них свой протокол); прикладные агенты пользователей (см. `examples/`).

**Роли:**

| Роль | Права |
|---|---|
| Contributor | PR в feature-ветки, предложения через issue |
| Reviewer | Approve в PR, тег `lgtm` |
| Maintainer | Merge в `main`, релизы, изменения протокола |
| User | Issues, Discussions, примеры в `examples/` через PR |

Maintainer определяется через `CODEOWNERS`. Смена состава — RFC (см. §17).

---

## 2. Базовые принципы

Их изменение — только через RFC (§17).

**P1. Один API для standalone и HF.**  
`@agent.program PROGRAM = "..."` — везде `PROGRAM`. `Agent.from_hub()` меняет источник базы, но не форму записи. Никаких `EXTRA`, `HF_PROGRAM`, `STANDALONE_PROGRAM`.

**P2. Prepend при merge.**  
Пользовательский `PROGRAM` вставляется **перед** `config.program` HF-модели. Ваши правила срабатывают первыми; HF-ные — как fallback при неудаче. Обоснование: `query_one('run.')` должен отработать ваш `run`, а не HF-ный.

**P3. Decorator-first.**  
Всё, что делает пользователь, — это `@agent.program`, `@agent.action`, `@agent.effect`, `@agent.generate` и `agent.run()`. Прямой доступ к `PyAgentPrologModel`, `FastAPI`, `proagent_gradio` — не часть публичного API Fona.

**P4. Никакой магии в runtime.**  
Декораторы выполняются один раз при импорте/определении. `build()`, `run()`, `query()` — детерминированы и предсказуемы. Никаких импорт-тайм side effects (кроме `agent = Agent()` в `__init__.py`).

**P5. Явные точки отказа.**  
`action`/`generate` при `None`/исключении → **fail** (никаких «тихих» успехов). Хочешь «всегда успешно» — `@agent.effect`.

**P6. Изоляция потоков.**  
`Database` не потокобезопасна (`interpreter.py` мутирует `rules`, `_cut_counter`, `tracer`). Шаблонная модель живёт под `api_lock`. HITL-сессии изолированы через `_clone_model`.

**P7. Минимальные зависимости в core.**  
`fastapi`, `uvicorn`, `httpx`, `pydantic`, `transformers`, `huggingface_hub`, `pyagentprolog`, `pyagentprolog-hf`. `torch`, `sentence-transformers` — опционально. Новая обязательная зависимость — только через RFC.

**P8. Никаких `print()` в библиотеке.**  
Только `sys.stderr` для ранних этапов и `logging` для релиза. Пользователь может перехватывать сообщения.

**P9. Обратная совместимость — контракт.**  
Публичный API по semver. Ломающие изменения — только в major-релизах с явным deprecation-циклом (§12).

**P10. Примеры = документация.**  
Каждая новая фича публичного API — пример в `examples/`. Если фича не показана в примере — она не существует для пользователя.

---

## 3. Структура репозитория

```
pyagentprolog-fona/
├── fona/                    # единственный публичный пакет
│   ├── __init__.py          # Agent, agent, __version__
│   ├── agent.py             # Agent, декораторы, _clone_model, _ensure_kb_loaded
│   ├── server.py            # create_app, QueryOneSession, api_lock
│   └── ui.py                # HTML-строка
├── examples/                # e2e-примеры (входят в тесты)
│   ├── hello.py
│   ├── with_hf.py
│   └── client_agent.py
├── tests/
│   ├── unit/
│   │   ├── test_decorators.py
│   │   ├── test_build.py
│   │   ├── test_clone.py
│   │   └── test_semantics.py
│   ├── integration/
│   │   ├── test_standalone.py
│   │   ├── test_hf_local.py     # локальная директория с config.json
│   │   └── test_server.py
│   └── conftest.py
├── docs/
│   ├── development-protocol.md  # этот файл
│   ├── public-api.md
│   └── migration-vX.md
├── pyproject.toml
├── CHANGELOG.md
├── CODEOWNERS
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   └── release.yml
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
└── README.md
```

**Правила:**

- Публичный пакет — **только** `fona/`. Внутренние модули не публикуются.
- Подпакеты внутри `fona/` запрещены (плоская структура — осознанный выбор, минимализм).
- `tests/` не входит в wheel, но входит в sdist.
- Примеры (`examples/`) импортируются из установленного пакета, не из локальной директории — это проверяется в CI.

---

## 4. Ветвление и коммиты

**Модель:** trunk-based с короткоживущими feature-ветками.

- `main` — всегда релизопригоден. Прямые коммиты запрещены (branch protection).
- `feat/<slug>` — новая функциональность.
- `fix/<slug>` — исправление.
- `docs/<slug>` — документация.
- `chore/<slug>` — инфраструктура.
- `release/vX.Y.Z` — только для release-кандидатов (см. §11).

**Conventional Commits** обязательны. Формат:

```
<type>(<scope>): <subject>

<body>

<footer>
```

`type` ∈ `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `build`, `ci`.  
`scope` ∈ `agent`, `server`, `ui`, `hf`, `examples`, `docs`, `deps`, `protocol`.

**Примеры:**

```
feat(agent): support async action functions
fix(server): drain output queue before closing SSE on finish
docs(protocol): add deprecation cycle rules
perf(build): cache _ensure_kb_loaded by repo_id+revision
```

**PR:**

- Заголовок = один из коммитов (squash-merge).
- Описание: `Closes #N`, что меняется, как проверять, чеклист §16.
- Минимум один approve от Reviewer.
- CI зелёный.
- Для `feat` — обновлён `CHANGELOG.md` (Unreleased).

**Запрещено:**

- Force-push в `main`.
- Merge с красным CI.
- Изменения публичного API без обновления `docs/public-api.md`.

---

## 5. Стандарты кода

**Python 3.10+.** Обязательны type hints на публичном API.

**Стиль:** `ruff` с конфигом из `pyproject.toml` (`select = ["E", "F", "I", "UP", "B"]`, `line-length = 88`). Никаких `# noqa` без указания причины.

**Docstrings:** Google style, обязательны для публичных функций/классов/декораторов.

```python
def action(self, func=None, *, name=None, arity=None, output_arg=None):
    """Декоратор действия, возвращающего значение.

    Args:
        name: имя предиката в Prolog. По умолчанию — имя функции.
        arity: общая арность. По умолчанию — len(params) + 1.
        output_arg: индекс выходного аргумента. По умолчанию — последний.

    Returns:
        Обёрнутая функция (для использования как декоратор).

    Raises:
        TypeError: если `func` не callable и не None.
    """
```

**Naming:**

| Публичное | Приватное |
|---|---|
| `program`, `action`, `effect`, `generate` | `_wrap_simple`, `_wrap_effector`, `_wrap_generator` |
| `build`, `run`, `query`, `query_one`, `stream` | `_invalidate`, `_start_query`, `_spawn_background` |
| `from_hub`, `load_hub`, `configure` | `_ensure_kb_loaded`, `_clone_model`, `_apply_overrides` |
| `Agent`, `agent` | `QueryOneSession` (внутри `server`) |

**Запреты:**

- `print()` — используй `sys.stderr.write` или `logging`.
- Глобальное состояние, кроме `agent = Agent()` в `__init__.py`.
- Изменение `PyAgentPrologModel` через monkey-patching. Все обходы — через документированные вызовы (`_load_kb_file`, `_apply_directives`, `_ensure_solver`) с комментарием `# noqa: SLF001 — обход ограничения обёртки`.
- `import *` в публичных модулях.

**Исключения:** свой базовый класс для ошибок Fona (см. §6).

---

## 6. Публичный API

**Публичный API** — то, что доступно через `from fona import ...` или через свойства/методы экземпляра `Agent` без подчёркивания.

```python
# fona/__init__.py
__all__ = ['Agent', 'agent']
```

**Публичные члены `Agent`:**

- `program`, `action`, `effect`, `generate` (декораторы)
- `from_hub`, `from_pretrained` (alias), `load_hub`
- `configure`
- `build`
- `query`, `query_one`, `stream`, `__call__`
- `run`

**Всё, что начинается с `_`, — приватное.** Может меняться в любой момент.

**`__version__`** следует semver:

- **major** — ломающие изменения в публичном API или семантике (P2, P5, P6).
- **minor** — новые публичные методы/параметры/декораторы.
- **patch** — исправления без изменения API.

**Семантические контракты (не могут меняться в minor/patch):**

| Что | Гарантия |
|---|---|
| `@agent.program` для standalone | заменяет всю логику |
| `@agent.program` для HF | prepend к `config.program` |
| `action` при `None` | fail |
| `action` при исключении | fail (исключение подавляется) |
| `effect` при успехе | всегда успешно |
| `effect` при исключении | fail |
| `generate` при пустом генераторе | fail |
| параметр `context` в функции | получает `agent.context` |
| `query_one` в HITL | только первое решение |
| `generate` в REST | все решения |
| `run(background=True)` | pythonw без окна |
| `from_hub` с `revision` | фиксирует коммит |

Любое изменение этих контрактов — major-релиз с миграционным гайдом в `docs/migration-vX.md`.

---

## 7. Правила семантики

**7.1. Arity выводится из сигнатуры.**

- `def ask(prompt): ...` → `ask/2` с `output_arg=1`.
- `def ask(prompt): yield x` → `ask/2` (генератор).
- `def ask(): ...` → `ask/1` с `output_arg=0`.
- `def ask(context): ...` → `ask/1` с `output_arg=0` (`context` не считается).

`context` — **зарезервированное имя параметра**. В arity не входит, в Prolog не доступно.

**7.2. Обёртки повторяют оригинальные `prolog.actions`:**

- Входные аргументы должны быть ground (`isinstance(arg, Variable)` → fail).
- `python_to_prolog` для выхода: `int/float` → `Number`, `str` → атом в кавычках, `list` → Prolog-список, `dict` → `-`(K,V), `None` → `[]`.
- `prolog_to_python` для входа: `Number` → `int/float`, атом → `str` без кавычек, список → `list`, составной терм → `str`.

**7.3. При merge HF:**

- `_ensure_solver()` вызывается **до** merge `PROGRAM`.
- `PROGRAM` парсится с `return_directives=True`, директивы применяются через `model.solver._apply_directives`.
- Правила добавляются через `add_rule(r, at_beginning=True)` в обратном порядке — итог: `PROGRAM` первым.
- `_ensure_kb_loaded()` вызывается **после** `_ensure_solver()` — обход ограничения `_resolve_kb_path` для `hf:repo`.

**7.4. `_start_query`:**

- Если `config.default_main` задан — используется он.
- Иначе — `run/0`, `main/0`, `main/N`.
- Иначе — `"run."` (fail при выполнении).

**7.5. HITL — `QueryOneSession`:**

- Наследник `AgentGradioSession`, переопределяет `_run`.
- Использует `agent.query_one`, а не `agent.query`.
- Причина: если в `PROGRAM` переопределён `run/0`, HF-ный `run/0` не должен выполняться вдогонку.

**7.6. REST под `api_lock`:**

- Все запросы к шаблонной модели (`generate`, `stream`, `add_facts`, `query_one`) — под `threading.RLock`.
- HITL-сессии изолированы (свой `Database`, свой `tracer`), лок не нужен.
- `_clone_model` копирует `_actions` **после** `_ensure_solver` — иначе действия не попадут в клон.

---

## 8. Тестирование

**Структура:**

```
tests/
├── unit/          # быстрые, без сети, без uvicorn
├── integration/   # поднимают FastAPI через TestClient, без реальной сети
└── conftest.py    # фикстуры: temp_model, temp_hf_dir, fake_llm
```

**Обязательные тесты для каждого PR:**

- **`unit/test_decorators.py`** — каждый декоратор: arity, output_arg, `None` → fail, исключение → fail, `context` передаётся, генератор даёт несколько решений.
- **`unit/test_build.py`** — standalone с пустым `PROGRAM`, standalone с непустым, HF с локальной директорией (без `config.json` — ошибка), HF + `PROGRAM` (prepend проверяется по `rule_index`).
- **`unit/test_clone.py`** — `_clone_model` даёт независимые `Database`, копирует `_actions`, не копирует `_hub_source`.
- **`unit/test_semantics.py`** — `_start_query` для `default_main`, `run`, `main/0`, `main/1`.
- **`integration/test_standalone.py`** — `create_app` + `TestClient`: `/`, `/api/v1/health`, `/api/v1/query`, `/api/v1/stream`, `/api/v1/facts`.
- **`integration/test_hf_local.py`** — `Agent.from_hub('tests/fixtures/local_model')` (директория с `config.json` без `auto_map`, без сети).
- **`integration/test_server.py`** — `ui_start` → `ui_input` → `ui_stream` (с использованием `httpx.AsyncClient` и SSE-парсера).

**Запрещено:**

- Тесты, требующие реальной сети/HF Hub. Для HF — локальная фикстура.
- Тесты с реальными LLM. `fake_llm` в `conftest.py` возвращает детерминированный ответ.
- Sleep > 100ms. Для SSE — polling через `get_output` с таймаутом.

**Coverage:** ≥ 80% для `fona/*.py`. Считается через `pytest --cov=fona`. Падение coverage — блокер merge.

**Примеры как e2e:** `tests/integration/test_examples.py` импортирует каждый `examples/*.py` через `importlib.util.spec_from_file_location`, вызывает `build()`, проверяет `_start_query` — без `run()`.

---

## 9. Бенчмарки

Целевые показатели (не регрессировать):

| Метрика | Бюджет |
|---|---|
| `import fona` | < 500 мс (без transformers) |
| `import fona` с transformers | < 2 с (без torch) |
| `Agent().build()` standalone | < 100 мс |
| `Agent.from_hub(local_dir).build()` | < 500 мс |
| `query_one('run.')` для hello-агента | < 50 мс |
| `create_app` cold start | < 100 мс |
| 1000 concurrent `query` через TestClient | < 5 с |

Бенчмарки в `tests/benchmarks/` (не запускаются в CI, только вручную). Регрессия > 20% — блокер.

---

## 10. CI

**`.github/workflows/ci.yml`:**

- Matrix: `{ubuntu-latest, windows-latest, macos-latest}` × `{3.10, 3.11, 3.12}`.
- Шаги: `pip install -e ".[all]"`, `ruff check`, `ruff format --check`, `mypy fona`, `pytest -q --cov=fona --cov-fail-under=80`.
- `mypy` — только публичный API (`fona/__init__.py`, `fona/agent.py` без `_` функций).
- Кэш pip по `pyproject.toml`.

**Branch protection `main`:**

- Require PR, 1 approve.
- Require status checks: `ci`.
- Require linear history (squash-merge).
- No force-push.

**Запрещено:**

- Merge с красным CI.
- `--no-verify` в коммитах.
- Прямой push в `main`.

---

## 11. Релизный процесс

**1. Freeze.**  
Maintainer создаёт `release/vX.Y.Z` от `main` и замораживает `main` для feature-PR. Bugfix — можно.

**2. Changelog.**  
`CHANGELOG.md` переписывается: `Unreleased` → `[X.Y.Z] — YYYY-MM-DD`. Разделы: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.

**3. Проверки.**  
Локально: `python -m build && twine check dist/*`. В CI — dry-run `test-release.yml`.

**4. Tag.**  
`git tag -s vX.Y.Z -m "vX.Y.Z"`, push tag. Тег запускает `release.yml`:

- Build wheel + sdist.
- `publish-to-pypi` через `pypa/gh-action-pypi-publish` (trusted publishing, без API-токена в секретах).
- GitHub Release с автогенерированными notes из `CHANGELOG.md`.

**5. Post-release.**  
`main` мержит `release/vX.Y.Z` (для `__version__`), версия снова `X.Y.Z.dev0`. `Unreleased` пустой.

**Hotfix:**

- `fix/<slug>` → `main` → patch-релиз.
- Если `main` нестабилен — `hotfix/vX.Y.Z` от тега, cherry-pick в `main`.

**Версии `pyagentprolog` и `pyagentprolog-hf`:**

Fona следует за `pyagentprolog-hf` минорно: если обёртка получает 0.3.0, Fona выпускает 0.2.0 с поддержкой новых полей `config`. Проверка совместимости — в CI: `test_hf_compat.py` устанавливает минимальную и максимальную поддерживаемую версию `pyagentprolog-hf` (matrix).

---

## 12. Deprecation policy

**Правило:** публичный API не удаляется в minor. Сначала — `DeprecationWarning` в течение **двух minor-релизов**, затем удаление в следующем major.

**Пример:**

```python
# v1.2.0
import warnings

def run_async(self, *args, **kwargs):
    """Устарело в 1.2.0. Используйте run(background=True)."""
    warnings.warn(
        "Agent.run_async is deprecated since 1.2.0; "
        "use Agent.run(background=True) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return self.run(background=True, **kwargs)
```

**В `CHANGELOG.md`:**

```markdown
### Deprecated
- `Agent.run_async` — используйте `Agent.run(background=True)`. Удаление в 2.0.0.
```

**Проверка в CI:** `filterwarnings = ["error::DeprecationWarning:fona"]` в `pyproject.toml` — `pytest` падает, если внутри Fona возникает deprecated-вызов.

---

## 13. Документация

**Обязательно для каждого PR, затрагивающего публичный API:**

1. **Docstring** в Google style на новом публичном методе/декораторе.
2. **`docs/public-api.md`** — обновлённая таблица.
3. **`examples/`** — новый или обновлённый пример, если фича видна пользователю.
4. **`CHANGELOG.md`** — раздел `Unreleased`.

**`docs/public-api.md`** — единственный источник истины по API. Содержит:

- Таблицу: имя, тип (декоратор/метод/класс), арность, семантика.
- Семантические контракты из §6.
- Ссылки на примеры.

**`docs/migration-vX.md`** — для major-релизов: что сломалось, как мигрировать, примеры «до/после».

**Запрещено:**

- Публичный API без docstring.
- Обновление `docs/public-api.md` «потом, в отдельном PR».

---

## 14. Безопасность

**14.1. Аутентификация REST.**  
`FONA_TOKEN` — если пусто, `/api/v1/query` и др. **без аутентификации**. Это осознанный выбор: по умолчанию `127.0.0.1`, локальный сценарий. Документируется в README явно:

> «Если вы слушаете на `0.0.0.0` — обязательно установите `FONA_TOKEN` и используйте reverse proxy с TLS».

`create_app` при `host != '127.0.0.1'` и пустом `token` пишет в `stderr` предупреждение.

**14.2. Secrets.**  
Только через env: `FONA_HF_TOKEN`, `FONA_TOKEN`. Никаких секретов в коде, в `config.json`, в `PROGRAM`.

**14.3. Логирование.**  
Токены **никогда** не логируются. `_ensure_kb_loaded` при ошибке выводит `repo_id` и `filename`, но не `token`. Проверяется в `test_security.py` (перехват `stderr`).

**14.4. `trust_remote_code=True`.**  
Обязательно для HF-моделей (обёртка требует кастомного кода). Документируется: «модель должна быть из доверенного источника». `FONA_LOCAL_ONLY=1` — режим без сети.

**14.5. Зависимости.**  
`pip-audit` в CI (weekly, отдельный workflow). Критические CVE в обязательных зависимостях — hotfix-релиз.

**14.6. Отчёт об уязвимости.**  
`SECURITY.md` с `security@<domain>`. Публичное раскрытие — через 90 дней или после фикса, что раньше.

---

## 15. Расширения (для third parties)

**Штатный путь расширения — декораторы.** Всё, что нужно, — `@agent.action` / `@agent.effect` / `@agent.generate` и `@agent.program`.

**Свои UI.**  
`create_app` принимает `with_ui=False` — тогда HTML не монтируется, но `/api/v1/*` работает. Кастомный UI — отдельное приложение, которое использует `/api/v1/*` как контракт.

**Свои actions в REST-агенте.**  
Через `agent.action` (до `run()`), как обычно.

**Своя логика запуска.**  
`agent.build()` возвращает `PyAgentPrologModel` — с ним можно делать что угодно (в том числе свой `FastAPI`). Это документированный уровень «продвинутого» использования.

**Запрещено:**

- Monkey-patching `_wrap_simple` и др. — не поддерживается.
- Импорт `fona.server._clone_model`, `fona.agent._ensure_kb_loaded` — приватные, могут меняться.
- Форк `fona/` в сторонний пакет с тем же именем модулей (`import fona` должен резолвиться в оригинал).

**Если нужен новый публичный hook** (например, `on_build` или `on_start`) — RFC (§17). Не PR «на всякий случай».

---

## 16. Чеклист ревью

Каждый PR проходит по списку. Reviewer обязан явно подтвердить пункты.

**Функциональность:**
- [ ] Изменение соответствует issue/RFC.
- [ ] Публичный API не изменён без обновления `docs/public-api.md`.
- [ ] Семантические контракты §6 не нарушены (или это major).

**Качество кода:**
- [ ] Type hints на публичном API.
- [ ] Docstring Google style.
- [ ] Нет `print()`, нет `# noqa` без причины.
- [ ] Нет `import *`.
- [ ] Приватные имена с `_`.

**Тесты:**
- [ ] Новый код покрыт unit-тестами.
- [ ] Изменение семантики покрыто integration-тестом.
- [ ] Coverage ≥ 80%.
- [ ] CI зелёный (3 ОС × 3 Python).

**Документация:**
- [ ] `CHANGELOG.md` обновлён в `Unreleased`.
- [ ] Пример в `examples/` (если фича видна пользователю).
- [ ] README актуален (если меняется установка/быстрый старт).

**Безопасность:**
- [ ] Секреты не попадают в код/логи.
- [ ] `trust_remote_code` / `FONA_TOKEN` документированы.
- [ ] Нет новых обязательных зависимостей без RFC.

**HF-специфика:**
- [ ] `_ensure_kb_loaded` вызывается после `_ensure_solver`.
- [ ] `_clone_model` копирует `_actions` после `_ensure_solver`.
- [ ] Prepend соблюдён при merge `PROGRAM`.

---

## 17. RFC для крупных изменений

**Когда нужен RFC:**

- Изменение базового принципа (§2).
- Новый публичный декоратор/метод/класс.
- Новая обязательная зависимость.
- Изменение семантического контракта §6.
- Изменение формата merge (prepend/append).

**Процесс:**

1. Issue с тегом `rfc` в репозитории `pyagentprolog-fona`.
2. Шаблон: `docs/rfc/0000-template.md`.
3. Обсуждение — минимум 7 дней.
4. Решение принимает maintainer (единолично или консенсусом — определяется в `CODEOWNERS`).
5. Принятый RFC — в `docs/rfc/NNNN-<slug>.md`, статус `Accepted`.
6. Отклонённый — статус `Rejected` с обоснованием (не удаляется).

**Статусы:** `Draft` → `Discussion` → `Accepted` / `Rejected` → `Implemented` (с релизом) / `Superseded` (новый RFC).

---

## 18. Шаблоны

**`.github/PULL_REQUEST_TEMPLATE.md`:**

```markdown
## Что меняется

Краткое описание.

## Зачем

Closes #N. Ссылка на RFC — если применимо.

## Как проверять

1. ...
2. ...

## Чеклист

- [ ] Протокол §16 пройден
- [ ] CHANGELOG обновлён
- [ ] docs/public-api.md обновлён (если API)
- [ ] Пример в examples/ (если API)
- [ ] CI зелёный
```

**`.github/ISSUE_TEMPLATE/bug.md`:**

```markdown
## Версия Fona
`fona.__version__`, `pyagentprolog-hf.__version__`, Python, ОС.

## Воспроизведение
Минимальный `PROGRAM` + код.

## Ожидаемое / фактическое

## Логи
Без `FONA_TOKEN`, `FONA_HF_TOKEN`.
```

**`.github/ISSUE_TEMPLATE/feature.md`:**

```markdown
## Задача
Какую проблему решает.

## Предлагаемое решение
API (декоратор/метод), семантика.

## Альтернативы

## Принципы (§2)
Какие принципы затрагивает. Если ломает — RFC.
```

---

## 19. Коммуникация

- **Issues** — баги и фичи.
- **Discussions** — вопросы, идеи до RFC.
- **RFC** — крупные изменения (§17).
- **Releases** — через GitHub Releases, уведомления в Discussions.
- **Breaking changes** — отдельный пост в Discussions до релиза major.

**Maintainer SLA:** ответ на issue с тегом `bug` — 7 дней; на `rfc` — 14 дней; на PR — 7 дней.

---

## 20. Резюме в одном абзаце

Fona развивается вокруг неизменного контракта: пользователь пишет Prolog и Python-функции, декораторы прячут PyAgentProlog-HF, FastAPI и фоновый запуск. Semver, prepend-семантика, явные точки отказа, изоляция `Database` и «пример = документация» — не рекомендации, а правила. Любое отклонение — RFC, любое изменение публичного API — через чеклист §16, любой релиз — через §11. Протокол обновляется только через RFC и живёт в `docs/development-protocol.md`.