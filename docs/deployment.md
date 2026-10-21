# Deployment

## What has to be true

Four things, in this order:

1. A unique `SECRET_KEY`. Anyone holding the default can mint a valid token for
   any tenant.
2. `ENVIRONMENT=production` and `DEBUG=false`.
3. Migrations applied, not `create_all()`.
4. Real datasets loaded, or the platform is a very elaborate way of displaying
   synthetic data.

The application refuses to start if 1 or 2 is not met. That is a settings
validator, not a startup check, so it fails at import before a socket is opened.

---

## Local development

No container required.

```bash
cd backend
python -m venv .venv && .\.venv\Scripts\activate   # Windows
pip install -e ".[dev]"

cd ..
export DATABASE_URL=sqlite:///./geothermal.db
python -m scripts.cli init
python -m scripts.cli bootstrap
python -m scripts.cli seed-user --email you@example.com --password "a-strong-one"

cd backend && uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

### With PostGIS, Redis and MinIO

```bash
docker compose -f infra/docker-compose.yml up -d

export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ukgeothermal
export REDIS_URL=redis://localhost:6379/0
python -m scripts.cli init --migrate
```

| Service | Port | Purpose |
|---|---|---|
| `db` | 5432 | PostgreSQL 16 + PostGIS 3.4 |
| `redis` | 6379 | Rate limiting and caching. No persistence by design — a full disk should degrade the cache, not resurrect stale entries |
| `minio` | 9000, 9001 | Object storage for well logs |

`infra/up.sh` runs the compose file and explains the SQLite alternative when
Docker is absent.

---

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `development`/`test`/`staging`/`production` |
| `DEBUG` | `true` | Must be `false` in production |
| `SECRET_KEY` | development value | **Must** be changed. Rejected at startup in production |
| `DATABASE_URL` | `postgresql+psycopg://…` | `sqlite:///./file.db` for local |
| `SQL_ECHO` | `false` | |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | 10, 20 | Ignored on SQLite |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `RATE_LIMIT_ENABLED` | `true` | |
| `RATE_LIMIT_PER_MINUTE` | `120` | Per caller identity |
| `CORS_ORIGINS` | `http://localhost:3000,…` | Comma-separated. Set to the real frontend origin |
| `AI_PROVIDER` | `auto` | `auto` = MiMo, then Anthropic, then mock. Pin `mimo`, `anthropic` or `mock`; an unknown value refuses to start |
| `ANTHROPIC_API_KEY` | unset | Absent → the next provider is tried. **Numbers are identical with any provider** |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | |
| `MIMO_API_KEY` | unset | Xiaomi MiMo key (platform.xiaomimimo.com). Absent → the next provider is tried |
| `MIMO_BASE_URL` | `https://api.xiaomimimo.com/v1` | OpenAI-compatible chat completions endpoint |
| `MIMO_MODEL` | `mimo-v2.6-flash` | Use V2.6 model IDs; the V2.5 IDs were retired on 2026-10-21 |
| `AI_ENABLED` | `true` | |
| `AI_MAX_TOKENS` | `4096` | |
| `AI_TEMPERATURE` | `0.0` | Do not raise. An agent that varies between runs cannot be used to review a decision |
| `OBJECT_STORAGE_*` | MinIO defaults | |
| `DEFAULT_PROJECT_LIFETIME_YEARS` | `20` | Assumption |
| `DEFAULT_ELECTRICITY_PRICE_P_PER_KWH` | `15.0` | Assumption |
| `DEFAULT_HEAT_PRICE_P_PER_KWH` | `8.5` | Assumption |
| `DEFAULT_DISCOUNT_RATE` | `0.08` | Assumption |

Frontend:

| Variable | Default | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api/v1` | Empty-relative routes through the rewrite proxy |
| `BACKEND_ORIGIN` | `http://localhost:8000` | Proxy target |
| `API_PROXY` | unset | `false` disables the rewrite |
| `NEXT_PUBLIC_MAP_STYLE` | unset (OpenFreeMap `liberty`) | `https` style URL for a custom basemap. `mapbox://…` is rejected; unreachable → OSM raster fallback, surfaced in the UI |

---

## Migrations

```bash
cd backend
python -m alembic upgrade head
python -m alembic current
python -m alembic downgrade -1
```

Run migrations as a release step, not on application start. Two replicas starting
simultaneously and racing to migrate is a well-known way to have a bad afternoon,
and Alembic takes a lock precisely because it expects to be the only thing doing
it.

`backend/alembic/env.py` reads the URL from application settings rather than
`alembic.ini`, so migrations and the application cannot disagree about the
database.

