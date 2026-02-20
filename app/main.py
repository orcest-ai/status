"""
Orcest AI Status Monitor — FastAPI application with SSO authentication.

Monitors health and availability of all Orcest AI ecosystem services.
Requires SSO login via login.orcest.ai for dashboard access.
"""

import os
import time
import asyncio
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SSO_ISSUER = os.getenv("SSO_ISSUER", "https://login.orcest.ai")
SSO_CLIENT_ID = os.getenv("SSO_CLIENT_ID", "status")
SSO_CLIENT_SECRET = os.getenv("SSO_CLIENT_SECRET", "")
SSO_CALLBACK_URL = os.getenv("SSO_CALLBACK_URL", "https://status.orcest.ai/auth/callback")

VERSION = "1.0.0"
HEALTH_CHECK_TIMEOUT = 10  # seconds per service
CACHE_TTL = 30  # seconds

# ---------------------------------------------------------------------------
# Service Registry
# ---------------------------------------------------------------------------

SERVICES = [
    {
        "name": "Orcest AI",
        "url": "https://orcest.ai",
        "health": "https://orcest.ai/health",
        "type": "web",
        "description": "Landing page & API gateway",
    },
    {
        "name": "RainyModel",
        "url": "https://rm.orcest.ai",
        "health": "https://rm.orcest.ai/health",
        "type": "api",
        "description": "LLM routing proxy",
    },
    {
        "name": "Lamino LLM",
        "url": "https://llm.orcest.ai",
        "health": "https://llm.orcest.ai/api/health",
        "type": "api",
        "description": "AI chat with RAG & workspace",
    },
    {
        "name": "Maestrist",
        "url": "https://agent.orcest.ai",
        "health": "https://agent.orcest.ai/health",
        "type": "web",
        "description": "AI-driven software development agent",
    },
    {
        "name": "Orcide",
        "url": "https://ide.orcest.ai",
        "health": "https://ide.orcest.ai",
        "type": "web",
        "description": "AI-powered code editor",
    },
    {
        "name": "Login SSO",
        "url": "https://login.orcest.ai",
        "health": "https://login.orcest.ai/health",
        "type": "api",
        "description": "OIDC identity provider",
    },
    {
        "name": "Ollama Free API",
        "url": "https://ollamafreeapi.orcest.ai",
        "health": "https://ollamafreeapi.orcest.ai/health",
        "type": "api",
        "description": "Free Ollama-compatible API",
    },
]

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_status_cache: dict = {}
_cache_ts: float = 0.0

# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Orcest AI Status Monitor",
    version=VERSION,
    docs_url=None,
    redoc_url=None,
)

# ---------------------------------------------------------------------------
# SSO Helpers
# ---------------------------------------------------------------------------


async def _verify_token(token: str) -> Optional[dict]:
    """Verify an SSO access token by calling the SSO issuer's verify endpoint.

    Returns the decoded user payload on success, or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SSO_ISSUER}/api/token/verify",
                json={"token": token},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


async def _exchange_code(code: str) -> Optional[dict]:
    """Exchange an authorization code for tokens via the SSO token endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SSO_ISSUER}/api/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": SSO_CALLBACK_URL,
                    "client_id": SSO_CLIENT_ID,
                    "client_secret": SSO_CLIENT_SECRET,
                },
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


def _get_token(request: Request) -> Optional[str]:
    """Extract the SSO token from the request cookies or Authorization header."""
    token = request.cookies.get("sso_token")
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _build_login_url() -> str:
    """Build the SSO authorization URL to redirect unauthenticated users."""
    return (
        f"{SSO_ISSUER}/authorize"
        f"?response_type=code"
        f"&client_id={SSO_CLIENT_ID}"
        f"&redirect_uri={SSO_CALLBACK_URL}"
        f"&scope=openid+profile+email"
    )


# ---------------------------------------------------------------------------
# SSO Middleware
# ---------------------------------------------------------------------------

# Paths that do not require authentication.
_PUBLIC_PREFIXES = ("/health", "/auth/")


