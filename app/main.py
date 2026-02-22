import asyncio
import math
import os
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

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
HISTORY_LIMIT = 120
FLOW_REPLAY_LIMIT = 200
DEFAULT_SLO = 99.5

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
_service_history: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=HISTORY_LIMIT))
_flow_replay: deque[dict[str, Any]] = deque(maxlen=FLOW_REPLAY_LIMIT)
_flow_replay_real: deque[dict[str, Any]] = deque(maxlen=FLOW_REPLAY_LIMIT)
FLOW_INGEST_TOKEN = os.getenv("FLOW_INGEST_TOKEN", "").strip()


class FlowEventIn(BaseModel):
    flow_key: str = Field(default="external-flow")
    flow_name: str = Field(default="External Request Flow")
    source: str = Field(default="external")
    nodes: list[str] = Field(default_factory=list)
    latency_ms: float = Field(default=0.0, ge=0)
    qps: float = Field(default=0.0, ge=0)
    status: str = Field(default="operational")
    checked_at: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class FlowBatchIn(BaseModel):
    events: list[FlowEventIn]

FLOW_DEFINITIONS: dict[str, dict[str, Any]] = {
    "lamino-openai": {
        "name": "Lamino -> RainyModel -> OpenAI",
        "nodes": ["Lamino", "RainyModel", "OpenAI API"],
        "services": ["Lamino", "RainyModel"],
        "provider_latency_ms": 650,
    },
    "lamino-openrouter": {
        "name": "Lamino -> RainyModel -> OpenRouter",
        "nodes": ["Lamino", "RainyModel", "OpenRouter API"],
        "services": ["Lamino", "RainyModel"],
        "provider_latency_ms": 520,
    },
    "orcest-langchain": {
        "name": "Orcest -> LangChain -> RainyModel",
        "nodes": ["Orcest Core", "Internal LangChain API", "RainyModel", "Provider Mesh"],
        "services": ["Orcest AI", "RainyModel"],
        "provider_latency_ms": 560,
    },
    "maestrist-routing": {
        "name": "Maestrist -> RainyModel -> Providers",
        "nodes": ["Maestrist", "RainyModel", "External Providers"],
        "services": ["Maestrist", "RainyModel"],
        "provider_latency_ms": 710,
    },
}

DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "RainyModel": ["Lamino", "Maestrist", "Orcest AI", "Ollama Primary", "Ollama Secondary"],
    "Login SSO": ["Orcest AI", "Lamino", "Maestrist", "Orcide"],
}


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

    for result in results:
        _service_history[result["name"]].append(
            {
                "status": result["status"],
                "latency_ms": result["latency_ms"],
                "code": result["code"],
                "checked_at": result["checked_at"],
            }
        )

    _append_flow_replay(results)

    _cache["data"] = payload
    _cache["ts"] = now
    return payload


def _is_failure_status(status: str) -> bool:
    return status in {"degraded", "down", "timeout", "partial_outage"}


def _estimate_qps(avg_latency_ms: float, has_failure: bool) -> float:
    # Health check telemetry proxy: faster and healthy services imply higher sustainable qps.
    base = max(0.2, min(12.0, 2200.0 / max(avg_latency_ms, 60.0)))
    if has_failure:
        return round(base * 0.45, 2)
    return round(base, 2)


def _append_flow_replay(results: list[dict[str, Any]]) -> None:
    by_name = {r["name"]: r for r in results}
    now_iso = datetime.now(timezone.utc).isoformat()
    for flow_key, flow in FLOW_DEFINITIONS.items():
        svc_points = [by_name[name] for name in flow["services"] if name in by_name]
        if not svc_points:
            continue
        avg_latency = sum(p["latency_ms"] for p in svc_points) / len(svc_points)
        provider_latency = float(flow.get("provider_latency_ms", 550))
        total_latency = round(avg_latency + provider_latency + random.uniform(15.0, 60.0), 2)
        has_failure = any(_is_failure_status(p["status"]) for p in svc_points)
        status = "degraded" if has_failure else "operational"
        qps = _estimate_qps(avg_latency, has_failure)
        _flow_replay.append(
            {
                "event_id": f"{flow_key}-{int(time.time() * 1000)}-{random.randint(100, 999)}",
                "flow_key": flow_key,
                "flow_name": flow["name"],
                "nodes": flow["nodes"],
                "latency_ms": total_latency,
                "qps": qps,
                "status": status,
                "checked_at": now_iso,
            }
        )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * pct
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(sorted_values[int(rank)])
    return float(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (rank - lo))


