from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.submission import GestureSubmission, SubmissionStatus
from app.schemas.submission import SubmissionResponse
from app.services.file_handler import save_pending_video

router = APIRouter(prefix="/submissions", tags=["Community Submissions"])


@router.post("/", response_model=SubmissionResponse)
def create_submission(
    label: str = Form(..., description="Kata/kalimat dari gesture, contoh: 'Halo'"),
    video: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    User upload video gesture baru beserta labelnya.
    Status otomatis: pending — menunggu admin review.
    """
    video_path = save_pending_video(video)

    submission = GestureSubmission(
        user_id=current_user.id,
        label=label.strip(),
        video_path=video_path,
        status=SubmissionStatus.pending
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    return submission


@router.get("/me", response_model=List[SubmissionResponse])
def my_submissions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lihat semua submission milik user yang sedang login, beserta statusnya."""
    submissions = (
        db.query(GestureSubmission)
        .filter(GestureSubmission.user_id == current_user.id)
        .order_by(GestureSubmission.created_at.desc())
        .all()
    )
    return submissions
