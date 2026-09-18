# agent.md — WeatherGPT Project Context Map

Purpose: let an agent jump straight to the right file/symbol for a change **without reading whole files**. Search for the task in "Where to make changes" first, then read only the listed file around the named symbol.

---

## 1. What this project is

**WeatherGPT** — AI-powered weather assistant. Core rule: **Weather API → facts · LLM → explanation**. The AI never invents weather values.

| Layer | Tech | Location |
|---|---|---|
| Backend API | FastAPI (async), Python 3.11+ (tested on 3.13) | `backend/app/` |
| Database | SQLAlchemy async — SQLite dev (`./weathergpt.db`), PostgreSQL prod | `backend/app/database/`, `backend/app/models/` |
| Weather provider | OpenWeather (needs `WEATHER_API_KEY`) for current/forecast/geocoding; Open-Meteo **Archive only** for historical/climate | `backend/app/services/weather_service.py`, `backend/app/services/historical_service.py` |
| AI/LLM | Gemini → Mistral → Groq fallback chain, rule-based fallback if all fail | `backend/app/services/llm_manager.py`, `backend/app/services/ai_service.py` |
| Cache | **In-memory TTL cache only** (no Redis) | `backend/app/services/cache_service.py` |
| Push | Firebase Cloud Messaging HTTP v1 (dry-run logs if unconfigured) | `backend/app/services/push_service.py` |
| TTS | Microsoft Edge Neural voices (Indian languages, auto-selected by script) | `backend/app/services/edge_tts_service.py` |
| Mobile | Flutter (provider + ChangeNotifier), Dart 3.4+ | `mobile/flutter_app/lib/` |
| Infra | docker-compose (api + postgres), k8s manifests | `docker-compose.yml`, `k8s/weathergpt.yaml` |

---

## 2. Commands

```bash
# Backend tests (107 tests, asyncio_mode=auto via backend/pytest.ini)
cd backend && python -m pytest tests/ -q

# Install backend deps
pip install -r backend/requirements.txt

# Run backend
cd backend && uvicorn app.main:app --reload   # http://127.0.0.1:8000/docs

# Flutter app
cd mobile/flutter_app && flutter pub get
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000   # Android emulator

# Docker stack (api + postgres only — no Redis)
docker compose up --build

# Kubernetes
kubectl apply -f k8s/weathergpt.yaml
```

---

## 3. Backend map (`backend/app/`)

### 3.1 Entrypoint & config

| File | Contains | When to touch |
|---|---|---|
| `main.py` | `app` (FastAPI), `lifespan` (init_db + alert scheduler), `request_context_middleware` (request ID + rate limit), error handlers (`http_exception_handler`, `validation_exception_handler`, `unhandled_exception_handler`), `_code_for`, router includes, `/health`, `/llm/status` | New router, middleware, global error format |
| `config.py` | `Settings` class (pydantic-settings, env-driven), grouped: app, CORS, weather provider, LLM providers + cooldowns, cache TTLs, database, auth/JWT, rate limits, provider-429 mitigation, alerts, firebase, RAG. `get_settings()` is `lru_cache`d; module-level `settings` singleton | Any new env var / setting |

### 3.2 API routes (`app/api/`) — thin handlers, no business logic

| File | Prefix | Endpoints |
|---|---|---|
| `routes_weather.py` | `/weather` | GET `/current` → `get_current_weather`, GET `/forecast` → `get_forecast`, GET `/search` → `search_locations`, POST `/activity-score`, POST `/compare`, GET `/best-time` |
| `routes_insights.py` | `/weather` | GET `/historical`, GET `/climate`, POST `/crop-advisory`, POST `/aviation`, GET `/city-overview`, GET `/models`; helpers `_serve_stale_historical`, `_serve_stale_climate`, `_gather_cities` |
| `routes_chat.py` | — | POST `/chat` → `chat`, POST `/chat/tts` → `chat_tts`; helpers `_load_history`, `_persist_exchange` |
| `routes_alerts.py` | `/alerts` | GET `` (list), POST `` (create), PATCH `/{alert_id}`, DELETE `/{alert_id}`, POST `/check`; helper `_get_owned` (ownership check) |
| `routes_locations.py` | `/locations` | GET `/search`, GET `` (saved list), POST `` (save), DELETE `/{location_id}` |
| `routes_auth.py` | `/auth` | POST `/register`, POST `/login`, GET `/me` (uses `get_current_user` dep) |
| `routes_notifications.py` | `/notifications` | POST `/register` (device token), POST `/unregister`, GET `/log`, POST `/broadcast`, GET `/health` |
| `routes_ws.py` | — | WS `/ws/weather` → `weather_socket`, `_snapshot` |

