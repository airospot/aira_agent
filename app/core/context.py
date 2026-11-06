#!/usr/bin/env python3
"""Request context for JWT-based authentication."""

from dataclasses import dataclass
from typing import List, Optional
from flask import g, request


@dataclass
class RequestContext:
    """Request context extracted from JWT."""
    user_id: int
    customer_id: int
    site_id: int
    site_slug: str
    # New: role slug / primary role (used by some UI/guards)
    role_slug: Optional[str] = None
    email: Optional[str] = None
    roles: List[str] = None
    permissions: List[str] = None
    
    def __post_init__(self):
        """Initialize default values."""
        if self.roles is None:
            self.roles = []
        if self.permissions is None:
            self.permissions = []

        # Normalize roles/permissions so templates can do simple membership checks.
        # Auth Provider may return display roles like "Admin" / "Super Admin".
        def _canon_role(val: str) -> str:
            v = (val or "").strip()
            if not v:
                return ""
            v_up = v.upper().replace("-", "_").replace(" ", "_")
            aliases = {
                "SUPERADMIN": "SUPER_ADMIN",
                "SYSTEM_OWNER": "SUPER_ADMIN",
                "SYSTEMOWNER": "SUPER_ADMIN",
            }
            return aliases.get(v_up, v_up)

        norm_roles: list[str] = []
        for r in (self.roles or []):
            cr = _canon_role(str(r))
            if cr:
                norm_roles.append(cr)

        if self.role_slug:
            cr = _canon_role(str(self.role_slug))
            if cr:
                norm_roles.append(cr)

        # unique, preserve order
        seen = set()
        self.roles = [r for r in norm_roles if not (r in seen or seen.add(r))]

        # permissions: normalize to lowercase codes
        norm_perms: list[str] = []
        for p in (self.permissions or []):
            s = (str(p) if p is not None else "").strip()
            if s:
                norm_perms.append(s.lower())
        seen_p = set()
        self.permissions = [p for p in norm_perms if not (p in seen_p or seen_p.add(p))]
    
    def has_permission(self, permission_code: str) -> bool:
        """Check if user has permission."""
        # Super Admin implicitly has all permissions
        if "SUPER_ADMIN" in (self.roles or []):
            return True
        return (permission_code or "").strip().lower() in (self.permissions or [])
    
    def has_role(self, role_name: str) -> bool:
        """Check if user has role."""
        def _norm(val: str) -> str:
            v = (val or "").strip()
            if not v:
                return ""
            v_low = v.lower()
            # Display names (TR/EN) → canonical slugs
            aliases = {
                # --- Super Admin ---
                "super admin": "super_admin",
                "super_admin": "super_admin",
                "superadmin": "super_admin",
                "super administrator": "super_admin",
                "superadministrator": "super_admin",
                # --- Admin ---
                "admin": "admin",
                "administrator": "admin",
                # --- System Owner ---
                "system owner": "super_admin",
                "system_owner": "super_admin",
            }
            if v_low in aliases:
                return aliases[v_low]
            return v_low.replace("-", "_").replace(" ", "_")

        want = _norm(role_name)
        if not want:
            return False

        # Prefer roles list; fall back to role_slug if roles missing
        role_values = list(self.roles or [])
        if self.role_slug:
            role_values.append(self.role_slug)

        have = {_norm(r) for r in role_values if r}
        return want in have
    
    def has_any_permission(self, *permission_codes: str) -> bool:
        """Check if user has any of the given permissions."""
        return any(self.has_permission(p) for p in permission_codes)
    
    def has_any_role(self, *role_names: str) -> bool:
        """Check if user has any of the given roles."""
        return any(self.has_role(r) for r in role_names)


