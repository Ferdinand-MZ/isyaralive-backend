from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import List
from app.models.user import UserRole
from app.models.submission import SubmissionStatus


class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: UserRole
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class ContributionSummary(BaseModel):
    """Item ringkas di 'Kontribusi Saya' pada layar Profile."""
    id: int
    label: str
    status: SubmissionStatus
    created_at: datetime
    upvotes: int = 0
    downvotes: int = 0


class ProfileResponse(BaseModel):
    """Layar 'Profile Kontributor Dataset'."""
    id: int
    name: str
    badge: str  # "Kontributor Aktif" / "Kontributor Baru"
    total_contributions: int
    validated_contributions: int
    points: int
    contributions: List[ContributionSummary]
