from app.interfaces.web.agent_routes.routes import agent_bp
from app.interfaces.web.agent_routes import document_upload as _document_upload  # noqa: F401
from app.interfaces.web.agent_routes import corpus_media as _corpus_media  # noqa: F401

__all__ = ["agent_bp"]
