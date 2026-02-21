"""
Orcest AI Status Monitor — FastAPI application with SSO authentication.

Monitors health and availability of all Orcest AI ecosystem services.
Requires SSO login via login.orcest.ai for dashboard access.
"""

import os
import time
import asyncio
from datetime import datetime, timezone
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

VERSION = "2.0.0"
HEALTH_CHECK_TIMEOUT = 10  # seconds per service
CACHE_TTL = 30  # seconds

# ---------------------------------------------------------------------------
# Service Registry — grouped by category
# ---------------------------------------------------------------------------

SERVICES = [
    # --- Core Platform ---
    {
        "name": "Orcest AI",
        "url": "https://orcest.ai",
        "health": "https://orcest.ai/health",
        "type": "web",
        "category": "core",
        "description": "صفحه اصلی و دروازه API — جستجو، استخراج و تحقیق",
        "description_en": "Landing page & API gateway — search, extraction & research",
    },
    {
        "name": "Login SSO",
        "url": "https://login.orcest.ai",
        "health": "https://login.orcest.ai/health",
        "type": "api",
        "category": "core",
        "description": "احراز هویت یکپارچه — OIDC/OAuth2 برای تمام سرویس‌ها",
        "description_en": "Single Sign-On — OIDC/OAuth2 identity provider",
    },
    # --- AI & LLM ---
    {
        "name": "RainyModel",
        "url": "https://rm.orcest.ai",
        "health": "https://rm.orcest.ai/health",
        "type": "api",
        "category": "ai",
        "description": "پراکسی هوشمند LLM — مسیریابی خودکار FREE → INTERNAL → PREMIUM",
        "description_en": "Smart LLM proxy — auto-routing FREE → INTERNAL → PREMIUM",
    },
    {
        "name": "Lamino",
        "url": "https://llm.orcest.ai",
        "health": "https://llm.orcest.ai/api/health",
        "type": "web",
        "category": "ai",
        "description": "فضای کاری هوشمند — چت، RAG، عامل‌ها، MCP و مدیریت اسناد",
        "description_en": "Intelligent workspace — chat, RAG, agents, MCP & document management",
    },
    {
        "name": "Maestrist",
        "url": "https://agent.orcest.ai",
        "health": "https://agent.orcest.ai/health",
        "type": "web",
        "category": "ai",
        "description": "عامل توسعه نرم‌افزار — CodeAct، مرور وب و اجرای کد خودکار",
        "description_en": "Software dev agent — CodeAct, browsing & autonomous code execution",
    },
    # --- Developer Tools ---
    {
        "name": "Orcide",
        "url": "https://ide.orcest.ai",
        "health": "https://ide.orcest.ai",
        "type": "web",
        "category": "dev",
        "description": "ویرایشگر کد ابری — تکمیل هوشمند کد و چت AI یکپارچه",
        "description_en": "Cloud IDE — AI code completion & integrated chat",
    },
    {
        "name": "Ollama Free API",
        "url": "https://ollamafreeapi.orcest.ai",
        "health": "https://ollamafreeapi.orcest.ai/health",
        "type": "api",
        "category": "dev",
        "description": "دسترسی رایگان به +۶۵۰ مدل — LLaMA، Mistral، DeepSeek، Qwen",
        "description_en": "Free access to 650+ models — LLaMA, Mistral, DeepSeek, Qwen",
    },
]

# Category labels (Farsi)
_CATEGORY_LABELS = {
    "core": "زیرساخت اصلی",
    "ai": "هوش مصنوعی و LLM",
    "dev": "ابزار توسعه‌دهنده",
}

_CATEGORY_ICONS = {
    "core": "&#9881;",   # gear
    "ai": "&#9733;",     # star
    "dev": "&#9000;",    # keyboard
}

# ---------------------------------------------------------------------------
# In-memory cache & uptime history
# ---------------------------------------------------------------------------

_status_cache: dict = {}
_cache_ts: float = 0.0

# Simple uptime tracking: {service_name: {"checks": int, "up": int}}
_uptime_counters: dict[str, dict[str, int]] = {}

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
    """Verify an SSO access token by calling the SSO issuer's verify endpoint."""
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

_PUBLIC_PREFIXES = ("/health", "/auth/")


