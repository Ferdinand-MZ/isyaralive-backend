from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.submission import GestureSubmission, SubmissionStatus

router = APIRouter(prefix="/gesture", tags=["SignPedia / Text-to-Gesture"])

ALPHABET_VIDEO_BASE = "/static/alphabet"  # video A-Z, disiapkan manual sekali


def find_gesture_video(word: str, db: Session):
    """Cari video gesture kosakata yang sudah approved (case-insensitive)."""
    return (
        db.query(GestureSubmission)
        .filter(
            GestureSubmission.status == SubmissionStatus.approved,
            GestureSubmission.label.ilike(word)
        )
        .first()
    )


def get_alphabet_video(letter: str) -> str:
    return f"{ALPHABET_VIDEO_BASE}/{letter.lower()}.mp4"


@router.post("/text-to-video")
def text_to_gesture(text: str, db: Session = Depends(get_db)):
    words = text.lower().split()
    results = []

    for word in words:
        gesture = find_gesture_video(word, db)
        if gesture:
            results.append({
                "word": word,
                "type": "word",
                "video_url": f"/static/approved/{gesture.video_path.split('/')[-1]}"
            })
        else:
            for letter in word:
                if letter.isalpha():
                    results.append({
                        "word": letter.upper(),
                        "type": "letter",
                        "video_url": get_alphabet_video(letter)
                    })

    return {"sequence": results}