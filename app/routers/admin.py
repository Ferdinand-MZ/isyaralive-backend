from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.core.database import get_db
from app.dependencies import get_current_admin
from app.models.user import User
from app.models.submission import GestureSubmission, SubmissionStatus
from app.schemas.submission import SubmissionResponse, SubmissionReview
from app.services.file_handler import move_video
from app.services.points_services import add_points, POINTS_SUBMISSION_APPROVED
from app.core.config import UPLOAD_APPROVED_DIR, UPLOAD_REJECTED_DIR

router = APIRouter(prefix="/admin", tags=["Admin Review"])


@router.get("/submissions/pending", response_model=List[SubmissionResponse])
def list_pending(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Lihat semua submission yang masih menunggu review."""
    submissions = (
        db.query(GestureSubmission)
        .filter(GestureSubmission.status == SubmissionStatus.pending)
        .order_by(GestureSubmission.created_at.asc())
        .all()
    )
    return submissions


@router.get("/submissions/approved", response_model=List[SubmissionResponse])
def list_approved(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Lihat semua submission yang sudah approved.
    Berguna untuk tim ML download batch video sebelum retraining manual.
    """
    submissions = (
        db.query(GestureSubmission)
        .filter(GestureSubmission.status == SubmissionStatus.approved)
        .order_by(GestureSubmission.reviewed_at.desc())
        .all()
    )
    return submissions


@router.post("/submissions/{submission_id}/approve", response_model=SubmissionResponse)
def approve_submission(
    submission_id: int,
    review: SubmissionReview,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Admin approve submission.
    Video dipindah dari /pending ke /approved.
    """
    submission = db.query(GestureSubmission).filter(
        GestureSubmission.id == submission_id
    ).first()

    if not submission:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Submission tidak ditemukan")

    new_path = move_video(submission.video_path, UPLOAD_APPROVED_DIR)

    submission.video_path = new_path
    submission.status = SubmissionStatus.approved
    submission.admin_note = review.admin_note
    submission.reviewed_by = current_admin.id
    submission.reviewed_at = datetime.utcnow()

    db.commit()
    db.refresh(submission)

    # Gamifikasi: submitter dapat poin karena dataset-nya berhasil divalidasi
    add_points(db, submission.user_id, POINTS_SUBMISSION_APPROVED, "submission_approved", submission.id)

    return submission


@router.post("/submissions/{submission_id}/reject", response_model=SubmissionResponse)
def reject_submission(
    submission_id: int,
    review: SubmissionReview,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Admin reject submission.
    Video dipindah dari /pending ke /rejected (bukan dihapus, untuk audit trail).
    """
    submission = db.query(GestureSubmission).filter(
        GestureSubmission.id == submission_id
    ).first()

    if not submission:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Submission tidak ditemukan")

    new_path = move_video(submission.video_path, UPLOAD_REJECTED_DIR)

    submission.video_path = new_path
    submission.status = SubmissionStatus.rejected
    submission.admin_note = review.admin_note
    submission.reviewed_by = current_admin.id
    submission.reviewed_at = datetime.utcnow()

    db.commit()
    db.refresh(submission)

    return submission