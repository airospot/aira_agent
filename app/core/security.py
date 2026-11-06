#!/usr/bin/env python3
"""Security utilities - JWT-based authentication only.

Auth guard (app.before_request):
  - auth_guard() is registered in app/main.py as app.before_request(auth_guard).
  - PUBLIC routes: no JWT required; request continues.
  - PROTECTED routes: if no JWT, redirect to central login (or 401 for API).
  - Root (/): allowed; dashboard route applies @require_permission as needed.

Decorators (use on route handlers):
  - @jwt_required()          : require valid JWT (cookie or Authorization header).
  - @jwt_required(optional=True): JWT optional; g.jwt_payload set if present.
  - @require_tenant          : require session user_id+customer_id; set g.user_id, g.customer_id.
  - @require_permission(code): JWT required + permission check.
  - @require_any_permission(*codes), @require_role(name), @require_any_role(*names).
"""

from functools import wraps
import os
import time
import threading
from typing import Optional, Union, Tuple
from flask import request, jsonify, redirect, current_app, g, session
from jose import jwt as jose_jwt, jwk
import requests
from app.core.context import get_context, RequestContext


# ---------------------------------------------------------------------------
# JWKS caching (performance)
# ---------------------------------------------------------------------------
_JWKS_CACHE_LOCK = threading.Lock()
_JWKS_CACHE_VALUE = None  # type: ignore[assignment]
_JWKS_CACHE_FETCHED_AT = 0.0


def _jwks_cache_ttl_seconds() -> int:
    """JWKS cache TTL in seconds. Defaults to 900 (15 minutes)."""
    try:
        raw = current_app.config.get("JWKS_CACHE_TTL_SECONDS")
    except Exception:
        raw = None
    if raw is None:
        raw = (os.environ.get("JWKS_CACHE_TTL_SECONDS") or "").strip()
    try:
        v = int(raw) if raw not in (None, "", False) else 900
    except Exception:
        v = 900
    # Safety bounds
    if v < 30:
        return 30
    if v > 86400:
        return 86400
    return v


def _wants_json_response() -> bool:
    """Best-effort detection for API/AJAX requests.

    Some JSON endpoints do not live under `/api/*` (e.g. media upload routes
    called via fetch + FormData). For those, Flask's `request.is_json` is false,
    so we additionally use Accept / XHR hints.
    """
    try:
        if request.path.startswith("/api/"):
            return True
        if request.is_json:
            return True
        accept = (request.headers.get("Accept") or "").lower()
        # If browser navigation, Accept often includes text/html; do not force JSON in that case.
        if "application/json" in accept and "text/html" not in accept:
            return True
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return True
    except Exception:
        return False
    return False


# Auth Provider configuration
def get_auth_provider_url():
    """Get Auth Provider URL from config."""
    return current_app.config.get('AUTH_PROVIDER_URL', 'https://auth.airaintelligence.ai')


def get_allowed_issuers():
    """Normalized JWT issuer allowlist. Live tokens stay valid."""
    raw = current_app.config.get('AUTH_PROVIDER_ALLOWED_ISSUERS') or [get_auth_provider_url()]
    if isinstance(raw, str):
        raw = [s.strip() for s in raw.split(',') if s.strip()]
    issuers = {normalize_issuer(v) for v in raw if v}
    issuers.add(normalize_issuer(get_auth_provider_url()))
    return {issuer for issuer in issuers if issuer}


def get_jwks_url():
    """JWKS URL. Prefer the internal auth container when it is configured."""
    internal = (current_app.config.get('AUTH_PROVIDER_INTERNAL_URL') or '').strip()
    base = internal.rstrip('/') if internal else get_auth_provider_url().rstrip('/')
    return f"{base}/auth/.well-known/jwks.json"

def get_accepted_site_slugs():
    """Accepted JWT site_slug values (from config, comma-separated). Default: aira_intelligence."""
    raw = current_app.config.get('JWT_ACCEPTED_SITE_SLUGS', 'aira_intelligence')
    return {s.strip() for s in str(raw).split(',') if s.strip()}


def _expected_site_slug() -> str:
    """Expected site slug for THIS sub-app (strict mode)."""
    return (current_app.config.get("AUTH_SITE_SLUG") or "aira_intelligence").strip() or "aira_intelligence"


def _normalize_audience(aud_val) -> set[str]:
    """Normalize JWT `aud` claim into a set of strings."""
    out: set[str] = set()
    if aud_val is None:
        return out
    if isinstance(aud_val, str):
        v = aud_val.strip()
        if v:
            out.add(v)
        return out
    if isinstance(aud_val, (list, tuple, set)):
        for it in aud_val:
            try:
                s = str(it).strip()
            except Exception:
                continue
            if s:
                out.add(s)
    return out

def normalize_issuer(val: str) -> str:
    """Normalize issuer URL by removing protocol and trailing slash.
    
    Examples:
        'https://auth.airaintelligence.ai' -> 'auth.airaintelligence.ai'
        'https://auth.airaintelligence.ai/' -> 'auth.airaintelligence.ai'
        'http://auth.airaintelligence.ai' -> 'auth.airaintelligence.ai'
    """
    if not val:
        return ""
    return val.replace("https://", "").replace("http://", "").rstrip("/")

# Route Classification Constants
# PUBLIC routes (no auth required) - exact matches
PUBLIC_ROUTES = {
    '/api/health',
    '/healthz',
    '/login',
    '/auth/login',
    '/logout',
    '/auth/logout',
    '/logged-out',
    '/offline',
    '/sso/bootstrap',
    '/set_language',
}

