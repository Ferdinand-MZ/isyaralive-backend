import numpy as np
import cv2
import os
import pickle
import threading
from collections import deque
from typing import Optional, Sequence, List

# ============================================================
# LSTM VERSION (v2 — thread-safe & stateless prediction)
#
# Perubahan dari versi sebelumnya:
# 1. Buffer 15 frame TIDAK lagi disimpan di detector (singleton), tapi
#    dipegang per-koneksi lewat app/services/stream_session.py.
#    Alasan: detector ini singleton dan dipakai bareng-bareng oleh semua
#    client WebSocket + chatbot upload video. Kalau buffernya nyatu, frame
#    dari user A dan user B tercampur dalam satu sequence -> prediksi ngaco.
# 2. Landmark extraction & inferensi dibungkus Lock, karena objek
#    MediaPipe HandLandmarker tidak thread-safe, sementara FastAPI
#    menjalankan handler di threadpool.
# 3. Dibuka API baru yang dipakai mode "landmark on-device":
#       predict_sequence(seq)  -> prediksi langsung dari 15x63 landmark
#       extract_landmarks(img) -> 63 angka dari 1 frame (mode fallback)
#    Method lama detect(frame) tetap ada supaya kode existing tidak pecah.
# ============================================================

SEQUENCE_LENGTH = 15          # harus sama dengan saat training
NUM_LANDMARKS = 21
FEATURE_SIZE = NUM_LANDMARKS * 3   # 63
CONFIDENCE_THRESHOLD = 0.7


def letterbox(frame: np.ndarray, size: int = 640) -> np.ndarray:
    """
    Resize ke kotak dengan padding (letterbox), BUKAN resize paksa yang
    meregangkan gambar — proporsi tangan tidak berubah.

    Sampai model versi sebelumnya, notebook training memakai
    `cv2.resize(img, (640, 640))` langsung (meregangkan rasio aspek), jadi
    jalur ini SENGAJA dibiarkan ikut meregangkan supaya cocok dengan
    distribusi input model. Model sudah dilatih ulang dengan landmark yang
    diekstrak pakai letterbox (lihat machine_learning/KMIPN_fixed.ipynb,
    cell ekstraksi utama) — jalur ini dan animation_service sekarang
    memakai fungsi yang SAMA, supaya keduanya konsisten dengan model.
    """
    h, w = frame.shape[:2]
    skala = size / max(h, w)
    baru_w, baru_h = max(1, int(round(w * skala))), max(1, int(round(h * skala)))
    kecil = cv2.resize(frame, (baru_w, baru_h))

    kanvas = np.zeros((size, size, 3), dtype=frame.dtype)
    atas = (size - baru_h) // 2
    kiri = (size - baru_w) // 2
    kanvas[atas:atas + baru_h, kiri:kiri + baru_w] = kecil
    return kanvas


def correct_aspect_ratio(landmark: Sequence, frame_w: float, frame_h: float) -> List[float]:
    """
    Koreksi mismatch normalisasi landmark mode "landmark" (on-device).

    Training & mode "frame" (lihat letterbox() di atas) memakai landmark
    yang diekstrak dari frame yang DIPAD jadi persegi dulu -> normalisasi
    ISOTROPIK (x dan y sama-sama dibagi sisi persegi S).

    Plugin MediaPipe di HP (mode "landmark") menormalisasi langsung dari
    frame kamera asli yang umumnya TIDAK persegi -> ANISOTROPIK (x dibagi
    lebar frame, y dibagi tinggi frame). Kalau dibiarkan, sumbu yang lebih
    pendek (yang kena padding di letterbox) meregang/menyusut dibanding
    yang dilihat model saat training -> distorsi geometris sistematis,
    cukup besar untuk bikin gestur mirip tertukar (mis. landmark frame
    640x480 membuat sumbu Y meregang 480/640 = 0,75x kalau tidak dikoreksi).

    `frame_w`/`frame_h` = ukuran frame kamera ASLI (piksel) yang dipakai
    device untuk landmark ini (BUKAN 640 letterbox), dikirim device lewat
    field "frame_width"/"frame_height" di payload landmark. Offset padding
    letterbox sengaja tidak direplikasi di sini karena itu konstanta per
    sumbu yang otomatis hilang lewat pengurangan wrist di
    normalize_landmarks() -- cuma faktor skalanya yang perlu dikoreksi.

    Kalau frame_w/frame_h tidak dikirim (klien lama), landmark dikembalikan
    apa adanya (tidak ada koreksi) supaya tidak breaking change.
    """
    if not frame_w or not frame_h:
        return list(landmark)

    pts = np.asarray(landmark, dtype=np.float32).reshape(NUM_LANDMARKS, 3).copy()
    frame_w = float(frame_w)
    frame_h = float(frame_h)

    if frame_w >= frame_h:
        # Landscape: lebar jadi acuan (sisi panjang letterbox), tinggi yang di-pad.
        pts[:, 1] *= (frame_h / frame_w)
    else:
        # Portrait: tinggi jadi acuan, lebar yang di-pad.
        pts[:, 0] *= (frame_w / frame_h)

    return pts.reshape(-1).tolist()