All routers are included in `main.py` at the bottom.

### 3.3 Services (`app/services/`) — all business logic

| File | Key symbols | Notes |
|---|---|---|
| `weather_service.py` | `WeatherService` (`get_current`, `get_forecast`, `geocode`, `_request`), `WeatherProviderError`, `WeatherRateLimitError`, `WeatherValidationError`, `_condition_from_code`, `_wmo_from_owm_id` | OpenWeather I/O + normalization (OpenWeather condition ids are mapped to WMO codes via `_wmo_from_owm_id`). Wind m/s → km/h. 429 → `WeatherRateLimitError`. `follow_redirects=True` on httpx. Forecast clamped to 5 days |
| `cached_weather_service.py` | `cached_weather_service` singleton, `CachedWeatherService.get_current/get_forecast`, module globals `_LAST_GOOD`, `_IN_FLIGHT_LOCKS` (single-flight coalescing), `_PROVIDER_RATE_LIMITED_UNTIL` | Cache layer over WeatherService; serves stale last-good on provider 429 |
| `cache_service.py` | `cache_service` singleton, `CacheService.get/set/delete_pattern/clear_memory`, module global `_MEMORY_CACHE` | **In-memory TTL cache (no Redis).** JSON payload + monotonic expiry. Only place cache code lives |
| `historical_service.py` | `HistoricalService`, `HistoricalServiceError` | Open-Meteo **Archive API** (the only Open-Meteo usage) for past obs + climate trends; cached; base URL via `settings.archive_api_base_url` |
| `ai_service.py` | `AIService`, `LLMError` | Chat brain: language detect → prompt build → `llm_manager` → validate. Rule-based fallback when no LLM. Routes never call LLM directly |
| `llm_manager.py` | `llm_manager` singleton, `LLMManager`, `ProviderState`, `_ProviderHealth` | Orchestrator: provider order (`LLM_PROVIDER_ORDER`), fallback on rate-limit, circuit-breaker cooldowns, `get_status()` (powers `/llm/status`) |
| `llm_providers.py` | `ErrorKind`, `ProviderError`, `classify_exception`, `LLMProvider` (ABC), `GeminiProvider`, `MistralProvider`, `GroqProvider` | One class per provider; normalizes SDK errors into `ErrorKind` (RATE_LIMIT/SERVER/TIMEOUT/…) |
| `activity_engine.py` | `compute_activity_score`, `SCORE_BANDS`, `FACTOR_CONFIGS`, `rating_for_score`, `score_factor`, `_best_time` | Deterministic 0–100 activity scoring (run/cycle/picnic…). Thresholds in constants, not scattered |
| `alert_service.py` | `evaluate_alert_rules`, `_check_rule`, `_explain`, `build_rules_context`, `AlertService`, `AlertRuleContext`, `DEFAULT_THRESHOLDS` | Rule-based alerting: rules decide, LLM may only explain |
| `alert_scheduler.py` | `run_alert_scheduler`, `start_alert_scheduler`, `stop_alert_scheduler` | Background asyncio task (disabled by default; `ALERT_SCHEDULER_ENABLED=true`). Started in `main.py` lifespan. Calls `push_service` |
| `comparison_service.py` | `ComparisonService.compare_locations`, `_fetch_both` | Compare weather between two locations/days |
| `crop_advisory_service.py` | `CropAdvisoryService`, `CROP_NOTES` | Deterministic crop-weather advisories (rice/wheat/cotton…) |
| `aviation_service.py` | `AviationService.generate` | VFR-style flight condition assessment |
| `language_service.py` | `detect_language`, `language_name`, `_SCRIPT_RANGES` | Local language detection via Unicode script + Hinglish stopwords |
| `edge_tts_service.py` | `EdgeTtsService`, `is_hindi`, `detect_language`, `clean_tts_text`, `VOICE_*` constants | Neural TTS for Indian languages; auto voice by script |
| `push_service.py` | `PushNotificationService`, `PushDispatchLog`, `FCM_SEND_URL_TEMPLATE` | FCM HTTP v1 via service-account JSON; dry-run logs when unconfigured |
| `auth_service.py` | `AuthService`, `get_current_user` (FastAPI dep), `get_current_user_optional` | JWT issue/verify, bcrypt password hashing |
| `location_service.py` | `LocationService` | Saved-location CRUD helpers |

