import cv2
import hashlib
import json
import numpy as np
import os
from typing import List, Optional

from app.services.detector import GestureDetector

# ============================================================
# ANIMATION SERVICE v2 — Teks/Suara -> Visualisasi Gestur
#
# Tujuan: menyediakan data untuk visualisasi gestur yang digambar ulang
# oleh Flutter CustomPainter, BUKAN aset animasi yang dibuat manual.
#
# Perbaikan dari v1:
# 1. FRAME KOSONG TIDAK LAGI DIBUANG, TAPI DIISI.
#    Sebelumnya frame yang tangannya tidak terdeteksi langsung dilewati,
#    jadi kata seperti "Ibu" hanya menyisakan 1 frame dari video utuh —
#    hasilnya gambar diam, bukan animasi. Sekarang celah di tengah diisi
#    interpolasi linear antara frame terdekat yang terdeteksi, sehingga
#    gerakannya utuh dan durasinya tetap benar.
# 2. RETRY OTOMATIS.
#    Kalau hasil pertama terlalu sedikit, video dipindai ulang setiap
#    frame sebelum menyerah.
# 3. DETEKSI PAKAI PADDING, BUKAN DITARIK JADI KOTAK.
#    Resize paksa ke 640x640 mendistorsi proporsi tangan dan menurunkan
#    tingkat deteksi pada video yang tidak persegi. Untuk animasi dipakai
#    letterbox (padding hitam) supaya proporsi terjaga.
#    Catatan: jalur DETEKSI REALTIME (detector.extract_landmarks) sengaja
#    TIDAK diubah, karena model dilatih dengan resize paksa — mengubahnya
#    akan menggeser distribusi input model.
# 4. LAPORAN COVERAGE.
#    Hasil menyertakan porsi frame yang benar-benar terdeteksi, supaya
#    video berkualitas buruk bisa ditandai dan direkam ulang.
#
# Hasil ekstraksi di-cache di cache/animations/ supaya video hanya
# diproses satu kali.
# ============================================================

CACHE_DIR = "cache/animations"
TARGET_FPS = 12          # cukup halus untuk gestur, hemat payload
MAX_FRAMES = 90          # batas aman ~7.5 detik per kata
MIN_FRAMES = 10          # di bawah ini dianggap kurang, coba lagi lebih rapat
MIN_COVERAGE = 0.15      # minimal 15% frame terdeteksi
CACHE_VERSION = 2        # cache v1 otomatis diabaikan


def _cache_key(video_path: str) -> str:
    try:
        stat = os.stat(video_path)
        raw = f"v{CACHE_VERSION}|{os.path.abspath(video_path)}|{stat.st_size}|{int(stat.st_mtime)}"
    except OSError:
        raw = f"v{CACHE_VERSION}|{os.path.abspath(video_path)}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _cache_path(video_path: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{_cache_key(video_path)}.json")


def _letterbox(frame: np.ndarray, size: int = 640) -> np.ndarray:
    """Resize ke kotak dengan padding — proporsi tangan tidak berubah."""
    h, w = frame.shape[:2]
    skala = size / max(h, w)
    baru_w, baru_h = max(1, int(round(w * skala))), max(1, int(round(h * skala)))
    kecil = cv2.resize(frame, (baru_w, baru_h))

    kanvas = np.zeros((size, size, 3), dtype=frame.dtype)
    atas = (size - baru_h) // 2
    kiri = (size - baru_w) // 2
    kanvas[atas:atas + baru_h, kiri:kiri + baru_w] = kecil
    return kanvas


