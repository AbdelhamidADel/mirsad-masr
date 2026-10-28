# Render Git-backed Docker Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship MIRSAD MASR to Render Free as a Git-backed Docker Web Service with `$PORT` binding, provider-independent health checks, non-blocking startup warm, and honest Free-tier docs — without committing secrets.

**Architecture:** Keep the existing FastAPI + multi-stage Dockerfile. Fix `CMD` to use a shell so `${PORT:-8000}` works locally and on Render. Add `render.yaml` Blueprint (`plan: free`, `healthCheckPath: /v1/health`, no conflicting `dockerCommand`). Strengthen tests so `/v1/health` stays fast and never calls market providers. Document Free sleep, cold starts, ephemeral in-memory state, and 512 MB limits.

**Tech Stack:** Docker, uvicorn/FastAPI, Render Blueprint (`render.yaml`), pytest, existing `docs/self-hosting.md`.

**Spec:** `docs/superpowers/specs/2026-10-28-render-deploy-design.md`

## Global Constraints

- Single Web Service only — do not deploy `apps/web` on Render.
- Secrets (`ALPHA_VANTAGE_KEY`, `FINNHUB_KEY`, demo keys) only via Render env / Blueprint `sync: false` — never Git or image layers.
- Health = app liveness; must succeed within 5s and must not probe Yahoo/AV/Finnhub.
- Startup quote warm must not block accepting traffic or health.
- In-memory cache / demo limiter are ephemeral — document, do not add Redis.
- Free tier: sleep ~15 min idle, ~1 min cold start, ~512 MB RAM, hobby/preview — not production SLA.
- Wildcard CORS must not be paired with credentialed browser requests (document).
- Do not rename Python package `egxdesk`.
- Prefer Dockerfile `CMD` as the only startup command (no duplicate Blueprint `dockerCommand`).

## File map

| File | Role |
|------|------|
| `Dockerfile` | Shell `CMD` with `${PORT:-8000}` |
| `render.yaml` | Free Docker Web Service Blueprint |
| `tests/test_endpoints.py` | Health stays provider-independent and fast |
| `tests/test_lifespan_startup.py` | Warm uses `create_task`; lifespan yields without awaiting warm |
| `docs/self-hosting.md` | Deploy on Render + Free caveats |
| `docs/superpowers/specs/2026-10-28-render-deploy-design.md` | Spec (already approved) |

---

### Task 1: Prove `/v1/health` never touches providers

**Files:**
- Modify: `tests/test_endpoints.py`
- Test: `tests/test_endpoints.py`

**Interfaces:**
- Consumes: existing `GET /v1/health` → `HealthResponse` (`status`, `version`, `providers_configured`)
- Produces: regression tests that fail if health starts calling `get_quote` / `get_all_quotes` / HTTP

- [ ] **Step 1: Write the failing/strengthening tests**

Add after `test_health_returns_ok` in `tests/test_endpoints.py`:

