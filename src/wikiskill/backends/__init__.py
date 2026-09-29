"""Backend registry — importing this package registers all built-in adapters.

Adapters: mock (offline/demo), hermes (reference real backend).
P3 adds claude / codex / pi (design.md §3).
"""
from __future__ import annotations

from .base import (AgentBackend, RunResult, available_backends, get_backend,
                   register)

# registration side effects
from . import mock as _mock      # noqa: F401
from . import hermes as _hermes  # noqa: F401

__all__ = ["AgentBackend", "RunResult", "available_backends", "get_backend", "register"]
