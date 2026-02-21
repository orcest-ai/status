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

TOPOLOGY_VIEWS: dict[str, dict[str, Any]] = {
    "overview": {
        "title": "Orcest Ecosystem Topology",
        "subtitle": "High-level architecture of status, core services, SSO, RainyModel, and internal inference nodes.",
        "mermaid": """
flowchart TD
  usersNode["Users"]
  statusNode["status.orcest.ai"]
  coreNode["orcest.ai Core"]
  rmNode["RainyModel"]
  laminoNode["Lamino"]
  maestristNode["Maestrist"]
  orcideNode["Orcide"]
  ssoNode["Login SSO"]
  ollamaPrimaryNode["Ollama Primary"]
  ollamaSecondaryNode["Ollama Secondary"]

  usersNode --> statusNode
  statusNode --> coreNode
  statusNode --> rmNode
  statusNode --> laminoNode
  statusNode --> maestristNode
  statusNode --> orcideNode
  statusNode --> ssoNode
  rmNode --> ollamaPrimaryNode
  rmNode --> ollamaSecondaryNode
""",
        "node_links": {
            "RainyModel": "/fc/rainymodel",
            "Lamino": "/fc/lamino",
            "orcest.ai Core": "/fc/langchain-loop",
        },
        "service_map": {
            "status.orcest.ai": "status.orcest.ai",
            "orcest.ai Core": "Orcest AI",
            "RainyModel": "RainyModel",
            "Lamino": "Lamino",
            "Maestrist": "Maestrist",
            "Orcide": "Orcide",
            "Login SSO": "Login SSO",
            "Ollama Primary": "Ollama Primary",
            "Ollama Secondary": "Ollama Secondary",
        },
    },
    "rainymodel": {
        "title": "RainyModel Routing Topology",
        "subtitle": "Tiered routing: free native models, internal inference, and external providers via OpenRouter/direct endpoints.",
        "mermaid": """
flowchart LR
  callerNode["Orcest/Lamino/Agents"]
  rmNode["RainyModel Router"]
  policyNode["Policy Engine"]
  freeNode["Native Free Models"]
  internalNode["Internal Model Servers"]
  externalNode["External Providers"]
  openRouterNode["OpenRouter Endpoint"]
  directOpenAINode["Direct OpenAI Endpoint"]
  directXaiNode["Direct xAI Endpoint"]
  directAnthropicNode["Direct Anthropic Endpoint"]
  directDeepSeekNode["Direct DeepSeek Endpoint"]
  directGeminiNode["Direct Gemini Endpoint"]

  callerNode --> rmNode
  rmNode --> policyNode
  policyNode --> freeNode
  policyNode --> internalNode
  policyNode --> externalNode

  externalNode --> openRouterNode
  externalNode --> directOpenAINode
  externalNode --> directXaiNode
  externalNode --> directAnthropicNode
  externalNode --> directDeepSeekNode
  externalNode --> directGeminiNode
""",
        "node_links": {
            "External Providers": "/fc/providers",
            "OpenRouter Endpoint": "/fc/providers",
            "Direct OpenAI Endpoint": "/fc/providers",
            "Direct xAI Endpoint": "/fc/providers",
        },
        "service_map": {
            "RainyModel Router": "RainyModel",
        },
    },
    "lamino": {
        "title": "Lamino Inference Path",
        "subtitle": "How Lamino request flow reaches OpenAI/Codex Max through RainyModel policy and endpoint routing.",
        "mermaid": """
flowchart TD
  userNode["Lamino User Prompt"]
  laminoNode["Lamino App"]
  rmNode["RainyModel"]
  policyNode["Routing Policy"]
  openAINode["OpenAI Endpoint"]
  codexNode["Codex Max Model"]
  responseNode["Response Back to Lamino"]

  userNode --> laminoNode
  laminoNode --> rmNode
  rmNode --> policyNode
  policyNode --> openAINode
  openAINode --> codexNode
  codexNode --> responseNode
  responseNode --> laminoNode
""",
        "node_links": {
            "RainyModel": "/fc/rainymodel",
            "OpenAI Endpoint": "/fc/providers",
            "Codex Max Model": "/fc/providers",
        },
        "service_map": {
            "Lamino App": "Lamino",
            "RainyModel": "RainyModel",
        },
    },
    "langchain-loop": {
        "title": "Orcest LangChain Feedback Loop",
        "subtitle": "How Orcest internal LangChain calls RainyModel and RainyModel can route back to Orcest LangChain API.",
        "mermaid": """
flowchart TD
  orchNode["Orcest Core"]
  lcNode["Internal LangChain API"]
  toolsNode["Tools/Agents/Chains"]
  rmNode["RainyModel"]
  providersNode["Provider Mesh"]
  callbackNode["Orcest LangChain Endpoint"]

  orchNode --> lcNode
  lcNode --> toolsNode
  toolsNode --> rmNode
  rmNode --> providersNode
  rmNode --> callbackNode
  callbackNode --> lcNode
""",
        "node_links": {
            "RainyModel": "/fc/rainymodel",
            "Provider Mesh": "/fc/providers",
            "Internal LangChain API": "/fc/overview",
        },
        "service_map": {
            "Orcest Core": "Orcest AI",
            "RainyModel": "RainyModel",
        },
    },
    "providers": {
        "title": "Provider and Endpoint Topology",
        "subtitle": "Detailed endpoint matrix: free native, internal servers, OpenRouter and direct provider endpoints.",
        "mermaid": """
flowchart TB
  rmNode["RainyModel"]
  nativeNode["Native Free"]
  internalNode["Internal Servers"]
  externalNode["External Providers"]

  openRouterNode["OpenRouter API"]
  openAINode["OpenAI API"]
  xaiNode["xAI API"]
  anthropicNode["Anthropic API"]
  deepSeekNode["DeepSeek API"]
  geminiNode["Gemini API"]

  nativeModel1["qwen2.5:7b"]
  nativeModel2["qwen2.5:14b"]
  internalModel1["Internal GPU Pool A"]
  internalModel2["Internal GPU Pool B"]

  rmNode --> nativeNode
  rmNode --> internalNode
  rmNode --> externalNode

  nativeNode --> nativeModel1
  nativeNode --> nativeModel2
  internalNode --> internalModel1
  internalNode --> internalModel2

  externalNode --> openRouterNode
  externalNode --> openAINode
  externalNode --> xaiNode
  externalNode --> anthropicNode
  externalNode --> deepSeekNode
  externalNode --> geminiNode
""",
        "node_links": {
            "RainyModel": "/fc/rainymodel",
            "OpenRouter API": "https://openrouter.ai",
            "OpenAI API": "https://platform.openai.com",
            "xAI API": "https://x.ai",
            "Anthropic API": "https://console.anthropic.com",
            "DeepSeek API": "https://platform.deepseek.com",
            "Gemini API": "https://aistudio.google.com",
        },
        "service_map": {
            "RainyModel": "RainyModel",
            "Internal GPU Pool A": "Ollama Primary",
            "Internal GPU Pool B": "Ollama Secondary",
        },
    },
}

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
    return templates.TemplateResponse(
        "fc.html",
        {
            "request": request,
            "current_view": "overview",
            "view_data": TOPOLOGY_VIEWS["overview"],
            "views": [{"key": key, "title": value["title"]} for key, value in TOPOLOGY_VIEWS.items()],
        },
    )


