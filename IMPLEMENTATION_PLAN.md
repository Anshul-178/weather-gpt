# WeatherGPT — Implementation Plan

## 1. Current Project State

- Repository contains only: `prd.md`, `technical.md`, and the development-prompt PDF.
- No existing code, no git history, no `.env`, no existing integrations.
- Local environment: Python 3.13.7, pip 26.1.2, Flutter SDK at `C:\flutter\sdk\flutter` (folder is not a git repo yet).
- Nothing to preserve; a clean monorepo will be created per `technical.md` §4.

## 2. Architecture

```
Flutter app ──HTTPS──► FastAPI backend ──► Weather provider (Open-Meteo)
                                  ├──► LLM provider (OpenAI-compatible / rule fallback)
                                  ├──► PostgreSQL (SQLAlchemy, users/locations/alerts/chat)
                                  └──► Redis cache (optional at runtime)
```

Key rule (from prompt §9, technical.md §36): the weather provider is the **source of truth**; the LLM only interprets structured weather context and must never invent weather values.

## 3. Weather Provider Choice

`technical.md` leaves the provider configurable via `WEATHER_API_BASE_URL` / `WEATHER_API_KEY`. This implementation uses **Open-Meteo** as the default provider because it requires no paid API key (the prompt forbids paying for services without approval) and supports current weather, multi-day/hourly forecast, and geocoding. The provider is isolated behind `weather_service.py`, so swapping to another provider (WeatherAPI.com, OpenWeather) only requires changing that one module plus env vars.

## 4. Backend Implementation Order

1. Config (`pydantic-settings`), logging, utils (units, validation, geo)
2. Pydantic schemas (weather, chat, activity, alerts, locations, auth)
3. Cache service (Redis with graceful in-memory fallback)
4. Weather service: current, forecast, geocoding → `/weather/*` routes
5. AI module: `prompts.py`, `intents.py`, `retriever.py`, `ai_service.py`
6. `/chat` route with bounded conversation context and follow-up resolution
7. Activity engine (configurable scoring) → `/weather/activity-score`, `/weather/compare`, `/weather/best-time`
8. Alert engine (deterministic rules) → `/alerts` routes + background scheduler
9. PostgreSQL models (User, Location, AlertPreference, Conversation, Message), auth (JWT + bcrypt) → `/auth`, `/locations`
10. `main.py`: error handlers, CORS, rate limiting, request IDs, `/health`

## 5. AI Implementation Order

1. System prompt module enforcing "provider data is truth, never invent values"
2. Deterministic intent detection (rule-based, no LLM cost for trivial queries)
3. Weather-context builder (current + daily + hourly slices, best/worst windows)
4. LLM service (OpenAI-compatible HTTP API via httpx, isolated); graceful rule-based fallback answer when no `LLM_API_KEY` is configured so the app remains usable
5. RAG: modular `retriever.py` with a Chroma-based implementation behind a factory (optional dependency), used only for reference/safety info — never for live weather values
6. Response validation and bounded conversation history

## 6. Database Implementation Order

1. SQLAlchemy engine/session, base models
2. Users → Locations → AlertPreferences → Conversations → Messages with proper relationships
3. Optional auth dependency (`get_current_user_optional`): MVP endpoints work without login, saved locations/alerts/chat history require a user
4. Migrations: Alembic placeholder directory (SQLite default for local dev, PostgreSQL via `DATABASE_URL`)

## 7. Flutter Implementation Order

1. `pubspec.yaml` with http, provider, shared_preferences, intl
2. Models (current weather, forecast, chat, location, activity score)
3. `api_service.dart` (single HTTP client, base URL from config, timeouts, errors)
4. Repository + ChangeNotifier providers
5. Screens: Home (current + summary + alert banner + hourly strip), Chat (suggested questions, loading/error states), Forecast (hourly/daily lists), Locations (search/save/switch/delete), Settings
6. Config via `--dart-define=API_BASE_URL=...` (no secrets in the app)

## 8. Alert Implementation

Deterministic rule engine with configurable thresholds (rain, heavy rain, thunderstorm, heat, strong wind, poor visibility, high UV, severe weather). `/alerts` CRUD for preferences; `/alerts/check` evaluates rules against live weather; an asyncio background scheduler runs the check periodically (disabled when `ALERT_SCHEDULER_ENABLED=false`). The LLM may only explain an alert after the rule engine triggers it.

## 9. Testing Strategy

- Unit: normalization, unit conversion, activity scores, alert thresholds, prompt building, validation, geocoder parsing
- API (pytest + httpx `TestClient`, mocked provider/LLM/cache): success + failure + timeout paths, 400/401/404/429/500/503 handling
- No network or external services required in CI; all external calls mocked

## 10. Deployment Strategy

- Backend: `Dockerfile` (slim Python image, uvicorn), `docker-compose.yml` for FastAPI + PostgreSQL + Redis
- Production: Nginx TLS proxy in front of uvicorn (documented in README)
- Flutter: standard release build with `--dart-define` pointing at the HTTPS API

## 11. Dependencies

Backend: fastapi, uvicorn, pydantic, pydantic-settings, httpx, SQLAlchemy (async), aiosqlite, asyncpg, redis, pyjwt, passlib[bcrypt], chromadb (optional), pytest, pytest-asyncio.
Flutter: http, provider, shared_preferences, intl.

## 12. Environment Variables

`WEATHER_API_KEY`, `WEATHER_API_BASE_URL`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `FIREBASE_PROJECT_ID` — all with placeholders in `.env.example`, real values never committed.

## 13. Potential Risks

- No LLM key available → rule-based fallback answers keep the product usable (clearly labeled)
- Redis/Postgres unavailable locally → cache falls back to in-memory; SQLite default DB
- Open-Meteo outage → clean 503 responses, never fabricated data
- Rate limiting per-process (in-memory) → document Redis-based limiting for multi-instance deploys

## 14. Milestones

1. M1 — Backend foundation: `/health`, config, schemas ✅ target first
2. M2 — Weather service + cache + endpoints
3. M3 — AI chat with live weather context
4. M4 — Activity engine, comparison, best-time
5. M5 — Database, auth, locations, alerts
6. M6 — Tests green, server verified end-to-end
7. M7 — Flutter app source complete
8. M8 — Docker, docs, final validation checklist
