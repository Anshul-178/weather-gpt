# WeatherGPT ⛅🤖

**Don't just tell users what the weather is. Tell them what it means for what they want to do.**

WeatherGPT is an AI-powered weather assistant: real-time weather data + forecasts + an LLM that
explains the data, plus activity recommendations, weather comparison, and deterministic weather
alerts. The weather provider is always the source of truth — the AI never invents weather values.

---

## Features

- 🌡️ **Current weather** — temperature, feels-like, humidity, wind, pressure, visibility, UV, condition
- 📅 **Forecast** — hourly + 7-day (up to 16 days) forecasts, with **NWP model selection**
  (GFS, ECMWF IFS, DWD ICON, UKMO, GEM, JMA via `?model=`)
- 💬 **AI chat** — ask *"Will it rain today?"*, *"What should I wear?"*, *"What about the evening?"*
  (follow-up questions keep location/date context)
- 🗣️ **Voice + multilingual** — STT and neural TTS in **9 Indian languages** (English, Hindi, Tamil,
  Telugu, Bengali, Marathi, Kannada, Malayalam, Gujarati), auto-detected from script
- 🏃 **Activity engine** — explainable 0–100 weather impact score for cycling, running, cricket,
  hiking, picnic, driving, and more, with best-time-of-day recommendation
- ⚖️ **Weather comparison** — two locations, computed from actual data
- 🚨 **Alerts** — deterministic rule engine (rain, heavy rain, thunderstorm, heat, wind, visibility,
  UV, cold, **flood risk**, **cyclone-strength winds**) with user-configurable thresholds and a
  background scheduler that **pushes to devices** (FCM; dry-run logging without credentials)
- 📲 **Push notifications** — device token registration, area-targeted broadcast, dispatch log
- 🌊 **Real-time WebSocket** — `/ws/weather` streams live conditions for monitoring dashboards
- 📈 **Climate trends & history** — Open-Meteo Archive-powered historical weather, monthly climate
  aggregates, warming trend (°C/decade), and current-month anomaly
- 🌾 **Crop advisories** — deterministic irrigation/spraying/disease/harvest guidance for 10 Indian
  crops from live forecast data
- ✈️ **Aviation briefing** — VFR-style go/no-go assessment with best-flight-window suggestions
- 🏙️ **City overview** — current conditions + AQI across 10 Indian cities (smart-city monitoring)
- 📍 **Locations** — search (geocoding), save, switch, delete
- 🔐 **Auth** — JWT with bcrypt-hashed passwords
- 🧠 **Optional RAG** — Chroma-backed reference retrieval (never a replacement for live weather data)

## Architecture

```
Flutter app ──HTTPS/WS──► FastAPI backend ──► Weather provider (Open-Meteo + Archive)
                                ├──► LLM (OpenAI-compatible, optional)
                                ├──► PostgreSQL (users, locations, alerts, chat, devices)
                                ├──► Redis cache (in-memory fallback)
                                └──► Firebase Cloud Messaging (push alerts)
```

**Core rule:** `Weather API → facts · LLM → explanation`. If the provider is down, the API returns
a clean "data unavailable" answer — the AI never fabricates weather values.

## Repository layout

```
weathergpt/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app: middleware, errors, routers
│   │   ├── config.py             # Environment-driven settings
│   │   ├── api/                  # Route handlers (thin)
│   │   ├── services/             # Business logic (weather, cache, AI, activity, alerts…)
│   │   ├── ai/                   # prompts, intent detection, RAG retriever
│   │   ├── models/               # SQLAlchemy ORM models
│   │   ├── schemas/              # Pydantic schemas
│   │   ├── database/             # Engine, sessions, base
│   │   └── utils/                # units, validation, geo, rate limit, logging
│   ├── tests/                    # pytest suite (47 tests)
│   ├── requirements.txt
│   ├── .env.example
│   ├── pytest.ini
│   └── Dockerfile
├── mobile/flutter_app/           # Flutter client
│   └── lib/                      # screens / providers / repositories / services / models
├── docker-compose.yml            # api + postgres + redis
├── prd.md  ·  technical.md  ·  IMPLEMENTATION_PLAN.md
└── README.md
```

## Requirements

