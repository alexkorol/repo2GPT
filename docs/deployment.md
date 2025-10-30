# Deployment guide

This guide describes a minimal setup for hosting the FastAPI service (`api/server.py`) and the new Vite/React control panel (`web/`) together. Each section outlines environment variables, build commands, and routing considerations.

## Shared prerequisites

- Configure a persistent storage volume (or mounted disk) for the repo snapshot workspace. Set `REPO2GPT_STORAGE_ROOT` to point at that path.
- Generate a strong API token and expose it as `REPO2GPT_API_KEY`. The web UI expects the same token during sign-in.
- Build the web app prior to deployment:

  ```bash
  cd web
  npm install
  npm run build
  ```

  The compiled assets will be emitted into `web/dist/`. Serve this directory via any static hosting mechanism and reverse proxy `/api` requests to the FastAPI server.

- Expose the API over HTTPS and ensure CORS allows the web origin. The FastAPI application inherits `REPO2GPT_API_KEY`; no extra configuration is required when both services share the same domain.

## Google Cloud Run

1. **Container image**
   - Extend the provided `Dockerfile` to install Node.js, build the web bundle, and copy `web/dist` into the image.
   - Serve the static assets with something lightweight (e.g., `uvicorn` + `fastapi.staticfiles` or `nginx`). Alternatively, host the UI on Firebase Hosting and run only the API on Cloud Run.
2. **Runtime configuration**
   - Set environment variables `REPO2GPT_API_KEY` and `REPO2GPT_STORAGE_ROOT` via the Cloud Run service configuration.
   - Attach a Cloud Storage bucket or Filestore instance, mount it into the container, and point `REPO2GPT_STORAGE_ROOT` to the mount path to persist job artifacts.
3. **Routing**
   - If bundling UI + API, mount the `web/dist` assets at `/` and proxy API calls to `/api/*` → Uvicorn (e.g., by running a small ASGI app that mounts `StaticFiles(directory="web/dist", html=True)` and includes the FastAPI router under `/api`).

## Render

1. **Web service**
   - Create a Render Web Service from the repository.
   - Use a start command similar to `bash run.sh` after augmenting `run.sh` to perform `npm install && npm run build` and to serve the compiled UI (for example, via `uvicorn main:app --host 0.0.0.0 --port $PORT`).
2. **Static site**
   - Alternatively, provision a separate Render Static Site that runs `npm install && npm run build` in the `web/` directory and serves `web/dist`. Pair it with a Web Service running the API and configure a custom domain/subdomain for each.
3. **Environment variables**
   - Add `REPO2GPT_API_KEY` and `REPO2GPT_STORAGE_ROOT` (pointing to the built-in persistent disk) in the Render dashboard.

## Heroku

1. **Buildpack selection**
   - Add the official Node.js buildpack first to compile the Vite bundle, then Python to install the FastAPI dependencies.
   - Use a `heroku-postbuild` script inside `web/package.json` or a root-level `Procfile` command to run `npm install --prefix web && npm run build --prefix web` before launching the server.
2. **Procfile**
   - Example: `web: uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Extend `main.py` (or create a dedicated ASGI entry point) that mounts the static files from `web/dist` and includes the API router under `/api` so that Heroku serves both UI and backend from one dyno.
3. **Persistent storage**
   - Heroku’s ephemeral filesystem resets on each deploy. Use an S3 bucket or another external storage provider for `REPO2GPT_STORAGE_ROOT` (e.g., via `s3fs` or by overriding the job store implementation) if persistence is required.

## Reverse proxy recommendations

- When serving the UI and API together, prefer the following structure:
  - `/` → static assets from `web/dist/index.html`
  - `/assets/*` → other static resources from `web/dist`
  - `/api/*` → FastAPI application (`api/server.py`)
- Ensure the proxy forwards the `X-API-Key` header untouched so that SSE subscriptions and artifact downloads remain authenticated.
- Configure HTTPS and enable HTTP/2 where possible for smoother SSE streaming.

## Operational tips

- Scale the API replicas cautiously; the job store currently uses disk-backed state. For multi-instance deployments, consider migrating to a shared database or object store.
- Monitor worker CPU and memory. Repo snapshotting can be resource-intensive, especially for large archives. Cloud Run and Render allow you to select higher CPU/memory tiers per instance.
- Surface API logs (e.g., via Cloud Logging, Render logs, or Heroku’s Logplex) to observe job progress and diagnose failures reported in the UI’s event timeline.
