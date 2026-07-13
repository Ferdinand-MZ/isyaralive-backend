from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from app.models.submission import SubmissionStatus
from app.schemas.user import UserResponse


class SubmissionResponse(BaseModel):
    id: int
    label: str
    video_path: str
    status: SubmissionStatus
    admin_note: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    user: UserResponse

    class Config:
        from_attributes = True


class SubmissionReview(BaseModel):
    """Body request saat admin approve/reject"""
    admin_note: Optional[str] = None