def _node_metrics(history: list[dict[str, Any]], slo_target: float = DEFAULT_SLO) -> dict[str, Any]:
    total = len(history)
    if total == 0:
        return {
            "samples": 0,
            "availability_pct": 100.0,
            "error_rate_pct": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "p99_latency_ms": 0.0,
            "status_transitions": 0,
            "slo_target_pct": slo_target,
            "slo_gap_pct": 0.0,
            "slo_burn_rate": 0.0,
        }
    statuses = [str(p.get("status", "unknown")) for p in history]
    latencies = [float(p.get("latency_ms", 0.0) or 0.0) for p in history]
    errors = sum(1 for p in history if p.get("code", 0) >= 400 or _is_failure_status(str(p.get("status", ""))))
    transitions = sum(1 for i in range(1, len(statuses)) if statuses[i] != statuses[i - 1])
    availability = ((total - errors) / total) * 100.0
    error_rate = (errors / total) * 100.0
    slo_gap = max(0.0, slo_target - availability)
    error_budget = max(0.1, 100.0 - slo_target)
    burn_rate = round((error_rate / error_budget), 3)
    return {
        "samples": total,
        "availability_pct": round(availability, 3),
        "error_rate_pct": round(error_rate, 3),
        "p50_latency_ms": round(_percentile(latencies, 0.50), 2),
        "p95_latency_ms": round(_percentile(latencies, 0.95), 2),
        "p99_latency_ms": round(_percentile(latencies, 0.99), 2),
        "status_transitions": transitions,
        "slo_target_pct": slo_target,
        "slo_gap_pct": round(slo_gap, 3),
        "slo_burn_rate": burn_rate,
    }


def _normalize_flow_event(event: FlowEventIn) -> dict[str, Any]:
    checked_at = event.checked_at or datetime.now(timezone.utc).isoformat()
    cleaned_nodes = [str(n).strip() for n in event.nodes if str(n).strip()]
    return {
        "event_id": f"{event.flow_key}-{int(time.time() * 1000)}-{random.randint(100, 999)}",
        "flow_key": event.flow_key.strip() or "external-flow",
        "flow_name": event.flow_name.strip() or "External Request Flow",
        "source": event.source.strip() or "external",
        "nodes": cleaned_nodes,
        "latency_ms": round(float(event.latency_ms), 2),
        "qps": round(float(event.qps), 2),
        "status": event.status.strip() or "operational",
        "checked_at": checked_at,
        "meta": event.meta,
    }


def _extract_ingest_token(authorization: str | None, x_ingest_token: str | None) -> str:
    if x_ingest_token:
        return x_ingest_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return ""


def _verify_ingest_auth(authorization: str | None, x_ingest_token: str | None) -> None:
    # If token is not configured, endpoint stays open for bootstrap/dev usage.
    if not FLOW_INGEST_TOKEN:
        return
    token = _extract_ingest_token(authorization, x_ingest_token)
    if token != FLOW_INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="invalid_ingest_token")


