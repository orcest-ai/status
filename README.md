# status
Orcest AI Ecosystem Status & Monitoring Dashboard

## Endpoints

- `/` — Realtime status dashboard
- `/fc` — Interactive topology diagram (pan/zoom/export)
- `/health` — Health check
- `/api/status` — Aggregated service status JSON
- `/api/status/stream` — SSE realtime status stream
- `/api/announcements` — Announcements feed
- `/api/topology` — Topology metadata

## Local run

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 10000 --reload
```
