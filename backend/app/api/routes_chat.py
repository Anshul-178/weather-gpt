"""Chat API route.

Flow (prompt §13): receive question → validate → resolve location →
retrieve weather → build weather context → optional RAG → call AI →
validate response → return answer.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intents import detect_activity, detect_intent, is_follow_up
from app.config import settings
from app.database.database import get_db
from app.models.chat import Conversation, Message
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse, TtsRequest
from app.services.ai_service import FALLBACK_NO_DATA, ai_service
from app.services.auth_service import get_current_user_optional
from app.services.activity_engine import compute_activity_score
from app.services.cached_weather_service import cached_weather_service
from app.services.edge_tts_service import edge_tts_service
from app.services.location_service import location_service
from app.services.weather_service import WeatherProviderError
router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        400: {"description": "Invalid request"},
        429: {"description": "Rate limited"},
        503: {"description": "Weather provider unavailable"},
    },
)
async def chat(
    body: ChatRequest,
    user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Answer a natural-language weather question using live weather data."""
    lat, lon, place = await location_service.resolve(
        body.latitude, body.longitude, body.location_name
    )

    conversation: Optional[Conversation] = None
    history: list[dict] = []
    if body.conversation_id is not None:
        result = await db.execute(
            select(Conversation).where(Conversation.id == body.conversation_id)
        )
        conversation = result.scalars().first()
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        history = await _load_history(db, conversation.id)

    try:
        current = await cached_weather_service.get_current(lat, lon)
        forecast = await cached_weather_service.get_forecast(lat, lon, days=2)
    except WeatherProviderError:
        # Never let the LLM invent weather when the provider is down.
        return ChatResponse(
            answer=FALLBACK_NO_DATA,
            location=place,
            sources=[],
            conversation_id=conversation.id if conversation else None,
        )

    intent = detect_intent(body.message)
    follow_up = is_follow_up(body.message) and bool(history)
    _ = follow_up  # resolved implicitly through bounded history passed to LLM

    activity_result = None
    if intent.value == "ACTIVITY_RECOMMENDATION":
        activity = detect_activity(body.message)
        if activity:
            score = compute_activity_score(activity, current, forecast)
            activity_result = score.model_dump()

    result = await ai_service.answer_question(
        question=body.message,
        current=current,
        forecast=forecast,
        location_name=place,
        conversation_history=history,
        activity_result=activity_result,
        rag_enabled=settings.rag_enabled,
    )

    conversation = await _persist_exchange(db, conversation, user, body.message, result["answer"])

    return ChatResponse(
        answer=result["answer"],
        location=place,
        intent=intent.value,
        sources=result["sources"],
        conversation_id=conversation.id if conversation else None,
    )


@router.post(
    "/chat/tts",
    summary="Synthesize speech with Microsoft Edge Neural TTS (Indian voices)",
    responses={
        200: {"content": {"audio/mpeg": {}}, "description": "MP3 audio stream"},
        400: {"description": "Empty text"},
    },
)
async def chat_tts(body: TtsRequest) -> Response:
    """Convert weather response text to neural speech (9 Indian languages)."""
    audio_bytes = await edge_tts_service.synthesize_speech(
        text=body.text,
        voice=body.voice,
        language=body.language,
    )
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not synthesize speech for the provided text.",
        )
    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline; filename=weather_response.mp3"},
    )


async def _load_history(db: AsyncSession, conversation_id: int) -> list[dict]:
    """Load bounded conversation history for LLM context."""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(settings.llm_max_history_messages)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    return [{"role": m.role, "content": m.content} for m in rows]


async def _persist_exchange(
    db: AsyncSession,
    conversation: Optional[Conversation],
    user: Optional[User],
    question: str,
    answer: str,
) -> Conversation:
    """Persist every exchange so conversational follow-ups keep working.

    Anonymous conversations are stored without a user link; authenticated
    users get their conversations associated with their account.
    """
    if conversation is None:
        conversation = Conversation(user_id=user.id if user else None)
        db.add(conversation)
        await db.flush()
    db.add(Message(conversation_id=conversation.id, role="user", content=question))
    db.add(Message(conversation_id=conversation.id, role="assistant", content=answer))
    await db.commit()
    return conversation
