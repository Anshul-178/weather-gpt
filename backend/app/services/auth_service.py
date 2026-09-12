"""Authentication service.

Implements register/login with bcrypt password hashing and JWT access
tokens (technical.md §25). Secrets never leave the server.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx  # noqa: F401 - kept for parity with other services
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.database import get_db
from app.models.user import User
from app.utils.logging import get_logger

logger = get_logger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


class AuthService:
    """Registration, login and token handling."""

    def hash_password(self, plain: str) -> str:
        """Hash a plaintext password (never store plaintext)."""
        return pwd_context.hash(plain)

    def verify_password(self, plain: str, hashed: str) -> bool:
        """Verify a plaintext password against a stored hash."""
        return pwd_context.verify(plain, hashed)

    def create_access_token(self, user_id: int) -> str:
        """Create a signed, expiring JWT access token."""
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.access_token_expire_minutes
        )
        payload = {"sub": str(user_id), "exp": expire, "iat": datetime.now(timezone.utc)}
        return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    def decode_token(self, token: str) -> int:
        """Decode a JWT and return the user id."""
        try:
            payload = jwt.decode(
                token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
            )
            return int(payload["sub"])
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
            ) from exc
        except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            ) from exc

    async def register(self, name: str, email: str, password: str, db: AsyncSession) -> User:
        """Register a new user with a hashed password."""
        existing = await self._get_by_email(email, db)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email already exists",
            )
        user = User(
            name=name.strip(),
            email=email.lower().strip(),
            password_hash=self.hash_password(password),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def authenticate(self, email: str, password: str, db: AsyncSession) -> User:
        """Authenticate a user by email and password."""
        user = await self._get_by_email(email, db)
        if user is None or not self.verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        return user

    async def _get_by_email(self, email: str, db: AsyncSession) -> Optional[User]:
        """Fetch a user by email."""
        result = await db.execute(
            select(User).where(User.email == email.lower().strip())
        )
        return result.scalars().first()


auth_service = AuthService()


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: requires a valid bearer token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    user_id = auth_service.decode_token(credentials.credentials)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Dependency: resolves the user when a token is present, else None."""
    if credentials is None:
        return None
    try:
        user_id = auth_service.decode_token(credentials.credentials)
    except HTTPException:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalars().first()
