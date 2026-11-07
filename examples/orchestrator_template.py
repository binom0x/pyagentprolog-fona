"""Orchestrator UI template — customize for your team.

The orchestrator is *the agent itself* (its Prolog program). This file
only configures which panels to show on top of the standard chat.

To adapt:
  1. Point base_url at your orchestrator agent.
  2. Replace `panels` with the views your team needs.
  3. Add `actions` for buttons/forms.
  4. Run:  python examples/orchestrator_template.py --port 8010

The default panels below (Goal, Plan, Subordinates) match a generic
team-lead agent exposing:
    GET  /orch/current_goal   -> {"goal": str}
    GET  /orch/tasks          -> {"tasks": [{"title", "status"}]}
    GET  /orch/subordinates   -> {"agents": [{"name", "url", "status"}]}
If your agent exposes different endpoints, just change the paths and
renderers — nothing in the UI is hard-coded.
"""
from __future__ import annotations

import argparse
import os
import sys

from fona.orchestrator_ui import (
    Action, OrchestratorConfig, Panel,
    build_ui, launch,
    render_kv, render_list, render_kanban, _status_box,
)


# ============================================================================
# 1. Panels — what the user sees (read-only views)
# ============================================================================
def _get_goal(client) -> str:
    data = client.get_json("/orch/current_goal") or {}
    return data.get("goal", "")


def _get_tasks(client) -> list:
    data = client.get_json("/orch/tasks") or {}
    return data.get("tasks", []) if isinstance(data, dict) else []


def _get_subs(client) -> list:
    data = client.get_json("/orch/subordinates") or {}
    return data.get("agents", []) if isinstance(data, dict) else []


def _render_goal(goal: str, lang: str) -> str:
    if not goal:
        return _status_box("No goal set." if lang == "en"
                           else "Цель не задана.")
    return (f'<div class="goal-card">'
            f'<div class="goal-label">\U0001f3af Goal</div>'
            f'<div>{goal}</div></div>')


PANELS = [
    Panel(
        key="goal",
        title_en="Goal", title_ru="Цель",
        fetcher=_get_goal,
        renderer=_render_goal,
        refresh_sec=2.0,
    ),
    Panel(
        key="tasks",
        title_en="Plan", title_ru="План",
        fetcher=_get_tasks,
        renderer=render_kanban,
        refresh_sec=1.0,
    ),
    Panel(
        key="subs",
        title_en="Subordinates", title_ru="Подчинённые",
        fetcher=_get_subs,
        renderer=render_list,
        refresh_sec=2.0,
    ),
]


# ============================================================================
# 2. Actions — optional buttons
# ============================================================================
def _set_goal_from_input(client, values):
    # The UI does not have a form for this yet; use the chat instead.
    return "Use chat to set the goal, or extend this template."


ACTIONS = [
    # Action(key="ping", title_en="Ping", title_ru="Пинг",
    #        handler=lambda c, v: c.get_json("/api/v1/health")),
]


# ============================================================================
# 3. Config + launch
# ============================================================================
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--orchestrator",
                        default=os.getenv("FONA_ORCHESTRATOR",
                                          "http://127.0.0.1:8000"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--lang", default=os.getenv("FONA_DASHBOARD_LANG", "en"))
    args = parser.parse_args(argv)

    cfg = OrchestratorConfig(
        base_url=args.orchestrator,
        token=os.getenv("FONA_TOKEN"),
        panels=PANELS,
        actions=ACTIONS,
    )
    launch(cfg, host=args.host, port=args.port, lang=args.lang)


if __name__ == "__main__":
    main()