### 3.4 AI package (`app/ai/`)

| File | Key symbols | Notes |
|---|---|---|
| `intents.py` | `Intent` enum (12 values), `_PATTERNS` (ordered keyword regexes, first match wins), `detect_intent`, `detect_period`, `is_follow_up`, `detect_activity` | Rule-based intent detection for chat |
| `prompts.py` | `SYSTEM_PROMPT`, `build_user_prompt`, `build_weather_context`, `build_activity_context`, `build_language_instruction` | All prompt text lives here |
| `retriever.py` | `maybe_retrieve`, `get_retriever` | Optional RAG (Chroma), off unless `RAG_ENABLED=true` |

### 3.5 Models (`app/models/`) & schemas (`app/schemas/`)

- Models (SQLAlchemy, in `app/models/`): `User` (user.py), `Location` (location.py), `AlertPreference` (alert.py), `ChatConversation`/`ChatMessage` (chat.py), `DeviceToken` (device.py). All registered in `database/database.py:init_db` — **add new model imports there**.
- Schemas (Pydantic, in `app/schemas/`): `weather.py` (incl. `GeoLocation`, `CurrentWeatherResponse`, `ForecastResponse`), `chat.py`, `alert.py`, `auth.py`, `insights.py` (historical/climate/crop/aviation), `location.py`, `notifications.py`, `activity.py`.

### 3.6 Database & utils

| File | Key symbols |
|---|---|
| `database/database.py` | `engine`, `AsyncSessionLocal`, `get_db` (FastAPI dep), `init_db`, `dispose_db` |
| `database/base.py` | `Base` (declarative) |
| `utils/units.py` | `ms_to_kmh`, `mph_to_kmh`, `metres_to_km`, `fahrenheit_to_celsius`, … |
| `utils/geo.py` | coordinate helpers |
| `utils/validation.py` | request validation |
| `utils/rate_limit.py` | `enforce_rate_limit(request, chat=...)`, `_client_ip`, `_HITS` — per-process sliding window; called from `main.py` middleware |
| `utils/logging.py` | `configure_logging`, `get_logger`, `request_id_var` (context var) |

---

## 4. Flutter app map (`mobile/flutter_app/lib/`)

| File | Role |
|---|---|
| `main.dart` | App bootstrap, provider wiring, theme |
| `config.dart` | `AppConfig` — backend URL from `--dart-define=API_BASE_URL`, user-override via SharedPreferences (`custom_api_base_url`) |
| `providers/app_state.dart` | `AppState` (ChangeNotifier): location, current/hourly/daily weather, `authToken`, `refreshWeather`, `useCurrentLocation`, `_restore`, `_useFallbackLocation` |
| `providers/chat_state.dart` | `ChatState`: conversation + messages |
| `services/api_service.dart` | `ApiService` (singleton), `retry()` helper, `retryableStatusCodes`, `ApiException` — all HTTP calls |
| `services/voice_service.dart` | speech-to-text + TTS wrappers |
| `repositories/weather_repository.dart` | typed data access over ApiService |
| `models/` | `weather.dart`, `chat.dart`, `insights.dart`, `saved_location.dart` |
| `screens/` | `home_screen`, `chat_screen`, `forecast_screen`, `locations_screen`, `advisories_screen`, `settings_screen` |
| `utils/weather_icon.dart` | weather code → icon mapping |

---

## 5. Where to make changes (task → file routing)

**Search this table first.** Read only the named file, around the named symbol.

