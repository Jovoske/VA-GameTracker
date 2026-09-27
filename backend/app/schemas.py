"""Pydantic request/response DTOs."""
import uuid

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    email: str
    password: str
    # The known-phone mark this phone was given at its last sign-in (TokenResponse).
    known_phone: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # The photo pass (app.core.security): what photo addresses carry, never the
    # sign-in itself.
    image_token: str | None = None
    # Kept by the phone and sent with its next sign-in: a phone that has signed in
    # with this email before isn't held up by strangers guessing it (api/throttle.py).
    known_phone: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    role: str
