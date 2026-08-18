import cv2
import hashlib
import json
import os
from typing import List, Optional

from app.services.detector import GestureDetector

# ============================================================
# ANIMATION SERVICE — Teks/Suara -> Visualisasi Gestur
#
# Tujuan: menyediakan data untuk visualisasi gestur yang digambar ulang
# oleh Flutter CustomPainter, BUKAN aset animasi yang dibuat manual.
#
# Cara kerja: video peraga (video kontribusi yang sudah approved, atau
# video kamus SignPedia) dilewatkan MediaPipe SEKALI, koordinat 21 titik
# tangan per frame disimpan sebagai JSON. Flutter tinggal menggambar
# rangkaian titik itu sebagai skeleton yang bergerak.
#
# Keuntungan dibanding streaming video:
#   - payload kecil (puluhan KB JSON vs beberapa MB video)
#   - bisa diputar lambat/cepat, di-zoom, diganti warna, tanpa render ulang
#   - satu pipeline yang sama dipakai untuk overlay kamera realtime
#
# Hasil ekstraksi di-cache di cache/animations/ supaya video hanya diproses
# satu kali (proses pertama beberapa detik, berikutnya instan).
# ============================================================

CACHE_DIR = "cache/animations"
TARGET_FPS = 12          # cukup halus untuk gestur, hemat payload
MAX_FRAMES = 90          # batas aman ~7.5 detik per kata


def _cache_key(video_path: str) -> str:
    try:
        stat = os.stat(video_path)
        raw = f"{os.path.abspath(video_path)}|{stat.st_size}|{int(stat.st_mtime)}"
    except OSError:
        raw = os.path.abspath(video_path)
    return hashlib.sha1(raw.encode()).hexdigest()


def _cache_path(video_path: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{_cache_key(video_path)}.json")


def extract_animation(video_path: str,
                      detector: GestureDetector,
                      use_cache: bool = True) -> Optional[dict]:
    """
    Return:
    {
      "fps": 12,
      "frame_count": 34,
      "frames": [[x1,y1,z1, ... x21,y21,z21], ...]   # koordinat ternormalisasi 0..1
    }
    None kalau video tidak ada / tidak ada tangan yang terdeteksi sama sekali.
    """
    if not video_path or not os.path.isfile(video_path):
        return None

    cache_file = _cache_path(video_path)
    if use_cache and os.path.isfile(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(src_fps / TARGET_FPS)))

    frames: List[List[float]] = []
    idx = 0
    try:
        while len(frames) < MAX_FRAMES:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % step == 0:
                landmark = detector.extract_landmarks(frame)
                if landmark is not None:
                    frames.append([round(float(v), 4) for v in landmark.tolist()])
            idx += 1
    finally:
        cap.release()

    if not frames:
        return None

    data = {"fps": TARGET_FPS, "frame_count": len(frames), "frames": frames}

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass

    return data