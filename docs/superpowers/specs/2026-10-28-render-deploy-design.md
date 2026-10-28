# Deploy MIRSAD MASR on Render (Git-backed Docker)

**Date:** 2026-10-28  
**Status:** Approved with revisions (pending final spec review)  
**Surface:** FastAPI app (landing + board + `/v1/*` + `/docs`) via existing Dockerfile

## Goal

Deploy the same app that runs locally today to [Render](https://render.com/) as a **Free** Web Service, built from Git with Docker on each push.

Behavior parity:

- Yahoo Finance enabled by default (`ENABLE_YAHOO_FINANCE=true`)
- Optional Alpha Vantage / Finnhub (and demo) keys if set in the Render dashboard — **never** in Git or the image
- CORS default `*` (document: do not combine with credentialed browser requests)
- Same product behavior; hosting limits of Free tier are documented honestly

## Non-goals

- Deploying `apps/web` (Next.js) on Render
- Custom domains (operator can add later in the dashboard)
- Paid Render plans (Blueprint targets Free; operator may upgrade later)
- Renaming the Python package `egxdesk`
- Durable cache / rate-limit storage (Redis, disk) before real usage data justifies it
- Promising always-on market data on Free tier

## Architecture

```
Git push → Render builds ./Dockerfile → Free Web Service
  → sh -c 'uvicorn … --port ${PORT:-8000}'
  → health check GET /v1/health  (app liveness only; ≤5s)
  → public URL https://<service>.onrender.com
```

Single process, no Redis/Postgres. **In-memory cache and demo rate limiter reset** on restart, Free-tier sleep wake, or any ephemeral filesystem recycle. Do not treat them as durable.

### Free-tier hosting caveats (document for operators)

- Sleep after ~15 minutes without inbound traffic; cold start can take ~1 minute
- Ephemeral filesystem; process may restart at any time
- ~512 MB RAM limit — verify the full app fits; do not add infrastructure “for later”
- Free is for hobby / preview, not production SLA

## Components

### 1. `render.yaml` Blueprint

- `type: web`
- `name: mirsad-masr`
- `runtime: docker`
- `plan: free`
- `dockerfilePath: ./Dockerfile`
- `healthCheckPath: /v1/health`
- **Do not** set a conflicting `dockerCommand` if the Dockerfile `CMD` already binds `$PORT` via shell (single source of truth)
- Env: Yahoo on, `DEV_MODE=false`, optional provider secrets as `sync: false`
- Prefer keeping `FETCH_QUOTES_ON_STARTUP` as a background task (see Startup refresh); if Free cold starts still struggle, Blueprint may set it `false` without changing health semantics

### 2. Dockerfile port binding (required)

Hardcoded `--port 8000` fails Render’s port scan. **`${PORT}` only expands in a shell.**

**Durable fix (single CMD for local + Render):**

```dockerfile
CMD ["sh", "-c", "exec uvicorn egxdesk.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

- Local / Compose: `PORT` unset → `8000`
- Render: injected `PORT` (documented default expected port is `10000`; use the value, never hardcode it)

If a Blueprint `dockerCommand` is used instead, it must also run through a shell and must not fight a second startup string in the Dockerfile. Prefer Dockerfile-only.

### 3. Health vs data freshness (required)

| Concern | Mechanism |
|---|---|
| **Application health** (Render deploy gate) | `GET /v1/health` — FastAPI is up; responds successfully within **5 seconds**; **must not** call Yahoo/AV/Finnhub or fail when providers are down |
| **Data freshness** | Shown in the product UI / quote payloads; not used as Render’s health check |

Today `/v1/health` already returns `status=ok`, version, and configured-provider flags without probing upstream. Implementation must **keep** that contract and add a quick verification (test or smoke) that health stays fast under provider failure.

### 4. Startup refresh (required)

Slow Yahoo / `get_all_quotes` **must not** block the process from accepting traffic or passing health checks.

- Startup quote warm must remain **non-blocking** relative to serving (e.g. `asyncio.create_task` after app is ready to accept requests — verify lifespan does not await the full catalog before yield)
- Provider timeouts/failures during warm → log and continue; process stays healthy
- Health check path must not wait on warm completion

### 5. Secrets

- Provider API keys live only in Render Environment / Blueprint `sync: false` dashboard values
- Never commit secrets; never bake keys into the Docker image
- `.env.example` stays a template with empty key values

### 6. Docs

“Deploy on Render” in `docs/self-hosting.md` (or linked `docs/render.md`):

- Connect repo → Blueprint → paste optional keys → open `/`, `/app`, `/docs`
- Free sleep / ~1 min cold start
- In-memory cache & demo limiter reset after restart/sleep
- Free = hobby/preview, not production availability
- Wildcard CORS + credentialed requests: don’t combine

## Environment

| Variable | Source | Notes |
|---|---|---|
| `PORT` | Render (or unset locally) | Shell `CMD` uses `${PORT:-8000}` |
| `ENABLE_YAHOO_FINANCE` | Blueprint `true` | Matches “works as now” |
| `DEV_MODE` | Blueprint `false` | Production logging |
| `HOST` | Optional | Uvicorn host is set in `CMD` |
| `CORS_ORIGINS` | `*` or omit | App default `*`; no credentials pairing |
| Cache / refresh | Defaults | Background warm only; may tune `FETCH_QUOTES_ON_STARTUP` for Free if needed |
| `ALPHA_VANTAGE_KEY`, `FINNHUB_KEY` | Dashboard secrets | Optional; never in Git |
| `DEMO_*` keys / limit | Dashboard / Blueprint | Optional |

## Failure modes

| Issue | Mitigation |
|---|---|
| Port probe fails | Shell `CMD` with `${PORT:-8000}` on `0.0.0.0` |
| Health >5s or provider-coupled | Keep `/v1/health` free of upstream I/O; verify with test |
| Slow Yahoo blocks ready | Non-blocking startup warm; health independent of warm |
| Free idle sleep | Document ~15 min sleep / ~1 min cold start |
| Ephemeral restart | Document in-memory state loss |
| OOM on 512 MB | Test full app under Free memory budget before promising scale |
| Secrets leak | `sync: false` only; no keys in image/Git |

## Acceptance checklist (before merge / ship)

- [ ] `render.yaml` validates against Render’s Blueprint specification
- [ ] Docker builds successfully; container responds on default **8000** and on an injected `PORT`
- [ ] App starts even if an external market-data provider fails or times out
- [ ] `/`, `/app`, `/docs`, and `/v1/health` work after deployment
- [ ] `/v1/quote/COMI` tested when a provider is available
- [ ] No secrets committed; wildcard CORS not combined with credentialed browser requests
- [ ] Memory use tested against Render Free’s **512 MB** limit (or documented measurement / local comparable run)
- [ ] Documentation explains cold starts and loss of in-memory state after restarts

## Operator steps (after merge)

1. Push repo to GitHub/GitLab  
2. Render Dashboard → New → Blueprint → select repo  
3. Apply Blueprint; paste optional API keys in Environment  
4. Wait for deploy; open the `onrender.com` URL  
5. Expect Free-tier sleep after idle; first request may be slow  

## Verdict

Keep the existing single-service Docker architecture. Address **port**, **provider-independent health**, **non-blocking startup refresh**, and **512 MB / Free caveats** in implementation and docs. Do not add Redis or extra infrastructure before real usage data.