`render_as_batch` is enabled on SQLite so a single migration is valid on both
backends. Without it the test suite would validate a schema production never
sees.

PostGIS and pgvector are created outside Alembic's transaction with dialect
guards, because `CREATE EXTENSION` cannot run inside a transaction in every
setup and SQLite must not attempt it. The database user needs superuser for this
step, or an administrator can run it once:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
```

---

## Backend deployment

### Container

No Dockerfile exists yet. The shape:

```dockerfile
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
RUN useradd --create-home --uid 10001 app

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY scripts ./scripts
RUN pip install --no-cache-dir .

COPY backend/alembic ./alembic
COPY backend/alembic.ini ./

USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

Install system dependencies first (`libpq5` for psycopg, `libgeos` for anything
spatially aware). Run migrations as a separate pre-deploy job, not in `CMD`.

### Without containers

```bash
pip install -e .
export ENVIRONMENT=production DEBUG=false SECRET_KEY=...
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

`--workers` matters: the in-process rate-limit fallback is correct for one worker
and wrong for several. With more than one worker, Redis must be reachable or
`RATE_LIMIT_ENABLED` must be false.

### Health

`GET /api/v1/admin/health` returns database, spatial dialect, Redis and LLM
provider status. Use it for liveness; use a database round trip for readiness.

---

## Frontend deployment

```bash
cd frontend
npm run build     # requires NEXT_PUBLIC_* to be set at build time
npm start
```

`NEXT_PUBLIC_*` variables are inlined at build time, not read at runtime.
Changing one requires a rebuild.

`next.config.mjs` proxies `/api/*` to `BACKEND_ORIGIN` so the browser sees one
origin. Set `API_PROXY=false` to call the backend directly, in which case
`CORS_ORIGINS` on the backend must include the frontend origin.

### Static export

Not supported: `AppProvider` and the API client read `window.localStorage` for
the token. A static export would have to move authentication to an httpOnly
cookie.

---

## Background work

Analyses run synchronously today and complete in a few seconds. If you need them
asynchronously, the pieces are already separated:

- `services/analysis_service.run_assessment()` takes an explicit `Session` and
  commits its own work, so it runs unchanged inside a worker loop.
- `analyses.status` (`pending`/`running`/`complete`/`failed`) and
  `GET /analyses/{id}/progress` already model an in-flight run.
- `analysis_service.progress_for()` derives the stage view from stored state.

A worker would poll for `status='pending'` rows, claim one, and set it to
`running`. The `workers/` directory is the intended home. Do not put a queue in
place before it is needed — at current volume the synchronous path is faster and
has one fewer thing to fail.

---

## Scaling notes

**Database.** The expensive queries are the dashboard aggregates and the
map-feature fetch, both of which are `limit`-bounded and indexed. The candidate
table joins to the latest analysis per well on `(well_id, created_at)`.

**Spatial.** On PostgreSQL, `earth_distance` over a `geography(Point)` index
answers the nearest-demand query without a sort. On SQLite the haversine
expansion is a full scan — fine at development scale, not at 40,000 wells with
millions of buildings. This is the main reason to move to PostGIS before a real
ingest.

**Rate limiting.** Redis-backed and per caller identity. Set it up before
scaling past one worker.

**Agents.** The slowest part of an analysis, and the only part that calls out to
a third party. Because agents never produce numbers, the design tolerates them
being disabled entirely — the assessment still returns, with `agent_outputs`
null and a note that the interpretation could not be produced.

---

## Security checklist

- [ ] `SECRET_KEY` is unique and random. Generate with
      `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- [ ] `ENVIRONMENT=production`, `DEBUG=false`. Both are enforced at startup.
- [ ] `CORS_ORIGINS` lists the real frontend origin, not `*`.
- [ ] `SECRET_KEY` is not in version control or an image layer.
- [ ] Database credentials are not defaults.
- [ ] API keys are issued per system, scoped `read` where read is enough, and
      rotated.
- [ ] Audit logs are retained and shipped somewhere they cannot be edited.
- [ ] TLS terminated in front of both services.
- [ ] `robots: noindex` is in place (it is in `layout.tsx`).
- [ ] Real dataset licences confirmed before ingest.

---

## Monitoring

Worth watching:

- `X-Is-Mock-Data` on responses. If a production deployment starts serving
  synthetic data, that header says so, and so does `/admin/health`.
- `spatial_dialect`. If a PostGIS deployment reports `haversine`, the connection
  string has changed and queries are about to get much slower.
- Adapter `records_rejected`. A spike means a source changed shape.
- `violations` counts from agent runs. A rise means the model is drifting toward
  the things the gate exists to catch.

Not worth watching: agent latency. It is bounded by the third party and does not
affect any figure.