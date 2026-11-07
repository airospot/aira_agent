"""Agent web routes — register modules on shared ``agent_bp``."""

from app.interfaces.web.agent_routes.blueprint import agent_bp
from app.interfaces.web.agent_routes import assistant as _assistant  # noqa: F401
from app.interfaces.web.agent_routes import conversations as _conversations  # noqa: F401
from app.interfaces.web.agent_routes import propose as _propose  # noqa: F401
from app.interfaces.web.agent_routes import document_upload as _document_upload  # noqa: F401
from app.interfaces.web.agent_routes import corpus_image_serve as _corpus_image_serve  # noqa: F401

__all__ = ["agent_bp"]