# PUBLIC route prefixes (explicit)
PUBLIC_PREFIXES = [
    '/static/',
]

# PROTECTED route prefixes
PROTECTED_PREFIXES = [
    '/dashboard',
    '/admin',
    '/api',  # except /api/health
    '/settings',
    '/graph',  # AiraVisor için
]


def is_public_route(path: str) -> bool:
    """Check if route is public (no auth required).
    
    Args:
        path: Request path (e.g., '/api/health', '/static/css/core.css').
    
    Returns:
        True if route is public, False otherwise.
    """
    # Exact matches
    if path in PUBLIC_ROUTES:
        return True
    
    # Prefix matches (explicit)
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    
    return False


def is_protected_route(path: str) -> bool:
    """Check if route is protected (JWT required).
    
    Args:
        path: Request path (e.g., '/dashboard/', '/api/rag/chat').
    
    Returns:
        True if route is protected, False otherwise.
    """
    # Exclude public routes
    if is_public_route(path):
        return False
    
    # Check protected prefixes
    for prefix in PROTECTED_PREFIXES:
        if path.startswith(prefix):
            # Special case: /api/health is public
            if path == '/api/health' or path.startswith('/api/health/'):
                return False
            return True
    
    return False


def is_platform_management_path(path: str) -> bool:
    """True if this request is within Platform Yönetimi scope.

    Used for SYSTEM_OWNER tenant override. Keep this list tight to avoid accidental tenant switching
    on normal (customer-facing) pages.
    """
    p = (path or "").strip()
    if not p:
        return False
    prefixes = (
        "/system/",  # logs/status/prompts
        "/management/media-settings",
        "/management/database",
        "/management/super-admin",
        "/clear_logs",
        "/platform/",  # switch/clear endpoints
    )
    return any(p.startswith(x) for x in prefixes)


def get_jwt_from_cookie() -> Optional[str]:
    """Read JWT from this app's site-scoped cookie.
    
    Returns:
        JWT token string if found, None otherwise.
    """
    cookie_name = current_app.config.get('JWT_COOKIE_NAME') or 'airacoder_jwt'
    return request.cookies.get(cookie_name)


def get_hub_jwt_from_cookie() -> Optional[str]:
    """Read hub JWT cookie (platform SSO)."""
    return request.cookies.get('aira_jwt')


def get_jwt_from_authorization_header() -> Optional[str]:
    """Extract JWT from Authorization header.
    
    Returns:
        JWT token string if found, None otherwise.
    """
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        return auth_header.split(' ')[1]
    return None


def auth_disabled() -> bool:
    """Local/dev bypass when no Auth Provider is available on this machine."""
    raw = ""
    try:
        raw = str(current_app.config.get("AUTH_DISABLED") or "").strip()
    except Exception:
        raw = ""
    if not raw:
        raw = (os.environ.get("AUTH_DISABLED") or "").strip()
    return raw.lower() in {"1", "true", "yes", "on"}


def install_auth_bypass_context() -> Tuple[int, int]:
    """Seed g.jwt_payload / RequestContext for AUTH_DISABLED local runs."""
    from app.core.context import RequestContext

    try:
        user_id = int(
            current_app.config.get("AUTH_BYPASS_USER_ID")
            or os.environ.get("AUTH_BYPASS_USER_ID")
            or 1
        )
    except Exception:
        user_id = 1
    try:
        customer_id = int(
            current_app.config.get("AUTH_BYPASS_CUSTOMER_ID")
            or os.environ.get("AUTH_BYPASS_CUSTOMER_ID")
            or 1
        )
    except Exception:
        customer_id = 1

    site_slug = (
        current_app.config.get("AUTH_SITE_SLUG")
        or os.environ.get("AUTH_SITE_SLUG")
        or "airacoder"
    )
    site_slug = str(site_slug).strip() or "airacoder"

    payload = {
        "user_id": user_id,
        "sub": str(user_id),
        "customer_id": customer_id,
        "site_id": 1,
        "site_slug": site_slug,
        "role_slug": "super_admin",
        "roles": ["Super Admin", "Admin"],
        "permissions": ["*"],
        "aud": site_slug,
        "email": "local@localhost",
        "name": "Local Dev",
    }
    g.jwt_payload = payload
    g.request_context = RequestContext(
        user_id=user_id,
        customer_id=customer_id,
        site_id=1,
        site_slug=site_slug,
        role_slug="super_admin",
        email="local@localhost",
        roles=["Super Admin", "Admin"],
        permissions=["*"],
    )
    try:
        _hydrate_session_from_jwt(payload)
    except Exception:
        pass
    return user_id, customer_id


def require_tenant_context() -> Union[Tuple[int, int], tuple]:
    """Hard-enforce tenant context from JWT context.

    Returns:
      - (user_id:int, customer_id:int) on success
      - (flask.Response, status_code) for API routes when missing
      - (flask.Response, status_code) redirect for web routes when missing

    Notes:
      - This MUST NOT fall back to session/DB for customer_id.
      - Web routes redirect to central login (cookie bridge) via redirect_to_auth().
      - API routes return 401 JSON.
    """
    if auth_disabled():
        return install_auth_bypass_context()

    ctx = get_context()
    if not ctx:
        if _wants_json_response():
            return jsonify({"error": "Authentication required"}), 401
        return redirect_to_auth()

    user_id = ctx.user_id
    customer_id = ctx.customer_id

    # SYSTEM_OWNER only: platform pages can "act as" another customer (by override in session).
    try:
        sess_user = session.get("user") or {}
        role_slug = (sess_user.get("role_slug") or "").strip().lower().replace("-", "_").replace(" ", "_")
    except Exception:
        role_slug = ""

    override_raw = session.get("platform_customer_override")
    if role_slug == "system_owner" and override_raw is not None and is_platform_management_path(request.path):
        try:
            override_customer_id = int(override_raw)
            if override_customer_id > 0 and override_customer_id != customer_id:
                current_app.logger.info(
                    "[PLATFORM_OVERRIDE] actor_user_id=%s base_customer_id=%s override_customer_id=%s path=%s",
                    user_id,
                    customer_id,
                    override_customer_id,
                    request.path,
                )
                customer_id = override_customer_id
        except Exception:
            # Ignore malformed override
            pass

    return user_id, customer_id


