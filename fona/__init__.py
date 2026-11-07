"""Fona — минималистичный фреймворк фоновых ИИ-агентов на PyAgentProlog."""
from .agent import Agent, agent
from .peers import call_peer, register_peers
from .protocol import register_protocol

__all__ = [
    'Agent', 'agent',
    'load_config', 'FonaConfig',
    'call_peer', 'register_peers',
    'register_protocol',
]
__version__ = '0.1.0'