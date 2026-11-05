"""Agent, decorators, model assembly, launch."""
from __future__ import annotations

import functools
import inspect
import os
import sys
import threading
from typing import Any, Optional

from prolog.bridge import prolog_to_python, python_to_prolog
from prolog.parser import Parser
from prolog.terms import Variable

# =====================================================================
# Lazy imports and standalone model (no torch/transformers)
# =====================================================================
import time as _time
from types import SimpleNamespace


def _log(msg: str):
    print(f"[fona] {msg}", file=sys.stderr, flush=True)


def _import_hf():
    """Imports pyagentprolog_hf ONLY on demand (HF path)."""
    t0 = _time.time()
    from pyagentprolog_hf import PyAgentPrologConfig, PyAgentPrologModel
    _log(f"import pyagentprolog_hf: {_time.time()-t0:.2f}s")
    return PyAgentPrologConfig, PyAgentPrologModel


class _StandaloneModel:
    """Lightweight duck-type of PyAgentPrologModel without torch/transformers.

    Implements exactly the attributes used by fona.server:
        .agent, .config, .add_facts(...), .name_or_path, ._model_dir
    """

    def __init__(self, program: str, config_overrides: dict):
        from prolog.agent import Agent as CoreAgent
        self.agent = CoreAgent(program, context={})
        self.solver = self.agent.solver
        self.name_or_path = '<inline>'
        self._model_dir = None

        # Minimal config for /api/v1/model and _start_query
        defaults = dict(
            program=program, kb_file=None, kb_format='auto',
            semantic_enabled=False, semantic_backend='st',
            semantic_model='intfloat/multilingual-e5-small',
            semantic_threshold=0.82, default_main=None,
            max_solutions=0, with_explanation=False,
        )
        defaults.update(config_overrides)
        self.config = SimpleNamespace(**defaults)

    def _ensure_solver(self):
        pass

    def add_fact(self, text):
        self.agent.add_fact(text)

    def add_facts(self, text):
        self.agent.add_facts(text)

    def __repr__(self):
        return f"_StandaloneModel(rules={len(self.agent.solver.database.rules)})"

# =====================================================================
# Wrappers: Python function -> Prolog predicate
# =====================================================================
def _tag(w, name, arity, func, kind):
    w._is_prolog_predicate = True
    w._predicate_name = name
    w._predicate_arity = arity
    w._agent_action = True
    w._action_name = name
    w._action_arity = arity
    w._action_description = func.__doc__ or ""
    w._action_type = kind
    return w


def _params(func):
    return [p for p in inspect.signature(func).parameters.values()
            if p.name != 'context']


def _has_ctx(func):
    return 'context' in inspect.signature(func).parameters


def _call(func, inputs, ctx):
    return func(*inputs, context=ctx) if _has_ctx(func) else func(*inputs)


def _wrap_simple(func, name, arity, out):
    @functools.wraps(func)
    def w(goal, db, subst, depth):
        if len(goal.arguments) != arity:
            return []
        inputs = []
        for i in range(arity):
            if i == out:
                continue
            a = goal.arguments[i].substitute(subst)
            if isinstance(a, Variable):
                return []
            inputs.append(prolog_to_python(a))
        try:
            r = _call(func, inputs, db.context)
        except Exception:
            return []
        if r is None:
            return []
        ns = goal.arguments[out].unify(python_to_prolog(r), subst.copy())
        return [ns] if ns is not None else []
    return _tag(w, name, arity, func, 'simple')


def _wrap_effector(func, name, arity):
    @functools.wraps(func)
    def w(goal, db, subst, depth):
        if len(goal.arguments) != arity:
            return []
        inputs = []
        for i in range(arity):
            a = goal.arguments[i].substitute(subst)
            if isinstance(a, Variable):
                return []
            inputs.append(prolog_to_python(a))
        try:
            _call(func, inputs, db.context)
        except Exception:
            return []
        return [subst.copy()]
    return _tag(w, name, arity, func, 'effector')


def _wrap_generator(func, name, arity, out):
    @functools.wraps(func)
    def w(goal, db, subst, depth):
        if len(goal.arguments) != arity:
            return []
        inputs = []
        for i in range(arity):
            if i == out:
                continue
            a = goal.arguments[i].substitute(subst)
            if isinstance(a, Variable):
                return []
            inputs.append(prolog_to_python(a))
        try:
            gen = _call(func, inputs, db.context)
        except Exception:
            return []
        results, out_arg = [], goal.arguments[out]
        for v in gen:
            ns = out_arg.unify(python_to_prolog(v), subst.copy())
            if ns is not None:
                results.append(ns)
        return results
    return _tag(w, name, arity, func, 'generator')

