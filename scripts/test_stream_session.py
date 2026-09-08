"""
Uji regresi DetectionSession — jalankan: .venv/bin/python scripts/test_stream_session.py

Menjaga perbaikan "bar hijau naik-turun-naik" dan "bar penuh tapi diam".
Sengaja tanpa pytest (belum jadi dependensi proyek) supaya bisa dijalankan
langsung dengan venv yang sudah ada.

GEJALA YANG DIJAGA
------------------
1. Satu frame tanpa tangan (motion blur — lumrah saat tangan bergerak) dulu
   menghapus SELURUH kemajuan 1,5 detik. Pada mode frame yang ~4 fps, itu
   membuat buffer nyaris tidak pernah penuh: bar naik sedikit, jatuh ke nol,
   naik lagi, dan prediksi jarang keluar.
2. Setelah jeda panjang (> MAX_GAP_MS), histori mentah dibuang tapi buffer
   15 frame lama DIBIARKAN, sehingga server tetap "siap" dan memprediksi dari
   data basi — bar terlihat penuh dan diam.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.stream_session import (  # noqa: E402
    DetectionSession,
    HAND_LOST_GRACE_MS,
    SEQUENCE_LENGTH,
)

LM = [0.5] * 63
_gagal = 0


def cek(nama: str, syarat: bool, detail: str = "") -> None:
    global _gagal
    if syarat:
        print(f"  OK   {nama}")
    else:
        _gagal += 1
        print(f"  GAGAL {nama} {detail}")


def sesi_terisi(interval_ms: int = 100, n: int = 20):
    """Sesi dengan buffer penuh + timestamp terakhir."""
    s = DetectionSession()
    t = 0
    for _ in range(n):
        t += interval_ms
        s.push(LM, t)
    return s, t


print("1. Buffer terisi normal pada 10 fps")
s, t = sesi_terisi()
cek("penuh setelah 1,5 detik", s.is_ready and s.buffer_size == SEQUENCE_LENGTH,
    f"(buffer_size={s.buffer_size})")

print("2. Tangan hilang SESAAT tidak menghapus kemajuan")
s, t = sesi_terisi()
s.push(None, t + 100)          # satu frame meleset
cek("kemajuan bertahan", s.buffer_size == SEQUENCE_LENGTH,
    f"(buffer_size={s.buffer_size})")
s.push(LM, t + 200)            # tangan muncul lagi
cek("tetap siap prediksi", s.is_ready)

print("3. Tangan hilang LAMA tetap mereset")
s, t = sesi_terisi()
s.push(None, t + HAND_LOST_GRACE_MS + 50)
cek("buffer direset", s.buffer_size == 0 and not s.is_ready,
    f"(buffer_size={s.buffer_size})")

print("4. Laju rendah (~4 fps) dengan deteksi meleset berkala tetap bisa penuh")
s = DetectionSession()
t = 0
gagal = {6, 11, 16}
siap = 0
for i in range(1, 25):
    t += 250
    s.push(None if i in gagal else LM, t)
    if s.is_ready:
        siap += 1
cek("buffer penuh berkali-kali, bukan cuma sekali-dua", siap >= 12,
    f"(hanya {siap} dari 24 frame)")

print("5. Jeda panjang tidak boleh memprediksi dari data basi")
s = DetectionSession()
t = 0
for i in range(20):
    t += 100
    s.push([0.1 * i] * 63, t)
lama = s.sequence()[0][0]
t += 5000                       # jauh di atas MAX_GAP_MS
s.push([9.9] * 63, t)
cek("tidak lagi 'siap' setelah jeda", not s.is_ready,
    f"(buffer_size={s.buffer_size})")
cek("buffer tidak menyimpan frame pra-jeda",
    not s.sequence() or s.sequence()[0][0] != lama)

print("6. Klien lama tanpa timestamp: perilaku lama dipertahankan")
s = DetectionSession()
for _ in range(20):
    s.push(LM, None)
cek("terisi tanpa timestamp", s.is_ready)
s.push(None, None)
cek("reset langsung saat tangan hilang", s.buffer_size == 0)

print("7. Progres buffer naik mulus, tidak melompat-lompat")
s = DetectionSession()
t = 0
urutan = []
for _ in range(8):
    t += 250                    # klien lambat
    s.push(LM, t)
    urutan.append(s.buffer_size)
cek("tidak pernah turun selama frame terus masuk",
    all(b <= a for a, b in zip(urutan[1:], urutan[:-1])), f"({urutan})")

print()
if _gagal:
    print(f"{_gagal} pemeriksaan GAGAL")
    sys.exit(1)
print("Semua pemeriksaan lulus.")
