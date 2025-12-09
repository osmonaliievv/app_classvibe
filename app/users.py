from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from .database import get_db
from .auth import get_current_user
from .models import User
from .schemas import UserShort

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search", response_model=list[UserShort])
def search_users(
    query: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = f"%{query.lower()}%"

    users = (
        db.query(User)
        .filter(
            or_(
                User.first_name.ilike(q),
                User.last_name.ilike(q),
                User.username.ilike(q),
            )
        )
        .limit(30)
        .all()
    )

    return users