# =====================================================================
# Descriptor enabling three forms of agent program definition:
#   agent.program = """..."""          # assignment
#   agent.program("""...""")           # call
#   @agent.program                     # decorator on def
#   def _(): return "..."
# =====================================================================
class _ProgramSetter:
    """Callable view of agent.program for the form agent.program('...')."""
    __slots__ = ('_agent',)
    def __init__(self, agent):
        self._agent = agent
    def __call__(self, source):
        self._agent._set_program(source)
        return source     # for @-decorator: the function name stays a function


class _ProgramDescriptor:
    """Descriptor: agent.program = ... OR agent.program(...) OR @agent.program."""
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return _ProgramSetter(obj)
    def __set__(self, obj, value):
        obj._set_program(value)

# =====================================================================
# KB from HF Hub (workaround for _resolve_kb_path limitation)
# =====================================================================
def _ensure_kb_loaded(
    model: PyAgentPrologModel,
    *,
    token: Optional[str] = None,
    local_only: bool = False,
    revision: Optional[str] = None,
) -> bool:
    """Loads kb_file if _ensure_solver did not find it locally."""
    if not model.config.kb_file:
        return False
    resolved = model._resolve_kb_path(model.config.kb_file)
    if resolved and os.path.exists(resolved):
        return True
    if not model.name_or_path or model.name_or_path == '<inline>':
        return False
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("[fona] huggingface_hub unavailable, KB not loaded from Hub",
              file=sys.stderr)
        return False
    try:
        path = hf_hub_download(
            repo_id=model.name_or_path,
            filename=model.config.kb_file,
            token=token or os.getenv('FONA_HF_TOKEN') or None,
            local_files_only=local_only,
            revision=revision,
        )
        model._load_kb_file(path, model.config.kb_format)
        return True
    except Exception as e:
        print(f"[fona] KB load failed ({model.config.kb_file}): {e}",
              file=sys.stderr)
        return False


# =====================================================================
# Model cloning for HITL session
# =====================================================================
_HF_SPECIFIC_KEYS = {
    'architectures', 'auto_map', 'torch_dtype', 'transformers_version',
    'model_type', '_name_or_path', '_commit_hash',
    'id2label', 'label2id', 'problem_type',
    'output_hidden_states', 'output_attentions', 'return_dict',
    'use_cache', 'is_encoder_decoder', 'add_cross_attention',
    'tie_encoder_decoder', 'chunk_size_feed_forward', 'pruned_heads',
    'finetuning_task', 'num_beams', 'early_stopping',
    'no_repeat_ngram_size', 'length_penalty',
    'bad_words_ids', 'forced_bos_token_id', 'forced_eos_token_id',
    'remove_invalid_values',
}


def _clone_model(template) -> Any:
    """Clone for HITL. Works for both HF and standalone."""
    if isinstance(template, _StandaloneModel):
        clone = _StandaloneModel(
            template.config.program, template.config.__dict__)
        for meta in template.agent._actions.values():
            clone.agent.register_action(meta['function'])
        return clone

    # HF branch — import only here
    PyCfg, PyModel = _import_hf()
    cfg_dict = template.config.to_dict()
    for k in _HF_SPECIFIC_KEYS:
        cfg_dict.pop(k, None)
    clone = PyModel(PyCfg(**cfg_dict))
    clone.name_or_path = template.name_or_path
    clone._model_dir = template._model_dir
    clone._ensure_solver()
    if template.name_or_path and template.name_or_path != '<inline>':
        _ensure_kb_loaded(clone)
    for meta in template.agent._actions.values():
        clone.agent.register_action(meta['function'])
    return clone


