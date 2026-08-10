from pydantic import BaseModel
from typing import Optional, List
from app.models.dictionary import DictionaryCategory


class DictionaryListItem(BaseModel):
    """Buat grid 'Kamus Isyarat' (search result / listing)."""
    id: int
    word: str
    category: DictionaryCategory
    video_path: str

    class Config:
        from_attributes = True


class DictionaryDetail(BaseModel):
    """Buat 'Detail Kata'."""
    id: int
    word: str
    category: DictionaryCategory
    video_path: str
    cara_isyarat: Optional[str] = None  
    already_learned: bool = False  # relatif ke user yang login (dari SignPedia belajar, kalau ada)

    class Config:
        from_attributes = True


class DictionaryMeaning(BaseModel):
    """Buat 'Makna Kata' / hasil tombol 'Lihat Penjelasan'."""
    id: int
    word: str
    illustration_path: Optional[str] = None
    meaning: Optional[str] = None
    source: Optional[str] = None
    related_words: List[str] = []

    class Config:
        from_attributes = True


class AlphabetLetter(BaseModel):
    letter: str
    video_url: str


class AlphabetFallbackResponse(BaseModel):
    """Buat 'Ejaan Alfabet' kalau kata gak ketemu di kamus."""
    found: bool
    query: str
    letters: List[AlphabetLetter] = []

class DictionarySearchResponse(BaseModel):
    """Layar 'Hasil Pencarian Kata' — daftar match di kamus,
    atau fallback ejaan alfabet kalau kata belum tersedia."""
    query: str
    found: bool
    matches: List[DictionaryListItem] = []
    alphabet: List[AlphabetLetter] = []