@app.middleware("http")
async def sso_middleware(request: Request, call_next):
    path = request.url.path
    for prefix in _PUBLIC_PREFIXES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return await call_next(request)

    token = _get_token(request)
    if not token:
        return RedirectResponse(url=_build_login_url())

    user = await _verify_token(token)
    if not user:
        return RedirectResponse(url=_build_login_url())

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

    # Update uptime counters
    name = service["name"]
    if name not in _uptime_counters:
        _uptime_counters[name] = {"checks": 0, "up": 0}
    _uptime_counters[name]["checks"] += 1
    if status == "operational":
        _uptime_counters[name]["up"] += 1

    return {
        "name": name,
        "url": service["url"],
        "type": service["type"],
        "category": service.get("category", "core"),
        "description": service["description"],
        "description_en": service.get("description_en", ""),
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


def _get_uptime_pct(name: str) -> str:
    """Return uptime percentage for a service since process start."""
    c = _uptime_counters.get(name)
    if not c or c["checks"] == 0:
        return "—"
    pct = (c["up"] / c["checks"]) * 100
    return f"{pct:.1f}%"


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
        "version": VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Main Status Page (Farsi UI — Enhanced v2)
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

_TYPE_BADGES = {
    "web": ("وب", "#3b82f6"),
    "api": ("API", "#8b5cf6"),
    "internal": ("داخلی", "#6b7280"),
}


@app.get("/", response_class=HTMLResponse)
async def status_page(request: Request):
    """Render the main status dashboard in Farsi (requires SSO)."""
    user = getattr(request.state, "user", {})
    user_name = user.get("name") or user.get("preferred_username") or user.get("email", "\u06a9\u0627\u0631\u0628\u0631")
    user_role = user.get("role", "\u06a9\u0627\u0631\u0628\u0631")

    services = await check_all_services()
    all_operational = all(s["status"] == "operational" for s in services)
    op_count = sum(1 for s in services if s["status"] == "operational")
    total_count = len(services)

    overall_label = "\u0647\u0645\u0647 \u0633\u0631\u0648\u06cc\u0633\u200c\u0647\u0627 \u0641\u0639\u0627\u0644 \u0647\u0633\u062a\u0646\u062f" if all_operational else f"{op_count} \u0627\u0632 {total_count} \u0633\u0631\u0648\u06cc\u0633 \u0641\u0639\u0627\u0644"
    overall_color = "#22c55e" if all_operational else "#eab308"
    overall_bg = "rgba(34,197,94,0.08)" if all_operational else "rgba(234,179,8,0.08)"

    # Group services by category
    categories = {}
    for svc in services:
        cat = svc.get("category", "core")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(svc)

    # Build category sections
    sections_html = ""
    cat_order = ["core", "ai", "dev"]
    for cat in cat_order:
        if cat not in categories:
            continue
        cat_label = _CATEGORY_LABELS.get(cat, cat)
        cat_icon = _CATEGORY_ICONS.get(cat, "")

        rows = ""
        for svc in categories[cat]:
            status_label = _STATUS_LABELS.get(svc["status"], svc["status"])
            status_color = _STATUS_COLORS.get(svc["status"], "#888")
            type_label, type_color = _TYPE_BADGES.get(svc["type"], ("?", "#888"))
            uptime = _get_uptime_pct(svc["name"])
            latency_color = "#22c55e" if svc["latency_ms"] < 500 else "#eab308" if svc["latency_ms"] < 2000 else "#f97316"

            rows += f"""
            <div class="svc-card">
                <div class="svc-header">
                    <div class="svc-name-row">
                        <span class="svc-dot" style="background:{status_color};"></span>
                        <a href="{svc['url']}" target="_blank" class="svc-name">{svc['name']}</a>
                        <span class="svc-type" style="background:{type_color}20;color:{type_color};">{type_label}</span>
                    </div>
                    <span class="svc-status" style="color:{status_color};">{status_label}</span>
                </div>
                <div class="svc-desc">{svc['description']}</div>
                <div class="svc-metrics">
                    <span class="svc-metric"><span class="metric-label">\u062a\u0623\u062e\u06cc\u0631</span> <span style="color:{latency_color};">{svc['latency_ms']} ms</span></span>
                    <span class="svc-metric"><span class="metric-label">\u0622\u067e\u062a\u0627\u06cc\u0645</span> <span>{uptime}</span></span>
                </div>
            </div>
            """

        sections_html += f"""
        <div class="category-section">
            <h3 class="category-title">{cat_icon} {cat_label}</h3>
            <div class="svc-grid">
                {rows}
            </div>
        </div>
        """

    # Summary stats
    avg_latency = round(sum(s["latency_ms"] for s in services) / len(services)) if services else 0
    down_count = sum(1 for s in services if s["status"] in ("down", "timeout"))
    checked_at = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    html = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="60">
    <title>Orcest AI — \u0648\u0636\u0639\u06cc\u062a \u0633\u0631\u0648\u06cc\u0633\u200c\u0647\u0627</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: Tahoma, 'Segoe UI', sans-serif;
            background: #0a0f1e;
            color: #e2e8f0;
            min-height: 100vh;
        }}
        .top-bar {{
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border-bottom: 1px solid #1e293b;
            padding: 0.75rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .top-bar .logo {{
            font-size: 1.1rem;
            font-weight: 700;
            color: #f8fafc;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .top-bar .logo span {{ color: #818cf8; }}
        .user-info {{
            display: flex;
            align-items: center;
            gap: 1rem;
            font-size: 0.85rem;
            color: #94a3b8;
        }}
        .user-info a {{
            color: #f87171;
            text-decoration: none;
            font-size: 0.8rem;
            padding: 0.25rem 0.6rem;
            border: 1px solid #f8717133;
            border-radius: 6px;
            transition: all 0.2s;
        }}
        .user-info a:hover {{ background: #f8717118; }}
        .container {{ max-width: 1000px; margin: 0 auto; padding: 2rem; }}

        /* Overall status hero */
        .hero {{
            text-align: center;
            padding: 2rem;
            margin-bottom: 2rem;
            border-radius: 16px;
            background: {overall_bg};
            border: 1px solid {overall_color}33;
            position: relative;
            overflow: hidden;
        }}
        .hero::before {{
            content: '';
            position: absolute;
            top: -50%;
            right: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, {overall_color}08 0%, transparent 60%);
            pointer-events: none;
        }}
        .hero h2 {{
            font-size: 1.4rem;
            color: {overall_color};
            margin-bottom: 0.75rem;
            position: relative;
        }}
        .hero-stats {{
            display: flex;
            justify-content: center;
            gap: 2rem;
            position: relative;
        }}
        .hero-stat {{
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.25rem;
        }}
        .hero-stat .val {{
            font-size: 1.3rem;
            font-weight: 700;
            color: #f8fafc;
        }}
        .hero-stat .lbl {{
            font-size: 0.75rem;
            color: #64748b;
        }}

        /* Category sections */
        .category-section {{
            margin-bottom: 2rem;
        }}
        .category-title {{
            font-size: 1rem;
            color: #94a3b8;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid #1e293b;
        }}
        .svc-grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 0.75rem;
        }}

        /* Service card */
        .svc-card {{
            background: #111827;
            border: 1px solid #1e293b;
            border-radius: 12px;
            padding: 1rem 1.25rem;
            transition: border-color 0.2s, box-shadow 0.2s;
        }}
        .svc-card:hover {{
            border-color: #334155;
            box-shadow: 0 4px 24px rgba(0,0,0,0.2);
        }}
        .svc-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }}
        .svc-name-row {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .svc-dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
            display: inline-block;
            flex-shrink: 0;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        .svc-name {{
            font-weight: 600;
            font-size: 0.95rem;
            color: #f1f5f9;
            text-decoration: none;
        }}
        .svc-name:hover {{ color: #818cf8; }}
        .svc-type {{
            font-size: 0.65rem;
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }}
        .svc-status {{
            font-size: 0.8rem;
            font-weight: 600;
        }}
        .svc-desc {{
            font-size: 0.8rem;
            color: #64748b;
            margin-bottom: 0.6rem;
            line-height: 1.5;
        }}
        .svc-metrics {{
            display: flex;
            gap: 1.5rem;
            font-size: 0.75rem;
        }}
        .svc-metric {{
            display: flex;
            gap: 0.4rem;
            align-items: center;
        }}
        .metric-label {{
            color: #475569;
        }}

        footer {{
            text-align: center;
            margin-top: 1rem;
            padding: 1.5rem;
            font-size: 0.75rem;
            color: #334155;
            border-top: 1px solid #1e293b;
        }}
        footer a {{ color: #818cf8; text-decoration: none; }}

        @media (max-width: 600px) {{
            .container {{ padding: 1rem; }}
            .hero-stats {{ gap: 1rem; }}
            .top-bar {{ padding: 0.5rem 1rem; }}
        }}
    </style>
</head>
<body>
    <div class="top-bar">
        <div class="logo">
            <span>Orcest</span> AI Status
        </div>
        <div class="user-info">
            <span>{user_name}</span>
            <a href="/auth/logout">\u062e\u0631\u0648\u062c</a>
        </div>
    </div>

    <div class="container">
        <div class="hero">
            <h2>{overall_label}</h2>
            <div class="hero-stats">
                <div class="hero-stat">
                    <span class="val">{op_count}/{total_count}</span>
                    <span class="lbl">\u0633\u0631\u0648\u06cc\u0633 \u0641\u0639\u0627\u0644</span>
                </div>
                <div class="hero-stat">
                    <span class="val">{avg_latency} ms</span>
                    <span class="lbl">\u0645\u06cc\u0627\u0646\u06af\u06cc\u0646 \u062a\u0623\u062e\u06cc\u0631</span>
                </div>
                <div class="hero-stat">
                    <span class="val">{down_count}</span>
                    <span class="lbl">\u0642\u0637\u0639\u06cc / \u062a\u0627\u06cc\u0645\u200c\u0627\u0648\u062a</span>
                </div>
                <div class="hero-stat">
                    <span class="val" style="font-size:0.9rem;">{checked_at}</span>
                    <span class="lbl">\u0622\u062e\u0631\u06cc\u0646 \u0628\u0631\u0631\u0633\u06cc</span>
                </div>
            </div>
        </div>

        {sections_html}

        <footer>
            \u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc \u062e\u0648\u062f\u06a9\u0627\u0631 \u0647\u0631 \u06f6\u06f0 \u062b\u0627\u0646\u06cc\u0647 &mdash; <a href="https://orcest.ai">Orcest AI</a> v{VERSION}
        </footer>
    </div>
</body>
</html>"""

    return HTMLResponse(content=html)