def _external_base_url() -> str:
    """External base url (respects reverse proxy headers)."""
    proto = request.headers.get("X-Forwarded-Proto")
    if not proto:
        proto = "https" if request.is_secure else "http"
    host = request.headers.get("X-Forwarded-Host") or request.host
    return f"{proto}://{host}".rstrip("/")


def _external_current_url() -> str:
    """Full external URL (scheme/host from proxy headers + path/query).

    Include SCRIPT_NAME so a path-prefixed staging proxy returns to the same mount.
    Production leaves SCRIPT_NAME empty, so the URL is unchanged there.
    """
    base = _external_base_url()
    root = (request.script_root or "").rstrip("/")
    path = request.full_path  # includes query string
    if path.endswith("?"):
        path = path[:-1]
    if path and not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{root}{path}"


def _login_redirect_url(return_url: str) -> str:
    """Central login UI URL with return_url parameter."""
    from urllib.parse import quote
    login_ui_url = current_app.config.get('LOGIN_UI_URL', 'https://airaintelligence.ai/platform/airacoder')
    return f"{login_ui_url}?return_url={quote(return_url, safe='')}"


def _role_from_payload(payload: dict) -> str:
    """Best-effort role mapping for legacy templates."""
    def _normalize_role_slug(val: str) -> str:
        v = (val or "").strip()
        if not v:
            return ""
        v_low = v.lower()
        # Common display names (TR/EN) → slugs
        tr_en = {
            "super admin": "super_admin",
            "superadmin": "super_admin",
            "superadministrator": "super_admin",
            "system owner": "super_admin",
            "system_owner": "super_admin",
            "admin": "admin",
            "administrator": "admin",
        }
        if v_low in tr_en:
            return tr_en[v_low]
        # Slug-ish values → normalize
        v_low = v_low.replace("-", "_").replace(" ", "_")
        return v_low

    display = {
        "super_admin": "Super Admin",
        "admin": "Admin",
    }

    # Prefer new claim if present (but normalize it!)
    user_role = payload.get("user_role") or payload.get("role_slug")
    if user_role:
        slug = _normalize_role_slug(str(user_role))
        if slug in display:
            return display[slug]
        # Fallback: keep original string (prevents hiding everything if new role arrives)
        return str(user_role)
    roles = payload.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    mapping = {
        "SUPER_ADMIN": "Super Admin",
        "SYSTEM_OWNER": "Super Admin",
        "ADMIN": "Admin",
    }
    for r in roles:
        if r in mapping:
            return mapping[r]
    return "User"


