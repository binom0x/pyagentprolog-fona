# fona/orchestrator_app.py
"""Entry point for orchestrator UI.

Loads the user's template module (which defines PANELS, ACTIONS, CFG)
and launches it. If no template is given, uses examples/orchestrator_template.py.
"""
import argparse
import importlib.util
import os
import sys

from fona.orchestrator_ui import OrchestratorConfig, build_ui, launch


def _load_template(path: str):
    spec = importlib.util.spec_from_file_location("orch_template", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--orchestrator", default="http://127.0.0.1:8000")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--template", default=None,
                        help="path to a Python file defining PANELS/ACTIONS")
    parser.add_argument("--lang", default=os.getenv("FONA_DASHBOARD_LANG", "en"))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    if args.template and os.path.isfile(args.template):
        mod = _load_template(args.template)
        cfg = mod.OrchestratorConfig(
            base_url=args.orchestrator,
            token=os.getenv("FONA_TOKEN"),
            panels=mod.PANELS,
            actions=getattr(mod, "ACTIONS", []),
        )
    else:
        cfg = OrchestratorConfig(base_url=args.orchestrator)

    launch(cfg, host=args.host, port=args.port, lang=args.lang)