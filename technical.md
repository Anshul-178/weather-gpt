# WeatherGPT — Technical Specification

## 1. Purpose

This document defines the technical architecture, implementation details, APIs, data flow, infrastructure, security, and development standards for WeatherGPT.

WeatherGPT is an AI-powered weather assistant consisting of:

- Flutter mobile application
- FastAPI backend
- Weather data provider
- LLM/AI service
- Optional RAG/retrieval layer
- PostgreSQL database
- Redis cache
- Firebase Cloud Messaging for notifications

---

# 2. System Architecture

```text
                    ┌─────────────────────┐
                    │    Flutter App      │
                    │     Android/iOS     │
                    └──────────┬──────────┘
                               │ HTTPS
                               ▼
                    ┌─────────────────────┐
                    │    FastAPI API      │
                    │     Backend         │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼─────────────────┐
              │                │                 │
              ▼                ▼                 ▼
       ┌────────────┐   ┌────────────┐   ┌─────────────┐
       │ Weather API│   │  AI / LLM  │   │ PostgreSQL  │
       └────────────┘   └────────────┘   └─────────────┘
              │                │                 │
              └────────────────┼─────────────────┘
                               ▼
                         ┌───────────┐
                         │   Redis   │
                         │   Cache   │
                         └───────────┘

                    ┌─────────────────────┐
                    │ Firebase Cloud      │
                    │ Messaging (FCM)     │
                    └─────────────────────┘
```

---

# 3. Recommended Technology Stack

| Component | Technology |
|---|---|
| Mobile | Flutter + Dart |
| Backend | Python + FastAPI |
| API validation | Pydantic |
| HTTP client | httpx |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| Cache | Redis |
| AI | LLM API |
| Embeddings | BGE / compatible embedding model |
| Vector DB | Chroma initially |
| Notifications | Firebase Cloud Messaging |
| Authentication | JWT |
| Deployment | Docker + cloud/VPS |
| Reverse proxy | Nginx |
| Version control | Git + GitHub |

---

# 4. Repository Structure

Recommended monorepo:

```text
weathergpt/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   │
│   │   ├── api/
│   │   │   ├── routes_weather.py
│   │   │   ├── routes_chat.py
│   │   │   ├── routes_alerts.py
│   │   │   ├── routes_locations.py
│   │   │   └── routes_auth.py
│   │   │
│   │   ├── services/
│   │   │   ├── weather_service.py
│   │   │   ├── ai_service.py
│   │   │   ├── alert_service.py
│   │   │   └── location_service.py
│   │   │
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   ├── location.py
│   │   │   ├── alert.py
│   │   │   └── chat.py
│   │   │
│   │   ├── schemas/
│   │   │   ├── weather.py
│   │   │   ├── chat.py
│   │   │   ├── alert.py
│   │   │   └── location.py
│   │   │
│   │   ├── database/
│   │   │   ├── database.py
│   │   │   └── migrations/
│   │   │
│   │   ├── ai/
│   │   │   ├── prompts.py
│   │   │   ├── retriever.py
│   │   │   └── embeddings.py
│   │   │
│   │   └── utils/
│   │       ├── units.py
│   │       ├── validation.py
│   │       └── logging.py
│   │
│   ├── tests/
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
│
├── mobile/
│   └── flutter_app/
│       ├── lib/
│       │   ├── main.dart
│       │   ├── models/
│       │   ├── screens/
│       │   ├── services/
│       │   ├── widgets/
│       │   └── providers/
│       ├── android/
│       ├── ios/
│       └── pubspec.yaml
│
├── docs/
├── prd.md
├── technical.md
├── docker-compose.yml
└── README.md
```

---

# 5. Backend Architecture

FastAPI should follow a layered architecture:

```text
API Route
   ↓
Schema Validation
   ↓
Service Layer
   ↓
External API / Database / AI
   ↓
Response Schema
   ↓
Client
```

Routes should remain thin. Business logic should be placed in services.

---

# 6. Configuration

Use environment variables.

Example `.env`:

```env
APP_ENV=development

WEATHER_API_KEY=your_weather_api_key
WEATHER_API_BASE_URL=https://example.com

LLM_API_KEY=your_llm_api_key

DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/weathergpt

REDIS_URL=redis://localhost:6379

JWT_SECRET=change_this_in_production

FIREBASE_PROJECT_ID=your_project
```

Never commit `.env` to GitHub.

Use `.env.example` instead.

---

# 7. Weather Data Flow

For a current-weather request:

```text
Flutter
  ↓
GET /weather/current
  ↓
FastAPI
  ↓
Validate latitude/longitude
  ↓
Check Redis cache
  ↓
If cache miss → Weather API
  ↓
Normalize provider response
  ↓
Cache result
  ↓
Return JSON
```

Weather-provider-specific response formats should be converted into an internal Weather schema.

