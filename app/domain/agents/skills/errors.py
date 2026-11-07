"""Coded skill load / bind errors (HTTP 400; no traceback to client)."""

from __future__ import annotations


class SkillError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