# =====================================================================
# Agent
# =====================================================================
class Agent:
    """Background AI agent with declarative logic in Prolog.

    Minimal example:
        a = Agent()
        @a.program
        PROGRAM = "run :- ui_print('hi')."
        a.run()

    With an HF model:
        a = Agent.from_hub('user/repo')
        @a.program PROGRAM = "..."   # appended to the model's config.program
        a.run()
    """

    def __init__(self):
        self._program: str = ""
        self._actions: list = []
        self._hub_source: Optional[tuple] = None
        self._config_overrides: dict = {}
        self._model: Optional[PyAgentPrologModel] = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Agent program
    # ------------------------------------------------------------------
    program = _ProgramDescriptor()

    def _set_program(self, source):
        if isinstance(source, str):
            text = source
        elif callable(source):
            text = source()
            if not isinstance(text, str):
                raise TypeError(
                    f"program function must return str, got "
                    f"{type(text).__name__}")
        else:
            raise TypeError(
                f"program must be str or callable, got "
                f"{type(source).__name__}")
        self._program = (self._program + "\n" + text).strip()
        self._invalidate()

    # ------------------------------------------------------------------
    # Action decorators
    # ------------------------------------------------------------------
    def action(self, func=None, *, name=None, arity=None, output_arg=None):
        """@agent.action — predicate that returns a value.

        @agent.action
        def ask(prompt):
            return llm(prompt)         # -> ask/2, output_arg=1

        @agent.action(name='ask_llm', arity=2, output_arg=1)
        def ask(prompt): ...

        If the function contains yield, it becomes a generator automatically.
        """
        if func is None:
            return lambda f: self.action(f, name=name, arity=arity,
                                         output_arg=output_arg)
        n = len(_params(func))
        ar = arity if arity is not None else n + 1
        out = output_arg if output_arg is not None else n
        nm = name or func.__name__
        w = (_wrap_generator if inspect.isgeneratorfunction(func)
             else _wrap_simple)(func, nm, ar, out)
        self._actions.append(w)
        self._invalidate()
        return func

    def effect(self, func=None, *, name=None, arity=None):
        """@agent.effect — side effect, no return value. Always succeeds.

        @agent.effect
        def ui_print(text):
            ...
        """
        if func is None:
            return lambda f: self.effect(f, name=name, arity=arity)
        n = len(_params(func))
        ar = arity if arity is not None else n
        nm = name or func.__name__
        self._actions.append(_wrap_effector(func, nm, ar))
        self._invalidate()
        return func

    def generate(self, func=None, *, name=None, arity=None, output_arg=None):
        """@agent.generate — solution generator.

        @agent.generate
        def rooms():
            yield "kitchen"
            yield "bedroom"         # -> rooms/1
        """
        if func is None:
            return lambda f: self.generate(f, name=name, arity=arity,
                                           output_arg=output_arg)
        n = len(_params(func))
        ar = arity if arity is not None else n + 1
        out = output_arg if output_arg is not None else n
        nm = name or func.__name__
        self._actions.append(_wrap_generator(func, nm, ar, out))
        self._invalidate()
        return func

    # ------------------------------------------------------------------
    # HF Hub
    # ------------------------------------------------------------------
    @classmethod
    def from_hub(cls, repo_or_path: str, *, revision: Optional[str] = None):
        """Load a PyAgentProlog-HF model as the base.

        repo_or_path — HF Hub ID ('user/repo') or a local directory.
        Program and actions can be added later via decorators.
        """
        inst = cls()
        inst._hub_source = (repo_or_path, revision)
        return inst

    # Alias for compatibility with HF conventions
    from_pretrained = from_hub

    def load_hub(self, repo_or_path: str, *, revision: Optional[str] = None):
        """Use an HF model as the base (for the singleton)."""
        self._hub_source = (repo_or_path, revision)
        self._invalidate()
        return self

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def configure(self, **kwargs):
        """Overrides applied after loading.

        agent.configure(
            semantic_enabled=True,
            semantic_threshold=0.82,
            semantic_model='intfloat/multilingual-e5-small',
            max_solutions=50,
            default_main='handle_request',
        )
        """
        self._config_overrides.update(kwargs)
        self._invalidate()
        return self

    # ------------------------------------------------------------------
    # Model assembly
    # ------------------------------------------------------------------
    def _invalidate(self):
        with self._lock:
            self._model = None

    def _apply_overrides(self, model: PyAgentPrologModel):
        o = self._config_overrides
        if not o:
            return
        cfg = model.config

        # semantic — HF only (for standalone it is already applied via config)
        if self._hub_source is not None and o.get('semantic_enabled'):
            try:
                from prolog.embedding_unify import semantic_on
                semantic_on(
                    threshold=o.get('semantic_threshold',
                                    getattr(cfg, 'semantic_threshold', 0.82)),
                    model=o.get('semantic_model',
                                getattr(cfg, 'semantic_model',
                                        'intfloat/multilingual-e5-small')),
                    backend=o.get('semantic_backend',
                                  getattr(cfg, 'semantic_backend', 'st')),
                )
            except Exception as e:
                print(f"[fona] semantic_on failed: {e}", file=sys.stderr)

        for key in ('max_solutions', 'with_explanation', 'default_main'):
            if key in o:
                try:
                    setattr(cfg, key, o[key])
                except Exception:
                    pass

        # other keys — best effort
        handled = {'semantic_enabled', 'semantic_threshold', 'semantic_model',
                   'semantic_backend', 'max_solutions', 'with_explanation',
                   'default_main'}
        for k, v in o.items():
            if k not in handled:
                try:
                    setattr(cfg, k, v)
                except Exception:
                    pass

    def build(self, *, with_ui: bool = False):
        with self._lock:
            if self._model is not None:
                return self._model

            t0 = _time.time()
            if self._hub_source:
                # --- HF path: importing transformers/torch is unavoidable ---
                PyCfg, PyModel = _import_hf()
                repo, rev = self._hub_source
                model = PyModel.from_pretrained(
                    repo, revision=rev, trust_remote_code=True,
                    local_files_only=os.getenv('FONA_LOCAL_ONLY', '0')
                        .lower() in ('1', 'true'),
                    token=os.getenv('FONA_HF_TOKEN') or None,
                )
                model._ensure_solver()
                _ensure_kb_loaded(
                    model,
                    token=os.getenv('FONA_HF_TOKEN') or None,
                    local_only=os.getenv('FONA_LOCAL_ONLY', '0')
                        .lower() in ('1', 'true'),
                    revision=rev,
                )
                if self._program:
                    rules, directives = Parser(self._program).parse_rules(
                        return_directives=True)
                    model.solver._apply_directives(directives)
                    for r in reversed(rules):
                        model.agent.solver.database.add_rule(
                            r, at_beginning=True)
            else:
                # --- Standalone: no torch, no transformers ---
                model = _StandaloneModel(self._program, self._config_overrides)

            _log(f"build(): {_time.time()-t0:.2f}s "
                 f"({'HF' if self._hub_source else 'standalone'})")

            for w in self._actions:
                model.agent.register_action(w)

            if self._hub_source:
                self._apply_overrides(model)

            if with_ui:
                self._install_ui_actions(model.agent)

            self._model = model
            return model

    @staticmethod
    def _install_ui_actions(agent_obj):
        """Registers ui_print/ui_read + gradio_*-compatible names."""
        from prolog.proagent_gradio import register_gradio_actions
        from prolog.actions import effector_action, simple_action

        # Standard gradio_* — for documentation compatibility
        register_gradio_actions(agent_obj)

        # Canonical aliases for Fona
        @effector_action('ui_print', 1,
                         description='Print to the UI log')
        def ui_print(text, context):
            session = context.get('agent_session')
            if session is not None:
                session.add_output(text)

        @simple_action('ui_read', 1, output_arg=0,
                       description='Wait for UI input')
        def ui_read(context):
            session = context.get('agent_session')
            if session is None:
                return None
            return session.get_input()

        agent_obj.register_action(ui_print)
        agent_obj.register_action(ui_read)

    # ------------------------------------------------------------------
    # Start goal
    # ------------------------------------------------------------------
    def _start_query(self, model: PyAgentPrologModel) -> str:
        db = model.agent.solver.database
        candidates = []
        if model.config.default_main:
            candidates.append(model.config.default_main)
        candidates.extend(['run', 'main'])
        for name in candidates:
            if (name, 0) in db.rule_index:
                return f"{name}."
            arities = [a for (n, a) in db.rule_index
                       if n == name and a > 0]
            if arities:
                max_a = max(arities)
                return f"{name}({', '.join(['_'] * max_a)})."
        return "run."

    # ------------------------------------------------------------------
    # Programmatic access (no HTTP)
    # ------------------------------------------------------------------
    def query(self, q: str) -> dict:
        return self.build().agent.query(q)

    def query_one(self, q: str) -> Optional[dict]:
        return self.build().agent.query_one(q)

    def stream(self, q: str):
        yield from self.build().agent.stream(q)

    def __call__(self, q: str):
        return self.query(q)

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------
    def run(
        self,
        host: str = '127.0.0.1',
        port: int = 8000,
        ui: bool = True,
        rest: bool = True,
        token: Optional[str] = None,
        background: bool = False,
    ):
        """Start the agent.

        background=True -> pythonw without a console window (Windows).
        """
        if os.environ.get('FONA_CHILD') == '1':
            background = False
        elif background:
            self._spawn_background()
            return

        model = self.build(with_ui=ui)

        from .server import create_app, run_uvicorn
        app = create_app(
            model,
            start_query=self._start_query(model),
            with_ui=ui,
            with_rest=rest,
            token=token or os.getenv('FONA_TOKEN'),
        )
        run_uvicorn(app, host=host, port=port)

    @staticmethod
    def _spawn_background():
        import subprocess

        script = getattr(sys.modules.get('__main__'), '__file__', None) \
            or sys.argv[0]
        if not script or not os.path.exists(script) \
                or not script.endswith('.py'):
            print("[fona] cannot locate .py script, running foreground",
                  file=sys.stderr)
            return

        exe = sys.executable
        if exe.lower().endswith('python.exe'):
            cand = exe[:-len('python.exe')] + 'pythonw.exe'
            if os.path.exists(cand):
                exe = cand

        env = os.environ.copy()
        env['FONA_CHILD'] = '1'
        flags = 0x08000000 if sys.platform == 'win32' else 0

        subprocess.Popen(
            [exe, script],
            env=env,
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[fona] spawned background: {exe} {script}")


# Singleton for quick start
agent = Agent()