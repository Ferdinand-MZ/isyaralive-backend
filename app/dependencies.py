from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole

# ============================================================
# DEPENDENCY INJECTION untuk proteksi endpoint
# Pakai di endpoint dengan: Depends(get_current_user)
#                       atau Depends(get_current_admin)
# ============================================================

bearer_scheme = HTTPBearer()
optional_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Cek JWT token valid, return User object.
    Dipakai di endpoint yang WAJIB login (user biasa atau admin).
    """
    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid atau sudah expired"
        )

    user_id = payload.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User tidak ditemukan"
        )

    return user


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_bearer_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Sama seperti get_current_user, tapi tidak wajib login.
    Dipakai di endpoint publik yang mau tetap tahu "my_vote" kalau user login,
    tapi tetap bisa diakses tanpa token (mis. feed komunitas, detail gestur).
    """
    if credentials is None:
        return None

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        return None

    user_id = payload.get("user_id")
    return db.query(User).filter(User.id == user_id).first()


def get_current_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Cek user adalah admin.
    Dipakai khusus di endpoint /admin/*
    """
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya admin yang bisa mengakses endpoint ini"
        )
    return current_user
