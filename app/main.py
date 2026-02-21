import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(
    title="Orcest Status",
    description="Orcest AI Ecosystem Status & Monitoring Dashboard",
    version="1.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

CACHE_TTL = 30
CHECK_TIMEOUT = 10.0

SERVICES: list[dict[str, str]] = [
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
        "name": "Lamino",
        "url": "https://llm.orcest.ai",
        "health": "https://llm.orcest.ai/api/health",
        "type": "web",
        "description": "AI chat + workspace",
    },
    {
        "name": "Maestrist",
        "url": "https://agent.orcest.ai",
        "health": "https://agent.orcest.ai/api/litellm-models",
        "type": "web",
        "description": "AI software development agent",
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
        "description": "Identity provider",
    },
    {
        "name": "Ollama Primary",
        "url": "http://10.0.0.16:11434",
        "health": "http://10.0.0.16:11434/api/tags",
        "type": "internal",
        "description": "16GB - qwen2.5:14b",
    },
    {
        "name": "Ollama Secondary",
        "url": "http://10.0.0.8:11434",
        "health": "http://10.0.0.8:11434/api/tags",
        "type": "internal",
        "description": "8GB - qwen2.5:7b fallback",
    },
]

ANNOUNCEMENTS = [
    {
        "date": "2026-02-21",
        "type": "success",
        "title": "Realtime Dashboard Upgrade",
        "body": "Interactive charts and service topology are now available.",
    },
    {
        "date": "2026-02-21",
        "type": "info",
        "title": "Live Status Streaming",
        "body": "SSE stream endpoint /api/status/stream has been enabled.",
    },
]

_cache: dict[str, Any] = {"data": None, "ts": 0.0}


async def check_service(service: dict[str, str], client: httpx.AsyncClient) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        resp = await client.get(service["health"])
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code < 400:
            status = "operational"
        else:
            status = "degraded"
        return {
            **service,
            "status": status,
            "code": resp.status_code,
            "latency_ms": latency_ms,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except httpx.TimeoutException:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            **service,
            "status": "timeout",
            "code": 0,
            "latency_ms": latency_ms,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            **service,
            "status": "down",
            "code": 0,
            "latency_ms": latency_ms,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


async def check_all_services(force: bool = False) -> dict[str, Any]:
    now = time.time()
    if not force and _cache["data"] and (now - _cache["ts"] < CACHE_TTL):
        return _cache["data"]

    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT, follow_redirects=True) as client:
        results = await asyncio.gather(*(check_service(svc, client) for svc in SERVICES))

    total = len(results)
    operational = sum(1 for r in results if r["status"] == "operational")
    degraded = sum(1 for r in results if r["status"] == "degraded")
    down = sum(1 for r in results if r["status"] in {"down", "timeout"})
    avg_latency = int(sum(r["latency_ms"] for r in results) / total) if total else 0
    overall = "operational" if down == 0 and degraded == 0 else ("degraded" if down == 0 else "partial_outage")

    payload = {
        "overall": overall,
        "summary": {
            "total": total,
            "operational": operational,
            "degraded": degraded,
            "down": down,
            "avg_latency_ms": avg_latency,
        },
        "services": results,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "cache_ttl_seconds": CACHE_TTL,
    }
    _cache["data"] = payload
    _cache["ts"] = now
    return payload


@app.get("/", response_class=HTMLResponse)
async def status_dashboard(request: Request):
    status_data = await check_all_services()
    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "status_data": status_data,
            "announcements": ANNOUNCEMENTS,
        },
    )


@app.get("/fc", response_class=HTMLResponse)
async def flowchart_page(request: Request):
    return templates.TemplateResponse("fc.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "1.1.0"}


@app.get("/api/status")
async def api_status(force: bool = False):
    return JSONResponse(await check_all_services(force=force))


@app.get("/api/announcements")
async def api_announcements():
    return {"announcements": ANNOUNCEMENTS}


@app.get("/api/topology")
async def api_topology():
    return {
        "nodes": [svc["name"] for svc in SERVICES],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "diagram_url": "https://status.orcest.ai/fc",
    }


@app.get("/api/status/stream")
async def api_status_stream():
    async def event_generator():
        while True:
            payload = await check_all_services(force=True)
            yield f"data: {JSONResponse(content=payload).body.decode('utf-8')}\n\n"
            await asyncio.sleep(8)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

