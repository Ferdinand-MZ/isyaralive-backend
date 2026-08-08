import cv2
from fastapi import HTTPException, status

from app.services.detector import GestureDetector

# ============================================================
# Proses video gestur yang DIUPLOAD (bukan streaming WebSocket).
# Dipakai fitur "Pencarian AI dengan Gestur" di AI Chatbot —
# user upload video pertanyaan dalam bentuk isyarat, sistem
# jalankan detector LSTM per-frame lalu susun jadi teks (glosses).
# ============================================================


def extract_glosses_from_video(video_path: str, detector: GestureDetector) -> str:
    """
    Baca file video, jalankan GestureDetector.detect() ke tiap frame
    (detector otomatis buffer 15 frame internal), kumpulkan semua label
    yang berhasil terdeteksi (dedup berurutan biar gak dobel-dobel).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Video tidak bisa dibaca/rusak.")

    detector.reset_buffer()
    glosses = []
    last_label = None

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            result = detector.detect(frame)
            if result.get("detected") and result.get("label"):
                label = result["label"]
                if label != last_label:  # hindari label sama berturut-turut
                    glosses.append(label)
                    last_label = label
    finally:
        cap.release()
        detector.reset_buffer()

    if not glosses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tidak ada gestur yang berhasil dikenali dari video ini."
        )

    return " ".join(glosses)