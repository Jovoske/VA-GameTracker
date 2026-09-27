"""Pydantic request/response DTOs."""
import uuid

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # The photo pass (app.core.security): what photo addresses carry, never the
    # sign-in itself.
    image_token: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    role: str