def normalize_landmarks(seq: Sequence) -> np.ndarray:
    """seq: (15, 63) -> (15, 63), relatif wrist (translasi) + scale-invariant."""
    pts = np.asarray(seq, dtype=np.float32).reshape(SEQUENCE_LENGTH, NUM_LANDMARKS, 3)
    wrist = pts[:, 0:1, :]
    pts = pts - wrist
    scale = np.linalg.norm(pts[:, 9, :], axis=-1, keepdims=True)
    scale = np.where(scale < 1e-6, 1e-6, scale)
    pts = pts / scale[:, None]
    return pts.reshape(SEQUENCE_LENGTH, FEATURE_SIZE)


class GestureDetector:
    def __init__(self):
        self.model_loaded = False
        self.model = None
        self.label_encoder = None
        self.landmarker = None
        self.mp = None
        self.torch = None

        # Lock supaya MediaPipe & torch tidak dipanggil paralel dari 2 thread
        self._mp_lock = threading.Lock()
        self._model_lock = threading.Lock()

        # Buffer legacy — HANYA dipakai kalau detect() dipanggil tanpa session.
        # Kode baru wajib pakai DetectionSession sendiri.
        self.buffer = deque(maxlen=SEQUENCE_LENGTH)

        self.class_names = [
            'Anak', 'Apa', 'Asal', 'Ayah', 'Bagaimana', 'Baik', 'Belajar', 'Berdiri',
            'Bingung', 'Dan', 'Dia', 'Dimana', 'Duduk', 'Guru', 'Halo', 'Hari ini',
            'Hobi', 'Ibu', 'Kalian', 'Kami', 'Kamu', 'Kapan', 'Keluarga', 'Kita',
            'Lagi', 'Makan', 'Malam', 'Mandi', 'Marah', 'Melihat', 'Membaca',
            'Mengapa', 'Menulis', 'Mereka', 'Minum', 'Nama', 'Olahraga', 'Pagi',
            'Ramah', 'Sabar', 'Saya', 'Sedih', 'Sekian', 'Selamat', 'Senang',
            'Siang', 'Siapa', 'Teman', 'Terima Kasih', 'Tidur'
        ]

        self._load_mediapipe()
        self._load_model()

    # ------------------------------------------------------------------
    # LOADING
    # ------------------------------------------------------------------
    def _load_mediapipe(self):
        try:
            import mediapipe as mp

            model_path = "models/hand_landmarker.task"
            if not os.path.exists(model_path):
                print("Downloading MediaPipe model...")
                import urllib.request
                os.makedirs("models", exist_ok=True)
                urllib.request.urlretrieve(
                    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
                    model_path
                )
                print("MediaPipe model downloaded")

            BaseOptions = mp.tasks.BaseOptions
            HandLandmarker = mp.tasks.vision.HandLandmarker
            HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
            VisionRunningMode = mp.tasks.vision.RunningMode

            options = HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=model_path),
                running_mode=VisionRunningMode.IMAGE,
                num_hands=1,
                min_hand_detection_confidence=0.3,
                min_hand_presence_confidence=0.3,
                min_tracking_confidence=0.3
            )

            self.landmarker = HandLandmarker.create_from_options(options)
            self.mp = mp
            print("MediaPipe loaded")

        except Exception as e:
            print(f"MediaPipe not loaded: {e}")

    def _load_model(self):
        """
        Muat checkpoint LSTM.

        Arsitektur TIDAK di-hardcode lagi. Urutan penentuannya:
          1. models/model_config.json kalau ada (dihasilkan notebook training)
          2. kalau tidak ada, disimpulkan langsung dari bentuk tensor checkpoint
        Ini mencegah kasus lama: notebook diubah (mis. hidden_size 128 -> 96),
        model baru di-copy ke server, load_state_dict gagal, lalu exception
        ditelan dan backend diam-diam jalan tanpa model.
        """
        model_path = "models/lstm_model.pt"
        encoder_path = "models/label_encoder.pkl"
        config_path = "models/model_config.json"

        if not os.path.exists(model_path):
            print("=" * 60)
            print("PERINGATAN: models/lstm_model.pt tidak ditemukan -> DUMMY MODE")
            print("Aplikasi akan mengembalikan label 'MODEL_BELUM_DILOAD'.")
            print("=" * 60)
            return

        try:
            import torch
            import json

            if os.path.exists(encoder_path):
                with open(encoder_path, "rb") as f:
                    self.label_encoder = pickle.load(f)
                    self.class_names = [str(c) for c in self.label_encoder.classes_]
            else:
                print("PERINGATAN: label_encoder.pkl tidak ada, memakai daftar kelas bawaan.")

            state = torch.load(model_path, map_location="cpu")

            # --- Tentukan arsitektur ---
            cfg = {}
            if os.path.exists(config_path):
                with open(config_path, encoding="utf-8") as f:
                    cfg = json.load(f)

            hidden_size = int(cfg.get("hidden_size") or state["lstm.weight_hh_l0"].shape[1])
            num_layers = int(cfg.get("num_layers") or len(
                {k.split("_l")[-1] for k in state if k.startswith("lstm.weight_ih_l")}
            ))
            fc_hidden = int(cfg.get("fc_hidden") or state["classifier.0.weight"].shape[0])
            num_classes_ckpt = int(state["classifier.3.weight"].shape[0])
            dropout = float(cfg.get("dropout", 0.3))

            # --- Cek konsistensi checkpoint vs label encoder ---
            if len(self.class_names) != num_classes_ckpt:
                print("=" * 60)
                print(f"PERINGATAN: label_encoder punya {len(self.class_names)} kelas, "
                      f"tapi checkpoint punya {num_classes_ckpt} kelas.")
                print("Pastikan lstm_model.pt dan label_encoder.pkl berasal dari "
                      "run training yang SAMA. Model tidak diload.")
                print("=" * 60)
                return

            class GestureLSTM(torch.nn.Module):
                def __init__(self):
                    super().__init__()
                    self.lstm = torch.nn.LSTM(
                        input_size=FEATURE_SIZE,
                        hidden_size=hidden_size,
                        num_layers=num_layers,
                        batch_first=True,
                        dropout=dropout,
                    )
                    self.classifier = torch.nn.Sequential(
                        torch.nn.Linear(hidden_size, fc_hidden),
                        torch.nn.ReLU(),
                        torch.nn.Dropout(dropout),
                        torch.nn.Linear(fc_hidden, num_classes_ckpt),
                    )

                def forward(self, x):
                    lstm_out, _ = self.lstm(x)
                    return self.classifier(lstm_out[:, -1, :])

            self.model = GestureLSTM()
            self.model.load_state_dict(state)   # strict=True: sengaja, biar ketahuan kalau beda
            self.model.eval()
            self.torch = torch
            self.model_loaded = True

            n_params = sum(p.numel() for p in self.model.parameters())
            print(f"LSTM model loaded: {num_classes_ckpt} kelas | hidden={hidden_size} | "
                  f"layers={num_layers} | {n_params:,} parameter")
            if not os.path.exists(config_path):
                print("  (model_config.json tidak ada — arsitektur disimpulkan dari checkpoint)")

        except Exception as e:
            print("=" * 60)
            print(f"GAGAL memuat model: {type(e).__name__}: {e}")
            print("Backend berjalan TANPA model (dummy mode). Jalankan cell '7c. Uji")
            print("kompatibilitas dengan backend' di notebook untuk menemukan sebabnya.")
            print("=" * 60)

    # ------------------------------------------------------------------
    # LANDMARK EXTRACTION (mode fallback: frame dikirim ke server)
    # ------------------------------------------------------------------
    def extract_landmarks(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Ekstrak 63 nilai (21 titik x,y,z) dari 1 frame BGR. None kalau tangan tak terdeteksi."""
        if self.landmarker is None:
            return None
        try:
            img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img_rgb = letterbox(img_rgb, 640)
            mp_image = self.mp.Image(
                image_format=self.mp.ImageFormat.SRGB,
                data=img_rgb
            )
            with self._mp_lock:
                result = self.landmarker.detect(mp_image)
            if not result.hand_landmarks:
                return None
            landmarks = []
            for lm in result.hand_landmarks[0]:
                landmarks.extend([lm.x, lm.y, lm.z])
            return np.array(landmarks, dtype=np.float32)
        except Exception as e:
            print(f"Landmark error: {e}")
            return None

    # alias lama supaya kode existing tetap jalan
    _extract_landmarks = extract_landmarks

    # ------------------------------------------------------------------
    # PREDIKSI (stateless — buffer dipegang pemanggil)
    # ------------------------------------------------------------------
    def predict_sequence(self, sequence: Sequence) -> dict:
        """
        sequence: 15 x 63 (list/np.array) landmark MENTAH dari MediaPipe.
        Normalisasi wrist + scale dilakukan di sini, jadi client (Flutter)
        cukup kirim landmark apa adanya.
        """
        if not self.model_loaded:
            return {
                "detected": False,
                "label": "",
                "confidence": 0.0,
                "info": "Model belum diload (taruh lstm_model.pt di /models/)",
            }

        arr = np.asarray(sequence, dtype=np.float32)
        if arr.shape != (SEQUENCE_LENGTH, FEATURE_SIZE):
            return {
                "detected": False,
                "label": "",
                "confidence": 0.0,
                "error": f"Bentuk sequence harus ({SEQUENCE_LENGTH}, {FEATURE_SIZE}), diterima {tuple(arr.shape)}",
            }

        seq = normalize_landmarks(arr)

        with self._model_lock:
            with self.torch.no_grad():
                input_tensor = self.torch.FloatTensor(seq).unsqueeze(0)
                output = self.model(input_tensor)
                probabilities = self.torch.softmax(output, dim=1)
                confidence, predicted = self.torch.max(probabilities, 1)
                confidence_val = float(confidence.item())
                predicted_idx = int(predicted.item())

        if confidence_val < CONFIDENCE_THRESHOLD:
            return {"detected": False, "label": "", "confidence": round(confidence_val, 3)}

        return {
            "detected": True,
            "label": self.class_names[predicted_idx],
            "confidence": round(confidence_val, 3),
        }

    def top_k(self, sequence: Sequence, k: int = 3) -> List[dict]:
        """Prediksi top-k, dipakai untuk fitur saran kata pada SmartSign AI."""
        if not self.model_loaded:
            return []
        arr = np.asarray(sequence, dtype=np.float32)
        if arr.shape != (SEQUENCE_LENGTH, FEATURE_SIZE):
            return []
        seq = normalize_landmarks(arr)
        with self._model_lock:
            with self.torch.no_grad():
                output = self.model(self.torch.FloatTensor(seq).unsqueeze(0))
                probs = self.torch.softmax(output, dim=1)[0]
                values, idxs = self.torch.topk(probs, min(k, len(self.class_names)))
        return [
            {"label": self.class_names[int(i)], "confidence": round(float(v), 3)}
            for v, i in zip(values, idxs)
        ]

    # ------------------------------------------------------------------
    # LEGACY API (dipakai kode lama; sekarang bisa dikasih session sendiri)
    # ------------------------------------------------------------------
    def detect(self, frame: np.ndarray, buffer: Optional[deque] = None) -> dict:
        """
        Mode lama: kirim frame gambar, server yang ekstrak landmark.
        `buffer` opsional — kalau diisi, state buffer dipegang pemanggil
        (aman untuk multi-user). Kalau None, pakai buffer internal (legacy).
        """
        buf = self.buffer if buffer is None else buffer

        landmark = self.extract_landmarks(frame)

        if landmark is None:
            buf.clear()
            return {
                "detected": False, "label": "", "confidence": 0.0,
                "buffering": False, "buffer_size": 0, "landmarks": None
            }

        buf.append(landmark)

        if len(buf) < SEQUENCE_LENGTH:
            return {
                "detected": False, "label": "", "confidence": 0.0,
                "buffering": True, "buffer_size": len(buf),
                "landmarks": landmark.tolist()
            }

        result = self.predict_sequence(np.array(list(buf)))
        result.update({
            "buffering": False,
            "buffer_size": SEQUENCE_LENGTH,
            "landmarks": landmark.tolist(),
        })
        return result

    def reset_buffer(self):
        """Reset buffer legacy."""
        self.buffer.clear()