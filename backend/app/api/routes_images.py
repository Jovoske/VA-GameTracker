"""Serve stored image files; let the user flag a frame as empty/animal."""
import os
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.core.security import decode_token
from app.models import Image, User

router = APIRouter(prefix="/images", tags=["images"])

# auto_error=False so a missing header falls through to the ?token= fallback
# rather than 403-ing before we can check it.
_optional_bearer = HTTPBearer(auto_error=False)


@router.get("/{image_id}/file")
def image_file(
    image_id: uuid.UUID,
    token: str | None = None,
    creds: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve a stored frame. Requires a valid session.

    An <img> tag cannot send an Authorization header, which is why this endpoint was
    previously open to anyone who could guess or obtain a UUID — and trail cameras
    photograph people, not just animals. The token may therefore arrive either as a
    normal bearer header or as a ?token= query parameter.

    Query-string tokens can leak through proxy logs and Referer headers, so this is a
    deliberate trade rather than a clean win: for a self-hosted estate it is a large
    improvement over no authentication at all. Short-lived per-image signed URLs are
    the better long-term answer.
    """
    raw = (creds.credentials if creds else None) or token
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        decode_token(raw)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    image = db.get(Image, image_id)
    if image is None or not image.original_path or not os.path.exists(image.original_path):
        raise HTTPException(404, "Image file not found")
    return FileResponse(image.original_path, media_type="image/jpeg")


class FlagBody(BaseModel):
    is_empty: bool


@router.post("/{image_id}/flag")
def flag_image(
    image_id: uuid.UUID,
    body: FlagBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Manual override of the detector. Sticky — the auto-scan won't touch it again."""
    image = db.get(Image, image_id)
    if image is None:
        raise HTTPException(404, "Image not found")
    image.is_empty_frame = body.is_empty
    image.reviewed = True
    db.commit()
    return {"id": str(image.id), "is_empty_frame": image.is_empty_frame, "reviewed": True}