- Python 3.11+ (tested on 3.13)
- Flutter SDK 3.22+ (Android toolchain for emulators)
- Docker (optional, for PostgreSQL + Redis)
- No weather/LLM API keys required to start: the default weather provider is
  [Open-Meteo](https://open-meteo.com) (free, no key) and the AI works without an LLM key using a
  deterministic rule-based responder. Add an `LLM_API_KEY` for richer natural-language answers.

## Backend setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows (Git Bash / PowerShell)
# .venv/bin/pip install -r requirements.txt       # Linux/macOS

cp .env.example .env                              # fill in values as needed

.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

- API: http://127.0.0.1:8000
- Interactive docs (Swagger): http://127.0.0.1:8000/docs

By default the backend uses SQLite (`./weathergpt.db`) and an in-memory cache — no PostgreSQL/Redis
needed for local development.

## Weather provider endpoints

The backend uses [Open-Meteo](https://open-meteo.com) by default. No API key is required for
non-commercial use. The exact provider endpoints used are:

| Provider | Endpoint |
|---|---|
| Weather Forecast API | `https://api.open-meteo.com/v1/forecast` |
| Air Quality API | `https://air-quality-api.open-meteo.com/v1/air-quality` |
| Geocoding API | `https://geocoding-api.open-meteo.com/v1/search` |

These are configured through `backend/.env.example`. If you switch providers, update
`WEATHER_API_BASE_URL` / `AIR_QUALITY_API_BASE_URL` / `GEOCODING_API_BASE_URL` there.

## Environment variables

See `backend/.env.example` (placeholders only — never commit a real `.env`):

| Variable | Purpose |
|---|---|
| `WEATHER_API_KEY` / `WEATHER_API_BASE_URL` | Weather provider (Open-Meteo default, key optional) |
| `AIR_QUALITY_API_BASE_URL` | Open-Meteo Air Quality API base URL |
| `GEOCODING_API_BASE_URL` | Open-Meteo Geocoding API base URL |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | Any OpenAI-compatible LLM (optional) |
| `DATABASE_URL` | `postgresql+asyncpg://…` in production; SQLite default in dev |
| `REDIS_URL` | Redis cache; falls back to in-memory if unreachable |
| `JWT_SECRET` | Token signing secret (change in production!) |
| `ALERT_SCHEDULER_ENABLED` | Enable background alert checker |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | FCM service-account JSON (inline or file path); without it pushes run in dry-run mode |
| `RAG_ENABLED` / `CHROMA_DIR` | Optional RAG module |

## Flutter setup

```bash
cd mobile/flutter_app
flutter pub get
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
```

`10.0.2.2` is the Android-emulator alias for your host machine. For a physical device use your
PC's LAN IP. **No API keys are ever embedded in the app** — all third-party secrets stay on the
backend.

Screens: **Home** (current weather, hourly strip, 7-day list), **AI Chat** (suggested questions,
loading/error states, conversation memory), **Forecast** (hourly + daily details), **Locations**
(search/save/switch/delete), **Settings** (activity score checker, login/register, privacy info).

## Database

SQLAlchemy async models: `User`, `Location`, `AlertPreference`, `Conversation`, `Message` with
proper relationships and cascade rules. Tables are created on startup; use Alembic for production
migrations. To use PostgreSQL, set `DATABASE_URL` (see `.env.example`).

## Testing

```bash
cd backend
.venv/Scripts/python -m pytest -q
```

47 tests cover: weather normalization, provider timeout/error mapping, caching behaviour, chat
flow (including the no-data guardrail), intent detection, activity scoring, alert thresholds and
boundary conditions, auth CRUD, and input validation. All external calls are mocked — no network
required.

## API overview

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/weather/current?latitude=&longitude=` | Normalized current weather |
| GET | `/weather/forecast?latitude=&longitude=&days=7` | Daily + hourly forecast |
| GET | `/weather/search?query=kanpur` | Geocoding search |
| POST | `/weather/activity-score` | Explainable activity score |
| POST | `/weather/compare` | Two-location comparison |
| GET | `/weather/best-time?activity=cycling` | Best time window |
| GET | `/weather/historical?days=30` | Historical daily observations (archive) |
| GET | `/weather/climate?years=5` | Monthly climate aggregates + warming trend |
| POST | `/weather/crop-advisory` | Deterministic crop-weather advisories |
| POST | `/weather/aviation` | VFR-style aviation briefing |
| GET | `/weather/city-overview` | Multi-city current conditions + AQI |
| GET | `/weather/models` | Selectable NWP models |
| GET | `/weather/forecast?model=gfs_seamless` | Forecast from a specific NWP model |
| POST | `/chat` | AI weather Q&A (weather context injected) |
| POST | `/chat/tts` | Neural TTS in 9 Indian languages |
| WS | `/ws/weather?latitude=&longitude=` | Live weather stream |
| GET/POST | `/locations`, `DELETE /locations/{id}` | Saved locations (auth) |
| GET/POST/PATCH/DELETE | `/alerts…`, POST `/alerts/check` | Alert preferences + rule check |
| POST | `/notifications/register` | Register device for push alerts |
| POST | `/notifications/broadcast` | Disseminate an alert (auth) |
| GET | `/notifications/log` | Recent dispatch records (auth) |
| POST | `/auth/register`, `/auth/login` | JWT auth |

Errors use a clean envelope: `{"error": {"code": "...", "message": "..."}}` — provider failures map
to `503`, rate limits to `429`, validation to `400`. Full OpenAPI docs at `/docs`.

## Docker

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

Brings up FastAPI (port 8000) + PostgreSQL + Redis with the right environment wiring.

## Kubernetes

```bash
kubectl apply -f k8s/weathergpt.yaml
```

Namespace-scoped stack: API (2–8 replicas, HPA) + PostgreSQL (PVC) + Redis + Ingress with
WebSocket-friendly timeouts.

## Security

- All third-party API keys are server-side only; the Flutter app holds none
- `.env` is git-ignored; `.env.example` contains placeholders
- CORS, per-IP rate limiting (stricter for `/chat`), input validation, JWT expiration
- Passwords hashed with bcrypt; no plaintext storage
- Logs avoid secrets, tokens, and sensitive content; production errors never leak stack traces

## Deployment notes

- Production: Nginx (HTTPS/TLS) → uvicorn; separate `development` / `staging` / `production`
  environments with distinct databases, secrets, and Redis instances
- Scale-out: replace the in-memory rate limiter/cache with Redis-backed implementations
- CI suggestion: `pytest` + `ruff` + `flutter analyze` on every push, then build the Docker image

## Documentation

- `prd.md` — product requirements
- `technical.md` — technical specification
- `IMPLEMENTATION_PLAN.md` — build plan, milestones and risks