This prevents the rest of the application from depending directly on a provider's response format.

---

# 8. Weather Schema

Example:

```json
{
  "location": {
    "name": "Kanpur",
    "latitude": 26.4499,
    "longitude": 80.3319
  },
  "current": {
    "temperature": 32.4,
    "feels_like": 36.1,
    "humidity": 71,
    "wind_speed": 12.5,
    "wind_direction": 180,
    "pressure": 1005,
    "visibility": 8.2,
    "uv_index": 7.0,
    "condition": "Partly cloudy"
  },
  "timestamp": "2026-09-10T12:00:00+05:30"
}
```

Units should be normalized by the backend.

Default:

- Temperature: Celsius
- Wind: km/h
- Visibility: km
- Pressure: hPa

---

# 9. Forecast API

Endpoint:

```http
GET /weather/forecast
```

Parameters:

```text
latitude
longitude
days
```

Example:

```http
GET /weather/forecast?latitude=26.4499&longitude=80.3319&days=7
```

Response:

```json
{
  "location": "Kanpur",
  "forecast": [
    {
      "date": "2026-09-10",
      "temperature_max": 35,
      "temperature_min": 27,
      "precipitation_probability": 60,
      "condition": "Partly cloudy"
    }
  ]
}
```

---

# 10. AI Chat Architecture

The AI system should use weather data as structured context.

```text
User Question
     ↓
Intent Detection
     ↓
Location Resolution
     ↓
Weather Data Retrieval
     ↓
Weather Context Creation
     ↓
Optional RAG Retrieval
     ↓
Prompt Construction
     ↓
LLM
     ↓
Response Validation
     ↓
User
```

---

# 11. AI Prompt Design

The system prompt should establish the following rules:

```text
You are WeatherGPT, an AI weather assistant.

Use the supplied weather data as the source of truth for current
weather and forecasts.

Never invent weather values.

Clearly distinguish:
- current observations
- forecasts
- warnings
- AI recommendations

When the user asks for an activity recommendation, explain which
weather factors affect the recommendation.

If weather data is unavailable, say that current weather data could
not be retrieved instead of guessing.

Keep answers concise unless the user asks for detailed information.
```

---

# 12. RAG Architecture

RAG should not replace the live weather API.

Use:

```text
Live weather API
        +
Trusted weather information
        +
Optional historical/reference data
        ↓
       LLM
```

Live weather values should always come from the weather provider.

RAG can be used for:

- Weather terminology
- Safety guidance
- Weather science
- Activity rules
- Government/public weather information
- Historical context
- Location information

Example:

```text
Question:
"Is this wind speed dangerous for cycling?"

Live weather API:
Wind = 32 km/h

RAG:
Cycling guidance and thresholds

LLM:
Combines both sources and explains the result.
```

---

# 13. Vector Database

Initial implementation:

```text
Chroma
```

Document pipeline:

```text
Documents
   ↓
Text extraction
   ↓
Chunking
   ↓
Embedding model
   ↓
Vector database
   ↓
Similarity/MMR retrieval
   ↓
LLM context
```

Recommended chunking starting point:

```text
chunk_size = 800–1200
chunk_overlap = 100–200
```

The exact values should be evaluated experimentally.

---

# 14. Chat Endpoint

Endpoint:

```http
POST /chat
```

Request:

```json
{
  "message": "Should I carry an umbrella today?",
  "latitude": 26.4499,
  "longitude": 80.3319,
  "conversation_id": "optional-id"
}
```

Response:

```json
{
  "answer": "There is a moderate chance of rain today, so carrying an umbrella would be a good idea.",
  "location": "Kanpur",
  "sources": [
    "weather_api"
  ],
  "timestamp": "2026-09-10T12:00:00+05:30"
}
```

---

# 15. Intent Detection

The backend should identify common weather intents.

Example intents:

```text
CURRENT_WEATHER
FORECAST
RAIN
TEMPERATURE
WIND
HUMIDITY
UV
WEATHER_COMPARISON
ACTIVITY_RECOMMENDATION
TRAVEL
ALERT
GENERAL_WEATHER_KNOWLEDGE
```

A lightweight rule-based layer can handle obvious requests before invoking an LLM.

---

# 16. Conversation Context

Conversation memory should be limited to relevant context.

Example:

```text
User:
What's the weather tomorrow in Kanpur?

Assistant:
...

User:
What about the evening?

```

The backend should resolve:

```text
location = Kanpur
date = tomorrow
period = evening
```

Do not send unlimited conversation history to the LLM.

Use a bounded history or summarized conversation state.

---

# 17. Activity Recommendation Engine

Create deterministic rules for important activities.

Example:

```text
Outdoor Score =
temperature_score
+ precipitation_score
+ wind_score
+ humidity_score
+ visibility_score
+ uv_score
```