| Task | Go to |
|---|---|
| Add/modify an API endpoint | Route file in §3.2 (match by prefix), add schema in `app/schemas/`, logic in `app/services/` |
| Add a config/env var | `app/config.py` → `Settings`; document in `backend/.env.example` |
| Change weather data shape | Normalize in `services/weather_service.py`; schema in `app/schemas/weather.py`; Flutter mirror in `lib/models/weather.dart` |
| Change cache TTLs/behavior | TTLs: `app/config.py` (cache_*_ttl_seconds); logic: `services/cache_service.py`; weather-cache usage: `services/cached_weather_service.py` |
| Change chat answer behavior | `services/ai_service.py` (`AIService`) + prompts in `ai/prompts.py` + intents in `ai/intents.py` |
| Add/swap an LLM provider | `services/llm_providers.py` (subclass `LLMProvider`), register in `services/llm_manager.py`, key/model in `app/config.py` |
| Change LLM fallback/cooldown rules | `services/llm_manager.py` (`LLMManager`, `_ProviderHealth`); tunables in `app/config.py` (`llm_*`) |
| Activity scoring rules | `services/activity_engine.py` → `FACTOR_CONFIGS`, `SCORE_BANDS`, `compute_activity_score` |
| Alert thresholds/rules | `services/alert_service.py` → `DEFAULT_THRESHOLDS`, `evaluate_alert_rules` |
| Alert background job | `services/alert_scheduler.py`; enable via `ALERT_SCHEDULER_ENABLED` |
| Push notifications | `services/push_service.py` (FCM); device registration `app/api/routes_notifications.py` |
| TTS voices/languages | `services/edge_tts_service.py` → `VOICE_*` constants |
| Language detection | `services/language_service.py` → `_SCRIPT_RANGES` |
| Historical/climate data | `services/historical_service.py` + `app/api/routes_insights.py` |
| Crop/aviation/comparison features | `crop_advisory_service.py` / `aviation_service.py` / `comparison_service.py` |
| Add a DB table/column | Model in `app/models/`, import in `database/database.py:init_db`, schema in `app/schemas/` |
| Auth (JWT, register, login) | `services/auth_service.py` + `app/api/routes_auth.py`; JWT settings in `app/config.py` |
| Rate limiting | `app/utils/rate_limit.py`; limits in `app/config.py` (`rate_limit_*`) |
| Error response format | `app/main.py` → exception handlers + `_code_for` |
| Request logging / request IDs | `app/utils/logging.py` + `request_context_middleware` in `app/main.py` |
| Unit conversions (C, km/h, km, hPa) | `app/utils/units.py` |
| Coordinate validation | `app/utils/validation.py`, `app/utils/geo.py` |
| Backend URL / networking (Flutter) | `lib/config.dart` + `lib/services/api_service.dart` |
| App state / location handling (Flutter) | `lib/providers/app_state.dart` |
| Chat UI state (Flutter) | `lib/providers/chat_state.dart` + `lib/screens/chat_screen.dart` |
| New Flutter screen | `lib/screens/`, register nav in `lib/main.dart` |
| Infra (deploy) | `docker-compose.yml` (api+postgres), `k8s/weathergpt.yaml`, `backend/Dockerfile` |

---

## 6. Conventions & invariants (do not break)

1. **Routes stay thin.** No business logic in `app/api/*` — call services.
2. **Cache code lives only in `cache_service.py`.** Never cache in route handlers.
3. **LLM calls only via `llm_manager`** (wrapped by `ai_service.py`). Routes never call LLMs.
4. **Deterministic rules decide, LLM explains.** Alerts/activity/crop/aviation trigger from data thresholds only; the LLM may phrase explanations but never decides outcomes or invents values.
5. **Error envelope is uniform:** `{"error": {"code": "...", "message": "..."}}` — codes mapped in `main.py:_code_for`.
6. **Units normalized backend-side:** Celsius, km/h, km, hPa (`utils/units.py`).
7. **Secrets only in `.env`** (never committed). New keys → `config.py` + `backend/.env.example`. No API keys in the Flutter app.
8. **Logging never contains secrets/tokens/keys**; use `get_logger(__name__)`.
9. **Cache is in-memory & per-process** (single-instance design). If scaling multi-instance, a shared store would be needed for cache + rate limiter.
10. **Provider failures degrade gracefully:** 503 for provider down (never fabricated data); stale last-good served on provider 429 (`cached_weather_service.py`).
11. **Tests:** `backend/tests/`, pytest with `asyncio_mode = auto` — async tests need no decorator. Fixtures in `tests/conftest.py` (`_clear_cache` resets `_MEMORY_CACHE` + `_LAST_GOOD`; `_sqlite_url` forces SQLite + OpenWeather with a dummy key; `_mock_provider` patches `WeatherService._request` with OpenWeather-shaped payloads).

---

## 7. Spec & docs

| File | Content |
|---|---|
| `prd.md` | Product requirements |
| `technical.md` | Technical spec (§ numbers are referenced in code docstrings) |
| `IMPLEMENTATION_PLAN.md` | Build plan / dependency list |
| `README.md` | Setup, env vars table, provider docs (OpenWeather + Open-Meteo Archive) |

Section references like "spec §17" or "prompt §10" in docstrings point into `technical.md` / the original development prompt.
