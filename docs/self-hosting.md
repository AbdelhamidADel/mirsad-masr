---
title: Self-hosting
description: How to run MIRSAD MASR on your own server
---

# Self-hosting

MIRSAD MASR is designed to run anywhere Docker runs — a VPS, a home server, Fly.io, Railway, Render, or any container platform.

## Requirements

- Docker + Docker Compose, **or** Python 3.12+ with `uv`
- At least one provider API key (Yahoo Finance works with no key)

## Docker Compose (recommended)

```bash
git clone https://github.com/your-username/egxdesk.git mirsad-masr
cd mirsad-masr
cp .env.example .env
# Edit .env and add your keys
docker compose up -d
```

The service starts on port `8000`. Map a different host port by editing `docker-compose.yml`:

```yaml
ports:
  - "3000:8000"   # host:container
```

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

## Using a published image

CI can publish a Docker image to your container registry on each push to `main`.
Pull your own tag (set `MIRSAD_MASR_IMAGE` or substitute below):

```bash
docker pull ghcr.io/<owner>/<image>:latest
```

On the demo server, run that image behind your reverse proxy:

```yaml
services:
  mirsad-masr:
    image: ghcr.io/<owner>/<image>:latest
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
```

For `https://demo.egxdesk.ashh.me`, set the API environment to allow the Vercel
frontend origin:

```dotenv
CORS_ORIGINS=https://egxdesk.ashh.me
CORS_ORIGIN_REGEX=https://.*\.vercel\.app
```

The regex is optional, but useful if you want Vercel preview deployments to call
the same demo API.

## Running with uv

```bash
uv sync
cp .env.example .env
uv run uvicorn egxdesk.main:app --host 0.0.0.0 --port 8000
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ALPHA_VANTAGE_KEY` | _(empty)_ | Alpha Vantage key, disabled if empty |
| `FINNHUB_KEY` | _(empty)_ | Finnhub key, disabled if empty |
| `ENABLE_YAHOO_FINANCE` | `false` | Enable unofficial Yahoo Finance/yfinance fetching |
| `CACHE_TTL_SECONDS` | `300` | Cache entry lifetime in seconds |
| `DEMO_CACHE_TTL_SECONDS` | `600` | Demo cache entry lifetime in seconds |
| `CACHE_MAX_SIZE` | `512` | Maximum cached entries |
| `FETCH_QUOTES_ON_STARTUP` | `true` | Fetch all `/v1` quotes when the app starts |
| `AUTO_REFRESH_QUOTES` | `true` | Force-refresh all `/v1` quotes every cache TTL |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Bind port |
| `LOG_LEVEL` | `info` | `debug` · `info` · `warning` · `error` |
| `CORS_ORIGINS` | `*` | Comma-separated browser origins allowed to call the API |
| `CORS_ORIGIN_REGEX` | _(empty)_ | Optional regex for preview domains, for example Vercel |

## Reverse proxy (nginx example)

```nginx
server {
    listen 80;
    server_name demo.egxdesk.ashh.me;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Health check

```bash
curl http://localhost:8000/v1/health
```

Expected: `{"status":"ok", ...}`
