# Deploying the full app

GitHub Pages hosts only the static well map (`site/`). The assessment platform
needs a database and a Python API, so it runs on three free services:

| Part | Service | Why |
|---|---|---|
| Database | Neon (Postgres + PostGIS + pgvector) | Free, and the app's production target |
| API | Render | Runs the FastAPI backend from `render.yaml` |
| Website | Vercel | Runs the Next.js frontend |

Do the steps in this order; each one produces something the next needs.

## 1. Database (Neon)

1. Sign up at neon.tech and create a project in **AWS Europe (London)**.
2. Copy the connection string from the dashboard exactly as shown. The app
   rewrites `postgresql://` to the right driver itself, and creates the
   `postgis` and `vector` extensions during the migration.

## 2. Load the data (GitHub Actions)

In the repository: **Settings > Secrets and variables > Actions > New
repository secret**. Add:

- `DATABASE_URL`: the Neon string
- `ADMIN_EMAIL`: the email you will log in with
- `ADMIN_PASSWORD`: at least 12 characters

Then **Actions > Load database > Run workflow**. It applies the schema, loads
the 2,138 real NSTA wells, creates the login and runs the assessments
(about three minutes). It is safe to run again.

## 3. API (Render)

1. Sign up at render.com with GitHub. **New > Blueprint**, select this repo.
2. Render reads `render.yaml` and asks for two values:
   - `DATABASE_URL`: the same Neon string
   - `CORS_ORIGINS`: put `https://placeholder.vercel.app` for now
3. When it is live, open `https://<your-service>.onrender.com/api/v1/admin/health`.
   You should see `"status":"ok"` and `"spatial_dialect":"postgis"`.

The free tier sleeps after 15 minutes idle; the first request after that takes
roughly 30 to 60 seconds.

## 4. Website (Vercel)

1. Sign up at vercel.com with GitHub. **Add New > Project**, select this repo.
2. Set **Root Directory** to `frontend`.
3. Add one environment variable:
   `NEXT_PUBLIC_API_URL` = `https://<your-service>.onrender.com/api/v1`
4. Deploy and note the URL Vercel gives you.

## 5. Connect them

In Render, change `CORS_ORIGINS` to the Vercel URL (no trailing slash) and let it
redeploy. Without this the browser blocks the website from calling the API.

## Licence

The NSTA data is used under the NSTA User Agreement: non-commercial use only,
with the attribution statement in `data/real/nsta/README.md`.

## Troubleshooting a failed Render deploy

**"Exited with status 1" during the build.** Render ran the build somewhere with no
Python project file. Open the service's **Settings** and check:

| Setting | Value |
|---|---|
| Root Directory | `backend` |
| Build Command | `pip install . && alembic upgrade head` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

A root-level `requirements.txt` also lets a build from the repository root succeed,
but setting the root directory is the intended configuration. After changing a
setting, use **Manual Deploy > Clear build cache & deploy**.

**The build passes but the service will not start.** The API refuses to start in
production unless every one of these environment variables is set:

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |
| `SECRET_KEY` | a long random string (`python -c "import secrets;print(secrets.token_urlsafe(48))"`) |
| `DATABASE_URL` | the Neon connection string, as copied |
| `CORS_ORIGINS` | the website's address, with no trailing slash |

The service log (Render > Logs) names the missing or invalid one.