def _hydrate_session_from_jwt(payload: dict) -> None:
    """Populate legacy session fields for templates/JS after JWT auth."""
    try:
        session["logged_in"] = True
        if payload.get("user_id") is not None:
            session["user_id"] = int(payload.get("user_id"))
        if payload.get("customer_id") is not None:
            session["customer_id"] = payload.get("customer_id")
        
        # Identity (email / first / last): prefer override, then JWT claims
        override = session.get("profile_override") if isinstance(session.get("profile_override"), dict) else None
        override_user_id = (override or {}).get("user_id") if override else None
        override_ok = False
        if override and override_user_id is not None:
            try:
                override_ok = int(override_user_id) == int(session.get("user_id") or 0)
            except Exception:
                override_ok = False

        ov_first = (override.get("first_name") or "").strip() if (override_ok and override) else ""
        ov_last = (override.get("last_name") or "").strip() if (override_ok and override) else ""
        ov_email = ((override.get("email") or "").strip().lower()) if (override_ok and override) else ""

        jwt_email = (payload.get("email") or "").strip().lower() if payload.get("email") else ""
        if ov_email:
            session["user_email"] = ov_email
        elif jwt_email:
            session["user_email"] = jwt_email

        first_name_claim = payload.get("first_name")
        last_name_claim = payload.get("last_name")

        if ov_first or ov_last:
            first_name = ov_first
            last_name = ov_last
            session["user_name"] = (f"{first_name} {last_name}").strip() or session.get("user_name")
        elif first_name_claim or last_name_claim:
            first_name = str(first_name_claim or "").strip()
            last_name = str(last_name_claim or "").strip()
            session["user_name"] = (f"{first_name} {last_name}").strip() or session.get("user_name")
        else:
            if payload.get("name"):
                session["user_name"] = payload.get("name")
            full_name = (session.get("user_name") or "").strip()
            first_name = ""
            last_name = ""
            if full_name:
                parts = full_name.split()
                first_name = parts[0]
                last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
        
        role_display = _role_from_payload(payload)
        role_source = "jwt"
        rbac_data = None

        # If JWT lacks role info, fetch RBAC from Auth Provider (source of truth).
        def _fetch_site_rbac(token: str, site_slug: str | None) -> dict:
            try:
                base = current_app.config.get("AUTH_PROVIDER_URL", "https://auth.airaintelligence.ai").rstrip("/")
                verify_ssl = current_app.config.get("AUTH_VERIFY_SSL", True)
                config_slug = (current_app.config.get("AUTH_SITE_SLUG") or "").strip()
                # Prefer app's configured slug (aira_intelligence). Fallback to JWT slug only if needed.
                preferred = (config_slug or "").strip()
                fallback = (site_slug or "").strip()
                slug = (preferred or fallback or "").strip()
                current_app.logger.info(
                    "[AUTH_SITE] security._fetch_site_rbac: AUTH_SITE_SLUG(config)=%r JWT_site_slug(param)=%r "
                    "using_slug=%r URL=%s",
                    config_slug or "(empty)",
                    site_slug if site_slug is not None else "(none)",
                    slug or "(empty)",
                    f"{base}/auth/me/sites/{slug}/roles" if slug else "(no request)",
                )
                if not slug:
                    return {}
                url = f"{base}/auth/me/sites/{slug}/roles"
                r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=5, verify=verify_ssl)
                if r.status_code != 200 and preferred and fallback and fallback != preferred:
                    # Fallback: try JWT slug if preferred slug fails (defensive)
                    url2 = f"{base}/auth/me/sites/{fallback}/roles"
                    current_app.logger.info("[RBAC] roles endpoint denied for preferred=%r (status=%s); trying fallback=%r", preferred, r.status_code, fallback)
                    r = requests.get(url2, headers={"Authorization": f"Bearer {token}"}, timeout=5, verify=verify_ssl)
                if r.status_code != 200:
                    current_app.logger.info("[RBAC] roles endpoint denied: status=%s", r.status_code)
                    return {}
                if not (r.headers.get("Content-Type", "").startswith("application/json")):
                    return {}
                data = r.json() or {}
                current_app.logger.info("[RBAC] roles endpoint returned: %s", data)
                return data
            except Exception as e:
                current_app.logger.info("[RBAC] roles endpoint failed: %s", e)
                return {}

        # Always prefer site-scoped RBAC from Auth Provider (even if JWT is hub/app-bound).
        # Cache in session to avoid calling Auth Provider on every request.
        token = get_jwt_from_authorization_header() or get_jwt_from_cookie()
        preferred_slug = (current_app.config.get("AUTH_SITE_SLUG") or "airacoder").strip() or "airacoder"
        cached_slug = (session.get("site_roles_slug") or "").strip()
        cached_source = (session.get("site_roles_source") or "").strip()
        has_cached = bool(session.get("site_roles")) and cached_slug == preferred_slug and cached_source == "provider"

        if token and has_cached:
            current_app.logger.info(
                "[RBAC] using cached provider RBAC: slug=%r roles=%s perms=%s",
                preferred_slug,
                len(session.get("site_roles") or []),
                len(session.get("site_permissions") or []),
            )
            rbac_data = {
                "roles": session.get("site_roles") or [],
                "user_role": session.get("site_roles")[0] if session.get("site_roles") else None,
                "role_slug": session.get("site_roles")[0] if session.get("site_roles") else None,
            }
        elif token and not has_cached:
            current_app.logger.info("[RBAC] fetching provider RBAC: slug=%r", preferred_slug)
            rbac_data = _fetch_site_rbac(token, payload.get("site_slug"))
            # keep provider RBAC in session for other parts of the app
            session["site_roles"] = rbac_data.get("roles", []) or []
            session["site_permissions"] = rbac_data.get("permissions", []) or []
            session["site_roles_slug"] = preferred_slug
            session["site_roles_source"] = "provider"
            # Keep a stable context slug for session-based parts
            session["site_slug"] = preferred_slug

        # Prefer provider RBAC (if any meaningful role info exists)
        rbac_roles = (rbac_data or {}).get("roles", []) or session.get("site_roles") or []
        rbac_user_role = (rbac_data or {}).get("user_role") or (rbac_data or {}).get("role_slug")
        
        # Log RBAC data for debugging
        if rbac_data:
            current_app.logger.info(
                "[RBAC] parsed: roles=%s user_role=%s role_slug=%s keys=%s",
                rbac_roles,
                rbac_user_role,
                (rbac_data or {}).get("role_slug"),
                list((rbac_data or {}).keys()) if isinstance(rbac_data, dict) else [],
            )
        else:
            current_app.logger.info("[RBAC] rbac_data is None or empty")
        
        if rbac_user_role or (isinstance(rbac_roles, list) and len(rbac_roles) > 0):
            role_display = _role_from_payload({"user_role": rbac_user_role, "roles": rbac_roles})
            role_source = "provider"
            current_app.logger.info("[RBAC] using provider role: role_display=%s", role_display)
        else:
            current_app.logger.warning(
                "[RBAC] No role found in RBAC response. rbac_user_role=%r rbac_roles=%r. Using JWT fallback.",
                rbac_user_role,
                rbac_roles,
            )
        
        # Canonical role_slug for menu/templates
        role_display_to_slug = {
            "Super Admin": "super_admin",
            "Admin": "admin",
        }
        raw_slug = (
            payload.get("role_slug") or payload.get("user_role")
            or ((rbac_data or {}).get("role_slug") or (rbac_data or {}).get("user_role"))
            or role_display_to_slug.get(role_display, "")
        )
        if not raw_slug:
            raw_slug = role_display_to_slug.get(role_display, "")
        raw_norm = (str(raw_slug).strip().lower().replace("-", "_").replace(" ", "_") or "") if raw_slug else ""
        slug_alias = {
            "super_admin": "super_admin",
            "system_owner": "super_admin",
            "admin": "admin",
            "administrator": "admin",
        }
        role_slug_canonical = slug_alias.get(raw_norm, raw_norm) or None

        # Legacy templates expect session.user with role
        session["user"] = {
            "id": session.get("user_id"),
            "name": session.get("user_name") or session.get("user_email") or "User",
            "email": session.get("user_email"),
            "role": role_display,
            "role_slug": role_slug_canonical,
            "first_name": first_name,
            "last_name": last_name,
        }
        current_app.logger.info("[HYDRATE] role=%s role_slug=%s source=%s", role_display, role_slug_canonical, role_source)
    except Exception:
        # Never break request on hydrate
        return