Normalize the final score to:

```text
0–100
```

Example:

```text
80–100 → Excellent
60–79  → Good
40–59  → Moderate
20–39  → Poor
0–19   → Very poor
```

These thresholds should be configurable rather than hard-coded throughout the application.

---

# 18. Alert Engine

Alerts should be rule-based.

Example:

```text
IF precipitation_probability >= threshold
THEN rain_alert

IF temperature >= threshold
THEN heat_alert

IF wind_speed >= threshold
THEN strong_wind_alert
```

AI can generate the human-readable explanation, but the trigger should come from deterministic weather rules.

---

# 19. Notifications

Architecture:

```text
Weather Scheduler
       ↓
Weather API
       ↓
Alert Rule Engine
       ↓
Alert detected
       ↓
Firebase Cloud Messaging
       ↓
Flutter
       ↓
Push Notification
```

Do not continuously poll from the mobile application.

Use backend scheduled jobs.

---

# 20. Database Design

## Users

```sql
id
name
email
password_hash
created_at
updated_at
```

## Locations

```sql
id
user_id
name
latitude
longitude
created_at
```

## Alert Preferences

```sql
id
user_id
location_id
alert_type
threshold
enabled
created_at
```

## Conversations

```sql
id
user_id
created_at
updated_at
```

## Messages

```sql
id
conversation_id
role
content
created_at
```

---

# 21. Caching

Redis should cache weather data.

Suggested strategy:

```text
Current weather:
TTL ≈ 5–15 minutes

Forecast:
TTL ≈ 30–60 minutes

Location/geocoding:
TTL ≈ several hours
```

TTL should be adjusted according to provider update frequency and API limits.

Cache key example:

```text
weather:current:26.4499:80.3319
```

Round coordinates before creating cache keys to avoid unnecessary cache fragmentation.

---

# 22. Flutter Architecture

Recommended structure:

```text
Flutter UI
   ↓
Provider / Riverpod / Bloc
   ↓
Repository
   ↓
API Service
   ↓
FastAPI
```

Recommended separation:

```text
screens/
widgets/
models/
services/
repositories/
providers/
utils/
```

---

# 23. Flutter API Service

The app should call the WeatherGPT backend.

```text
Flutter
   |
   | HTTPS
   ↓
https://api.yourdomain.com
```

Do not place weather-provider or LLM secret keys inside Flutter.

---

# 24. Mobile Screens

## Home

Components:

```text
Location
Temperature
Condition
Feels-like
Weather summary
Hourly forecast
Daily forecast
Alert banner
Ask WeatherGPT button
```

## Chat

```text
Message list
Input field
Send button
Loading indicator
Suggested questions
```

## Forecast

```text
Hourly
Daily
Temperature
Rain probability
Wind
UV
```

## Locations

```text
Search
Saved locations
Current location
```

## Alerts

```text
Rain
Heat
Wind
Storm
UV
Visibility
```

---

# 25. Authentication

Production authentication:

```text
Register
   ↓
Login
   ↓
JWT access token
   ↓
Authorization header
   ↓
FastAPI
```

Example:

```http
Authorization: Bearer <access_token>
```

Passwords must be hashed using a modern password-hashing algorithm.

Never store plaintext passwords.

---

# 26. API Security

Implement:

- HTTPS
- CORS restrictions
- Request validation
- Rate limiting
- Authentication
- Authorization
- Secret management
- API-key protection
- Logging without sensitive data

Third-party keys must remain server-side.

---

# 27. Error Handling

Standard response:

```json
{
  "error": {
    "code": "WEATHER_PROVIDER_ERROR",
    "message": "Unable to retrieve weather data right now."
  }
}
```

Suggested HTTP codes:

```text
200 OK
201 Created
400 Bad Request
401 Unauthorized
403 Forbidden
404 Not Found
429 Too Many Requests
500 Internal Server Error
502 Bad Gateway
503 Service Unavailable
```

---

# 28. Logging

Log:

```text
request_id
endpoint
HTTP method
status code
latency
error code
external provider status
```

Avoid logging:

- Passwords
- API keys
- JWT tokens
- Unnecessary precise location history
- Sensitive conversation content

---

# 29. Testing

## Unit tests

Test:

- Weather normalization
- Unit conversion
- Activity scores
- Alert thresholds
- Prompt construction
- Input validation

## Integration tests

Test:

```text
Flutter → FastAPI
FastAPI → Weather API
FastAPI → Database
FastAPI → Redis
FastAPI → LLM
```

## API tests

Use:

```text
pytest
httpx
```

Test successful and failure responses.

---

# 30. Docker

Backend Dockerfile should:

1. Use a lightweight Python image.
2. Install dependencies.
3. Copy application code.
4. Expose FastAPI port.
5. Run Uvicorn.

Development services:

```text
FastAPI
PostgreSQL
Redis
```

can be managed using Docker Compose.

---

# 31. Deployment Architecture

Production:

```text
                    Internet
                       |
                       v
                    Nginx
                       |
                       v
                 FastAPI Server
                  /                            /                             v               v
          PostgreSQL          Redis
                |
                v
         Persistent Storage

FastAPI
  |
  +---- Weather Provider
  |
  +---- LLM Provider
  |
  +---- Firebase FCM
```

Flutter communicates only with the public HTTPS API.

---

# 32. CI/CD

Recommended pipeline:

```text
Git Push
   ↓
GitHub Actions
   ↓
Run linting
   ↓
Run tests
   ↓
Build Docker image
   ↓
Deploy backend
```

Before deployment:

```text
pytest
ruff
mypy (optional)
```

---

# 33. Environment Separation

Use:

```text
development
staging
production
```

Each environment should have separate:

- Database
- API credentials
- Redis
- JWT secrets
- Firebase configuration where appropriate

---

# 34. Rate Limiting

Rate-limit:

```text
/chat
/weather/*
/auth/*
```

Chat endpoints should have stricter limits because LLM calls have higher cost.

Example conceptual policy:

```text
Anonymous:
10 requests/minute

Authenticated:
30 requests/minute

Chat:
separate AI-specific quota
```

Actual limits should be adjusted after load testing.

---

# 35. Cost Optimization

Primary cost sources:

- LLM calls
- Weather API requests
- Embedding generation
- Database/cloud infrastructure

Optimization:

1. Cache weather responses.
2. Avoid unnecessary LLM calls.
3. Use deterministic intent detection where possible.
4. Limit conversation history.
5. Cache embeddings.
6. Use smaller models for simple tasks.
7. Use larger models only for complex reasoning.

---

# 36. AI Reliability Strategy

Never allow the LLM to become the weather-data source.

Correct:

```text
Weather API → Weather facts
LLM → Explanation/recommendation
```

Incorrect:

```text
LLM → Guess current temperature
```

The backend should inject structured weather data into the AI request.

---

# 37. Observability

Production monitoring should track:

```text
API latency
Error rate
Weather API failures
LLM failures
LLM latency
Cache hit rate
Database latency
Notification failures
Daily active users
```

Set alerts for abnormal failure rates.

---

# 38. Performance Targets

Initial targets:

| Metric | Target |
|---|---:|
| Weather API endpoint | <2 sec |
| Cached weather request | <500 ms |
| Chat response | <5–8 sec |
| API availability | ≥99% target |
| Cache hit rate | >60% target |
| Mobile startup | <3 sec target |

These are engineering targets and should be validated through real measurements.

---

# 39. Development Roadmap

## Phase 1 — Backend Foundation

- Create FastAPI project
- Configure environment variables
- Add weather provider
- Implement `/health`
- Implement `/weather/current`
- Implement `/weather/forecast`

## Phase 2 — AI

- Add LLM service
- Build WeatherGPT system prompt
- Implement `/chat`
- Inject live weather context
- Add response validation

## Phase 3 — Flutter

- Create Flutter project
- Build home screen
- Connect FastAPI
- Build forecast UI
- Build chat UI

## Phase 4 — Database

- PostgreSQL
- Users
- Saved locations
- Chat history
- Alert preferences

## Phase 5 — Advanced AI

- RAG
- Activity recommendations
- Weather Impact Score
- Comparison engine

## Phase 6 — Notifications

- FCM
- Scheduler
- Alert engine
- Push notifications

## Phase 7 — Production

- Docker
- HTTPS
- Nginx
- Monitoring
- CI/CD
- Load testing

---

# 40. Definition of Done

The technical MVP is complete when:

- [ ] FastAPI runs successfully.
- [ ] Weather provider integration works.
- [ ] Current weather endpoint works.
- [ ] Forecast endpoint works.
- [ ] Chat endpoint works.
- [ ] AI receives live weather context.
- [ ] AI does not invent weather values.
- [ ] Flutter communicates with FastAPI over HTTPS.
- [ ] PostgreSQL stores required user data.
- [ ] Redis caching works.
- [ ] Basic weather alerts work.
- [ ] API secrets are server-side.
- [ ] Error handling is implemented.
- [ ] Unit and API tests pass.
- [ ] Backend is deployable with Docker.
- [ ] Android build works.

---

# 41. Key Engineering Principle

The most important architecture rule for WeatherGPT is:

```text
             FACTS
               ↓
        Weather Provider
               ↓
        FastAPI Backend
               ↓
        Structured Context
               ↓
             LLM
               ↓
       Explanation / Advice
               ↓
          Flutter App
```

**The LLM explains weather data; it does not create the weather data.**

This separation improves accuracy, reliability, cost control, and future extensibility.
