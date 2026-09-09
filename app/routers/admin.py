from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta

from app.core.database import get_db
from app.dependencies import get_current_admin
from app.models.user import User
from app.models.point_log import PointLog
from app.models.submission import GestureSubmission, SubmissionStatus
from app.schemas.submission import SubmissionResponse, SubmissionReview
from app.services.file_handler import move_video, delete_video
from app.services.points_services import add_points, POINTS_SUBMISSION_APPROVED
from app.routers.submissions import to_submission_response
from app.core.config import (
    UPLOAD_APPROVED_DIR,
    UPLOAD_REJECTED_DIR,
    UPLOAD_VOTING_DIR,
    VOTING_DURATION_DAYS,
)

router = APIRouter(prefix="/admin", tags=["Admin Review"])


def _ambil_atau_404(db: Session, submission_id: int) -> GestureSubmission:
    submission = db.query(GestureSubmission).filter(
        GestureSubmission.id == submission_id
    ).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission tidak ditemukan")
    return submission


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
    return [to_submission_response(db, s, current_admin.id) for s in submissions]


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
    return [to_submission_response(db, s, current_admin.id) for s in submissions]


@router.get("/submissions/voting", response_model=List[SubmissionResponse])
def list_voting(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Submission yang SEDANG DIBUKA UNTUK VOTING komunitas.

    Ini antrean keputusan akhir admin: tiap item sudah lolos verifikasi, tapi
    BELUM masuk dataset. Yang paling dekat tenggat voting-nya di atas, supaya
    yang perlu diputuskan duluan tidak tenggelam.
    """
    submissions = (
        db.query(GestureSubmission)
        .filter(GestureSubmission.status == SubmissionStatus.voting)
        .order_by(GestureSubmission.voting_ends_at.asc())
        .all()
    )
    return [to_submission_response(db, s, current_admin.id) for s in submissions]


@router.post("/submissions/{submission_id}/open-voting", response_model=SubmissionResponse)
def open_voting(
    submission_id: int,
    review: SubmissionReview,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Admin memverifikasi submission lalu MEMBUKA VOTING komunitas.

    Ini BUKAN "masuk dataset": statusnya jadi `voting`, videonya pindah ke
    /voting supaya bisa ditonton publik, dan jendela voting dibuka selama
    VOTING_DURATION_DAYS hari. Poin +10 sengaja BELUM diberikan — poin itu
    milik keputusan akhir (approve), bukan lolos verifikasi.

    Hanya sah dari status `pending`; selain itu 409, supaya jendela voting
    tidak bisa di-reset diam-diam dan gestur yang sudah masuk dataset tidak
    bisa ditarik mundur lewat pintu ini.
    """
    submission = _ambil_atau_404(db, submission_id)

    if submission.status != SubmissionStatus.pending:
        raise HTTPException(
            status_code=409,
            detail=(
                "Voting hanya bisa dibuka untuk submission berstatus pending "
                f"(status sekarang: {submission.status.value})"
            ),
        )

    dibuka = datetime.utcnow()

    submission.video_path = move_video(submission.video_path, UPLOAD_VOTING_DIR)
    submission.status = SubmissionStatus.voting
    submission.admin_note = review.admin_note
    submission.reviewed_by = current_admin.id
    submission.reviewed_at = dibuka
    submission.voting_started_at = dibuka
    submission.voting_ends_at = dibuka + timedelta(days=VOTING_DURATION_DAYS)

    db.commit()
    db.refresh(submission)

    return to_submission_response(db, submission, current_admin.id)


@router.post("/submissions/{submission_id}/approve", response_model=SubmissionResponse)
def approve_submission(
    submission_id: int,
    review: SubmissionReview,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Admin approve submission — KEPUTUSAN AKHIR "masuk dataset".

    Sah dari `pending` (alur langsung, tanpa voting) MAUPUN dari `voting`
    (setelah admin menimbang hasil voting komunitas). Videonya dipindah ke
    /approved dari folder mana pun ia berada sekarang, dan di sinilah
    submitter mendapat +10 poin.
    """
    submission = _ambil_atau_404(db, submission_id)

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

    return to_submission_response(db, submission, current_admin.id)


@router.post("/submissions/{submission_id}/reject", response_model=SubmissionResponse)
def reject_submission(
    submission_id: int,
    review: SubmissionReview,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Admin reject submission.

    Sah dari `pending` maupun `voting` (mis. hasil voting jelek). Video
    dipindah ke /rejected — BUKAN dihapus, supaya ada jejak audit dan
    kontributor masih bisa menontonnya untuk tahu apa yang harus diperbaiki.
    Untuk benar-benar melenyapkan, pakai DELETE /admin/submissions/{id}.
    """
    submission = _ambil_atau_404(db, submission_id)

    new_path = move_video(submission.video_path, UPLOAD_REJECTED_DIR)

    submission.video_path = new_path
    submission.status = SubmissionStatus.rejected
    submission.admin_note = review.admin_note
    submission.reviewed_by = current_admin.id
    submission.reviewed_at = datetime.utcnow()

    db.commit()
    db.refresh(submission)

    return to_submission_response(db, submission, current_admin.id)


@router.delete("/submissions/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission(
    submission_id: int,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    HAPUS PERMANEN sebuah submission — baris, berkas video, dan vote-nya.

    Beda dengan reject: reject menyimpan jejak (status `rejected` + berkas di
    /rejected). Ini untuk yang memang tidak boleh tersisa — salah unggah,
    duplikat, konten menyimpang. TIDAK bisa dibatalkan.

    Yang ikut dibereskan:
      - `votes` submission ini terhapus (cascade relasi ORM).
      - Poin yang pernah lahir DARI submission ini ditarik kembali lewat satu
        entri kompensasi, supaya papan peringkat tidak menyimpan poin milik
        kontribusi yang sudah tidak ada.
      - `point_logs` lamanya TIDAK dihapus, hanya dilepas dari submission
        (`submission_id = NULL`) — histori periode leaderboard tetap utuh dan
        tidak berubah surut.
      - Berkas videonya dihapus dari disk (best-effort).
    """
    submission = _ambil_atau_404(db, submission_id)

    logs = db.query(PointLog).filter(PointLog.submission_id == submission.id).all()
    poin_dari_submission = sum(log.points for log in logs)
    for log in logs:
        log.submission_id = None

    # Dibaca SEBELUM delete: setelah commit, instance-nya sudah kedaluwarsa
    # dan menyentuh atributnya melempar.
    video_path = submission.video_path
    pemilik_id = submission.user_id

    db.delete(submission)   # votes ikut terhapus lewat cascade relasi
    db.commit()

    if poin_dari_submission:
        add_points(db, pemilik_id, -poin_dari_submission, "submission_deleted", None)

    delete_video(video_path)

    return Response(status_code=status.HTTP_204_NO_CONTENT)