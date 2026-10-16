# WeatherGPT — Project Report

**Date:** 2026-10-15 (verification run)
**Repository:** `weathergpt` · branch `main` · 31 commits · 158 indexed files

---

## 1. Executive Summary

WeatherGPT is an AI-powered weather assistant consisting of a FastAPI backend and a Flutter
mobile client. Its defining design rule is **"Weather API → facts · LLM → explanation"**:
all weather values come deterministically from the provider (OpenWeather + Open-Meteo
Archive), while the LLM only explains and converses. Alerts, activity scores, crop
advisories, and aviation briefings are deterministic engines — the model never decides
outcomes and never invents weather data.

The project is feature-complete relative to its PRD, well-documented (≈2,800 lines of
spec/plan docs), and in a healthy verified state:

| Check | Result |
|---|---|
| Backend test suite (`pytest`) | **111 passed** in 12.1 s (6 warnings) |
| Flutter static analysis (`flutter analyze`) | **1 info-level lint** (no errors) |
| Flutter tests (`flutter test`) | **14 passed** in 10 s |

---

## 2. Architecture

```
Flutter app ──HTTPS/WS──► FastAPI backend ──► Weather provider (OpenWeather + Open-Meteo Archive)
                                ├──► LLM chain (Gemini → Mistral → Groq → rule-based fallback)
                                ├──► PostgreSQL (prod) / SQLite (dev)
                                ├──► In-memory TTL cache (no Redis)
                                └──► Firebase Cloud Messaging (push alerts)
```

| Layer | Technology | Location |
|---|---|---|
| Backend API | FastAPI (async), Python 3.11+ (tested on 3.13) | `backend/app/` |
| Database | SQLAlchemy 2.0 async — SQLite dev, PostgreSQL prod (asyncpg) | `backend/app/database/`, `backend/app/models/` |
| Weather data | OpenWeather (current/forecast/geocoding, key required); Open-Meteo Archive (history/climate, keyless) | `services/weather_service.py`, `services/historical_service.py` |
| AI/LLM | LangChain-Google-Genai + REST providers, multi-provider fallback with circuit breakers, deterministic rule-based fallback | `services/llm_manager.py`, `services/llm_providers.py`, `services/ai_service.py` |
| Auth | JWT (PyJWT) + bcrypt password hashing | `services/auth_service.py` |
| Push | FCM HTTP v1 (dry-run logging when unconfigured) | `services/push_service.py` |
| TTS/STT | Microsoft Edge neural voices (9 Indian languages, script auto-detection) | `services/edge_tts_service.py` |
| Mobile | Flutter / Dart 3.4+, provider (ChangeNotifier) state management | `mobile/flutter_app/lib/` |
| Infra | docker-compose (api + PostgreSQL 16), Kubernetes manifests, Dockerfile | `docker-compose.yml`, `k8s/weathergpt.yaml` |

### Backend layering (enforced by documented conventions in `agent.md`)

- **Routes are thin** — `app/api/` (8 route modules) holds handlers only; all logic lives in
  `app/services/` (18 service modules).
- **Single cache owner** — `cache_service.py`; `cached_weather_service.py` adds single-flight
  request coalescing, stale last-good serving (up to ~1 h) on provider 429, and cooldown caps.
- **LLM isolation** — routes never call LLMs; everything goes through `ai_service` →
  `llm_manager` (provider order, retries, cooldowns, `/llm/status`).
- **Uniform error envelope** — `{"error": {"code", "message"}}`; 503 provider down,
  429 rate limit, 400 validation; stack traces never leak.

---

## 3. Codebase Statistics

| Area | Files | Lines |
|---|---:|---:|
| Backend app (`backend/app/`, excl. `__pycache__`) | 59 Python | 7,179 |
| Backend tests (`backend/tests/`) | 7 Python | 2,066 |
| Flutter app (`mobile/flutter_app/lib/`) | 20 Dart | 6,021 |
| Documentation (`prd.md`, `technical.md`, `IMPLEMENTATION_PLAN.md`, `agent.md`, `README.md`) | 5 | 2,767 |

**Backend modules:** 8 route files, 18 services, 5 ORM models (User, Location,
AlertPreference, ChatConversation/ChatMessage, DeviceToken), 8 schema files, AI package
(prompts / intents / retriever), utils (units, geo, validation, rate limit, logging).

**Flutter screens:** Home, AI Chat, Forecast, Locations, Advisories, Settings — backed by
2 providers, an API service with retry logic (429 deliberately not retried — server sends
`Retry-After`), a weather repository, voice service, and 4 model files.

---

## 4. Feature Inventory

- Current weather, hourly + 5-day forecast, geocoding search, saved locations
- AI chat with weather context, follow-up intent detection, conversation persistence,
  per-request language instruction