def get_request_context() -> Optional[RequestContext]:
    """Extract request context from JWT."""
    from flask import g, current_app, request
    from app.core.security import is_public_route
    
    # Skip context extraction for public routes (static files, health checks, etc.)
    if is_public_route(request.path):
        return None
    
    try:
        jwt_data = getattr(g, 'jwt_payload', None)

        if not jwt_data:
            # Only log ERROR for non-public requests
            current_app.logger.error("[CONTEXT] g.jwt_payload is None")
            return None

        # Extract values first (before validation)
        user_id_val = jwt_data.get('user_id') or jwt_data.get('sub')
        customer_id_val = jwt_data.get('customer_id')
        site_id_val = jwt_data.get('site_id')
        site_slug_val = jwt_data.get('site_slug')
        # role_slug may arrive as user_role (new claim) or role_slug; keep both for compatibility
        role_slug_val = jwt_data.get('role_slug') or jwt_data.get('user_role')
        
        current_app.logger.info(
            f"[CONTEXT] Extracting values from JWT: "
            f"user_id={jwt_data.get('user_id')} sub={jwt_data.get('sub')} user_id_val={user_id_val} "
            f"customer_id={customer_id_val} (type: {type(customer_id_val).__name__}), "
            f"site_id={site_id_val} (type: {type(site_id_val).__name__}), "
            f"site_slug={site_slug_val} (type: {type(site_slug_val).__name__}), "
            f"role_slug={role_slug_val} (type: {type(role_slug_val).__name__})"
        )
        
        # Validation: user_id OR sub must exist and be non-empty
        if not user_id_val:
            current_app.logger.error(
                "[CONTEXT] Missing user_id/sub: user_id=%s sub=%s | payload keys=%s",
                jwt_data.get('user_id'),
                jwt_data.get('sub'),
                list(jwt_data.keys())
            )
            return None
        
        # Validation: customer_id must exist and be non-empty
        if customer_id_val is None or customer_id_val == '':
            current_app.logger.error(
                "[CONTEXT] Missing or empty customer_id: value=%s (type: %s) | payload keys=%s",
                customer_id_val,
                type(customer_id_val).__name__,
                list(jwt_data.keys())
            )
            return None
        
        # Validation: site_id must exist and be non-empty
        if site_id_val is None or site_id_val == '':
            current_app.logger.error(
                "[CONTEXT] Missing or empty site_id: value=%s (type: %s) | payload keys=%s",
                site_id_val,
                type(site_id_val).__name__,
                list(jwt_data.keys())
            )
            return None
        
        # Validation: site_slug must exist and be non-empty
        if not site_slug_val or site_slug_val == '':
            current_app.logger.error(
                "[CONTEXT] Missing or empty site_slug: value=%s (type: %s) | payload keys=%s",
                site_slug_val,
                type(site_slug_val).__name__,
                list(jwt_data.keys())
            )
            return None
        
        # Type conversion with explicit error handling
        try:
            user_id_int = int(user_id_val)
        except (ValueError, TypeError) as e:
            current_app.logger.error(
                "[CONTEXT] Cannot convert user_id to int: value=%s (type: %s) error=%s",
                user_id_val,
                type(user_id_val).__name__,
                str(e)
            )
            return None
        
        try:
            customer_id_int = int(customer_id_val)
        except (ValueError, TypeError) as e:
            current_app.logger.error(
                "[CONTEXT] Cannot convert customer_id to int: value=%s (type: %s) error=%s",
                customer_id_val,
                type(customer_id_val).__name__,
                str(e)
            )
            return None
        
        try:
            site_id_int = int(site_id_val)
        except (ValueError, TypeError) as e:
            current_app.logger.error(
                "[CONTEXT] Cannot convert site_id to int: value=%s (type: %s) error=%s",
                site_id_val,
                type(site_id_val).__name__,
                str(e)
            )
            return None
        
        roles_list = list(jwt_data.get('roles', []) or [])
        permissions_list = list(jwt_data.get('permissions', []) or [])
        # Ensure primary role is present in roles list for decorators (JWTs sometimes only set user_role)
        if role_slug_val is not None and role_slug_val != '':
            roles_list.append(role_slug_val)

        # If JWT has no role info, fetch from Auth Provider so @role_required works (e.g. Admin/Super Admin).
        # Some tokens omit role claims; Auth Provider RBAC endpoint is source of truth.
        if not roles_list or (not role_slug_val and not any(r for r in roles_list if (r or "").strip())):
            import requests
            from app.core.security import get_jwt_from_authorization_header, get_jwt_from_cookie

            token = get_jwt_from_authorization_header() or get_jwt_from_cookie()
            # Prefer app's configured slug (aira_intelligence). Hub tokens may carry site_slug=aira_intelligence.
            jwt_slug = (site_slug_val or "").strip()
            config_slug = (current_app.config.get("AUTH_SITE_SLUG") or "").strip()
            preferred_slug = config_slug or "airacoder"

            if token and (preferred_slug or jwt_slug):
                base = current_app.config.get("AUTH_PROVIDER_URL", "https://auth.airaintelligence.ai").rstrip("/")
                verify_ssl = current_app.config.get("AUTH_VERIFY_SSL", True)
                using_slug = preferred_slug or jwt_slug
                url = f"{base}/auth/me/sites/{using_slug}/roles"
                current_app.logger.info(
                    "[AUTH_SITE] context.get_request_context: AUTH_SITE_SLUG(config)=%r JWT_site_slug=%r using_slug=%r URL=%s",
                    config_slug or "(empty)",
                    jwt_slug or "(empty)",
                    using_slug or "(empty)",
                    url,
                )
                try:
                    r = requests.get(
                        url,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-Site-Slug": using_slug,
                        },
                        timeout=5,
                        verify=verify_ssl,
                    )
                    if r.status_code != 200 and jwt_slug and using_slug != jwt_slug:
                        # Fallback: try JWT slug if preferred slug fails (defensive)
                        url2 = f"{base}/auth/me/sites/{jwt_slug}/roles"
                        current_app.logger.info(
                            "[AUTH_SITE] context.get_request_context fallback: preferred=%r status=%s trying_jwt_slug=%r URL=%s",
                            using_slug,
                            r.status_code,
                            jwt_slug,
                            url2,
                        )
                        r = requests.get(
                            url2,
                            headers={
                                "Authorization": f"Bearer {token}",
                                "X-Site-Slug": jwt_slug,
                            },
                            timeout=5,
                            verify=verify_ssl,
                        )
                    ct = (r.headers.get("Content-Type") or "")
                    data: dict = {}
                    if ct.startswith("application/json"):
                        try:
                            data = r.json() or {}
                        except Exception:
                            data = {}

                    # Some deployments wrap payload under {"data": {...}}
                    payload = data.get("data") if isinstance(data.get("data"), dict) else data

                    # Extract role(s) from multiple possible shapes
                    provider_role = (
                        payload.get("user_role")
                        or payload.get("role_slug")
                        or payload.get("role")
                        or (payload.get("user") or {}).get("user_role")
                        or (payload.get("user") or {}).get("role_slug")
                    )
                    provider_roles_raw = payload.get("roles") or payload.get("site_roles") or payload.get("user_roles") or []
                    provider_roles: list[str] = []
                    if isinstance(provider_roles_raw, str):
                        provider_roles = [provider_roles_raw]
                    elif isinstance(provider_roles_raw, list):
                        for it in provider_roles_raw:
                            if isinstance(it, str):
                                provider_roles.append(it)
                            elif isinstance(it, dict):
                                rs = (it.get("role_slug") or it.get("slug") or it.get("name") or "").strip()
                                if rs:
                                    provider_roles.append(rs)

                    if provider_role and provider_role not in roles_list:
                        roles_list.append(provider_role)
                        role_slug_val = role_slug_val or provider_role
                    for pr in provider_roles:
                        if pr and pr not in roles_list:
                            roles_list.append(pr)

                    if (provider_roles or provider_role) and not permissions_list:
                        perms_raw = payload.get("permissions") or payload.get("perms") or []
                        if isinstance(perms_raw, list):
                            permissions_list = [p for p in perms_raw if isinstance(p, str)]

                    current_app.logger.info(
                        "[CONTEXT] RBAC fetch: slug=%s status=%s role=%r roles=%s keys=%s",
                        (preferred_slug or jwt_slug),
                        r.status_code,
                        provider_role,
                        roles_list,
                        sorted(list(payload.keys()))[:30] if isinstance(payload, dict) else [],
                    )

                    # If status OK but roles still empty, log payload for diagnostics (contains no PII beyond ids)
                    if r.status_code == 200 and not roles_list:
                        current_app.logger.info(
                            "[CONTEXT] RBAC payload (empty roles): slug=%s payload=%s",
                            (preferred_slug or jwt_slug),
                            payload,
                        )
                except Exception as e:
                    current_app.logger.debug("[CONTEXT] Auth Provider roles fetch failed for preferred=%s jwt=%s: %s", preferred_slug, jwt_slug, e)

        # Last resort: If roles are still empty, fall back to session-provided role/site_roles.
        # This preserves UX when JWT omits roles and RBAC endpoint returns empty roles for a valid token.
        if not roles_list:
            try:
                from flask import session as flask_session

                sess_user = flask_session.get("user") or {}
                sess_role = (sess_user.get("role") or "").strip()
                sess_site_roles = flask_session.get("site_roles") or []

                if sess_role:
                    roles_list.append(sess_role)
                    role_slug_val = role_slug_val or sess_role
                # Also append any stored site_roles (usually slugs)
                if isinstance(sess_site_roles, list):
                    for sr in sess_site_roles:
                        if isinstance(sr, str) and sr.strip() and sr.strip() not in roles_list:
                            roles_list.append(sr.strip())

                if roles_list:
                    current_app.logger.info(
                        "[CONTEXT] Filled roles from session fallback: role_slug=%r roles=%s",
                        role_slug_val,
                        roles_list,
                    )
            except Exception as e:
                current_app.logger.debug("[CONTEXT] Session roles fallback failed: %s", e)

        # Extra fallback: Some Auth Provider deployments expose role on /auth/me (not site-scoped).
        if not roles_list:
            try:
                import requests
                from app.core.security import get_jwt_from_authorization_header, get_jwt_from_cookie

                token = get_jwt_from_authorization_header() or get_jwt_from_cookie()
                if token:
                    base = current_app.config.get("AUTH_PROVIDER_URL", "https://auth.airaintelligence.ai").rstrip("/")
                    verify_ssl = current_app.config.get("AUTH_VERIFY_SSL", True)
                    jwt_slug = (site_slug_val or "").strip()
                    config_slug = (current_app.config.get("AUTH_SITE_SLUG") or "").strip()
                    hdr_slug = jwt_slug or config_slug
                    for path in ("/auth/me", "/me", "/auth/me/profile"):
                        url = f"{base}{path}"
                        r = requests.get(
                            url,
                            headers={
                                "Authorization": f"Bearer {token}",
                                **({"X-Site-Slug": hdr_slug} if hdr_slug else {}),
                            },
                            timeout=5,
                            verify=verify_ssl,
                        )
                        ct = (r.headers.get("Content-Type") or "")
                        data = {}
                        if ct.startswith("application/json"):
                            try:
                                data = r.json() or {}
                            except Exception:
                                data = {}
                        payload = data.get("data") if isinstance(data.get("data"), dict) else data
                        role_val = (
                            (payload.get("user_role") if isinstance(payload, dict) else None)
                            or (payload.get("role_slug") if isinstance(payload, dict) else None)
                            or (payload.get("role") if isinstance(payload, dict) else None)
                            or ((payload.get("user") or {}).get("user_role") if isinstance(payload, dict) else None)
                            or ((payload.get("user") or {}).get("role_slug") if isinstance(payload, dict) else None)
                        )
                        roles_raw = payload.get("roles") if isinstance(payload, dict) else []
                        if role_val and role_val not in roles_list:
                            roles_list.append(role_val)
                            role_slug_val = role_slug_val or str(role_val)
                        if isinstance(roles_raw, list):
                            for it in roles_raw:
                                if isinstance(it, str) and it.strip() and it.strip() not in roles_list:
                                    roles_list.append(it.strip())
                        current_app.logger.info(
                            "[CONTEXT] /me fallback: path=%s status=%s role=%r roles=%s keys=%s",
                            path,
                            r.status_code,
                            role_val,
                            roles_list,
                            sorted(list(payload.keys()))[:30] if isinstance(payload, dict) else [],
                        )
                        if roles_list:
                            break
            except Exception as e:
                current_app.logger.debug("[CONTEXT] /me fallback failed: %s", e)

        ctx = RequestContext(
            user_id=user_id_int,
            customer_id=customer_id_int,
            site_id=site_id_int,
            site_slug=str(site_slug_val),  # Ensure string type
            role_slug=str(role_slug_val) if role_slug_val is not None and role_slug_val != '' else None,
            email=jwt_data.get('email'),
            roles=roles_list,
            permissions=permissions_list,
        )
        
        current_app.logger.info(
            f"[CONTEXT] Successfully created context: "
            f"user_id={ctx.user_id}, customer_id={ctx.customer_id}, "
            f"site_id={ctx.site_id}, site_slug='{ctx.site_slug}' "
            f"(type: {type(ctx.site_slug).__name__}), "
            f"role_slug={ctx.role_slug} "
            f"roles={len(ctx.roles)} {ctx.roles}, permissions={len(ctx.permissions)} {ctx.permissions}"
        )
        
        return ctx
    except Exception:
        current_app.logger.exception("[CONTEXT] Fatal error")
        return None


def get_context() -> Optional[RequestContext]:
    """Get request context from Flask g or extract from JWT."""
    if not hasattr(g, 'request_context'):
        g.request_context = get_request_context()
    return g.request_context


def get_customer_id_from_request() -> Optional[int]:
    """Customer ID from RequestContext (JWT-based)."""
    ctx = get_context()
    if not ctx or getattr(ctx, "customer_id", None) is None:
        return None
    try:
        return int(ctx.customer_id)
    except (TypeError, ValueError):
        return None


def get_user_id_from_request() -> Optional[int]:
    """User ID from RequestContext (JWT-based)."""
    ctx = get_context()
    if not ctx or getattr(ctx, "user_id", None) is None:
        return None
    try:
        return int(ctx.user_id)
    except (TypeError, ValueError):
        return None

