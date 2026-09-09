from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import asyncio
import base64
import numpy as np
import cv2
import json
import os
import time
from typing import Optional

from app.core.database import init_db
from app.core.security import decode_access_token
from app.routers import (
    auth, submissions, admin, gesture_lookup, ai, vote,
    leaderboard, dictionary, learning, chatbot, users, corrections,
)
from app.services.detector_instance import detector
from app.services.stream_session import DetectionSession
from app.services.detector import SEQUENCE_LENGTH, FEATURE_SIZE, correct_aspect_ratio
from app.services.correction_service import simpan_koreksi

app = FastAPI(title="IsyaraLive API", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

os.makedirs("uploads/approved", exist_ok=True)
os.makedirs("uploads/pending", exist_ok=True)
os.makedirs("uploads/voting", exist_ok=True)
os.makedirs("uploads/rejected", exist_ok=True)
os.makedirs("assets/alphabet", exist_ok=True)
os.makedirs("assets/dictionary", exist_ok=True)

# PEMETAAN yang dipegang aplikasi: video_path di database selalu berbentuk
# `uploads/<status>/<berkas>`, dan tiap folder status punya mount sendiri
# dengan nama yang SAMA — `uploads/pending/x.mp4` -> `/static/pending/x.mp4`.
# Flutter menurunkan URL-nya dari aturan itu (lihat core/utils/media_url.dart),
# jadi jangan mengubah nama mount tanpa mengubah sisi aplikasi.
app.mount("/static/approved", StaticFiles(directory="uploads/approved"), name="approved")
# Admin butuh pratinjau video yang MASIH ANTRI (belum di-approve/reject) di
# panel moderasi, makanya folder pending juga di-mount, terpisah dari /approved
# yang publik supaya jelas mana yang belum lolos review.
app.mount("/static/pending", StaticFiles(directory="uploads/pending"), name="pending")
# Video yang sedang DIBUKA UNTUK VOTING tampil publik di feed komunitas —
# pengguna tidak bisa menilai gestur yang tidak bisa ditonton. Folder & mount
# sendiri supaya jelas bedanya dengan /approved (sudah masuk dataset).
app.mount("/static/voting", StaticFiles(directory="uploads/voting"), name="voting")
# Kontributor tetap perlu melihat ulang video yang DITOLAK di "Kontribusi Saya"
# supaya tahu apa yang harus diperbaiki sebelum mengunggah lagi. Tanpa mount ini
# kartunya tampil sebagai video rusak, bukan sebagai bahan evaluasi.
app.mount("/static/rejected", StaticFiles(directory="uploads/rejected"), name="rejected")
app.mount("/static/alphabet", StaticFiles(directory="assets/alphabet"), name="alphabet")
app.mount("/static/dictionary", StaticFiles(directory="assets/dictionary"), name="dictionary")

app.include_router(auth.router)
app.include_router(submissions.router)
app.include_router(admin.router)
app.include_router(gesture_lookup.router)
app.include_router(ai.router)
app.include_router(vote.router)
app.include_router(leaderboard.router)
app.include_router(dictionary.router)
app.include_router(learning.router)
app.include_router(chatbot.router)
app.include_router(users.router)
app.include_router(corrections.router)


@app.get("/")
def root():
    return {"status": "IsyaraLive API v2 running"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": detector.model_loaded,
        "sequence_length": SEQUENCE_LENGTH,
        "feature_size": FEATURE_SIZE,
        "classes": detector.class_names,
    }


# ============================================================
# WEBSOCKET DETEKSI REAL-TIME
#
# Mendukung DUA mode dalam satu endpoint:
#
# 1. MODE LANDMARK (dianjurkan, sesuai desain sistem):
#    MediaPipe dijalankan ON-DEVICE di Flutter, aplikasi cuma mengirim
#    63 angka per frame. Payload ~1 KB, bukan gambar puluhan KB, sehingga
#    latensi jauh lebih rendah dan server tidak perlu compute vision.
#      kirim: {"landmarks": [x1,y1,z1, ... , x21,y21,z21], "t": <epoch_ms>,
#               "frame_width": <lebar_piksel_frame_kamera>,
#               "frame_height": <tinggi_piksel_frame_kamera>}
#      kirim: {"landmarks": null}  -> tangan tidak terdeteksi, buffer di-reset
#
#    "frame_width"/"frame_height" (resolusi ASLI frame kamera di device saat
#    landmark ini diekstrak, BUKAN 640) bersifat OPSIONAL tapi SANGAT
#    DIANJURKAN. Training & mode "frame" menormalisasi landmark dari frame
#    yang dipad jadi persegi dulu (isotropik), sedangkan plugin MediaPipe
#    di device menormalisasi langsung dari frame kamera asli yang biasanya
#    tidak persegi (anisotropik) -- kalau tidak dikoreksi, sumbu yang lebih
#    pendek meregang/menyusut dan gestur mirip bisa tertukar. Kalau kedua
#    field ini dikirim, server mengoreksinya (lihat correct_aspect_ratio()
#    di services/detector.py) sebelum dipakai prediksi. Tanpa keduanya,
#    server fallback ke perilaku lama (tidak ada koreksi).
#
#    "t" (epoch ms saat frame DIAMBIL di device, bukan saat dikirim) bersifat
#    OPSIONAL tapi SANGAT DIANJURKAN. Laju kirim klien di lapangan tidak
#    pernah persis 10 fps — RTT/jarak antar-kirim WS berayun cukup jauh
#    (device kelas menengah, jaringan jelek), padahal model dilatih pada
#    jendela 15 frame @ 10 fps (1,5 detik) yang rata. Kalau "t" dikirim,
#    server meng-interpolasi ulang landmark ke grid 100ms genap sebelum
#    dipakai prediksi (lihat DetectionSession di stream_session.py), jadi
#    rentang waktu 15 frame yang dilihat model selalu ~1,5 detik apa pun
#    kecepatan/kestabilan kirim klien. Tanpa "t", server fallback ke
#    perilaku lama (percaya urutan kirim apa adanya) — tetap jalan, cuma
#    tidak dapat jaminan itu.
#
# 2. MODE FRAME (fallback, kompatibel dengan client lama):
#    Aplikasi mengirim JPEG base64, MediaPipe dijalankan di server.
#      kirim: {"frame": "<base64 jpeg>"}
#
# Pesan kontrol:
#      {"type": "reset"}  -> kosongkan buffer + transkrip (mulai kalimat baru)
#      {"type": "ping"}   -> balasan {"type": "pong"} untuk cek koneksi
#      {"type": "edit", "index": <i>, "label": "<kata benar>"}
#          -> betulkan kata ke-i di transkrip. Balasan {"type":"edit_ok", ...}.
#      {"type": "delete", "index": <i>}
#          -> buang kata ke-i (model memunculkan kata padahal bukan isyarat).
#
# KOREKSI = DATA LATIH. Saat kata dibetulkan/dibuang, potongan gerakan yang
# menghasilkan tebakan itu (15x63 landmark, disimpan DetectionSession saat kata
# masuk) ikut dicatat ke tabel detection_corrections. Inilah satu-satunya
# kesempatan menyimpannya — buffer sesi terus bergulir. Tanpa itu koreksi cuma
# berarti "tebakannya salah" tanpa contoh yang bisa dipelajari model.
#
# `label` untuk edit HARUS salah satu kelas yang dikenal model (lihat daftar
# "classes" pada balasan {"type":"ready"}). Kata di luar itu tidak bisa
# dipelajari model tanpa menambah kelas & melatih ulang dari awal, jadi
# ditolak dengan pesan yang mengarahkan ke jalur kontribusi SignHub.
#
# Setiap balasan yang membawa "transcript" juga membawa "transcript_words"
# (transkrip sebagai DAFTAR). Klien WAJIB memakai daftar itu untuk menentukan
# indeks kata: sebagian label memang berisi spasi ("Terima Kasih", "Hari ini"),
# jadi memecah "transcript" dengan split(" ") menghasilkan indeks yang meleset.
#
# Autentikasi opsional: /ws/detect?token=<JWT>. Kalau token dikirim dan
# valid, user_id ikut dicatat di balasan pertama. Tanpa token, endpoint
# tetap bisa dipakai untuk mode demo.
# ============================================================

@app.websocket("/ws/detect")
async def websocket_detect(websocket: WebSocket, token: Optional[str] = Query(default=None)):
    await websocket.accept()

    user_id = None
    if token:
        payload = decode_access_token(token)
        if payload is None:
            await websocket.send_text(json.dumps({
                "type": "auth_error",
                "message": "Token tidak valid atau sudah expired",
            }))
            await websocket.close(code=1008)
            return
        user_id = payload.get("user_id")

    session = DetectionSession()

    await websocket.send_text(json.dumps({
        "type": "ready",
        "user_id": user_id,
        "sequence_length": SEQUENCE_LENGTH,
        "feature_size": FEATURE_SIZE,
        "model_loaded": detector.model_loaded,
        "accepted_modes": ["landmark", "frame"],
        # Kosakata yang benar-benar bisa dikenali model. Klien memakainya untuk
        # membatasi pilihan saat pengguna membetulkan kata — mengoreksi ke kata
        # di luar daftar ini tidak bisa dipelajari model.
        "classes": list(detector.class_names or []),
    }))

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "Payload bukan JSON valid"}))
                continue

            msg_type = payload.get("type")
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            if msg_type == "reset":
                session.reset()
                await websocket.send_text(json.dumps({
                    "type": "reset_ok", "transcript": "", "transcript_words": [],
                }))
                continue
            if msg_type in ("edit", "delete"):
                balasan = await _tangani_koreksi(session, payload, user_id)
                await websocket.send_text(json.dumps(balasan))
                continue

            # ---------- MODE LANDMARK ----------
            if "landmarks" in payload:
                landmarks = payload.get("landmarks")

                if landmarks is None:
                    # Tangan tidak terdeteksi pada frame ini. JANGAN langsung
                    # membuang buffer: satu frame meleset (blur saat tangan
                    # bergerak) tidak berarti pengguna berhenti berisyarat.
                    # DetectionSession yang memutuskan lewat masa tenggang.
                    t_ms = payload.get("t")
                    session.hand_lost(t_ms if isinstance(t_ms, (int, float)) else time.time() * 1000)
                    tersisa = session.buffer_size
                    await websocket.send_text(json.dumps({
                        "mode": "landmark", "detected": False, "label": "",
                        "confidence": 0.0,
                        # Selama kemajuan masih tersimpan, klien tetap
                        # diberi tahu "sedang merekam" supaya bar tidak
                        # berkedip ke nol lalu naik lagi.
                        "buffering": tersisa > 0,
                        "buffer_size": tersisa,
                        "transcript": session.transcript_text(),
                        "transcript_words": session.transcript_words(),
                    }))
                    continue

                if not isinstance(landmarks, list) or len(landmarks) != FEATURE_SIZE:
                    await websocket.send_text(json.dumps({
                        "mode": "landmark", "detected": False,
                        "error": f"'landmarks' harus list {FEATURE_SIZE} angka",
                    }))
                    continue

                t_ms = payload.get("t")
                if not isinstance(t_ms, (int, float)):
                    # Klien lama / belum kirim "t" -> fallback ke waktu
                    # terima server (tetap lebih baik daripada tidak sama sekali).
                    t_ms = time.time() * 1000

                # Koreksi mismatch normalisasi isotropik (training/letterbox)
                # vs anisotropik (MediaPipe on-device) -- lihat correct_aspect_ratio().
                # No-op kalau device belum kirim frame_width/frame_height.
                landmarks = correct_aspect_ratio(
                    landmarks, payload.get("frame_width"), payload.get("frame_height")
                )

                session.push(landmarks, t_ms)
                result = await _predict_from_session(session)
                result["mode"] = "landmark"
                await websocket.send_text(json.dumps(result))
                continue

            # ---------- MODE FRAME (fallback) ----------
            frame_b64 = payload.get("frame", "")
            if not frame_b64:
                await websocket.send_text(json.dumps({
                    "detected": False, "label": "", "confidence": 0.0,
                    "error": "Kirim 'landmarks' (63 angka) atau 'frame' (base64 jpeg)",
                }))
                continue

            frame = await asyncio.to_thread(_decode_frame, frame_b64)
            if frame is None:
                await websocket.send_text(json.dumps({
                    "mode": "frame", "detected": False, "label": "", "confidence": 0.0,
                    "error": "Gagal decode gambar",
                }))
                continue

            landmark = await asyncio.to_thread(detector.extract_landmarks, frame)
            if landmark is None:
                # Sama seperti mode landmark: satu frame tanpa tangan belum
                # tentu berarti berhenti berisyarat. Mode frame JUSTRU paling
                # sering kena — lajunya rendah dan gambarnya lebih blur, jadi
                # tanpa masa tenggang buffer nyaris tidak pernah penuh.
                session.hand_lost(time.time() * 1000)
                tersisa = session.buffer_size
                await websocket.send_text(json.dumps({
                    "mode": "frame", "detected": False, "label": "", "confidence": 0.0,
                    "buffering": tersisa > 0, "buffer_size": tersisa, "landmarks": None,
                    "transcript": session.transcript_text(),
                    "transcript_words": session.transcript_words(),
                }))
                continue

            # Mode frame tidak punya timestamp capture dari klien -> pakai
            # waktu terima server. Tetap membantu resampling menghadapi
            # jitter kedatangan frame, walau tidak sepresisi mode landmark.
            session.push(landmark.tolist(), time.time() * 1000)
            result = await _predict_from_session(session)
            result["mode"] = "frame"
            # landmark dikirim balik supaya Flutter bisa gambar skeleton overlay
            result["landmarks"] = landmark.tolist()
            await websocket.send_text(json.dumps(result))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


