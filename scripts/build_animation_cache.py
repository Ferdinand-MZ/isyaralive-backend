"""
PREBUILD ANIMATION CACHE
========================
Ekstrak landmark dari semua video peraga (kamus SignPedia, kontribusi
approved SignHub, dan video alfabet) menjadi JSON di cache/animations/.

Kenapa perlu:
Endpoint /gesture/text-to-animation mengekstrak landmark saat pertama kali
sebuah video diminta — proses ini butuh beberapa detik per video. Jalankan
script ini SEBELUM demo/presentasi supaya semua permintaan langsung instan.

Cara pakai:
    python scripts/build_animation_cache.py
    python scripts/build_animation_cache.py --only alphabet
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, init_db
from app.models.dictionary import DictionaryEntry
from app.models.submission import GestureSubmission, SubmissionStatus
from app.services.animation_service import extract_animation
from app.services.detector_instance import detector

ALPHABET_DIR = "assets/alphabet"


def collect_targets(only: str) -> list[tuple[str, str]]:
    """Return list of (label, video_path)."""
    targets: list[tuple[str, str]] = []
    init_db()
    db = SessionLocal()

    try:
        if only in ("all", "dictionary"):
            for entry in db.query(DictionaryEntry).all():
                if entry.video_path:
                    targets.append((entry.word, entry.video_path))

        if only in ("all", "community"):
            subs = (
                db.query(GestureSubmission)
                .filter(GestureSubmission.status == SubmissionStatus.approved)
                .all()
            )
            for sub in subs:
                targets.append((sub.label, sub.video_path))
    finally:
        db.close()

    if only in ("all", "alphabet") and os.path.isdir(ALPHABET_DIR):
        for filename in sorted(os.listdir(ALPHABET_DIR)):
            if filename.lower().endswith((".mp4", ".mov")):
                targets.append((os.path.splitext(filename)[0].upper(),
                                os.path.join(ALPHABET_DIR, filename)))

    return targets


def run(only: str):
    targets = collect_targets(only)
    if not targets:
        print("Tidak ada video peraga yang ditemukan. "
              "Isi kamus / approve kontribusi / taruh video alfabet dulu.")
        return

    ok, gagal = 0, 0
    for label, path in targets:
        if not os.path.isfile(path):
            print(f"[SKIP] {label}: file tidak ada -> {path}")
            gagal += 1
            continue

        data = extract_animation(path, detector)
        if data is None:
            print(f"[GAGAL] {label}: tidak ada tangan terdeteksi di video")
            gagal += 1
        else:
            print(f"[OK]    {label}: {data['frame_count']} frame")
            ok += 1

    print(f"\nSelesai. Berhasil: {ok}, gagal/dilewati: {gagal}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prebuild cache animasi landmark")
    parser.add_argument(
        "--only",
        default="all",
        choices=["all", "dictionary", "community", "alphabet"],
        help="Batasi sumber video yang diproses",
    )
    args = parser.parse_args()
    run(args.only)