def _service_impact_payload(current: dict[str, Any]) -> dict[str, Any]:
    by_name = {s["name"]: s for s in current["services"]}
    impact_scores: dict[str, float] = {}
    reasons: dict[str, str] = {}
    for upstream, downstreams in DEPENDENCY_GRAPH.items():
        upstream_status = by_name.get(upstream, {}).get("status", "unknown")
        if not _is_failure_status(upstream_status):
            continue
        if upstream_status in {"down", "timeout"}:
            base = 1.0
        else:
            base = 0.65
        for idx, downstream in enumerate(downstreams):
            decay = max(0.35, 1.0 - (idx * 0.12))
            score = round(base * decay, 3)
            impact_scores[downstream] = max(impact_scores.get(downstream, 0.0), score)
            reasons[downstream] = f"Impacted by {upstream} ({upstream_status})"
    return {
        "impact_scores": impact_scores,
        "reasons": reasons,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


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


@app.get("/node/{service_name}", response_class=HTMLResponse)
async def node_drilldown_page(request: Request, service_name: str):
    current = await check_all_services()
    service = next((s for s in current["services"] if s["name"].lower() == service_name.lower()), None)
    if service is None:
        return templates.TemplateResponse(
            "node.html",
            {
                "request": request,
                "service_name": service_name,
                "service": None,
                "metrics": None,
                "history": [],
                "error_message": "Service not found.",
            },
            status_code=404,
        )
    history = list(_service_history[service["name"]])
    metrics = _node_metrics(history)
    return templates.TemplateResponse(
        "node.html",
        {
            "request": request,
            "service_name": service["name"],
            "service": service,
            "metrics": metrics,
            "history": history[-80:],
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


@app.get("/api/status/history")
async def api_status_history(limit: int = 40):
    safe_limit = max(1, min(limit, HISTORY_LIMIT))
    return {
        "limit": safe_limit,
        "services": {
            name: list(history)[-safe_limit:]
            for name, history in _service_history.items()
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status/node/{service_name}")
async def api_status_node(service_name: str, limit: int = 40):
    safe_limit = max(1, min(limit, HISTORY_LIMIT))
    current = await check_all_services()
    match = next((s for s in current["services"] if s["name"].lower() == service_name.lower()), None)
    if match is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "service_not_found",
                "service_name": service_name,
                "available_services": [s["name"] for s in current["services"]],
            },
        )
    return {
        "service": match,
        "history": list(_service_history[match["name"]])[-safe_limit:],
        "metrics": _node_metrics(list(_service_history[match["name"]])[-safe_limit:]),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/topology/impact")
async def api_topology_impact():
    current = await check_all_services()
    return _service_impact_payload(current)


@app.get("/api/flows/replay")
async def api_flows_replay(limit: int = 30, prefer_real: bool = True):
    safe_limit = max(1, min(limit, FLOW_REPLAY_LIMIT))
    current = await check_all_services()
    has_real = len(_flow_replay_real) > 0
    source_mode = "real" if (prefer_real and has_real) else "synthetic"
    source_queue = _flow_replay_real if source_mode == "real" else _flow_replay
    recent = list(source_queue)[-safe_limit:]
    avg_qps = round(sum(r["qps"] for r in recent) / len(recent), 2) if recent else 0.0
    avg_latency = round(sum(r["latency_ms"] for r in recent) / len(recent), 2) if recent else 0.0
    return {
        "summary": {
            "events": len(recent),
            "avg_qps": avg_qps,
            "avg_latency_ms": avg_latency,
            "overall": current["overall"],
            "source_mode": source_mode,
            "synthetic_events_available": len(_flow_replay),
            "real_events_available": len(_flow_replay_real),
        },
        "recent_paths": recent,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/flows/ingest")
async def api_flows_ingest(
    payload: FlowBatchIn,
    authorization: str | None = Header(default=None),
    x_ingest_token: str | None = Header(default=None),
):
    _verify_ingest_auth(authorization, x_ingest_token)
    accepted = 0
    for event in payload.events:
        normalized = _normalize_flow_event(event)
        if len(normalized["nodes"]) < 2:
            continue
        _flow_replay_real.append(normalized)
        accepted += 1
    return {
        "accepted": accepted,
        "received": len(payload.events),
        "real_replay_size": len(_flow_replay_real),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/flows/ingest/single")
async def api_flows_ingest_single(
    payload: FlowEventIn,
    authorization: str | None = Header(default=None),
    x_ingest_token: str | None = Header(default=None),
):
    _verify_ingest_auth(authorization, x_ingest_token)
    normalized = _normalize_flow_event(payload)
    if len(normalized["nodes"]) < 2:
        raise HTTPException(status_code=400, detail="nodes_must_have_at_least_two_hops")
    _flow_replay_real.append(normalized)
    return {
        "accepted": 1,
        "event_id": normalized["event_id"],
        "real_replay_size": len(_flow_replay_real),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/flows/stream")
async def api_flows_stream(prefer_real: bool = True):
    async def event_generator():
        cursor = ""
        while True:
            source_queue = _flow_replay_real if (prefer_real and len(_flow_replay_real) > 0) else _flow_replay
            if source_queue:
                latest = source_queue[-1]
                if latest["event_id"] != cursor:
                    cursor = latest["event_id"]
                    yield f"data: {JSONResponse(content=latest).body.decode('utf-8')}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