def get_jwks(*, force_refresh: bool = False):
    """Fetch JWKS from Auth Provider (cached with TTL).

    This must NOT affect JWT payload parsing (role/user_id/customer_id). It only reduces
    network calls to Auth Provider JWKS endpoint.
    """
    global _JWKS_CACHE_VALUE, _JWKS_CACHE_FETCHED_AT
    ttl = _jwks_cache_ttl_seconds()
    now = time.time()

    # Fast path (no lock) if cache is valid and not forced.
    if not force_refresh and _JWKS_CACHE_VALUE is not None and (now - _JWKS_CACHE_FETCHED_AT) < ttl:
        return _JWKS_CACHE_VALUE

    with _JWKS_CACHE_LOCK:
        now = time.time()
        if not force_refresh and _JWKS_CACHE_VALUE is not None and (now - _JWKS_CACHE_FETCHED_AT) < ttl:
            return _JWKS_CACHE_VALUE

        try:
            # Note: verify=False for now (production should use proper CA bundle)
            response = requests.get(get_jwks_url(), timeout=5, verify=False)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("keys"):
                _JWKS_CACHE_VALUE = data
                _JWKS_CACHE_FETCHED_AT = now
            return _JWKS_CACHE_VALUE
        except Exception as e:
            # Degrade gracefully: keep last known JWKS if present.
            try:
                age = int(max(0, now - float(_JWKS_CACHE_FETCHED_AT or 0.0)))
            except Exception:
                age = -1
            current_app.logger.error(f"Failed to fetch JWKS (cached_age_s={age}): {e}")
            return _JWKS_CACHE_VALUE


def verify_jwt_token(token: str) -> dict:
    """Verify JWT token using JWKS."""
    try:
        def _select_key(jwks_data: dict, kid_val: str | None):
            chosen_key = None
            if kid_val:
                for jwk_key in jwks_data.get("keys", []):
                    if jwk_key.get("kid") == kid_val:
                        chosen_key = jwk.construct(jwk_key)
                        break
            if not chosen_key and jwks_data.get("keys"):
                if kid_val:
                    current_app.logger.warning(f"No matching kid found (kid: {kid_val}), using first key as fallback")
                else:
                    current_app.logger.debug(f"No kid in JWT header, using first key as fallback")
                chosen_key = jwk.construct(jwks_data["keys"][0])
            return chosen_key

        # Decode header to get kid
        unverified_header = jose_jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        # Get JWKS (cached)
        jwks_data = get_jwks()
        if not jwks_data:
            raise ValueError("Failed to fetch JWKS")

        key = _select_key(jwks_data, kid)
        if not key:
            # Force refresh once (key rotation / stale cache)
            jwks_data = get_jwks(force_refresh=True)
            if not jwks_data:
                raise ValueError(f"No JWKS available after refresh (kid: {kid})")
            key = _select_key(jwks_data, kid)
        if not key:
            raise ValueError(f"No key found in JWKS (kid: {kid})")
        
        # Decode without verification to get JWT's unverified claims (for logging)
        unverified_payload = jose_jwt.decode(
            token,
            key="",
            options={"verify_signature": False, "verify_aud": False, "verify_iss": False},
        )
        
        # 1️⃣ Decode WITHOUT claim validation (only signature + exp)
        # NOTE: We do NOT validate audience here. Audience (aud) is Auth Provider's internal concern.
        # Application authorization is done via site_slug + permissions, not via audience.
        # We disable both audience and issuer validation in jose_jwt.decode() and do manual checks.
        current_app.logger.info(
            f"[VERIFY_JWT] About to decode token. "
            f"JWT aud={unverified_payload.get('aud')} "
            f"JWT site_slug={unverified_payload.get('site_slug')} "
            f"JWT user_role={unverified_payload.get('user_role')} "
            f"JWT roles={unverified_payload.get('roles', [])} "
            f"JWT issuer={unverified_payload.get('iss')}"
        )
        
        try:
            current_app.logger.info(
                f"[VERIFY_JWT] Calling jose_jwt.decode() with options={{'verify_aud': False, 'verify_iss': False}}"
            )
            try:
                payload = jose_jwt.decode(
                    token,
                    key,
                    algorithms=["RS256"],
                    options={
                        "verify_aud": False,
                        "verify_iss": False,  # Manual issuer check below
                    },
                )
            except Exception as first_decode_error:
                # If JWKS rotated, refresh once and retry.
                try:
                    jwks_data2 = get_jwks(force_refresh=True) or {}
                    key2 = _select_key(jwks_data2, kid) if isinstance(jwks_data2, dict) else None
                    if key2:
                        payload = jose_jwt.decode(
                            token,
                            key2,
                            algorithms=["RS256"],
                            options={
                                "verify_aud": False,
                                "verify_iss": False,
                            },
                        )
                    else:
                        raise first_decode_error
                except Exception:
                    raise first_decode_error
            current_app.logger.info(f"[VERIFY_JWT] jose_jwt.decode() succeeded")
            
            # 2️⃣ MANUAL issuer check (safe & explicit)
            allowed_issuers = get_allowed_issuers()
            token_issuer = normalize_issuer(payload.get("iss", ""))
            
            current_app.logger.info(
                f"[VERIFY_JWT] Issuer check: allowed='{sorted(allowed_issuers)}' token_issuer='{token_issuer}' "
                f"match={token_issuer in allowed_issuers}"
            )
            
            if token_issuer not in allowed_issuers:
                raise ValueError(
                    f"Invalid issuer: expected one of {sorted(allowed_issuers)}, got {token_issuer}"
                )
            
            current_app.logger.info(
                f"[VERIFY_JWT] Token decoded successfully. "
                f"aud={payload.get('aud')} site_slug={payload.get('site_slug')} "
                f"user_id={payload.get('user_id')} customer_id={payload.get('customer_id')} "
                f"issuer={payload.get('iss')} "
                f"user_role={payload.get('user_role')} "
                f"roles={payload.get('roles', [])} permissions={payload.get('permissions', [])}"
            )
            
            return payload
        except Exception as decode_error:
            current_app.logger.error(
                f"[VERIFY_JWT] jose_jwt.decode() failed: {type(decode_error).__name__}: {str(decode_error)}. "
                f"JWT unverified payload: aud={unverified_payload.get('aud')} "
                f"site_slug={unverified_payload.get('site_slug')} issuer={unverified_payload.get('iss')} "
                f"Exception details: {repr(decode_error)}"
            )
            # Re-raise with more context
            raise ValueError(f"JWT decode failed: {type(decode_error).__name__}: {str(decode_error)}") from decode_error
    except Exception as e:
        raise ValueError(f"Token verification failed: {str(e)}")


