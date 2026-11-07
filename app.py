"""Standalone entry for the Native Knowledge Flow application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv
from flask import Flask, send_from_directory, request
from markupsafe import Markup

load_dotenv(ROOT / ".env", override=True)

_DIR_KEYS = ("AGENT_CORPUS_DIR", "TENANT_DATA_ROOT")

_ENV_OVERLAY = (
    "SECRET_KEY",
    "DATABASE_URL",
    "AUTH_PROVIDER_URL",
    "AUTH_PROVIDER_INTERNAL_URL",
    "AUTH_PROVIDER_ALLOWED_ISSUERS",
    "AUTH_SITE_SLUG",
    "JWT_ACCEPTED_SITE_SLUGS",
    "JWKS_CACHE_TTL_SECONDS",
    "AUTH_DISABLED",
    "AUTH_BYPASS_USER_ID",
    "AUTH_BYPASS_CUSTOMER_ID",
    "LOGIN_UI_URL",
    "KNOWLEDGE_FLOW_LLM_BASE_URL",
    "KNOWLEDGE_FLOW_LLM_MODEL",
    "KNOWLEDGE_FLOW_LLM_API_KEY",
    "KNOWLEDGE_FLOW_LLM_TIMEOUT_SECONDS",
    "AGENT_CORPUS_DIR",
    "TENANT_DATA_ROOT",
    "AGENT_SUBMISSION_TIMEOUT_SECONDS",
)

_SECRET_KEY_PLACEHOLDERS = frozenset(
    {
        "replace-with-a-long-random-string",
        "dev-runtime-governance",
        "changeme",
        "change-me",
        "secret",
        "your-secret-key",
    }
)


def _require_secret_key(raw: object) -> str:
    if raw is None:
        raise SystemExit("SECRET_KEY gerekli.")
    value = str(raw).strip()
    if not value:
        raise SystemExit("SECRET_KEY gerekli (boş/whitespace kabul edilmez).")
    if value.lower() in _SECRET_KEY_PLACEHOLDERS:
        raise SystemExit(
            f"SECRET_KEY placeholder kabul edilmez: {value!r}. "
            "Uzun rastgele bir değer kullanın."
        )
    return value


def _psycopg2_uri(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://") :]
    return url


def _absolutize(value: object) -> object:
    if not isinstance(value, str) or not value.strip():
        return value
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((ROOT / path).resolve())


def create_app() -> Flask:
    from app.core.config import build_app_config
    from app.adapters.db.agents.models.base import db
    import app.adapters.db.agents.models.memory  # noqa: F401
    import app.adapters.db.agents.models.user  # noqa: F401
    import app.adapters.db.agents.models.structured_memory_tables  # noqa: F401
    import app.adapters.db.agents.models.rbac  # noqa: F401
    from app.interfaces.web.safe_markdown import render_safe_markdown
    from app.interfaces.web.agent_routes import agent_bp

    templates = ROOT / "app/interfaces/web/templates"
    static_dir = ROOT / "app/interfaces/web/static"
    app = Flask(
        "native_knowledge_flow",
        template_folder=str(templates),
        static_folder=None,
    )
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    app.config.update(build_app_config())
    for key in _ENV_OVERLAY:
        raw = os.environ.get(key)
        if raw is not None and str(raw).strip() != "":
            app.config[key] = raw
    for key in _DIR_KEYS:
        if key in app.config:
            app.config[key] = _absolutize(app.config.get(key))

    database_url = str(app.config.get("DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        raise SystemExit(
            "DATABASE_URL gerekli. Konuşma belleği PostgreSQL kullanır; "
            "değer .env içine yazılmalıdır."
        )
    app.config["SQLALCHEMY_DATABASE_URI"] = _psycopg2_uri(database_url)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = _require_secret_key(app.config.get("SECRET_KEY"))

    auth_disabled_raw = str(app.config.get("AUTH_DISABLED") or "").strip().lower()
    auth_disabled = auth_disabled_raw in {"1", "true", "yes", "on"}
    if not auth_disabled and not str(app.config.get("LOGIN_UI_URL") or "").strip():
        raise SystemExit(
            "LOGIN_UI_URL gerekli (AUTH_DISABLED kapalı). "
            "Provider giriş yolu varsayılmaz; gerçek login URL'sini ayarlayın. "
            "Yerel geliştirme için AUTH_DISABLED=1 kullanın."
        )

    db.init_app(app)

    def safe_markdown(value):
        return Markup(render_safe_markdown(value or ""))

    app.jinja_env.filters["safe_markdown"] = safe_markdown

    @app.route(
        "/agent/static/<path:filename>",
        endpoint="agent_static",
    )
    def agent_static(filename: str):
        return send_from_directory(static_dir, filename)

    @app.before_request
    def _agent_jwt():
        path = request.path or ""
        if not path.startswith("/agent/") and path.rstrip("/") != "/agent":
            return None
        if path.startswith("/agent/static/"):
            return None
        from app.core.security import auth_disabled, install_auth_bypass_context, jwt_required

        if auth_disabled():
            install_auth_bypass_context()
            return None

        @jwt_required()
        def _allow():
            return None

        return _allow()

    app.register_blueprint(agent_bp, url_prefix="/agent")

    @app.get("/")
    def root():
        from flask import redirect

        return redirect("/agent/")

    @app.get("/health")
    def health():
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        assistant = "/agent/assistant" in rules
        propose = "/agent/assistant/propose" in rules
        ok = assistant and propose
        return {
            "status": "healthy" if ok else "unhealthy",
            "native_flow": {
                "get_assistant": assistant,
                "post_propose": propose,
                "screen": "/agent/assistant",
            },
        }, (200 if ok else 503)

    return app


if __name__ == "__main__":
    application = create_app()
    host = os.environ.get("AIRA_DEV_HOST", "127.0.0.1")
    port = int(os.environ.get("AIRA_DEV_PORT", os.environ.get("FLASK_RUN_PORT", "5000")))
    application.run(host=host, port=port, debug=False)
