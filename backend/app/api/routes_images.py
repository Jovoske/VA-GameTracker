"""Serve stored original image files.

Unauthenticated by design: the URL carries an unguessable UUID and browsers
can't attach a bearer token to an <img> tag. Fine for a local-first app.
"""
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Image

router = APIRouter(prefix="/images", tags=["images"])


@router.get("/{image_id}/file")
def image_file(image_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    image = db.get(Image, image_id)
    if image is None or not image.original_path or not os.path.exists(image.original_path):
        raise HTTPException(404, "Image file not found")
    return FileResponse(image.original_path, media_type="image/jpeg")
