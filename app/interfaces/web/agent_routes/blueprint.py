"""Shared Flask blueprint for agent HTTP routes."""

from __future__ import annotations

from flask import Blueprint

agent_bp = Blueprint(
    "agent",
    __name__,
    template_folder="../templates",
)
