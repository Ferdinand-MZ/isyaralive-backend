import cv2
from fastapi import HTTPException, status

from app.services.detector import GestureDetector, SEQUENCE_LENGTH
from app.services.stream_session import DetectionSession

# ============================================================
# Proses video gestur yang DIUPLOAD (bukan streaming WebSocket).
# Dipakai fitur "Pencarian AI dengan Gestur" di AI Chatbot.
#
# Perubahan v2: proses video TIDAK lagi memakai buffer internal detector.
# Setiap pemanggilan membuat DetectionSession sendiri, jadi user yang
# mengunggah video tidak mengganggu user lain yang sedang streaming
# lewat WebSocket (dulu keduanya berbagi satu buffer di singleton).
# ============================================================


def extract_glosses_from_video(video_path: str, detector: GestureDetector) -> str:
    """
    Baca file video, ekstrak landmark per frame, jalankan LSTM tiap kali
    buffer sudah 15 frame, lalu susun label jadi rangkaian gloss.
    Dedup + stabilitas ditangani oleh DetectionSession.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Video tidak bisa dibaca/rusak.")

    session = DetectionSession()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            landmark = detector.extract_landmarks(frame)
            if landmark is None:
                session.clear_buffer()
                continue

            session.push(landmark.tolist())

            if not session.is_ready:
                continue

            result = detector.predict_sequence(session.sequence())
            session.commit(result["label"] if result.get("detected") else "")
    finally:
        cap.release()

    if not session.transcript:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tidak ada gestur yang berhasil dikenali dari video ini.",
        )

    return session.transcript_text()