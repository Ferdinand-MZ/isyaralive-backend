from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from app.models.submission import SubmissionStatus, GestureCategory
from app.schemas.user import UserResponse


class SubmissionResponse(BaseModel):
    id: int
    label: str
    video_path: str
    status: SubmissionStatus
    category: GestureCategory
    description: Optional[str] = None
    region: Optional[str] = None
    admin_note: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None

    # Terisi hanya untuk submission yang pernah dibuka voting-nya. Null pada
    # alur lama (pending -> approved langsung), jadi klien lama tidak rusak.
    voting_started_at: Optional[datetime] = None
    voting_ends_at: Optional[datetime] = None

    user: UserResponse

    # Ringkasan vote, dihitung di router (bukan kolom asli tabel)
    upvotes: int = 0
    downvotes: int = 0
    my_vote: Optional[str] = None  # "upvote" / "downvote" / None, relatif ke user yang request

    class Config:
        from_attributes = True


class SubmissionReview(BaseModel):
    """Body request saat admin/validator approve/reject"""
    admin_note: Optional[str] = None

class ContributorInfo(BaseModel):
    """Info kontributor + peringkatnya, dipakai di layar 'Detail Gestur'."""
    id: int
    name: str
    rank: Optional[int] = None
    total_contributions: int


class RelatedGesture(BaseModel):
    """Item ringkas untuk 'Gestur Lainnya'."""
    id: int
    label: str
    video_path: str


class SubmissionDetailResponse(SubmissionResponse):
    """Layar 'Detail Gestur' — SubmissionResponse + info kontributor & rekomendasi."""
    contributor: ContributorInfo
    related: List[RelatedGesture] = []