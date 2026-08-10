import random
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.learning import LearningLevel, LearningMaterial, UserProgress
from app.schemas.learning import (
    OverallProgress,
    LevelSummary,
    LevelDetail,
    MaterialItem,
    QuizQuestion,
    QuizSubmitRequest,
    QuizSubmitResponse,
)

router = APIRouter(prefix="/learning", tags=["Materi Pembelajaran"])


def _completed_material_ids(db: Session, user_id: int) -> set[int]:
    rows = db.query(UserProgress.material_id).filter(UserProgress.user_id == user_id).all()
    return {r.material_id for r in rows}


@router.get("/progress", response_model=OverallProgress)
def get_overall_progress(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Header 'Progress Belajar: X dari Y kata' + ringkasan tiap level."""
    completed_ids = _completed_material_ids(db, current_user.id)

    levels = db.query(LearningLevel).order_by(LearningLevel.order.asc()).all()

    level_summaries = []
    total_words = 0
    learned_words = 0

    for level in levels:
        materials = level.materials
        total = len(materials)
        completed = sum(1 for m in materials if m.id in completed_ids)

        total_words += total
        learned_words += completed

        level_summaries.append(
            LevelSummary(
                id=level.id,
                order=level.order,
                title=level.title,
                total_materials=total,
                completed_materials=completed,
            )
        )

    return OverallProgress(
        total_words=total_words,
        learned_words=learned_words,
        levels=level_summaries,
    )


@router.get("/levels/{level_id}", response_model=LevelDetail)
def get_level_detail(
    level_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Daftar materi/kata dalam satu level, dengan status 'Sudah Dipelajari'."""
    level = db.query(LearningLevel).filter(LearningLevel.id == level_id).first()
    if not level:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Level tidak ditemukan")

    completed_ids = _completed_material_ids(db, current_user.id)

    materials = [
        MaterialItem(
            id=m.id,
            order=m.order,
            word=m.word,
            video_path=m.video_path,
            cara_isyarat=m.cara_isyarat,
            completed=m.id in completed_ids,
        )
        for m in level.materials
    ]

    return LevelDetail(id=level.id, order=level.order, title=level.title, materials=materials)


@router.post("/materials/{material_id}/complete", response_model=MaterialItem)
def mark_material_completed(
    material_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tandai materi 'Sudah Dipelajari' setelah user selesai berlatih."""
    material = db.query(LearningMaterial).filter(LearningMaterial.id == material_id).first()
    if not material:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Materi tidak ditemukan")

    already = (
        db.query(UserProgress)
        .filter(UserProgress.user_id == current_user.id, UserProgress.material_id == material_id)
        .first()
    )
    if not already:
        db.add(UserProgress(user_id=current_user.id, material_id=material_id))
        db.commit()

    return MaterialItem(
        id=material.id,
        order=material.order,
        word=material.word,
        video_path=material.video_path,
        cara_isyarat=material.cara_isyarat,
        completed=True,
    )


@router.get("/quiz/{material_id}", response_model=QuizQuestion)
def get_quiz_question(material_id: int, db: Session = Depends(get_db)):
    """Ambil 1 soal kuis: video gestur + 4 pilihan kata (1 benar, 3 pengecoh acak)."""
    material = db.query(LearningMaterial).filter(LearningMaterial.id == material_id).first()
    if not material:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Materi tidak ditemukan")

    distractors = (
        db.query(LearningMaterial)
        .filter(LearningMaterial.id != material_id)
        .order_by(LearningMaterial.id.asc())
        .all()
    )
    distractor_words = [m.word for m in distractors]
    random.shuffle(distractor_words)
    options = [material.word] + distractor_words[:3]
    random.shuffle(options)

    return QuizQuestion(material_id=material.id, video_path=material.video_path, options=options)


@router.post("/quiz/submit", response_model=QuizSubmitResponse)
def submit_quiz_answer(data: QuizSubmitRequest, db: Session = Depends(get_db)):
    """Cek jawaban kuis user."""
    material = db.query(LearningMaterial).filter(LearningMaterial.id == data.material_id).first()
    if not material:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Materi tidak ditemukan")

    correct = data.answer.strip().lower() == material.word.strip().lower()
    return QuizSubmitResponse(correct=correct, correct_answer=material.word)