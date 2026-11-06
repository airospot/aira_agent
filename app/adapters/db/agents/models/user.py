"""Minimal User stub for Native Knowledge Flow.

Auth/RBAC is disabled locally. Kept only so SQLAlchemy can resolve the
``users`` table name if referenced; memory no longer enforces a FK.
"""

from __future__ import annotations

from app.adapters.db.agents.models.base import db


class User(db.Model):
    __tablename__ = "users"

    user_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, nullable=True)
    email = db.Column(db.String(255), nullable=True)

    @property
    def id(self):
        return self.user_id

    def __repr__(self):
        return f"<User stub {self.user_id}>"