```python
def test_health_is_fast(client: TestClient) -> None:
    import time

    start = time.perf_counter()
    resp = client.get("/v1/health")
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200
    assert elapsed < 5.0


def test_health_does_not_call_stock_service_fetch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Render health must not depend on market-data providers."""

    def _boom(*_a: object, **_k: object) -> object:
        raise AssertionError("health must not fetch quotes")

    monkeypatch.setattr(main.app.state.stock_svc, "get_quote", _boom)
    monkeypatch.setattr(main.app.state.stock_svc, "get_all_quotes", _boom)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

- [ ] **Step 2: Run the new tests**

Run: `uv run pytest tests/test_endpoints.py::test_health_is_fast tests/test_endpoints.py::test_health_does_not_call_stock_service_fetch -v`

Expected: PASS (current health already avoids providers). If FAIL, fix `health()` in `src/egxdesk/main.py` so it only reads `provider_status()` / version — no await of quote fetches.

- [ ] **Step 3: Commit**

```bash
git add tests/test_endpoints.py
git commit -m "test: lock /v1/health as fast provider-independent liveness"
```

---

### Task 2: Lock non-blocking startup warm

**Files:**
- Create: `tests/test_lifespan_startup.py`
- Modify only if needed: `src/egxdesk/main.py` (lifespan already uses `asyncio.create_task` before `yield`)

**Interfaces:**
- Consumes: `lifespan` in `src/egxdesk/main.py` — schedules `_warm_quote_cache` via `create_task` when `fetch_quotes_on_startup` is true, then `yield`s
- Produces: test proving TestClient startup returns health while a hanging warm would otherwise block forever if awaited

- [ ] **Step 1: Write the failing test for blocking warm**

Create `tests/test_lifespan_startup.py`:

```python
"""Startup warm must not block readiness / health."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import egxdesk.main as main
from egxdesk.main import app


@pytest.fixture()
def client_with_hanging_warm(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    async def _hang(_svc: object) -> None:
        await asyncio.Event().wait()  # never completes

    monkeypatch.setattr(main.settings, "fetch_quotes_on_startup", True)
    monkeypatch.setattr(main.settings, "auto_refresh_quotes", False)
    monkeypatch.setattr(main.settings, "enable_yahoo_finance", False)
    monkeypatch.setattr(main, "_warm_quote_cache", _hang)
    with TestClient(app) as test_client:
        yield test_client


def test_health_ok_while_startup_warm_hangs(client_with_hanging_warm: TestClient) -> None:
    resp = client_with_hanging_warm.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_lifespan_startup.py::test_health_ok_while_startup_warm_hangs -v`

Expected: PASS. If the client hangs or times out, lifespan is awaiting warm — change `src/egxdesk/main.py` so warm is only `asyncio.create_task(...)` and `yield` happens immediately after scheduling (do not `await _warm_quote_cache(...)` before `yield`).

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifespan_startup.py src/egxdesk/main.py
git commit -m "test: ensure startup quote warm cannot block /v1/health"
```

---

### Task 3: Dockerfile `$PORT` via shell CMD

**Files:**
- Modify: `Dockerfile` (final `CMD` line)

**Interfaces:**
- Consumes: Render injects `PORT`; local unset → 8000
- Produces: container listens on `${PORT:-8000}`

- [ ] **Step 1: Replace hardcoded CMD**

In `Dockerfile`, replace:

```dockerfile
CMD ["python", "-m", "uvicorn", "egxdesk.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

with:

```dockerfile
CMD ["sh", "-c", "exec uvicorn egxdesk.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

Do not add a Blueprint `dockerCommand` that duplicates this.

- [ ] **Step 2: Build the image**

Run: `docker build -t mirsad-masr:local .`

Expected: image builds successfully.

- [ ] **Step 3: Smoke default port 8000**

Run:

```bash
docker run --rm -d --name mirsad-port-default -p 8000:8000 mirsad-masr:local
# wait a few seconds
curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8000/v1/health
docker stop mirsad-port-default
```

Expected: HTTP `200`.

- [ ] **Step 4: Smoke injected PORT**

Run:

```bash
docker run --rm -d --name mirsad-port-custom -e PORT=10000 -p 10000:10000 mirsad-masr:local
curl -s -o NUL -w "%{http_code}" http://127.0.0.1:10000/v1/health
docker stop mirsad-port-custom
```

Expected: HTTP `200`.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile
git commit -m "fix(docker): bind uvicorn to PORT with local 8000 default"
```

---

### Task 4: Add `render.yaml` Blueprint

**Files:**
- Create: `render.yaml` (repo root)

**Interfaces:**
- Consumes: `./Dockerfile` with shell `CMD` from Task 3
- Produces: Free Docker web service `mirsad-masr` with `/v1/health` check

- [ ] **Step 1: Create `render.yaml`**

```yaml
# MIRSAD MASR — Render Blueprint (Free Web Service)
# https://render.com/docs/blueprint-spec
services:
  - type: web
    name: mirsad-masr
    runtime: docker
    plan: free
    dockerfilePath: ./Dockerfile
    healthCheckPath: /v1/health
    envVars:
      - key: ENABLE_YAHOO_FINANCE
        value: "true"
      - key: DEV_MODE
        value: "false"
      - key: LOG_LEVEL
        value: info
      - key: CORS_ORIGINS
        value: "*"
      - key: FETCH_QUOTES_ON_STARTUP
        value: "true"
      - key: AUTO_REFRESH_QUOTES
        value: "true"
      - key: ALPHA_VANTAGE_KEY
        sync: false
      - key: FINNHUB_KEY
        sync: false
      - key: DEMO_ALPHA_VANTAGE_KEY
        sync: false
      - key: DEMO_FINNHUB_KEY
        sync: false
```

Notes for the implementer:

- No `dockerCommand` — Dockerfile owns startup.
- Leave secret values empty in the dashboard if unused; Yahoo alone is enough for “works as now”.
- Do not put real keys in this file.

- [ ] **Step 2: Sanity-check YAML**

Run: `python -c "import yaml; yaml.safe_load(open('render.yaml')); print('ok')"`

If PyYAML is missing: `uv run python -c "import json; print(open('render.yaml').read()[:20])"` and visually confirm indentation (2 spaces, list under `services` / `envVars`).

Expected: parses / looks valid against Blueprint fields: `type`, `name`, `runtime`, `plan`, `dockerfilePath`, `healthCheckPath`, `envVars` with `value` or `sync`.

- [ ] **Step 3: Commit**

```bash
git add render.yaml
git commit -m "chore: add Render Free Docker Blueprint for MIRSAD MASR"
```

---

### Task 5: Document Render deploy + Free limits

**Files:**
- Modify: `docs/self-hosting.md`

**Interfaces:**
- Consumes: Tasks 3–4 artifacts (`Dockerfile` PORT behavior, `render.yaml`)
- Produces: operator-facing deploy steps and caveats

- [ ] **Step 1: Add a “Deploy on Render” section**

Append (or insert after Docker Compose) in `docs/self-hosting.md`:

```markdown
## Deploy on Render

MIRSAD MASR ships a [Render Blueprint](https://render.com/docs/infrastructure-as-code) at the repo root (`render.yaml`).

1. Push this repository to GitHub or GitLab.
2. In the [Render Dashboard](https://dashboard.render.com/), choose **New → Blueprint** and select the repo.
3. Apply the Blueprint. When prompted, paste optional `ALPHA_VANTAGE_KEY` / `FINNHUB_KEY` (and demo keys) — or leave them blank and rely on Yahoo Finance.
4. Wait for the first deploy. Open the service URL: `/` (landing), `/app` (board), `/docs` (API), `/v1/health` (liveness).

The container listens on Render’s injected `PORT` (see `Dockerfile`). Do not commit API keys; set them only in Render **Environment**.

### Free plan limits

Render’s Free web services are for hobby / preview use, not a production SLA:

- The service **sleeps** after about **15 minutes** without inbound traffic; the next request can take about **a minute** (cold start).
- The filesystem is **ephemeral**; the process may restart at any time.
- Memory is limited (~**512 MB**). The in-process quote cache and `/demo` rate limiter live in RAM and **reset** on restart or sleep wake — they are not durable storage.
- Do not combine `CORS_ORIGINS=*` with credentialed browser requests (`credentials: include` / cookies).
```

Also update the intro line that lists hosts (Fly.io, Railway, …) to include Render.

- [ ] **Step 2: Commit**

```bash
git add docs/self-hosting.md
git commit -m "docs: explain Render Blueprint deploy and Free-tier limits"
```

---

### Task 6: Memory / acceptance verification

**Files:**
- None required (verification + optional note in docs if measurement fails)

**Interfaces:**
- Consumes: built `mirsad-masr:local` image from Task 3

- [ ] **Step 1: Rough RAM check under Docker**

Run a container, hit health + landing, sample memory:

```bash
docker run --rm -d --name mirsad-mem -m 512m -e PORT=8000 -e ENABLE_YAHOO_FINANCE=true -p 8000:8000 mirsad-masr:local
curl -sf http://127.0.0.1:8000/v1/health
curl -sf -o NUL http://127.0.0.1:8000/
docker stats --no-stream mirsad-mem
docker stop mirsad-mem
```

Expected: container stays up under `-m 512m` (no OOM kill); `docker stats` MEM USAGE well under 512 MiB at idle after health + `/`.

If OOM: set Blueprint `FETCH_QUOTES_ON_STARTUP` to `"false"` and document why; do not add Redis in this plan.

- [ ] **Step 2: Run full relevant pytest slice**

Run: `uv run pytest tests/test_endpoints.py tests/test_lifespan_startup.py -v`

Expected: all PASS.

- [ ] **Step 3: Final checklist (tick in PR / commit message body)**

- [ ] `render.yaml` matches Blueprint fields used in Task 4  
- [ ] Docker responds on 8000 and injected `PORT`  
- [ ] App starts if provider warm hangs / fails  
- [ ] `/`, `/app`, `/docs`, `/v1/health` intended post-deploy  
- [ ] `/v1/quote/COMI` manual when provider available (post-deploy)  
- [ ] No secrets in Git  
- [ ] Memory checked vs 512 MB  
- [ ] Docs cover cold starts + in-memory reset  

- [ ] **Step 4: Commit only if docs/Blueprint tweaked for memory**

If Task 6 required `FETCH_QUOTES_ON_STARTUP=false` or doc tweaks:

```bash
git add render.yaml docs/self-hosting.md
git commit -m "fix(render): tune Free-tier startup for 512MB memory budget"
```

Otherwise skip empty commit.

---

## Spec coverage (self-review)

| Spec requirement | Task |
|---|---|
| Git-backed Docker Free Blueprint | 4 |
| Shell `CMD` `${PORT:-8000}` | 3 |
| No conflicting `dockerCommand` | 4 |
| `/v1/health` provider-independent + ≤5s | 1 |
| Non-blocking startup warm | 2 |
| Secrets `sync: false` / never in Git | 4, 5 |
| Free sleep / cold start / ephemeral / 512 MB docs | 5, 6 |
| Acceptance checklist | 6 |
| No `apps/web` / no Redis | Global + non-goals |

No TBD placeholders. Types/paths consistent (`egxdesk.main:app`, `/v1/health`, `mirsad-masr`).
