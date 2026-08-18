from collections import deque
from typing import List, Optional, Sequence

from app.services.detector import SEQUENCE_LENGTH, FEATURE_SIZE

# ============================================================
# DetectionSession — state deteksi PER KONEKSI / PER VIDEO.
#
# Kenapa perlu:
# GestureDetector adalah singleton (model diload sekali). Kalau buffer
# 15 frame ikut disimpan di singleton, dua user yang streaming barengan
# akan saling menimpa isi buffer. Kelas ini memisahkan state itu:
#   - buffer landmark 15 frame
#   - transkrip gloss berjalan (dengan dedup + cooldown)
# Satu WebSocket = satu DetectionSession.
# ============================================================

# Berapa prediksi berturut-turut dengan label sama sebelum dianggap "fix".
# Menghindari label kedip-kedip saat tangan masih di tengah gerakan.
STABILITY_FRAMES = 3

# Setelah satu kata masuk transkrip, tunggu N frame sebelum kata yang SAMA
# boleh masuk lagi (biar "makan makan makan" tidak terjadi).
REPEAT_COOLDOWN_FRAMES = 20


class DetectionSession:
    def __init__(self,
                 stability_frames: int = STABILITY_FRAMES,
                 repeat_cooldown: int = REPEAT_COOLDOWN_FRAMES):
        self.buffer: deque = deque(maxlen=SEQUENCE_LENGTH)
        self.transcript: List[str] = []

        self._stability_frames = stability_frames
        self._repeat_cooldown = repeat_cooldown

        self._candidate: Optional[str] = None
        self._candidate_count = 0
        self._last_committed: Optional[str] = None
        self._cooldown = 0

    # ---------------- buffer ----------------
    def push(self, landmark: Sequence) -> None:
        """Masukkan 1 frame landmark (63 angka) ke buffer."""
        if landmark is None:
            self.clear_buffer()
            return
        if len(landmark) != FEATURE_SIZE:
            raise ValueError(f"Landmark harus {FEATURE_SIZE} angka, diterima {len(landmark)}")
        self.buffer.append(list(landmark))
        if self._cooldown > 0:
            self._cooldown -= 1

    @property
    def is_ready(self) -> bool:
        return len(self.buffer) == SEQUENCE_LENGTH

    @property
    def buffer_size(self) -> int:
        return len(self.buffer)

    def sequence(self) -> List[List[float]]:
        return list(self.buffer)

    def clear_buffer(self) -> None:
        self.buffer.clear()
        self._candidate = None
        self._candidate_count = 0

    # ---------------- transkrip ----------------
    def commit(self, label: str) -> bool:
        """
        Daftarkan hasil prediksi. Return True kalau kata BARU masuk transkrip.
        Kata baru dianggap valid kalau muncul stabil beberapa frame berturut-turut
        dan tidak sedang dalam cooldown pengulangan.
        """
        if not label:
            self._candidate = None
            self._candidate_count = 0
            return False

        if label == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate = label
            self._candidate_count = 1

        if self._candidate_count < self._stability_frames:
            return False

        if label == self._last_committed and self._cooldown > 0:
            return False

        self.transcript.append(label)
        self._last_committed = label
        self._cooldown = self._repeat_cooldown
        self._candidate_count = 0
        return True

    def transcript_text(self) -> str:
        return " ".join(self.transcript)

    def reset(self) -> None:
        """Reset total — dipakai saat user menekan tombol 'mulai ulang'."""
        self.clear_buffer()
        self.transcript.clear()
        self._last_committed = None
        self._cooldown = 0