import numpy as np
import cv2
import os
import pickle
from collections import deque
from typing import Optional

# ============================================================
# LSTM VERSION
# Model butuh sequence 15 frame berurutan
# Buffer otomatis mengumpulkan frame sebelum prediksi
# ============================================================

def normalize_landmarks(seq: np.ndarray) -> np.ndarray:
    """seq: (15, 63) -> (15, 63), relatif wrist (translasi) + scale-invariant."""
    pts = np.asarray(seq, dtype=np.float32).reshape(15, 21, 3)
    wrist = pts[:, 0:1, :]
    pts = pts - wrist
    scale = np.linalg.norm(pts[:, 9, :], axis=-1, keepdims=True)
    scale = np.where(scale < 1e-6, 1e-6, scale)
    pts = pts / scale[:, None]
    return pts.reshape(15, 63)

SEQUENCE_LENGTH = 15  # harus sama dengan saat training


class GestureDetector:
    def __init__(self):
        self.model_loaded = False
        self.model = None
        self.label_encoder = None
        self.landmarker = None
        self.mp = None

        # Buffer untuk kumpulkan 15 frame landmark berurutan
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
                print("✅ MediaPipe model downloaded")

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
            print("✅ MediaPipe loaded")

        except Exception as e:
            print(f"⚠️ MediaPipe not loaded: {e}")

    def _load_model(self):
        try:
            model_path = "models/lstm_model.pt"
            encoder_path = "models/label_encoder.pkl"

            if not os.path.exists(model_path):
                print("⚠️ lstm_model.pt not found → DUMMY MODE")
                print("   Taruh lstm_model.pt di folder /models/")
                return

            import torch

            # Load label encoder
            with open(encoder_path, "rb") as f:
                self.label_encoder = pickle.load(f)
                self.class_names = list(self.label_encoder.classes_)

            # Definisi arsitektur LSTM
            # Harus sama persis dengan saat training di Colab
            class GestureLSTM(torch.nn.Module):
                def __init__(self, input_size=63, hidden_size=128,
                             num_layers=2, num_classes=15):
                    super().__init__()
                    self.lstm = torch.nn.LSTM(
                        input_size=input_size,
                        hidden_size=hidden_size,
                        num_layers=num_layers,
                        batch_first=True,
                        dropout=0.3
                    )
                    self.classifier = torch.nn.Sequential(
                        torch.nn.Linear(hidden_size, 64),
                        torch.nn.ReLU(),
                        torch.nn.Dropout(0.3),
                        torch.nn.Linear(64, num_classes)
                    )

                def forward(self, x):
                    lstm_out, _ = self.lstm(x)
                    last = lstm_out[:, -1, :]
                    return self.classifier(last)

            num_classes = len(self.class_names)
            self.model = GestureLSTM(num_classes=num_classes)
            self.model.load_state_dict(
                torch.load(model_path, map_location="cpu")
            )
            self.model.eval()
            self.torch = torch

            self.model_loaded = True
            print(f"✅ LSTM Model loaded: {num_classes} kelas")
            print(f"   Kelas: {self.class_names}")

        except Exception as e:
            print(f"⚠️ Model not loaded: {e}")

    def _extract_landmarks(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Ekstrak 63 landmark dari 1 frame"""
        if self.landmarker is None:
            return None
        try:
            img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img_rgb = cv2.resize(img_rgb, (640, 640))
            mp_image = self.mp.Image(
                image_format=self.mp.ImageFormat.SRGB,
                data=img_rgb
            )
            result = self.landmarker.detect(mp_image)
            if not result.hand_landmarks:
                return None
            landmarks = []
            for lm in result.hand_landmarks[0]:
                landmarks.extend([lm.x, lm.y, lm.z])
            return np.array(landmarks, dtype=np.float32)  # (63,)
        except Exception as e:
            print(f"Landmark error: {e}")
            return None

    def detect(self, frame: np.ndarray) -> dict:
        """
        Main detection - LSTM version.
        Buffer kumpulkan 15 frame landmark dulu baru prediksi.

        Return:
        - buffering: True kalau masih ngumpulin frame
        - detected: True kalau sudah prediksi dan confidence cukup
        """
        # Ekstrak landmark dari frame ini
        landmark = self._extract_landmarks(frame)

        # Kalau tangan tidak terdeteksi, reset buffer
        if landmark is None:
            self.buffer.clear()
            return {
                "detected": False,
                "label": "",
                "confidence": 0.0,
                "buffering": False,
                "buffer_size": 0
            }

        # Tambah landmark ke buffer
        self.buffer.append(landmark)

        # Belum cukup frame
        if len(self.buffer) < SEQUENCE_LENGTH:
            return {
                "detected": False,
                "label": "",
                "confidence": 0.0,
                "buffering": True,
                "buffer_size": len(self.buffer)
            }

        # DUMMY MODE
        if not self.model_loaded:
            return {
                "detected": True,
                "label": "MODEL_BELUM_DILOAD",
                "confidence": 0.0,
                "buffering": False,
                "buffer_size": SEQUENCE_LENGTH,
                "info": "Taruh lstm_model.pt di /models/"
            }

        # Prediksi dengan LSTM
        sequence_raw = np.array(list(self.buffer))  # (15, 63)
        sequence = normalize_landmarks(sequence_raw)

        with self.torch.no_grad():
            input_tensor = self.torch.FloatTensor(sequence).unsqueeze(0)  # (1, 15, 63)
            output = self.model(input_tensor)
            probabilities = self.torch.softmax(output, dim=1)
            confidence, predicted = self.torch.max(probabilities, 1)

            confidence_val = confidence.item()
            predicted_idx = predicted.item()

        CONFIDENCE_THRESHOLD = 0.7

        if confidence_val < CONFIDENCE_THRESHOLD:
            return {
                "detected": False,
                "label": "",
                "confidence": round(confidence_val, 3),
                "buffering": False,
                "buffer_size": SEQUENCE_LENGTH
            }

        label = self.class_names[predicted_idx]

        return {
            "detected": True,
            "label": label,
            "confidence": round(confidence_val, 3),
            "buffering": False,
            "buffer_size": SEQUENCE_LENGTH
        }

    def reset_buffer(self):
        """Reset buffer — panggil saat user mau mulai gesture baru"""
        self.buffer.clear()