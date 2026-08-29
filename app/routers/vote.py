from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.submission import GestureSubmission
from app.models.vote import Vote, VoteType
from app.schemas.vote import VoteRequest, VoteResponse
from app.services.points_services import add_points, POINTS_RECEIVED_UPVOTE, POINTS_RECEIVED_DOWNVOTE

router = APIRouter(prefix="/submissions", tags=["Community Voting"])


def get_vote_counts(db: Session, submission_id: int) -> tuple[int, int]:
    """Hitung upvote/downvote sebuah submission. Dipakai juga di router submissions."""
    upvotes = db.query(Vote).filter(
        Vote.submission_id == submission_id, Vote.type == VoteType.upvote
    ).count()
    downvotes = db.query(Vote).filter(
        Vote.submission_id == submission_id, Vote.type == VoteType.downvote
    ).count()
    return upvotes, downvotes


def get_my_vote(db: Session, user_id: int, submission_id: int) -> str | None:
    """Vote user tertentu pada sebuah submission ("upvote"/"downvote"/None)."""
    vote = db.query(Vote).filter(
        Vote.user_id == user_id, Vote.submission_id == submission_id
    ).first()
    return vote.type.value if vote else None


# Alias lama, biar tidak breaking kalau ada pemanggil lain yang lupa di-update.
_vote_counts = get_vote_counts


@router.post("/{submission_id}/vote", response_model=VoteResponse)
def vote_submission(
    submission_id: int,
    data: VoteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upvote / downvote sebuah submission komunitas.
    1 user hanya boleh 1 vote per submission — vote baru akan menimpa
    (ubah upvote<->downvote) vote lama, bukan menambah dobel.
    """
    submission = db.query(GestureSubmission).filter(
        GestureSubmission.id == submission_id
    ).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission tidak ditemukan")

    existing = db.query(Vote).filter(
        Vote.user_id == current_user.id, Vote.submission_id == submission_id
    ).first()

    if existing and existing.type == data.type:
        raise HTTPException(status_code=400, detail="Kamu sudah vote seperti ini sebelumnya")

    if existing:
        # Batalkan efek poin vote lama sebelum ganti tipe vote
        old_points = POINTS_RECEIVED_UPVOTE if existing.type == VoteType.upvote else POINTS_RECEIVED_DOWNVOTE
        add_points(db, submission.user_id, -old_points, "vote_changed", submission.id)
        existing.type = data.type
    else:
        db.add(Vote(user_id=current_user.id, submission_id=submission_id, type=data.type))

    db.commit()

    new_points = POINTS_RECEIVED_UPVOTE if data.type == VoteType.upvote else POINTS_RECEIVED_DOWNVOTE
    add_points(db, submission.user_id, new_points, "received_" + data.type.value, submission.id)

    upvotes, downvotes = _vote_counts(db, submission_id)
    return VoteResponse(
        submission_id=submission_id,
        upvotes=upvotes,
        downvotes=downvotes,
        my_vote=data.type.value,
    )