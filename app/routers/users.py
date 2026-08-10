from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.submission import GestureSubmission, SubmissionStatus
from app.models.vote import Vote, VoteType
from app.schemas.user import ProfileResponse, ContributionSummary

router = APIRouter(prefix="/users", tags=["Profil Kontributor"])

# Kontributor dianggap "Aktif" kalau punya minimal 1 submission approved
# dalam N hari terakhir. Gampang diubah kalau kriterianya beda.
ACTIVE_CONTRIBUTOR_WINDOW_DAYS = 30
ACTIVE_CONTRIBUTOR_MIN_APPROVED = 1


@router.get("/me/profile", response_model=ProfileResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Layar 'Profile Kontributor Dataset'.
    Statistik (total kontribusi, tervalidasi, poin) + daftar 'Kontribusi Saya'
    lengkap dengan vote count masing-masing.
    """
    submissions = (
        db.query(GestureSubmission)
        .filter(GestureSubmission.user_id == current_user.id)
        .order_by(GestureSubmission.created_at.desc())
        .all()
    )

    total = len(submissions)
    validated = sum(1 for s in submissions if s.status == SubmissionStatus.approved)

    recent_cutoff = datetime.utcnow() - timedelta(days=ACTIVE_CONTRIBUTOR_WINDOW_DAYS)
    recent_approved = sum(
        1 for s in submissions
        if s.status == SubmissionStatus.approved
        and s.reviewed_at is not None
        and s.reviewed_at >= recent_cutoff
    )
    badge = "Kontributor Aktif" if recent_approved >= ACTIVE_CONTRIBUTOR_MIN_APPROVED else "Kontributor Baru"

    contributions = []
    for s in submissions:
        upvotes = db.query(Vote).filter(
            Vote.submission_id == s.id, Vote.type == VoteType.upvote
        ).count()
        downvotes = db.query(Vote).filter(
            Vote.submission_id == s.id, Vote.type == VoteType.downvote
        ).count()
        contributions.append(ContributionSummary(
            id=s.id,
            label=s.label,
            status=s.status,
            created_at=s.created_at,
            upvotes=upvotes,
            downvotes=downvotes,
        ))

    return ProfileResponse(
        id=current_user.id,
        name=current_user.name,
        badge=badge,
        total_contributions=total,
        validated_contributions=validated,
        points=current_user.points,
        contributions=contributions,
    )