def jwt_required(optional=False):
    """Decorator for JWT authentication with Auth Provider validation.
    
    Hybrid JWT reading: Priority 1 = Authorization header, Priority 2 = Cookie.
    
    Can be used as:
        @jwt_required()
        @jwt_required(optional=True)
        @jwt_required  # Also works without parentheses
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            current_app.logger.info(
                f"[JWT_REQUIRED] Entering decorator for {request.path} "
                f"Function: {f.__name__}"
            )

            if auth_disabled():
                install_auth_bypass_context()
                return f(*args, **kwargs)
            
            # Priority 1: Authorization header
            token = get_jwt_from_authorization_header()
            
            # Priority 2: Cookie (if header not found)
            if not token:
                token = get_jwt_from_cookie()
            
            current_app.logger.info(
                f"[JWT_REQUIRED] Token found: {bool(token)} for {request.path}"
            )
            
            if not token:
                if optional:
                    # Allow request to proceed without JWT
                    return f(*args, **kwargs)
                # If user has hub token cookie, bootstrap to site token instead of redirecting to login again.
                if not _wants_json_response():
                    try:
                        hub_token = get_hub_jwt_from_cookie()
                        if hub_token and request.path != "/sso/bootstrap":
                            from urllib.parse import quote
                            return redirect(f"/sso/bootstrap?next={quote(request.full_path.rstrip('?'), safe='')}", 302)
                    except Exception:
                        pass
                # Redirect to our /login (starts authorization code flow)
                return_url = _external_current_url()
                login_url = _login_redirect_url(return_url)
                if _wants_json_response():
                    return jsonify({
                        'error': 'Authentication required',
                        'redirect_url': login_url
                    }), 401
                return redirect(login_url), 302
            
            try:
                current_app.logger.info(
                    f"[JWT_REQUIRED] Verifying token for {request.path}"
                )
                # Verify token
                payload = verify_jwt_token(token)
                
                # STRICT: Validate site_slug + audience (aud) == this app's site_slug.
                # Auth Provider tokens are site-scoped; cross-site tokens MUST be rejected.
                expected_slug = _expected_site_slug()
                jwt_site_slug = (payload.get("site_slug") or "").strip()
                aud_set = _normalize_audience(payload.get("aud"))
                slug_ok = bool(jwt_site_slug) and jwt_site_slug == expected_slug
                aud_ok = expected_slug in aud_set
                current_app.logger.info(
                    "[JWT_REQUIRED] Strict site validation: expected_slug=%r jwt_site_slug=%r slug_ok=%s aud=%r aud_ok=%s",
                    expected_slug,
                    jwt_site_slug,
                    slug_ok,
                    payload.get("aud"),
                    aud_ok,
                )
                
                current_app.logger.debug(
                    f"[JWT_REQUIRED] Token verified for {request.path}. "
                    f"site_slug={jwt_site_slug} "
                    f"aud={payload.get('aud')} "
                    f"user_id={payload.get('user_id')} "
                    f"customer_id={payload.get('customer_id')} "
                    f"issuer={payload.get('iss')}"
                )
                
                if not slug_ok or not aud_ok:
                    current_app.logger.warning(
                        "[JWT_REQUIRED] Strict site validation failed for %s. expected_slug=%r jwt_site_slug=%r aud=%r",
                        request.path,
                        expected_slug,
                        jwt_site_slug,
                        payload.get("aud"),
                    )
                    if _wants_json_response():
                        if not slug_ok:
                            return jsonify({"error": "Invalid site_slug"}), 403
                        return jsonify({"error": "Invalid audience"}), 403
                    else:
                        # If user is holding a hub token (aira_intelligence), bootstrap to this site's token.
                        if request.path != "/sso/bootstrap":
                            try:
                                from urllib.parse import quote
                                return redirect(f"/sso/bootstrap?next={quote(request.full_path.rstrip('?'), safe='')}", 302)
                            except Exception:
                                return redirect("/sso/bootstrap", 302)
                        return redirect_to_auth()
                
                # Store in request context
                g.jwt_payload = payload
                _hydrate_session_from_jwt(payload)
                # Ensure RequestContext exists for templates (base.html) on routes that only use @jwt_required().
                try:
                    g.request_context = get_context()
                except Exception:
                    pass
                current_app.logger.debug(
                    f"[JWT_REQUIRED] JWT payload stored in g.jwt_payload for {request.path}"
                )
                
            except ValueError as e:
                current_app.logger.warning(
                    f"[JWT_REQUIRED] Token verification failed for {request.path}: {str(e)}"
                )
                # API routes: return JSON
                # Web routes: refresh via hub SSO when the site cookie is stale
                if _wants_json_response():
                    return jsonify({'error': 'Invalid or expired token', 'details': str(e)}), 401
                refreshed = _bootstrap_from_hub()
                if refreshed is not None:
                    return refreshed
                return redirect_to_auth()
            except Exception as e:
                current_app.logger.error(
                    f"[JWT_REQUIRED] Unexpected error during JWT verification for {request.path}: {str(e)}",
                    exc_info=True
                )
                # Same logic for other exceptions
                if _wants_json_response():
                    return jsonify({'error': 'Authentication failed'}), 401
                else:
                    return redirect_to_auth()
            
            return f(*args, **kwargs)
        return decorated_function
    
    # Support both @jwt_required() and @jwt_required (without parentheses)
    if callable(optional):
        # Called without parentheses: @jwt_required
        f = optional
        optional = False
        return decorator(f)
    else:
        # Called with parentheses: @jwt_required() or @jwt_required(optional=True)
        return decorator


def _bootstrap_from_hub():
    """Replace an expired site JWT using the hub cookie, instead of bouncing to login."""
    if (request.path or "").startswith("/api/") or request.path == "/sso/bootstrap":
        return None
    if not get_hub_jwt_from_cookie():
        return None
    from urllib.parse import quote
    nxt = quote((request.full_path or "/").rstrip("?"), safe="")
    resp = redirect(f"/sso/bootstrap?next={nxt}", 302)
    cookie_name = current_app.config.get("JWT_COOKIE_NAME") or "airacoder_jwt"
    resp.delete_cookie(cookie_name, path="/")
    domain = (current_app.config.get("JWT_COOKIE_DOMAIN") or "").strip()
    if domain:
        resp.delete_cookie(cookie_name, path="/", domain=domain)
    return resp


def redirect_to_auth(return_url: str = None):
    """Redirect to central Login UI (cookie bridge)."""
    return_url = return_url or _external_current_url()
    return redirect(_login_redirect_url(return_url)), 302


def require_tenant(f):
    """Decorator: enforce tenant context and set g.user_id, g.customer_id.
    On success calls f(*args, **kwargs); on failure returns 401/redirect like require_tenant_context().
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        ctx = require_tenant_context()
        if not (isinstance(ctx, tuple) and len(ctx) == 2 and isinstance(ctx[0], int) and isinstance(ctx[1], int)):
            return ctx
        user_id, customer_id = ctx
        g.user_id = user_id
        g.customer_id = customer_id
        return f(*args, **kwargs)
    return decorated


