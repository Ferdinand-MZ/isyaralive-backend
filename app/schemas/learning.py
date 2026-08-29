from pydantic import BaseModel
from datetime import date
from typing import Optional, List


class MaterialItem(BaseModel):
    id: int
    order: int
    word: str
    video_path: str
    cara_isyarat: Optional[str] = None
    completed: bool = False

    class Config:
        from_attributes = True


class LevelSummary(BaseModel):
    """Buat card level di 'Materi Pembelajaran' (ringkas + progress bar)."""
    id: int
    order: int
    title: str
    total_materials: int
    completed_materials: int

    class Config:
        from_attributes = True


class LevelDetail(BaseModel):
    id: int
    order: int
    title: str
    materials: List[MaterialItem]

    class Config:
        from_attributes = True


class OverallProgress(BaseModel):
    """Buat header 'Progress Belajar: 48 dari 100 kata'."""
    total_words: int
    learned_words: int
    levels: List[LevelSummary]

    # Statistik winstreak, dipakai juga di kartu 'N hari winstreak' Beranda.
    current_streak: int = 0
    longest_streak: int = 0


class LearningStreak(BaseModel):
    """Statistik winstreak belajar berdiri sendiri (kartu 'N hari winstreak' Beranda)."""
    current_streak: int = 0
    longest_streak: int = 0
    last_activity_date: Optional[date] = None


class QuizQuestion(BaseModel):
    material_id: int
    video_path: str
    options: List[str]  # 4 pilihan kata, salah satunya benar


class QuizSubmitRequest(BaseModel):
    material_id: int
    answer: str


class QuizSubmitResponse(BaseModel):
    correct: bool
    correct_answer: str
    points_awarded: int = 0  # >0 kalau ini pertama kali user jawab benar utk materi ini