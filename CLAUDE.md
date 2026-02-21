# CLAUDE.md

## Project Overview

**Orcest AI Ecosystem Status & Monitoring Dashboard** — a real-time status page that monitors health, latency, and availability of services across the Orcest AI platform.

- **Repository**: `orcest-ai/status`
- **Production URL**: `https://status.orcest.ai`
- **Primary branch**: `main`
- **Language**: Python 3.11
- **Framework**: FastAPI + Uvicorn
- **Deployment**: Docker on Render.com

## Repository Structure

```
status/
├── CLAUDE.md              # AI assistant guidelines (this file)
├── README.md              # Project description
├── Dockerfile             # Docker container (python:3.11-slim)
├── render.yaml            # Render.com deployment config
├── requirements.txt       # Python dependencies
├── .gitignore             # Excludes __pycache__, *.pyc, .env
├── app/
│   ├── __init__.py        # Package init
│   └── main.py            # FastAPI application — all routes and service checks
├── templates/
│   └── status.html        # Jinja2 HTML template — full dashboard UI
└── static/
    └── .gitkeep           # Placeholder for static assets
```

## Tech Stack & Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| FastAPI | >=0.109.0 | Async web framework |
| Uvicorn | >=0.27.0 | ASGI server |
| httpx | >=0.26.0 | Async HTTP client for health checks |
| Jinja2 | >=3.1.3 | Server-side HTML templating |

No database. No frontend build step. Pure Python backend with server-rendered HTML.

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

| Method | Path | Response | Description |
|--------|------|----------|-------------|
| GET | `/` | HTML | Status dashboard page (auto-refreshes every 60s) |
| GET | `/health` | JSON | Health check — `{"status": "healthy", "version": "1.0.0"}` |
| GET | `/api/status` | JSON | All service statuses with latency and overall health |
| GET | `/api/announcements` | JSON | System announcements array |

OpenAPI/Swagger docs are intentionally disabled in production.

## Architecture

### Service Monitoring

The app monitors 8 services across 3 types:

| Service | Type | Description |
|---------|------|-------------|
| Orcest AI | web | Landing page & API gateway |
| RainyModel | api | LLM routing proxy |
| Lamino | web | AI chat with RAG & workspace |
| Maestrist | web | AI-driven software development agent |
| Orcide | web | AI-powered code editor |
| Login SSO | api | OIDC identity provider |
| Ollama Primary | internal | 16GB — qwen2.5:14b |
| Ollama Secondary | internal | 8GB — qwen2.5:7b (fallback) |

### Key Patterns

- **Async health checks**: All service checks run in parallel via `asyncio.gather()`
- **In-memory TTL cache**: Results cached for 30 seconds (`CACHE_TTL = 30`) to avoid hammering services
- **Status classification**: HTTP < 400 = `operational`, timeout = `timeout`, exception = `down`, else `degraded`
- **Health check timeout**: 10 seconds per service
- **Server-side rendering**: Jinja2 templates with CSS-in-HTML styling (dark theme)
- **Auto-refresh**: HTML meta tag refreshes the dashboard every 60 seconds

### Service Registry

Services are defined as a hardcoded `SERVICES` list in `app/main.py`. Each entry has: `name`, `url`, `health` (endpoint), `type`, and `description`.

### Announcements

System announcements are defined as a hardcoded `ANNOUNCEMENTS` list in `app/main.py`. Each entry has: `date`, `type` (info/success/warning), `title`, and `body`.

## Deployment

### Render.com

Configured in `render.yaml`:
- **Service**: `status-orcest-ai` (Docker web service)
- **Branch**: deploys from `main`
- **Domain**: `status.orcest.ai`
- **Plan**: starter
- **Health check**: `GET /health`
- **Port**: 10000

Auto-deploys on push to `main`.

## Testing

No test framework is configured yet. When adding tests:
- Use `pytest` with `httpx` for async FastAPI testing
- Test health check endpoints and service status aggregation
- Mock external service calls to avoid hitting real services in tests

## Linting & Formatting

No linter or formatter is configured yet. When adding tooling:
- Consider `ruff` for linting and formatting (fast, all-in-one)
- Consider `mypy` for type checking

## Key Conventions

### Git Workflow

- Default branch: `main`
- Use descriptive commit messages that explain the "why" not just the "what"
- Keep commits focused and atomic
- Render auto-deploys from `main` — verify changes before merging

### Code Style

- Async-first: use `async def` for all route handlers and I/O operations
- Services and announcements are defined as module-level constants in `app/main.py`
- No environment variables currently used; `.env` is gitignored for future use
- Template variables are passed via `TemplateResponse` context dict

### Important Files

- **`app/main.py`** — The entire backend. All routes, service checks, caching, and data definitions live here.
- **`templates/status.html`** — The entire frontend. Server-rendered HTML with inline CSS. Dark theme, responsive grid layout, status badges with color coding.

## AI Assistant Guidelines

When working on this codebase:

1. **Read before writing** — Always read existing files before proposing changes
2. **Keep it simple** — This is a lean, focused app (~350 lines total). Avoid over-engineering
3. **Update this file** — When adding new tooling, frameworks, or services, update the relevant sections of this CLAUDE.md
4. **No unnecessary files** — Prefer editing existing files over creating new ones
5. **Security first** — Do not expose internal service IPs/URLs beyond what's needed; do not introduce XSS, injection, or other vulnerabilities
6. **Minimal changes** — Don't refactor or "improve" code beyond the scope of the current task
7. **Async patterns** — Use async/await for all I/O operations; maintain the `asyncio.gather()` pattern for parallel health checks
8. **Cache awareness** — The 30-second TTL cache in `check_all_services()` affects how quickly status changes appear. Account for this in any monitoring changes
