from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.db.models import User
from app.schemas.usage import CurrentUserUsageResponse
from app.services.usage_service import get_user_usage

router = APIRouter()


@router.get("/usage/me", response_model=CurrentUserUsageResponse)
def get_my_usage(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_user_usage(db, current_user.id)
