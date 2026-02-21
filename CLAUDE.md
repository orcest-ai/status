# CLAUDE.md

## Project Overview

**Orcest AI Ecosystem Status & Monitoring Dashboard** — a real-time status page that monitors health, latency, and availability of services across the Orcest AI platform.

- **Repository**: `orcest-ai/status`
- **Production URL**: `https://status.orcest.ai`
- **Primary branch**: `main`
- **Language**: Python 3.11
- **Framework**: FastAPI + Uvicorn
- **Deployment**: Docker on Render.com
- **Version**: 2.0.0

## Repository Structure

```
status/
├── CLAUDE.md              # AI assistant guidelines (this file)
├── README.md              # Project description
├── Dockerfile             # Docker container (python:3.11-slim)
├── render.yaml            # Render.com deployment config
├── requirements.txt       # Python dependencies
├── .gitignore             # Excludes __pycache__, *.pyc, .env
└── app/
    ├── __init__.py        # Package init
    └── main.py            # FastAPI application — all routes, service checks, and inline HTML
```

## Tech Stack & Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| FastAPI | >=0.109.0 | Async web framework |
| Uvicorn | >=0.27.0 | ASGI server |
| httpx | >=0.27.0 | Async HTTP client for health checks |

No database. No frontend build step. Pure Python backend with server-rendered inline HTML (no templates).

## Development Setup

### Prerequisites

- Python 3.11+
- Docker (optional, for container-based workflow)

### Getting Started

```bash
git clone https://github.com/orcest-ai/status.git
cd status
pip install -r requirements.txt
```

### Run Locally

```bash
uvicorn app.main:app --host 0.0.0.0 --port 10000 --reload
```

The dashboard will be available at `http://localhost:10000`.

### Run with Docker

```bash
docker build -t status .
docker run -p 10000:10000 status
```

## API Endpoints

| Method | Path | Auth | Response | Description |
|--------|------|------|----------|-------------|
| GET | `/` | SSO | HTML | Status dashboard page (auto-refreshes every 60s) |
| GET | `/health` | Public | JSON | Health check — `{"status": "healthy", "version": "2.0.0"}` |
| GET | `/api/status` | SSO | JSON | All service statuses with latency, uptime, and overall health |
| GET | `/api/me` | SSO | JSON | Current authenticated user's profile |
| GET | `/auth/callback` | Public | Redirect | OAuth2 authorization code callback |
| GET | `/auth/logout` | Public | Redirect | Clear SSO cookie, redirect to SSO logout |

OpenAPI/Swagger docs are intentionally disabled in production.

## Architecture

### Service Monitoring

The app monitors 7 services across 3 categories:

**Core Platform:**

| Service | Type | Health Endpoint | Description |
|---------|------|-----------------|-------------|
| Orcest AI | web | `orcest.ai/health` | Landing page & API gateway — search, extraction & research |
| Login SSO | api | `login.orcest.ai/health` | Single Sign-On — OIDC/OAuth2 identity provider |

**AI & LLM:**

| Service | Type | Health Endpoint | Description |
|---------|------|-----------------|-------------|
| RainyModel | api | `rm.orcest.ai/health` | Smart LLM proxy — auto-routing FREE → INTERNAL → PREMIUM |
| Lamino | web | `llm.orcest.ai/api/health` | Intelligent workspace — chat, RAG, agents, MCP & docs |
| Maestrist | web | `agent.orcest.ai/health` | Software dev agent — CodeAct, browsing & code execution |

**Developer Tools:**

| Service | Type | Health Endpoint | Description |
|---------|------|-----------------|-------------|
| Orcide | web | `ide.orcest.ai` | Cloud IDE — AI code completion & integrated chat |
| Ollama Free API | api | `ollamafreeapi.orcest.ai/health` | Free access to 650+ models |

### Key Patterns

- **Async health checks**: All service checks run in parallel via `asyncio.gather()`
- **In-memory TTL cache**: Results cached for 30 seconds (`CACHE_TTL = 30`) to avoid hammering services
- **Uptime tracking**: In-memory counters track uptime percentage since process start
- **Status classification**: HTTP < 400 = `operational`, timeout = `timeout`, exception = `down`, else `degraded`
- **Health check timeout**: 10 seconds per service
- **Server-side rendering**: Inline HTML with CSS (dark theme, card-based layout, category grouping)
- **Auto-refresh**: HTML meta tag refreshes the dashboard every 60 seconds
- **Bilingual descriptions**: Each service has both Farsi and English descriptions

### Authentication (OAuth2/OIDC SSO)

All routes except `/health` and `/auth/*` require SSO authentication via `login.orcest.ai`:
- Tokens extracted from `sso_token` cookie or `Authorization: Bearer` header
- Token verified against `SSO_ISSUER/api/token/verify`
- Unauthenticated browser requests redirected to SSO login
- OAuth2 callback exchanges authorization code for access token

### Service Registry

Services are defined as a hardcoded `SERVICES` list in `app/main.py`. Each entry has: `name`, `url`, `health`, `type`, `category`, `description` (Farsi), and `description_en`.

### Dashboard UI (v2)

- Dark theme with glassmorphism effects
- Card-based service layout (not table)
- Services grouped by category (core, ai, dev) with labeled sections
- Type badges (web/API) with distinct colors
- Latency color coding: green (<500ms), yellow (<2000ms), orange (>2000ms)
- Pulsing status dots with color animation
- Hero section with summary stats (operational count, avg latency, down count, timestamp)
- Responsive design with mobile breakpoints

## Deployment

### Render.com

Configured in `render.yaml`:
- **Service**: `status-orcest-ai` (Docker web service)
- **Branch**: deploys from `main`
- **Domain**: `status.orcest.ai`
- **Plan**: starter
- **Health check**: `GET /health`
- **Port**: 10000

Environment variables:
- `SSO_ISSUER`: `https://login.orcest.ai`
- `SSO_CLIENT_ID`: `status`
- `SSO_CLIENT_SECRET`: (from Render secrets)
- `SSO_CALLBACK_URL`: `https://status.orcest.ai/auth/callback`

Auto-deploys on push to `main`.

## Key Conventions

### Git Workflow

- Default branch: `main`
- Use descriptive commit messages that explain the "why" not just the "what"
- Keep commits focused and atomic
- Render auto-deploys from `main` — verify changes before merging

### Code Style

- Async-first: use `async def` for all route handlers and I/O operations
- Services defined as module-level constants in `app/main.py`
- All HTML rendered inline (no template files) — keeps the app as a single Python file
- f-strings with doubled braces `{{}}` for CSS in inline HTML

### Important Files

- **`app/main.py`** — The entire application. All routes, service checks, SSO auth, caching, and HTML rendering live here.

## AI Assistant Guidelines

When working on this codebase:

1. **Read before writing** — Always read existing files before proposing changes
2. **Keep it simple** — This is a lean, focused app. Avoid over-engineering
3. **Update this file** — When adding new tooling, frameworks, or services, update the relevant sections of this CLAUDE.md
4. **No unnecessary files** — Prefer editing existing files over creating new ones
5. **Security first** — Do not expose internal service IPs/URLs beyond what's needed; do not introduce XSS, injection, or other vulnerabilities
6. **Minimal changes** — Don't refactor or "improve" code beyond the scope of the current task
7. **Async patterns** — Use async/await for all I/O operations; maintain the `asyncio.gather()` pattern for parallel health checks
8. **Cache awareness** — The 30-second TTL cache in `check_all_services()` affects how quickly status changes appear. Account for this in any monitoring changes
