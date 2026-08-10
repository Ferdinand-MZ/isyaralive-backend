from string import ascii_uppercase
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.dictionary import DictionaryEntry, DictionaryCategory
from app.routers.gesture_lookup import get_alphabet_video
from app.schemas.dictionary import (
    DictionaryListItem,
    DictionaryDetail,
    DictionaryMeaning,
    DictionarySearchResponse,
    AlphabetLetter,
)

router = APIRouter(prefix="/dictionary", tags=["SignPedia / Kamus Isyarat"])


# NOTE: /alphabet dan /search didaftarkan SEBELUM /{entry_id} supaya
# tidak ketabrak sama path parameter dinamis di bawahnya.


@router.get("/alphabet", response_model=List[AlphabetLetter])
def list_alphabet():
    """Tab 'Huruf' — 26 video ejaan alfabet A-Z (aset statis, di luar tabel kamus)."""
    return [
        AlphabetLetter(letter=letter, video_url=get_alphabet_video(letter))
        for letter in ascii_uppercase
    ]


@router.get("/search", response_model=DictionarySearchResponse)
def search_dictionary(
    q: str = Query(..., min_length=1, description="Kata yang dicari, mis: 'fotosintesis'"),
    db: Session = Depends(get_db),
):
    """
    Layar 'Hasil Pencarian Kata'.
    Kalau kata ketemu di kamus -> balikin daftar match (found=True).
    Kalau TIDAK ketemu -> balikin ejaan alfabet sebagai alternatif komunikasi (found=False).
    """
    matches = (
        db.query(DictionaryEntry)
        .filter(DictionaryEntry.word.ilike(f"%{q}%"))
        .order_by(DictionaryEntry.word.asc())
        .all()
    )

    if matches:
        return DictionarySearchResponse(query=q, found=True, matches=matches, alphabet=[])

    alphabet = [
        AlphabetLetter(letter=ch.upper(), video_url=get_alphabet_video(ch))
        for ch in q
        if ch.isalpha()
    ]
    return DictionarySearchResponse(query=q, found=False, matches=[], alphabet=alphabet)


@router.get("/", response_model=List[DictionaryListItem])
def list_dictionary(
    search: Optional[str] = Query(None, description="Cari kata, mis: 'terima'"),
    category: Optional[DictionaryCategory] = Query(None, description="Filter kategori (Angka/Emoji/dst)"),
    sort: str = Query("az", pattern="^(az|recent)$", description="'az' abjad (default), 'recent' buat tab Terkini"),
    db: Session = Depends(get_db),
):
    """Grid 'Kamus Isyarat' — daftar kosakata BISINDO, bisa difilter/dicari/diurutkan."""
    query = db.query(DictionaryEntry)

    if search:
        query = query.filter(DictionaryEntry.word.ilike(f"%{search}%"))
    if category:
        query = query.filter(DictionaryEntry.category == category)

    if sort == "recent":
        query = query.order_by(DictionaryEntry.created_at.desc())
    else:
        query = query.order_by(DictionaryEntry.word.asc())

    return query.all()


@router.get("/{entry_id}", response_model=DictionaryDetail)
def get_dictionary_detail(entry_id: int, db: Session = Depends(get_db)):
    """Layar 'Detail Kata' — video peraga + cara isyarat."""
    entry = db.query(DictionaryEntry).filter(DictionaryEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kata tidak ditemukan di kamus")

    return DictionaryDetail(
        id=entry.id,
        word=entry.word,
        category=entry.category,
        video_path=entry.video_path,
        cara_isyarat=entry.cara_isyarat,
        already_learned=False,
    )


@router.get("/{entry_id}/meaning", response_model=DictionaryMeaning)
def get_dictionary_meaning(entry_id: int, db: Session = Depends(get_db)):
    """Layar 'Makna Kata' — tombol 'Lihat Penjelasan'."""
    entry = db.query(DictionaryEntry).filter(DictionaryEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kata tidak ditemukan di kamus")

    related = [w.strip() for w in entry.related_words.split(",")] if entry.related_words else []

    return DictionaryMeaning(
        id=entry.id,
        word=entry.word,
        illustration_path=entry.illustration_path,
        meaning=entry.meaning,
        source=entry.source,
        related_words=related,
    )