- Voice: STT + neural TTS in 9 Indian languages, script-based auto-detection
- Deterministic activity engine (0–100 explainable score, best-time-of-day)
- Deterministic alert rule engine (rain, thunderstorm, heat, wind, UV, flood risk,
  cyclone winds) with per-user thresholds, background scheduler, FCM push, dispatch log
- Weather comparison, historical observations, climate trends + warming anomaly
  (Open-Meteo Archive)
- Crop advisories (10 Indian crops), VFR-style aviation briefing, 10-city smart-city
  overview, WebSocket `/ws/weather` live stream
- Optional Chroma RAG (off by default), JWT auth, per-IP rate limiting (stricter on
  `/chat`), multi-language UI support

---

## 5. Verification Results (run for this report)

1. **Backend:** `python -m pytest tests/ -q` → **111 passed, 6 warnings, 12.09 s**.
   All external calls mocked; no network needed.
   - Warnings are `InsecureKeyLengthWarning` from PyJWT — the *test* JWT secret is 25
     bytes (< 32 recommended for SHA-256). Test-only, but production `JWT_SECRET`
     should be ≥ 32 random bytes.
2. **Flutter:** `flutter pub get` → `flutter analyze` → **1 issue** (info level:
   `use_build_context_synchronously` at `settings_screen.dart:186`).
3. **Flutter tests:** `flutter test` → **14 passed** (API retry/backoff semantics,
   exception behavior, settings screen widget tests).
4. **Note:** `flutter analyze` initially reported 91 errors before `flutter pub get`
   resolved dependencies — this is expected for a fresh checkout, not a code defect.

---

## 6. Documentation & Process

| Doc | Lines | Content |
|---|---:|---|
| `prd.md` | 904 | Product requirements, MVP/Phase 2/3 scope, AI guardrails |
| `technical.md` | 1,303 | Full technical spec — sections referenced from code docstrings (e.g. "spec §17") |
| `IMPLEMENTATION_PLAN.md` | 104 | Build order, milestones, risks |
| `agent.md` | 202 | Agent-oriented context map: task → file routing, invariants |
| `README.md` | 254 | Setup, env vars, API table, deployment |

Tooling: pre-commit git hook with a **secret scanner** (`scripts/git-hooks/`) to block API
keys from being committed; `.env` git-ignored with `.env.example` placeholders; Docker and
Kubernetes deployment paths (HPA 2–8 replicas, WebSocket-friendly ingress timeouts).

---

## 7. Findings & Improvement Opportunities

**Doc drift (low effort, worth fixing):**
1. `README.md` claims **47 tests** and `agent.md` claims **107** — the actual count is
   **111**. Both numbers are stale.
2. (Verified correct: README's 9 TTS languages match the 9 `VOICE_*` constants in
   `services/edge_tts_service.py` — English, Hindi, Tamil, Telugu, Bengali, Marathi,
   Kannada, Malayalam, Gujarati.)

**Engineering (medium effort):**
3. **No schema migrations** — tables are created on startup (`init_db`); the README itself
   recommends Alembic for production. Any column change on a live PostgreSQL DB will be
   painful without it.
4. **Per-process state** — the in-memory cache, rate limiter, provider-429 cooldown, and
   LLM circuit breakers are all process-local. Running >1 replica (the k8s HPA goes to 8)
   multiplies provider load and weakens rate limiting. A shared store (Redis) or sticky
   routing is needed before scaling out; this is acknowledged in the README but not yet
   addressed.
5. **One info-level lint** in `settings_screen.dart:186` (BuildContext across async gap) —
   trivial to fix, would bring `flutter analyze` to zero.
6. **Test JWT secret length** warning — use a ≥32-byte secret in `tests/conftest.py`.

**Repository hygiene (low effort):**
7. Commit messages are poor quality for a 31-commit history (`hello`, `heelo`, `open`,
   `notify`); consider squashing/rewriting before publishing, or improve going forward.
8. `backend/.env` and `backend/weathergpt.db` exist locally — both are correctly
   git-ignored, but confirm they are never pushed on any remote.

**Product/scale (future phases):**
9. Chat history, alerts, and devices require auth, but there is no rate limiting per
   *user* (only per-IP) — trivially bypassed with rotating IPs or NAT.
10. No CI pipeline is present (the README suggests `pytest` + `ruff` + `flutter analyze`);
    the git hook is local-only, so quality gates depend on each developer's machine.

---

## 8. Overall Assessment

WeatherGPT is a well-structured, unusually well-documented full-stack project. Its
strongest engineering traits are the strict deterministic-vs-LLM separation, graceful
provider-failure degradation (stale cache, single-flight coalescing, multi-provider LLM
fallback), and a fully mocked offline test suite that passes cleanly. The main gaps are
production-readiness items — migrations, shared cache/rate-limit state for multi-replica
deployment, and CI — rather than correctness or structure. All automated checks currently
pass: **111/111 backend tests, 14/14 Flutter tests, 0 analyzer errors.**