def _decode_frame(frame_b64: str):
    try:
        img_bytes = base64.b64decode(frame_b64)
        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
        return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _cocokkan_kelas(label: str) -> Optional[str]:
    """
    Samakan `label` dengan salah satu kelas model, tanpa peduli huruf
    besar/kecil & spasi berlebih. Return bentuk resmi kelasnya, atau None kalau
    memang bukan kosakata model.
    """
    bersih = " ".join((label or "").split()).lower()
    if not bersih:
        return None
    for kelas in (detector.class_names or []):
        if kelas.lower() == bersih:
            return kelas
    return None


async def _tangani_koreksi(
    session: DetectionSession,
    payload: dict,
    user_id: Optional[int],
) -> dict:
    """
    Jalankan pesan {"type":"edit"|"delete"} dan CATAT koreksinya sebagai data
    latih (lihat catatan protokol di atas).

    Penyimpanan ke database dijalankan di threadpool: SQLAlchemy di proyek ini
    sinkron, dan event loop yang sama sedang melayani stream landmark 10 fps
    milik semua pengguna lain.

    Kegagalan menyimpan TIDAK membatalkan koreksinya di layar — transkrip
    pengguna tetap terbetulkan, `tersimpan: false` yang memberi tahu bahwa
    contohnya tidak terekam.
    """
    jenis = payload.get("type")
    indeks = payload.get("index")
    if not isinstance(indeks, int):
        return {"type": "edit_error", "message": "'index' harus berupa angka"}

    if jenis == "delete":
        dibuang = session.hapus_kata(indeks)
        if dibuang is None:
            return {"type": "edit_error", "message": f"Tidak ada kata di indeks {indeks}"}
        tersimpan = await asyncio.to_thread(
            simpan_koreksi, dibuang, None, user_id, payload.get("mode")
        )
        return {
            "type": "edit_ok",
            "action": "delete",
            "index": indeks,
            "predicted_label": dibuang.label,
            "corrected_label": None,
            "tersimpan": tersimpan,
            "transcript": session.transcript_text(),
            "transcript_words": session.transcript_words(),
        }

    label_benar = _cocokkan_kelas(payload.get("label", ""))
    if label_benar is None:
        # Kata di luar 46 kelas tidak bisa dipelajari model tanpa menambah
        # kelas & melatih ulang — jadi jangan diterima diam-diam seolah model
        # akan mengenalinya nanti. Jalur yang benar untuk kosakata baru adalah
        # kontribusi gestur SignHub (unggah video -> verifikasi -> voting).
        return {
            "type": "edit_error",
            "message": "Kata itu belum ada di kosakata model. Untuk menambah "
                       "kosakata baru, kirim lewat kontribusi gestur SignHub.",
            "classes": list(detector.class_names or []),
        }

    lama = session.ganti_kata(indeks, label_benar)
    if lama is None:
        return {"type": "edit_error", "message": f"Tidak ada kata di indeks {indeks}"}

    tersimpan = False
    if lama.label != label_benar:
        # Kalau pengguna "mengoreksi" ke kata yang sama, tidak ada yang perlu
        # dipelajari — jangan kotori data latih dengan baris tanpa isi.
        tersimpan = await asyncio.to_thread(
            simpan_koreksi, lama, label_benar, user_id, payload.get("mode")
        )

    return {
        "type": "edit_ok",
        "action": "edit",
        "index": indeks,
        "predicted_label": lama.label,
        "corrected_label": label_benar,
        "tersimpan": tersimpan,
        "transcript": session.transcript_text(),
        "transcript_words": session.transcript_words(),
    }


async def _predict_from_session(session: DetectionSession) -> dict:
    """Jalankan LSTM kalau buffer sudah 15 frame, lalu update transkrip."""
    if not session.is_ready:
        return {
            "detected": False, "label": "", "confidence": 0.0,
            "buffering": True, "buffer_size": session.buffer_size,
            "transcript": session.transcript_text(),
            "transcript_words": session.transcript_words(),
        }

    result = await asyncio.to_thread(detector.predict_sequence, session.sequence())

    is_new_word = False
    if result.get("detected"):
        # Keyakinan ikut dicatat bersama katanya: kalau nanti kata ini
        # dikoreksi, seberapa yakin model saat salah itu informasi yang
        # membedakan "tebakan asal" dari "salah tapi mantap".
        is_new_word = session.commit(result["label"], result.get("confidence", 0.0))
    else:
        session.commit("")

    result.update({
        "buffering": False,
        "buffer_size": session.buffer_size,
        "is_new_word": is_new_word,           # True saat kata resmi masuk transkrip
        "transcript": session.transcript_text(),
        "transcript_words": session.transcript_words(),
    })
    return result


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