def require_permission(permission_code: str):
    """Decorator for permission checking (JWT-based).
    
    For web routes: redirects to Auth Provider on failure.
    For API routes: returns JSON error.
    """
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def decorated_function(*args, **kwargs):
            current_app.logger.info(
                f"[REQUIRE_PERMISSION] Route: {request.path} "
                f"Permission: {permission_code} "
                f"JWT in g: {hasattr(g, 'jwt_payload')}"
            )
            
            ctx = get_context()
            if not ctx:
                current_app.logger.error(
                    f"[REQUIRE_PERMISSION] Context is None for {request.path}. "
                    f"JWT payload: {getattr(g, 'jwt_payload', None)}"
                )
                # Web route: redirect, API route: JSON
                if _wants_json_response():
                    return jsonify({'error': 'Failed to extract request context'}), 401
                return redirect_to_auth()
            
            if not ctx.has_permission(permission_code):
                current_app.logger.warning(
                    f"[REQUIRE_PERMISSION] Permission denied: {permission_code} "
                    f"for user {ctx.user_id} on {request.path}. "
                    f"User permissions: {ctx.permissions}"
                )
                # Web route: redirect, API route: JSON
                if _wants_json_response():
                    return jsonify({'error': 'Insufficient permissions'}), 403
                return redirect_to_auth()
            
            current_app.logger.debug(
                f"[REQUIRE_PERMISSION] Permission granted: {permission_code} for {request.path}"
            )
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_any_permission(*permission_codes: str):
    """Decorator for checking any of multiple permissions (JWT-based)."""
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def decorated_function(*args, **kwargs):
            ctx = get_context()
            if not ctx:
                if _wants_json_response():
                    return jsonify({'error': 'Failed to extract request context'}), 401
                return redirect_to_auth()
            if not ctx.has_any_permission(*permission_codes):
                if _wants_json_response():
                    return jsonify({'error': 'Insufficient permissions'}), 403
                return redirect_to_auth()
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_role(role_name: str):
    """Decorator for role checking (JWT-based)."""
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def decorated_function(*args, **kwargs):
            ctx = get_context()
            if not ctx:
                if _wants_json_response():
                    return jsonify({'error': 'Failed to extract request context'}), 401
                return redirect_to_auth()
            if not ctx.has_role(role_name):
                # Web UX: redirect instead of JSON
                if not _wants_json_response():
                    try:
                        from flask import flash, redirect, url_for
                        flash("You do not have access to this page.", "error")
                        return redirect(url_for("main_web.index")), 302
                    except Exception:
                        pass
                return jsonify({'error': 'Insufficient role'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_any_role(*role_names: str):
    """Decorator for checking any of multiple roles (JWT-based)."""
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def decorated_function(*args, **kwargs):
            ctx = get_context()
            if not ctx:
                if _wants_json_response():
                    return jsonify({'error': 'Failed to extract request context'}), 401
                return redirect_to_auth()
            if not ctx.has_any_role(*role_names):
                try:
                    current_app.logger.warning(
                        "[ROLE_REQUIRED] denied path=%s endpoint=%s allowed=%s role_slug=%r roles=%s",
                        request.path,
                        getattr(request, "endpoint", None),
                        list(role_names),
                        getattr(ctx, "role_slug", None),
                        list(getattr(ctx, "roles", []) or []),
                    )
                except Exception:
                    pass
                # Web UX: redirect instead of JSON
                if not _wants_json_response():
                    try:
                        from flask import flash, redirect, url_for
                        flash("You do not have access to this page.", "error")
                        return redirect(url_for("main_web.index")), 302
                    except Exception:
                        pass
                return jsonify({'error': 'Insufficient role'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def role_required(allowed_roles):
    """Backward-compat: @role_required(['Admin', 'Super Admin']) – JWT roles from Aira Intelligence."""
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    # Product rule: SYSTEM_OWNER is treated as SUPER_ADMIN in Coder.
    # To make this explicit across the app, automatically widen any Super-Admin gate.
    try:
        norm = {
            str(r).strip().lower().replace("-", "_").replace(" ", "_")
            for r in (allowed_roles or [])
            if r is not None and str(r).strip()
        }
        if "super_admin" in norm or "superadmin" in norm or "super_admins" in norm:
            # Keep original role strings, append System Owner variants.
            extra = ["System Owner", "SYSTEM_OWNER", "system_owner", "system owner"]
            seen = set()
            widened = []
            for r in list(allowed_roles) + extra:
                k = (str(r) if r is not None else "").strip()
                if not k:
                    continue
                if k in seen:
                    continue
                seen.add(k)
                widened.append(k)
            allowed_roles = widened
    except Exception:
        pass
    return require_any_role(*allowed_roles)


# ---------------------------------------------------------------------------
# Backward-compat aliases: authorization from Aira Intelligence (JWT), not local session
# Used by app.core.__init__ and many routes that import from app.core.security
# ---------------------------------------------------------------------------

permission_required = require_permission
"""Alias: require JWT + permission from central auth."""


def auth_guard():
    """Route-based auth guard middleware.
    
    - PUBLIC routes: Allow without JWT
    - PROTECTED routes: Check token presence only (JWT validation happens in jwt_required())
    - Workspace root (/): Allow without JWT (dashboard route handles auth via @require_permission)
    
    IMPORTANT: 
    - Never validates JWT (that's jwt_required()'s job)
    - Never raises exceptions, only return redirect or None
    - This runs as a before_request hook
    """
    path = request.path
    
    # Debug logging
    cookie_header = request.headers.get('Cookie', '')
    app_cookie_name = (current_app.config.get('JWT_COOKIE_NAME') or 'airacoder_jwt')
    has_jwt_cookie = (app_cookie_name in cookie_header) or ('aira_jwt' in cookie_header)
    current_app.logger.info(
        f"[AUTH_GUARD] Path={path} "
        f"CookiePresent={bool(cookie_header)} "
        f"HasJWT={has_jwt_cookie}"
    )
    
    # PUBLIC routes: Always allow
    if is_public_route(path):
        return None  # Continue request
    
    # Root route: Allow without JWT (dashboard route handles auth)
    if path == '/':
        current_app.logger.info(f"[AUTH_GUARD] Root (/) - allowing (dashboard route will handle)")
        return None
    
    # PROTECTED routes: Check token presence only
    if is_protected_route(path):
        # TEMPORARY: Skip authentication for agent verification endpoints (testing/monitoring)
        if path.startswith('/api/agent/verify/'):
            current_app.logger.info(f"[AUTH_GUARD] Skipping auth for verification endpoint: {path}")
            return None  # Allow request to proceed
        
        token = get_jwt_from_authorization_header() or get_jwt_from_cookie()
        if not token:
            # If only hub cookie exists, bootstrap to site token instead of re-sending user to login.
            hub_token = get_hub_jwt_from_cookie()
            if hub_token and not path.startswith('/api/') and path != '/sso/bootstrap':
                try:
                    from urllib.parse import quote
                    return redirect(f"/sso/bootstrap?next={quote(request.full_path.rstrip('?'), safe='')}", 302)
                except Exception:
                    return redirect("/sso/bootstrap", 302)
            # No JWT: only /api/* returns JSON; web routes (/dashboard, /admin, etc.) always redirect to login
            if path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect_to_auth()
        
        # Token exists - let jwt_required() handle validation
        # auth_guard does NOT validate JWT
        return None
    
    return None  # Continue request
