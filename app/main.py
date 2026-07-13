from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import base64
import numpy as np
import cv2
import json
import os

from app.core.database import init_db
from app.routers import auth, submissions, admin, gesture_lookup
from app.services.detector import GestureDetector  # pindah dari app/detector.py lama

app = FastAPI(title="IsyaraLive API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Buat tabel database saat startup
init_db()

# Static files (video approved & video alfabet fallback)
os.makedirs("uploads/approved", exist_ok=True)
os.makedirs("assets/alphabet", exist_ok=True)
app.mount("/static/approved", StaticFiles(directory="uploads/approved"), name="approved")
app.mount("/static/alphabet", StaticFiles(directory="assets/alphabet"), name="alphabet")

# Daftarkan semua router
app.include_router(auth.router)
app.include_router(submissions.router)
app.include_router(admin.router)
app.include_router(gesture_lookup.router)

# Detector untuk WebSocket deteksi real-time (load model sekali)
detector = GestureDetector()


@app.get("/")
def root():
    return {"status": "IsyaraLive API v2 running"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": detector.model_loaded,
        "classes": detector.class_names
    }


@app.websocket("/ws/detect")
async def websocket_detect(websocket: WebSocket):
    """
    WebSocket endpoint untuk deteksi gesture real-time (LSTM, buffer 15 frame).
    Endpoint ini TIDAK pakai auth — dipakai untuk demo deteksi cepat.
    """
    await websocket.accept()
    print("Client connected")

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            frame_b64 = payload.get("frame", "")
            if not frame_b64:
                await websocket.send_text(json.dumps({
                    "detected": False, "label": "", "confidence": 0.0,
                    "error": "No frame received"
                }))
                continue

            img_bytes = base64.b64decode(frame_b64)
            img_array = np.frombuffer(img_bytes, dtype=np.uint8)
            frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

            if frame is None:
                await websocket.send_text(json.dumps({
                    "detected": False, "label": "", "confidence": 0.0,
                    "error": "Failed to decode image"
                }))
                continue

            result = detector.detect(frame)
            await websocket.send_text(json.dumps(result))

    except WebSocketDisconnect:
        print("Client disconnected")
        detector.reset_buffer()
    except Exception as e:
        print(f"Error: {e}")
        await websocket.close()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)