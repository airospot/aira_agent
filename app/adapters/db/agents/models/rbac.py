"""Minimal RBAC stub for Native Knowledge Flow.

JWT/role gates are bypassed with AUTH_DISABLED. These empty markers keep
legacy imports from breaking without loading full RBAC tables.
"""

from __future__ import annotations

from app.adapters.db.agents.models.base import db


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=True)

    def __repr__(self):
        return f"<Role stub {self.id}>"