def _ekstrak_landmark_padded(frame: np.ndarray, detector: GestureDetector) -> Optional[np.ndarray]:
    """
    Sama seperti detector.extract_landmarks tapi memakai letterbox.
    Dipakai KHUSUS untuk animasi, bukan untuk input model.
    """
    if detector.landmarker is None:
        return None
    try:
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img_rgb = _letterbox(img_rgb, 640)
        mp_image = detector.mp.Image(
            image_format=detector.mp.ImageFormat.SRGB,
            data=img_rgb,
        )
        with detector._mp_lock:
            hasil = detector.landmarker.detect(mp_image)
        if not hasil.hand_landmarks:
            return None
        titik = []
        for lm in hasil.hand_landmarks[0]:
            titik.extend([lm.x, lm.y, lm.z])
        return np.array(titik, dtype=np.float32)
    except Exception as e:
        print(f"Landmark error (animasi): {e}")
        return None


def _isi_celah(frames: List[Optional[np.ndarray]]) -> List[np.ndarray]:
    """
    Isi frame yang tidak terdeteksi:
      - celah di TENGAH -> interpolasi linear antara tetangga terdekat
      - kosong di AWAL & AKHIR -> dipotong
    """
    idx_ada = [i for i, f in enumerate(frames) if f is not None]
    if not idx_ada:
        return []

    potong = frames[idx_ada[0]:idx_ada[-1] + 1]

    hasil: List[np.ndarray] = []
    for i, f in enumerate(potong):
        if f is not None:
            hasil.append(f)
            continue

        kiri = next((j for j in range(i - 1, -1, -1) if potong[j] is not None), None)
        kanan = next((j for j in range(i + 1, len(potong)) if potong[j] is not None), None)

        if kiri is None or kanan is None:
            sumber = potong[kiri if kiri is not None else kanan]
            hasil.append(sumber)
            continue

        t = (i - kiri) / (kanan - kiri)
        hasil.append(potong[kiri] * (1 - t) + potong[kanan] * t)

    return hasil


def _pindai(video_path: str, detector: GestureDetector, step: int):
    """Return: (list landmark/None per frame yang dipindai, jumlah frame dipindai)."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return [], 0

    frames: List[Optional[np.ndarray]] = []
    idx = 0
    try:
        while len(frames) < MAX_FRAMES:
            ret = cap.grab()
            if not ret:
                break
            if idx % step == 0:
                ok, frame = cap.retrieve()
                if ok:
                    frames.append(_ekstrak_landmark_padded(frame, detector))
            idx += 1
    finally:
        cap.release()

    return frames, len(frames)


def extract_animation(video_path: str,
                      detector: GestureDetector,
                      use_cache: bool = True) -> Optional[dict]:
    """
    Return:
    {
      "fps": 12,
      "frame_count": 34,
      "coverage": 0.82,       # porsi frame yang benar-benar terdeteksi
      "interpolated": 6,      # berapa frame hasil interpolasi
      "frames": [[63 angka], ...]
    }
    None kalau video tidak ada atau tangan hampir tidak pernah terdeteksi.
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
    src_fps = (cap.get(cv2.CAP_PROP_FPS) or 25.0) if cap.isOpened() else 25.0
    cap.release()

    step = max(1, int(round(src_fps / TARGET_FPS)))

    mentah, dipindai = _pindai(video_path, detector, step)
    terdeteksi = sum(1 for f in mentah if f is not None)

    # Retry lebih rapat kalau hasilnya terlalu sedikit
    if terdeteksi < MIN_FRAMES and step > 1:
        mentah, dipindai = _pindai(video_path, detector, 1)
        terdeteksi = sum(1 for f in mentah if f is not None)

    if dipindai == 0 or terdeteksi == 0:
        return None

    coverage = terdeteksi / dipindai
    if coverage < MIN_COVERAGE and terdeteksi < MIN_FRAMES:
        return None

    isi = _isi_celah(mentah)
    if not isi:
        return None

    data = {
        "fps": TARGET_FPS,
        "frame_count": len(isi),
        "coverage": round(coverage, 3),
        "interpolated": len(isi) - terdeteksi,
        "frames": [[round(float(v), 4) for v in f.tolist()] for f in isi],
    }

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass

    return data