"""Admin routes — version info now; Git self-update lands in a later milestone."""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin
from app.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/version")
def version(_: User = Depends(get_current_admin)) -> dict:
    return {"version": "0.1.0", "channel": "milestone-0"}