@app.get("/fc/{view_key}", response_class=HTMLResponse)
async def flowchart_view_page(request: Request, view_key: str):
    view = TOPOLOGY_VIEWS.get(view_key)
    if view is None:
        return templates.TemplateResponse(
            "fc.html",
            {
                "request": request,
                "current_view": "overview",
                "view_data": TOPOLOGY_VIEWS["overview"],
                "views": [{"key": key, "title": value["title"]} for key, value in TOPOLOGY_VIEWS.items()],
                "error_message": f"Unknown topology '{view_key}', showing overview.",
            },
        )
    return templates.TemplateResponse(
        "fc.html",
        {
            "request": request,
            "current_view": view_key,
            "view_data": view,
            "views": [{"key": key, "title": value["title"]} for key, value in TOPOLOGY_VIEWS.items()],
        },
    )


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
        "views": [{"key": key, "title": value["title"], "subtitle": value["subtitle"]} for key, value in TOPOLOGY_VIEWS.items()],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "diagram_url": "https://status.orcest.ai/fc",
    }


@app.get("/api/topology/{view_key}")
async def api_topology_view(view_key: str):
    view = TOPOLOGY_VIEWS.get(view_key)
    if view is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "view_not_found",
                "view_key": view_key,
                "available_views": list(TOPOLOGY_VIEWS.keys()),
            },
        )
    return {
        "view_key": view_key,
        "title": view["title"],
        "subtitle": view["subtitle"],
        "node_links": view["node_links"],
        "service_map": view.get("service_map", {}),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status/stream")
async def api_status_stream():
    async def event_generator():
        while True:
            payload = await check_all_services(force=True)
            yield f"data: {JSONResponse(content=payload).body.decode('utf-8')}\n\n"
            await asyncio.sleep(8)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

