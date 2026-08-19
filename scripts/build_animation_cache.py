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

# Animasi di bawah ini dianggap terlalu pendek untuk diperagakan dengan layak.
# 15 frame pada 12 fps = 1,25 detik.
BATAS_PENDEK = 15


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

    ok = 0
    gagal, pendek = [], []
    for label, path in targets:
        if not os.path.isfile(path):
            print(f"[SKIP] {label}: file tidak ada -> {path}")
            gagal.append((label, "file tidak ada"))
            continue

        data = extract_animation(path, detector)
        if data is None:
            print(f"[GAGAL] {label}: tidak ada tangan terdeteksi di video")
            gagal.append((label, "tidak terdeteksi"))
            continue

        n = data["frame_count"]
        cov = data.get("coverage", 1.0)
        interp = data.get("interpolated", 0)

        catatan = f"{n} frame | deteksi {cov*100:.0f}%"
        if interp:
            catatan += f" | {interp} frame diinterpolasi"

        if n < BATAS_PENDEK:
            print(f"[PENDEK] {label}: {catatan}")
            pendek.append((label, n, cov))
        else:
            print(f"[OK]    {label}: {catatan}")
        ok += 1

    print(f"\nSelesai. Berhasil: {ok}, gagal: {len(gagal)}")

    if pendek:
        print(f"\nPERLU DIPERIKSA — animasi terlalu pendek (< {BATAS_PENDEK} frame, "
              f"kurang dari {BATAS_PENDEK/12:.1f} detik):")
        for label, n, cov in sorted(pendek, key=lambda x: x[1]):
            print(f"  {label:<18} {n:>3} frame, deteksi hanya {cov*100:.0f}%")
        print("\n  Penyebab tersering: gestur dua tangan, tangan keluar frame,")
        print("  gerakan terlalu cepat sehingga blur, atau video memang pendek.")
        print("  Untuk kata-kata ini pertimbangkan rekam ulang, atau tampilkan")
        print("  video biasa lewat video_url alih-alih animasi CustomPainter.")

    if gagal:
        print("\nGAGAL TOTAL — tidak ada tangan terdeteksi sama sekali:")
        for label, alasan in gagal:
            print(f"  {label:<18} ({alasan})")


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