@app.middleware("http")
async def sso_middleware(request: Request, call_next):
    path = request.url.path

    # Allow public paths through without authentication.
    for prefix in _PUBLIC_PREFIXES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return await call_next(request)

    # Require a valid SSO token for everything else.
    token = _get_token(request)
    if not token:
        return RedirectResponse(url=_build_login_url())

    user = await _verify_token(token)
    if not user:
        return RedirectResponse(url=_build_login_url())

    # Attach user info to the request state so handlers can use it.
    request.state.user = user
    return await call_next(request)


# ---------------------------------------------------------------------------
# Health Checking Logic
# ---------------------------------------------------------------------------


async def _check_service(service: dict) -> dict:
    """Check a single service's health endpoint and return a status dict."""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
            resp = await client.get(service["health"])
            latency = round((time.monotonic() - start) * 1000)
            if resp.status_code < 400:
                status = "operational"
            else:
                status = "degraded"
    except httpx.TimeoutException:
        latency = round((time.monotonic() - start) * 1000)
        status = "timeout"
    except Exception:
        latency = round((time.monotonic() - start) * 1000)
        status = "down"

    return {
        "name": service["name"],
        "url": service["url"],
        "type": service["type"],
        "description": service["description"],
        "status": status,
        "latency_ms": latency,
    }


async def check_all_services() -> list[dict]:
    """Check every registered service in parallel, with a TTL cache."""
    global _status_cache, _cache_ts

    now = time.monotonic()
    if _status_cache and (now - _cache_ts) < CACHE_TTL:
        return _status_cache  # type: ignore[return-value]

    results = await asyncio.gather(*[_check_service(s) for s in SERVICES])
    _status_cache = list(results)
    _cache_ts = now
    return _status_cache


# ---------------------------------------------------------------------------
# Public Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Public health check — no authentication required."""
    return {"status": "healthy", "version": VERSION}


# ---------------------------------------------------------------------------
# Auth Endpoints
# ---------------------------------------------------------------------------


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = ""):
    """OAuth2 callback — exchanges the authorization code for tokens."""
    if not code:
        return RedirectResponse(url=_build_login_url())

    token_data = await _exchange_code(code)
    if not token_data or "access_token" not in token_data:
        return RedirectResponse(url=_build_login_url())

    response = RedirectResponse(url="/")
    response.set_cookie(
        key="sso_token",
        value=token_data["access_token"],
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=token_data.get("expires_in", 3600),
    )
    return response


@app.get("/auth/logout")
async def auth_logout():
    """Clear the SSO cookie and redirect to the SSO issuer's logout page."""
    response = RedirectResponse(url=f"{SSO_ISSUER}/logout?redirect_uri={SSO_CALLBACK_URL}")
    response.delete_cookie("sso_token")
    return response


# ---------------------------------------------------------------------------
# Protected API Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/me")
async def api_me(request: Request):
    """Return the current authenticated user's profile."""
    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    return user


@app.get("/api/status")
async def api_status(request: Request):
    """Return JSON status of all monitored services (requires SSO)."""
    services = await check_all_services()
    all_operational = all(s["status"] == "operational" for s in services)
    return {
        "overall": "operational" if all_operational else "degraded",
        "services": services,
    }


# ---------------------------------------------------------------------------
# Main Status Page (Farsi UI)
# ---------------------------------------------------------------------------

_STATUS_LABELS = {
    "operational": "\u0641\u0639\u0627\u0644",
    "degraded": "\u0646\u0627\u067e\u0627\u06cc\u062f\u0627\u0631",
    "timeout": "\u062a\u0627\u06cc\u0645\u200c\u0627\u0648\u062a",
    "down": "\u0642\u0637\u0639",
}

_STATUS_COLORS = {
    "operational": "#22c55e",
    "degraded": "#eab308",
    "timeout": "#f97316",
    "down": "#ef4444",
}


