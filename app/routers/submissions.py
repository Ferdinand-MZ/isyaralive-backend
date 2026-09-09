from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.dependencies import get_current_user, get_current_user_optional
from app.models.user import User
from app.models.submission import GestureSubmission, SubmissionStatus, GestureCategory
from app.schemas.submission import (
    SubmissionResponse,
    SubmissionDetailResponse,
    ContributorInfo,
    RelatedGesture,
)
from app.services.file_handler import save_pending_video
from app.routers.vote import get_vote_counts, get_my_vote

router = APIRouter(prefix="/submissions", tags=["Community Submissions"])

RELATED_GESTURES_LIMIT = 5


def to_submission_response(db: Session, submission: GestureSubmission, current_user_id: Optional[int]) -> SubmissionResponse:
    """Bungkus GestureSubmission jadi SubmissionResponse + ringkasan vote."""
    upvotes, downvotes = get_vote_counts(db, submission.id)
    my_vote = get_my_vote(db, current_user_id, submission.id) if current_user_id else None

    response = SubmissionResponse.model_validate(submission)
    response.upvotes = upvotes
    response.downvotes = downvotes
    response.my_vote = my_vote
    return response


@router.post("/", response_model=SubmissionResponse)
def create_submission(
    label: str = Form(..., description="Kata/kalimat dari gesture, contoh: 'Halo'"),
    category: GestureCategory = Form(GestureCategory.lainnya, description="Kategori gestur"),
    description: str = Form(None, description="Deskripsi/Konteks penggunaan gestur"),
    region: str = Form(None, description="Daerah/Dialek asal gestur (opsional)"),
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
        status=SubmissionStatus.pending,
        category=category,
        description=description.strip() if description else None,
        region=region.strip() if region else None,
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
    return [to_submission_response(db, s, current_user.id) for s in submissions]


@router.get("/", response_model=List[SubmissionResponse])
def list_submissions(
    status: SubmissionStatus = Query(
        SubmissionStatus.approved,
        description="Filter status submission yang ditampilkan (default: approved).",
    ),
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """
    Feed komunitas SignHub: daftar kontribusi dari SEMUA user (default hanya
    yang sudah approved), lengkap dengan upvotes/downvotes dan my_vote relatif
    ke user yang sedang login. Tidak wajib login (public), tapi kalau ada
    token valid, my_vote ikut terisi.
    """
    submissions = (
        db.query(GestureSubmission)
        .filter(GestureSubmission.status == status)
        .order_by(GestureSubmission.created_at.desc())
        .all()
    )
    current_user_id = current_user.id if current_user else None
    return [to_submission_response(db, s, current_user_id) for s in submissions]


@router.get("/{submission_id}", response_model=SubmissionDetailResponse)
def get_submission_detail(
    submission_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """
    Layar 'Detail Gestur': submission + info kontributor (nama, peringkat,
    total kontribusi) + rekomendasi beberapa gestur approved lainnya.
    Tidak wajib login (public), tapi kalau ada token valid, my_vote ikut terisi.
    """
    submission = (
        db.query(GestureSubmission).filter(GestureSubmission.id == submission_id).first()
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission tidak ditemukan")

    current_user_id = current_user.id if current_user else None
    base = to_submission_response(db, submission, current_user_id)

    contributor_user = submission.user
    total_contributions = (
        db.query(GestureSubmission)
        .filter(GestureSubmission.user_id == contributor_user.id)
        .count()
    )

    # Peringkat kontributor berdasarkan total poin, dibanding semua user.
    rank = None
    ranked_user_ids = [
        row.id for row in db.query(User.id).order_by(User.points.desc()).all()
    ]
    if contributor_user.id in ranked_user_ids:
        rank = ranked_user_ids.index(contributor_user.id) + 1

    contributor = ContributorInfo(
        id=contributor_user.id,
        name=contributor_user.name,
        rank=rank,
        total_contributions=total_contributions,
    )

    related_rows = (
        db.query(GestureSubmission)
        .filter(
            GestureSubmission.status == SubmissionStatus.approved,
            GestureSubmission.id != submission.id,
        )
        .order_by(func.random())
        .limit(RELATED_GESTURES_LIMIT)
        .all()
    )
    related = [
        RelatedGesture(id=r.id, label=r.label, video_path=r.video_path) for r in related_rows
    ]

    return SubmissionDetailResponse(**base.model_dump(), contributor=contributor, related=related)
