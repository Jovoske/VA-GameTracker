"""Serve stored image files; let the user flag a frame as empty/animal."""
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import Image, User

router = APIRouter(prefix="/images", tags=["images"])


@router.get("/{image_id}/file")
def image_file(image_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    # Unauthenticated by design: unguessable UUID, and <img> tags can't send a bearer token.
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
