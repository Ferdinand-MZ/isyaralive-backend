import os
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.submission import GestureSubmission, SubmissionStatus
from app.models.dictionary import DictionaryEntry
from app.services.animation_service import extract_animation
from app.services.detector_instance import detector

router = APIRouter(prefix="/gesture", tags=["SignPedia / Text-to-Gesture"])

# ============================================================
# TEKS/SUARA -> GESTUR
#
# Dua bentuk keluaran, dipakai bergantian oleh aplikasi:
#   /gesture/text-to-video      -> URL video peraga (mode sederhana)
#   /gesture/text-to-animation  -> koordinat landmark per frame, digambar
#                                  ulang oleh Flutter CustomPainter
#
# Sumber peraga untuk satu kata, berurutan:
#   1. Kamus SignPedia (DictionaryEntry) — konten kurasi
#   2. Video kontribusi komunitas yang sudah approved (SignHub)
#   3. Fallback ejaan alfabet per huruf
# Setiap item selalu punya flag "available" supaya aplikasi tidak
# menampilkan URL yang ternyata 404 (mis. video alfabet belum diisi).
# ============================================================

ALPHABET_DIR = "assets/alphabet"
ALPHABET_URL_BASE = "/static/alphabet"
DICTIONARY_URL_BASE = "/static/dictionary"
APPROVED_URL_BASE = "/static/approved"


def _dictionary_source(word: str, db: Session) -> Optional[dict]:
    entry = (
        db.query(DictionaryEntry)
        .filter(DictionaryEntry.word.ilike(word))
        .first()
    )
    if not entry or not entry.video_path:
        return None
    return {
        "source": "dictionary",
        "path": entry.video_path,
        "url": f"{DICTIONARY_URL_BASE}/{os.path.basename(entry.video_path)}",
    }


def _community_source(word: str, db: Session) -> Optional[dict]:
    gesture = (
        db.query(GestureSubmission)
        .filter(
            GestureSubmission.status == SubmissionStatus.approved,
            GestureSubmission.label.ilike(word),
        )
        .order_by(GestureSubmission.reviewed_at.desc())
        .first()
    )
    if not gesture:
        return None
    return {
        "source": "community",
        "path": gesture.video_path,
        "url": f"{APPROVED_URL_BASE}/{os.path.basename(gesture.video_path)}",
    }


def get_alphabet_video(letter: str) -> str:
    """
    URL video ejaan satu huruf.

    Dipakai app/routers/dictionary.py untuk tab "Huruf" (A-Z) dan untuk
    hasil pencarian kata yang tidak ada di kamus. Dipertahankan dengan
    signature yang sama seperti versi sebelumnya supaya dictionary.py
    tidak perlu diubah.
    """
    return f"{ALPHABET_URL_BASE}/{letter.lower()}.mp4"


def alphabet_video_available(letter: str) -> bool:
    """Cek file video huruf benar-benar ada di assets/alphabet/."""
    return os.path.isfile(os.path.join(ALPHABET_DIR, f"{letter.lower()}.mp4"))


def _alphabet_source(letter: str) -> dict:
    filename = f"{letter.lower()}.mp4"
    path = os.path.join(ALPHABET_DIR, filename)
    return {
        "source": "alphabet",
        "path": path,
        "url": f"{ALPHABET_URL_BASE}/{filename}",
    }


def resolve_word(word: str, db: Session) -> list[dict]:
    """
    Ubah SATU kata menjadi daftar item peraga.
    Kalau kata ada di kamus/komunitas -> 1 item bertipe 'word'.
    Kalau tidak -> beberapa item bertipe 'letter' (ejaan alfabet).
    """
    src = _dictionary_source(word, db) or _community_source(word, db)
    if src:
        return [{
            "word": word,
            "type": "word",
            "source": src["source"],
            "path": src["path"],
            "video_url": src["url"],
            "available": os.path.isfile(src["path"]),
        }]

    items = []
    for letter in word:
        if not letter.isalpha():
            continue
        src = _alphabet_source(letter)
        items.append({
            "word": letter.upper(),
            "type": "letter",
            "source": "alphabet",
            "path": src["path"],
            "video_url": src["url"],
            "available": os.path.isfile(src["path"]),
        })
    return items


@router.post("/text-to-video")
def text_to_gesture(text: str = Query(..., description="Teks/hasil speech-to-text yang mau diperagakan"),
                    db: Session = Depends(get_db)):
    """Peragaan berbasis video. Item dengan available=false berarti aset belum tersedia."""
    results = []
    for word in text.lower().split():
        results.extend(resolve_word(word, db))

    missing = [r["word"] for r in results if not r["available"]]
    return {
        "sequence": [
            {k: v for k, v in item.items() if k != "path"}
            for item in results
        ],
        "missing_assets": missing,
    }


@router.post("/text-to-animation")
def text_to_animation(text: str = Query(..., description="Teks/hasil speech-to-text yang mau diperagakan"),
                      db: Session = Depends(get_db)):
    """
    Peragaan berbasis LANDMARK — dipakai Flutter CustomPainter untuk
    menggambar ulang gerakan tangan tanpa aset animasi buatan tangan.

    Response:
    {
      "sequence": [
        {"word": "halo", "type": "word", "source": "dictionary",
         "available": true, "fps": 12, "frame_count": 30,
         "frames": [[63 angka], ...]},
        ...
      ],
      "missing_assets": ["z"]
    }
    """
    sequence = []
    missing = []

    for word in text.lower().split():
        for item in resolve_word(word, db):
            animation = extract_animation(item["path"], detector) if item["available"] else None

            if animation is None:
                missing.append(item["word"])
                sequence.append({
                    "word": item["word"],
                    "type": item["type"],
                    "source": item["source"],
                    "available": False,
                    "video_url": item["video_url"],
                    "fps": 0,
                    "frame_count": 0,
                    "frames": [],
                })
                continue

            sequence.append({
                "word": item["word"],
                "type": item["type"],
                "source": item["source"],
                "available": True,
                "video_url": item["video_url"],   # cadangan kalau painter dimatikan
                "fps": animation["fps"],
                "frame_count": animation["frame_count"],
                "frames": animation["frames"],
            })

    return {"sequence": sequence, "missing_assets": missing}