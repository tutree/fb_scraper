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