@app.get("/", response_class=HTMLResponse)
async def status_page(request: Request):
    """Render the main status dashboard in Farsi (requires SSO)."""
    user = getattr(request.state, "user", {})
    user_name = user.get("name") or user.get("preferred_username") or user.get("email", "\u06a9\u0627\u0631\u0628\u0631")
    user_role = user.get("role", "\u06a9\u0627\u0631\u0628\u0631")

    services = await check_all_services()
    all_operational = all(s["status"] == "operational" for s in services)
    overall_label = "\u0647\u0645\u0647 \u0633\u0631\u0648\u06cc\u0633\u200c\u0647\u0627 \u0641\u0639\u0627\u0644 \u0647\u0633\u062a\u0646\u062f" if all_operational else "\u0628\u0631\u062e\u06cc \u0633\u0631\u0648\u06cc\u0633\u200c\u0647\u0627 \u062f\u0686\u0627\u0631 \u0645\u0634\u06a9\u0644 \u0647\u0633\u062a\u0646\u062f"
    overall_color = "#22c55e" if all_operational else "#eab308"

    rows = ""
    for svc in services:
        status_label = _STATUS_LABELS.get(svc["status"], svc["status"])
        status_color = _STATUS_COLORS.get(svc["status"], "#888")
        rows += f"""
        <tr>
            <td style="font-weight:600;">{svc["name"]}</td>
            <td style="color:#94a3b8;">{svc["description"]}</td>
            <td>
                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{status_color};margin-left:6px;"></span>
                <span style="color:{status_color};">{status_label}</span>
            </td>
            <td style="color:#94a3b8;">{svc["latency_ms"]} ms</td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="60">
    <title>Orcest AI Status Monitor</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: Tahoma, 'Segoe UI', sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            min-height: 100vh;
            padding: 2rem;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            flex-wrap: wrap;
            gap: 1rem;
        }}
        header h1 {{ font-size: 1.5rem; color: #f8fafc; }}
        .user-info {{
            display: flex;
            align-items: center;
            gap: 1rem;
            font-size: 0.9rem;
            color: #94a3b8;
        }}
        .user-info a {{
            color: #f87171;
            text-decoration: none;
            font-size: 0.85rem;
        }}
        .user-info a:hover {{ text-decoration: underline; }}
        .overall {{
            text-align: center;
            padding: 1.5rem;
            margin-bottom: 2rem;
            border-radius: 12px;
            background: #1e293b;
            border: 1px solid #334155;
        }}
        .overall h2 {{ font-size: 1.25rem; color: {overall_color}; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #1e293b;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid #334155;
        }}
        th, td {{
            padding: 0.85rem 1rem;
            text-align: right;
        }}
        th {{
            background: #334155;
            font-weight: 600;
            color: #cbd5e1;
            font-size: 0.85rem;
        }}
        tr:not(:last-child) td {{ border-bottom: 1px solid #334155; }}
        footer {{
            text-align: center;
            margin-top: 2rem;
            font-size: 0.8rem;
            color: #475569;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Orcest AI Status Monitor</h1>
            <div class="user-info">
                <span>\u062e\u0648\u0634 \u0622\u0645\u062f\u06cc\u062f\u060c {user_name} ({user_role})</span>
                <a href="/auth/logout">\u062e\u0631\u0648\u062c</a>
            </div>
        </header>

        <div class="overall">
            <h2>{overall_label}</h2>
        </div>

        <table>
            <thead>
                <tr>
                    <th>\u0633\u0631\u0648\u06cc\u0633</th>
                    <th>\u062a\u0648\u0636\u06cc\u062d\u0627\u062a</th>
                    <th>\u0648\u0636\u0639\u06cc\u062a</th>
                    <th>\u062a\u0623\u062e\u06cc\u0631</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>

        <footer>
            <p>\u0627\u06cc\u0646 \u0635\u0641\u062d\u0647 \u0647\u0631 \u06f6\u06f0 \u062b\u0627\u0646\u06cc\u0647 \u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc \u0645\u06cc\u200c\u0634\u0648\u062f. &mdash; Orcest AI v{VERSION}</p>
        </footer>
    </div>
</body>
</html>"""

    return HTMLResponse(content=html)
