"""Fona — минималистичный фреймворк фоновых ИИ-агентов на PyAgentProlog.

Пользователь пишет Prolog и Python-функции, всё остальное — под капотом.

    from fona import agent

    @agent.program
    PROGRAM = '''
    run :- ui_print('hello').
    '''

    agent.run()
"""
from .agent import Agent, agent

__all__ = ['Agent', 'agent']
__version__ = '0.1.0'