# Deployment Guide (Docker Compose)

## 1. Prerequisites
- Docker Engine 24+ with Compose plugin
- `config/credentials.json` and `config/keywords.json` present on host

## 2. Environment Setup
1. Copy `docker.env.example` to `.env`.
2. Fill required values:
   - `POSTGRES_PASSWORD`
   - `FACEBOOK_EMAIL` / `FACEBOOK_PASSWORD` (or use `config/credentials.json`)
   - `GEMINI_API_KEY` (if running AI analysis)

## 3. Bring Up the Stack
```bash
docker compose up -d --build
```

Services:
- API: `http://localhost:${API_PORT:-8000}`
- API docs: `http://localhost:${API_PORT:-8000}/docs`
- Dashboard: `http://localhost:${FRONTEND_PORT:-3000}`
- Postgres: `${POSTGRES_PORT:-5432}`

## 4. Verify Health
```bash
docker compose ps
docker compose logs -f api
```

## 5. Common Operations
- Rebuild API only:
```bash
docker compose build api
docker compose up -d api
```

- Run post analyzer:
```bash
docker compose exec api python analyze_posts.py --limit 100
```

- Run comment analyzer:
```bash
docker compose exec api python analyze_comments.py --limit 200
```

- Stop stack:
```bash
docker compose down
```

- Stop and remove volumes (destructive):
```bash
docker compose down -v
```

## 6. Data Persistence
The stack persists data in named volumes:
- `postgres_data` (database)
- `redis_data`
- `scraper_cookies`
- `scraper_logs`

Host-mounted path:
- `./config -> /app/config`

## 7. Production Notes
- Put this behind a reverse proxy (Nginx/Caddy/Traefik) with TLS.
- Restrict `POSTGRES_PORT` exposure at firewall/network level if external access is not needed.
- Rotate Facebook and Gemini credentials regularly.

## 8. CI/CD To DigitalOcean
This repo now includes a GitHub Actions workflow at `.github/workflows/deploy.yml`.

Behavior:
- Every push to `main` runs backend tests and the dashboard build.
- If both pass, GitHub Actions connects to your DigitalOcean server over SSH.
- The server runs `scripts/deploy_on_server.sh`, which pulls the latest `main`, rebuilds the Docker Compose stack, and waits for `GET /health` to return `200`.

### Server Preparation
1. Provision a DigitalOcean droplet with Docker Engine and the Docker Compose plugin.
2. Clone this repository onto the server in a dedicated deploy path, for example `/opt/facebook_scrapper`.
3. In that clone, create `.env` from `docker.env.example` and fill production values.
4. Place persistent config files on the server:
   - `config/credentials.json`
   - `config/keywords.json` if you use it
5. Make sure the deployment user can run Docker commands.
6. Make the deploy script executable once on the server:

```bash
chmod +x scripts/deploy_on_server.sh
```

### GitHub Secrets
Add these repository secrets in GitHub:

- `DO_HOST`: Droplet IP or DNS name
- `DO_USER`: SSH user that owns the deployment checkout
- `DO_PORT`: SSH port, usually `22`
- `DO_SSH_PRIVATE_KEY`: Private key matching the server's authorized key
- `DO_KNOWN_HOSTS`: Output of `ssh-keyscan -H <your-droplet-host>`
- `DO_DEPLOY_PATH`: Absolute path to the repo clone on the server, for example `/opt/facebook_scrapper`

Optional secrets:

- `DO_COMPOSE_FILE`: Compose file path relative to `DO_DEPLOY_PATH` if not `docker-compose.yml`
- `DO_API_HEALTH_URL`: Override health URL if the API is not exposed at `http://127.0.0.1:8000/health`
- `DO_HEALTH_TIMEOUT_SECONDS`: Override deploy health timeout, default `180`

### Recommended First-Time Server Setup
```bash
git clone <your-repo-url> /opt/facebook_scrapper
cd /opt/facebook_scrapper
cp docker.env.example .env
chmod +x scripts/deploy_on_server.sh
docker compose up -d --build
```

### Deployment Assumptions
- The server checkout is dedicated to deployments and has no uncommitted local changes.
- The checkout stays on the `main` branch.
- Docker Compose is the source of truth for production runtime.

If the server working tree is dirty or on the wrong branch, deployment fails intentionally instead of overwriting server-side changes.
