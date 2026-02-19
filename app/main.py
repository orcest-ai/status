import os
import time
import asyncio
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(
    title="Orcest AI Status",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

SERVICES = [
    {"name": "Orcest AI", "url": "https://orcest.ai", "health": "https://orcest.ai/health", "type": "web", "description": "Landing page & API gateway"},
    {"name": "RainyModel", "url": "https://rm.orcest.ai", "health": "https://rm.orcest.ai/health", "type": "api", "description": "LLM routing proxy (FREE → INTERNAL → PREMIUM)"},
    {"name": "Lamino", "url": "https://llm.orcest.ai", "health": "https://llm.orcest.ai/api/health", "type": "web", "description": "AI chat with RAG & workspace management"},
    {"name": "Maestrist", "url": "https://agent.orcest.ai", "health": "https://agent.orcest.ai/api/litellm-models", "type": "web", "description": "AI-driven software development agent"},
    {"name": "Orcide", "url": "https://ide.orcest.ai", "health": "https://ide.orcest.ai", "type": "web", "description": "AI-powered code editor"},
    {"name": "Login SSO", "url": "https://login.orcest.ai", "health": "https://login.orcest.ai/health", "type": "api", "description": "Single sign-on identity provider"},
    {"name": "Ollama Primary", "url": "http://164.92.147.36:11434", "health": "http://164.92.147.36:11434/api/version", "type": "internal", "description": "16GB - qwen2.5:14b (primary)"},
    {"name": "Ollama Secondary", "url": "http://178.128.196.3:11434", "health": "http://178.128.196.3:11434/api/version", "type": "internal", "description": "8GB - qwen2.5:7b (fallback)"},
]

ANNOUNCEMENTS = [
    {"date": "2026-02-19", "type": "info", "title": "System Launch", "body": "Orcest AI ecosystem is now live with all core services operational."},
    {"date": "2026-02-19", "type": "success", "title": "SSO Deployed", "body": "login.orcest.ai is live with OIDC support for all ecosystem services."},
    {"date": "2026-02-19", "type": "warning", "title": "Security Hardening", "body": "Swagger/OpenAPI endpoints being disabled on public services. PRs pending merge."},
]

_check_cache: dict = {"results": [], "timestamp": 0}
CACHE_TTL = 30


async def check_service(client: httpx.AsyncClient, svc: dict) -> dict:
    start = time.time()
    try:
        resp = await client.get(svc["health"], timeout=10.0)
        latency_ms = int((time.time() - start) * 1000)
        status = "operational" if resp.status_code < 400 else "degraded"
        return {**svc, "status": status, "latency_ms": latency_ms, "http_code": resp.status_code}
    except httpx.TimeoutException:
        return {**svc, "status": "timeout", "latency_ms": 10000, "http_code": 0}
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        return {**svc, "status": "down", "latency_ms": latency_ms, "http_code": 0, "error": str(type(e).__name__)}


async def check_all_services() -> list:
    now = time.time()
    if now - _check_cache["timestamp"] < CACHE_TTL and _check_cache["results"]:
        return _check_cache["results"]

    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [check_service(client, svc) for svc in SERVICES]
        results = await asyncio.gather(*tasks)

    _check_cache["results"] = list(results)
    _check_cache["timestamp"] = now
    return list(results)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "status.orcest.ai", "version": "1.0.0"}


@app.get("/api/status")
async def api_status():
    results = await check_all_services()
    operational = sum(1 for r in results if r["status"] == "operational")
    total = len(results)
    overall = "operational" if operational == total else "degraded" if operational > total // 2 else "major_outage"
    return {
        "overall": overall,
        "services": results,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "operational_count": operational,
        "total_count": total,
    }


@app.get("/api/announcements")
async def api_announcements():
    return {"announcements": ANNOUNCEMENTS}


@app.get("/", response_class=HTMLResponse)
async def status_page(request: Request):
    results = await check_all_services()
    operational = sum(1 for r in results if r["status"] == "operational")
    total = len(results)

    if operational == total:
        overall = "operational"
        overall_text = "All Systems Operational"
        overall_class = "status-operational"
    elif operational > total // 2:
        overall = "degraded"
        overall_text = "Partial System Degradation"
        overall_class = "status-degraded"
    else:
        overall = "major_outage"
        overall_text = "Major Outage Detected"
        overall_class = "status-down"

    return templates.TemplateResponse("status.html", {
        "request": request,
        "services": results,
        "overall": overall,
        "overall_text": overall_text,
        "overall_class": overall_class,
        "operational": operational,
        "total": total,
        "announcements": ANNOUNCEMENTS,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    })
