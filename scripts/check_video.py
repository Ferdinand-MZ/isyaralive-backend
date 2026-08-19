"""
CEK VIDEO KANDIDAT
==================
Menguji apakah sebuah video layak dipakai sebagai peraga, SEBELUM disalin
ke assets/. Lebih cepat daripada menyalin lalu membangun ulang cache dan
baru ketahuan gagal.

Cara pakai:
    # cek satu video
    python scripts/check_video.py ~/Downloads/aridone/dataset/Ayah/subjek1/a.mp4

    # cek semua video dalam satu folder, diurutkan dari yang terbaik
    python scripts/check_video.py ~/Downloads/aridone/dataset/Ayah/ --folder

    # cek folder, lalu langsung salin yang terbaik ke assets/dictionary/
    python scripts/check_video.py ~/Downloads/aridone/dataset/Ayah/ --folder \\
        --pasang Ayah

Nilai yang dilaporkan:
  deteksi  = porsi frame yang tangannya terbaca MediaPipe. Di bawah 50%
             animasinya banyak diinterpolasi; di bawah 20% biasanya jelek.
  frame    = perkiraan jumlah frame animasi pada 12 fps.
"""

import argparse
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2

from app.services.detector_instance import detector
from app.services.animation_service import _ekstrak_landmark_padded, TARGET_FPS

EKSTENSI = (".mp4", ".mov", ".webm", ".m4v", ".mkv")
TUJUAN_DEFAULT = "assets/dictionary"


def slug(kata: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", kata.lower()).strip("_")


def periksa(path: str, maks_sampel: int = 40) -> dict:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return {"path": path, "error": "tidak bisa dibuka"}

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if total <= 0:
        cap.release()
        return {"path": path, "error": "tidak ada frame"}

    step = max(1, total // maks_sampel)
    diperiksa = terdeteksi = 0

    idx = 0
    while True:
        ret = cap.grab()
        if not ret:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                diperiksa += 1
                if _ekstrak_landmark_padded(frame, detector) is not None:
                    terdeteksi += 1
        idx += 1
    cap.release()

    coverage = terdeteksi / diperiksa if diperiksa else 0.0
    durasi = total / fps
    perkiraan_frame = int(durasi * TARGET_FPS * coverage)

    return {
        "path": path,
        "durasi": durasi,
        "resolusi": f"{w}x{h}",
        "coverage": coverage,
        "perkiraan_frame": perkiraan_frame,
    }


def verdict(hasil: dict) -> str:
    if hasil.get("error"):
        return "RUSAK"
    if hasil["coverage"] == 0:
        return "GAGAL"
    if hasil["coverage"] < 0.2 or hasil["perkiraan_frame"] < 10:
        return "BURUK"
    if hasil["coverage"] < 0.6:
        return "CUKUP"
    return "BAGUS"


def cetak(hasil: dict):
    nama = os.path.basename(hasil["path"])
    if hasil.get("error"):
        print(f"  [RUSAK] {nama:<40} {hasil['error']}")
        return
    print(f"  [{verdict(hasil):<5}] {nama:<40} "
          f"{hasil['durasi']:>5.1f}s  {hasil['resolusi']:<10} "
          f"deteksi {hasil['coverage']*100:>3.0f}%  ~{hasil['perkiraan_frame']} frame animasi")


def run(args):
    if args.folder:
        if not os.path.isdir(args.target):
            print(f"Bukan folder: {args.target}")
            return
        video = []
        for dirpath, _, files in os.walk(args.target):
            for fn in files:
                if fn.lower().endswith(EKSTENSI):
                    video.append(os.path.join(dirpath, fn))
        if not video:
            print(f"Tidak ada video di {args.target}")
            return

        print(f"Memeriksa {len(video)} video di {args.target}\n")
        hasil = [periksa(p) for p in sorted(video)[:args.maks]]
        hasil.sort(key=lambda h: (-(h.get("coverage") or 0), -(h.get("perkiraan_frame") or 0)))
        for h in hasil:
            cetak(h)

        terbaik = next((h for h in hasil if verdict(h) in ("BAGUS", "CUKUP")), None)
        if terbaik is None:
            print("\nTidak ada kandidat yang layak di folder ini.")
            return

        print(f"\nTerbaik: {os.path.basename(terbaik['path'])} "
              f"(deteksi {terbaik['coverage']*100:.0f}%)")

        if args.pasang:
            ext = os.path.splitext(terbaik["path"])[1].lower()
            tujuan = os.path.join(args.tujuan, f"{slug(args.pasang)}{ext}")
            os.makedirs(args.tujuan, exist_ok=True)
            for lama in os.listdir(args.tujuan):
                if os.path.splitext(lama)[0].lower() == slug(args.pasang):
                    os.remove(os.path.join(args.tujuan, lama))
                    print(f"File lama dihapus: {lama}")
            shutil.copy(terbaik["path"], tujuan)
            print(f"Disalin ke: {tujuan}")
            print("\nJalankan: python scripts/build_animation_cache.py --only dictionary")
    else:
        h = periksa(args.target)
        print()
        cetak(h)
        if args.pasang and verdict(h) in ("BAGUS", "CUKUP"):
            ext = os.path.splitext(args.target)[1].lower()
            tujuan = os.path.join(args.tujuan, f"{slug(args.pasang)}{ext}")
            os.makedirs(args.tujuan, exist_ok=True)
            shutil.copy(args.target, tujuan)
            print(f"\nDisalin ke: {tujuan}")
            print("Jalankan: python scripts/build_animation_cache.py --only dictionary")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cek kelayakan video peraga")
    parser.add_argument("target", help="Path video, atau folder kalau pakai --folder")
    parser.add_argument("--folder", action="store_true", help="Periksa semua video dalam folder")
    parser.add_argument("--pasang", metavar="KATA",
                        help="Salin yang terbaik ke assets sebagai kata ini, mis. --pasang Ayah")
    parser.add_argument("--tujuan", default=TUJUAN_DEFAULT, help="Folder tujuan salinan")
    parser.add_argument("--maks", type=int, default=25, help="Maksimal video yang diperiksa")
    args = parser.parse_args()

    run(args)