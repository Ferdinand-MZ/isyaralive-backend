from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from app.services.detector import SEQUENCE_LENGTH, FEATURE_SIZE

# ============================================================
# DetectionSession — state deteksi PER KONEKSI / PER VIDEO.
#
# Kenapa perlu:
# GestureDetector adalah singleton (model diload sekali). Kalau buffer
# 15 frame ikut disimpan di singleton, dua user yang streaming barengan
# akan saling menimpa isi buffer. Kelas ini memisahkan state itu:
#   - buffer landmark 15 frame (SUDAH di-resample ke 10 fps rata)
#   - transkrip gloss berjalan (dengan dedup + cooldown)
# Satu WebSocket = satu DetectionSession.
# ============================================================

# Berapa prediksi berturut-turut dengan label sama sebelum dianggap "fix".
# Menghindari label kedip-kedip saat tangan masih di tengah gerakan.
STABILITY_FRAMES = 3

# Setelah satu kata masuk transkrip, tunggu N frame sebelum kata yang SAMA
# boleh masuk lagi (biar "makan makan makan" tidak terjadi).
REPEAT_COOLDOWN_FRAMES = 20

# ============================================================
# RESAMPLING KE 10 FPS
#
# Model dilatih pada 15 frame @ 10 fps = jendela 1,5 detik yang RATA.
# Klien (terutama HP kelas menengah / jaringan jelek) tidak selalu bisa
# kirim persis setiap 100ms — jarak antar-kirim bisa berayun cukup jauh
# (lihat hasil ukur RTT WS mode landmark). Kalau 15 frame mentah yang
# diterima server langsung dipakai, jendela waktunya bisa melenceng jauh
# dari 1,5 detik dan prediksi meleset diam-diam.
#
# Solusinya: setiap landmark yang masuk dicatat beserta timestamp-nya,
# lalu sebelum prediksi, kita INTERPOLASI ulang supaya buffer yang dipakai
# model selalu 15 titik dengan jarak 100ms yang genap — tidak peduli
# secepat/selambat apa & serata/setidak-rata apa klien mengirim.
# ============================================================

TARGET_FPS = 10
FRAME_INTERVAL_MS = 1000 // TARGET_FPS  # 100ms, harus sama dengan asumsi training

# Kalau jeda antara dua landmark berturut-turut melebihi ini, dianggap
# gestur terputus (tangan sempat hilang / koneksi tersendat parah) —
# histori lama dibuang daripada diinterpolasi paksa melintasi jeda itu.
MAX_GAP_MS = SEQUENCE_LENGTH * FRAME_INTERVAL_MS * 2  # 3000ms

# ============================================================
# TOLERANSI TANGAN HILANG SESAAT
#
# MASALAH (terlihat sebagai bar hijau naik-turun-naik terus):
# MediaPipe sesekali GAGAL menemukan tangan pada satu frame — biasa terjadi
# justru saat tangan sedang BERGERAK (motion blur), padahal gerakan itulah
# yang mau dideteksi. Versi lama langsung membuang SELURUH histori begitu
# ada satu frame tanpa tangan, jadi kemajuan 1,5 detik hilang hanya karena
# satu frame meleset. Pada mode frame yang lajunya ~4 fps, satu kegagalan
# tiap 5 frame sudah cukup membuat buffer TIDAK PERNAH penuh — pengguna
# melihat bar naik sedikit, jatuh ke nol, naik lagi, dan prediksi nyaris
# tidak pernah keluar.
#
# SOLUSI: beri masa tenggang. Selama tangan hilangnya lebih singkat dari
# ini, histori DIPERTAHANKAN — resampler memang sudah bisa menjembatani
# lubang kecil lewat interpolasi. Baru kalau tangan benar-benar pergi
# (lebih lama dari ini), histori dibuang.
#
# 400ms dipilih supaya menutup 1 frame meleset pada 2,5 fps dan sampai 4
# frame pada 10 fps, tapi tetap jauh di bawah panjang jendela 1,5 detik —
# jadi bagian yang "ditebak" interpolasi tidak pernah mendominasi jendela.
HAND_LOST_GRACE_MS = 400

# Histori mentah yang disimpan dibatasi seperlunya supaya deque tidak tumbuh
# tanpa batas kalau klien mengirim sangat cepat.
#
# Slack-nya SENGAJA selebar masa tenggang tangan hilang: kalau cuma pas-pasan
# 1,6 detik, satu frame yang meleset meninggalkan lubang di tepi lama histori,
# sampel tertua ikut terbuang, dan jendela 1,4 detik jadi tidak tertutup —
# buffer yang tadinya penuh turun sebentar ke ~13 lalu naik lagi. Menyimpan
# sedikit lebih panjang membuat bar tetap mantap. Biayanya sepele: pada 10 fps
# ini cuma ~20 sampel berisi 63 angka.
_RAW_WINDOW_MS = (
    SEQUENCE_LENGTH * FRAME_INTERVAL_MS + HAND_LOST_GRACE_MS + FRAME_INTERVAL_MS
)

RawSample = Tuple[float, List[float]]


@dataclass
class KataTranskrip:
    """
    Satu kata yang sudah masuk transkrip, BESERTA bukti yang menghasilkannya.

    `sequence` (15x63 landmark yang dipakai model saat itu) disimpan justru
    karena inilah satu-satunya kesempatan menyimpannya: buffer sesi terus
    bergulir, jadi begitu frame berikutnya masuk, potongan gerakan yang
    melahirkan kata ini hilang selamanya.

    Gunanya: kalau pengguna membetulkan kata yang salah tebak, koreksinya
    baru berguna untuk melatih model bila kita masih punya gerakan aslinya.
    Tanpa ini, koreksi cuma jadi "katanya salah" tanpa contoh yang bisa
    dipelajari.

    Ukurannya kecil: 15 x 63 angka ~ 7,5 KB sebagai JSON per kata.
    """
    label: str
    sequence: List[List[float]] = field(default_factory=list)
    confidence: float = 0.0


class DetectionSession:
    def __init__(self,
                 stability_frames: int = STABILITY_FRAMES,
                 repeat_cooldown: int = REPEAT_COOLDOWN_FRAMES):
        self.buffer: deque = deque(maxlen=SEQUENCE_LENGTH)
        self.transcript: List[str] = []

        # Sejajar indeks dengan `transcript`: kata ke-i di transkrip punya
        # bukti gerakan di `kata[i]`. Dipakai saat pengguna mengoreksi kata
        # (lihat KataTranskrip).
        self.kata: List[KataTranskrip] = []

        self._stability_frames = stability_frames
        self._repeat_cooldown = repeat_cooldown

        self._candidate: Optional[str] = None
        self._candidate_count = 0
        self._last_committed: Optional[str] = None
        self._cooldown = 0

        # histori mentah (timestamp_ms, landmark) buat resampling
        self._raw: deque[RawSample] = deque()
        self._last_t: Optional[float] = None

        # Kapan terakhir kali tangan BENAR-BENAR terlihat — dasar masa
        # tenggang HAND_LOST_GRACE_MS (lihat hand_lost()).
        self._last_seen_t: Optional[float] = None

    # ---------------- buffer ----------------
    def push(self, landmark: Optional[Sequence], t_ms: Optional[float] = None) -> None:
        """
        Masukkan 1 frame landmark (63 angka) + timestamp (epoch ms, boleh dari
        klien atau fallback waktu terima server). `landmark=None` berarti
        tangan tidak terdeteksi -> buffer & histori mentah direset.

        `t_ms` sengaja opsional: kalau klien lama tidak kirim field `t`,
        sesi tetap jalan seperti sebelumnya (tanpa resampling presisi),
        supaya tidak ada breaking change untuk klien yang belum update.
        """
        if landmark is None:
            self.hand_lost(t_ms)
            return
        if len(landmark) != FEATURE_SIZE:
            raise ValueError(f"Landmark harus {FEATURE_SIZE} angka, diterima {len(landmark)}")

        landmark = [float(v) for v in landmark]
        self._last_seen_t = t_ms if t_ms is not None else self._last_seen_t

        if t_ms is None:
            # Tanpa timestamp, tidak ada dasar buat resampling -> fallback
            # ke perilaku lama (percaya urutan kirim apa adanya).
            self.buffer.append(landmark)
            if self._cooldown > 0:
                self._cooldown -= 1
            return

        self._push_raw(landmark, float(t_ms))
        if self._cooldown > 0:
            self._cooldown -= 1

    def hand_lost(self, t_ms: Optional[float] = None) -> None:
        """
        Laporkan satu frame TANPA tangan terdeteksi.

        Histori TIDAK langsung dibuang: selama tangan hilangnya masih dalam
        HAND_LOST_GRACE_MS, kemajuan buffer dipertahankan supaya satu frame
        yang meleset (motion blur — hal biasa saat tangan bergerak) tidak
        menghapus 1,5 detik kemajuan. Lihat catatan di HAND_LOST_GRACE_MS.

        Tanpa timestamp (klien lama) tidak ada dasar mengukur lamanya hilang,
        jadi perilaku lama dipakai: langsung reset.
        """
        if t_ms is None or self._last_seen_t is None:
            self.clear_buffer()
            return

        if (float(t_ms) - self._last_seen_t) > HAND_LOST_GRACE_MS:
            self.clear_buffer()

    def _push_raw(self, landmark: List[float], t_ms: float) -> None:
        # Jam klien kadang mundur/lompat (misal NTP sync) -> paksa maju
        # sedikit biar interpolasi tidak dapat rentang waktu negatif/nol.
        if self._last_t is not None and t_ms <= self._last_t:
            t_ms = self._last_t + 1.0

        if self._raw and (t_ms - self._raw[-1][0]) > MAX_GAP_MS:
            # Jeda kelewat lama dianggap gestur baru -> histori lama basi.
            # `self.buffer` WAJIB ikut dikosongkan: kalau tidak, ia masih
            # memegang 15 frame dari SEBELUM jeda, sehingga is_ready tetap
            # True dan server memprediksi dari data basi — bar terlihat penuh
            # dan diam padahal data barunya baru satu frame.
            self._raw.clear()
            self.buffer.clear()

        self._raw.append((t_ms, landmark))
        self._last_t = t_ms

        cutoff = t_ms - _RAW_WINDOW_MS
        while len(self._raw) > 1 and self._raw[0][0] < cutoff:
            self._raw.popleft()

        self._resample()

    def _resample(self) -> None:
        """Isi ulang self.buffer dengan 15 titik berjarak 100ms genap,
        diinterpolasi linear dari histori mentah. Kalau histori belum
        cukup panjang (jendela < 1,5 detik), buffer belum di-update
        (tetap dianggap 'buffering')."""
        latest_t = self._raw[-1][0]
        targets = [latest_t - (SEQUENCE_LENGTH - 1 - i) * FRAME_INTERVAL_MS
                   for i in range(SEQUENCE_LENGTH)]

        if self._raw[0][0] > targets[0]:
            # Histori belum menutupi seluruh jendela 1,5 detik. Buffer lama
            # (kalau ada) sudah tidak mewakili jendela sekarang, jadi harus
            # dikosongkan — bukan dibiarkan supaya "kelihatan siap".
            self.buffer.clear()
            return

        self.buffer = deque(
            (self._interpolate(t) for t in targets),
            maxlen=SEQUENCE_LENGTH,
        )

    def _interpolate(self, t: float) -> List[float]:
        raw = self._raw
        if t <= raw[0][0]:
            return raw[0][1]
        if t >= raw[-1][0]:
            return raw[-1][1]

        # raw terurut menaik berdasarkan waktu -> cari dua titik pengapit
        lo, hi = 0, len(raw) - 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if raw[mid][0] <= t:
                lo = mid
            else:
                hi = mid

        t0, v0 = raw[lo]
        t1, v1 = raw[hi]
        if t1 == t0:
            return v1
        ratio = (t - t0) / (t1 - t0)
        return [a + (b - a) * ratio for a, b in zip(v0, v1)]

    @property
    def is_ready(self) -> bool:
        return len(self.buffer) == SEQUENCE_LENGTH

    @property
    def buffer_size(self) -> int:
        if self.buffer:
            return len(self.buffer)
        if not self._raw:
            return 0
        # Belum cukup histori buat resample penuh -> kasih perkiraan progres
        # berdasarkan rentang waktu yang sudah tertampung, biar klien tetap
        # dapat indikator "buffering" yang masuk akal.
        #
        # Dihitung sebagai PORSI dari jendela yang dibutuhkan, bukan
        # "jumlah frame yang masuk": klien yang lambat mengirim tiap ~250ms
        # akan membuat hitungan per-frame melompat 1->3->6, terlihat seperti
        # bar yang tersendat. Porsi waktu naik mulus berapa pun laju kirimnya.
        span_ms = self._raw[-1][0] - self._raw[0][0]
        dibutuhkan = (SEQUENCE_LENGTH - 1) * FRAME_INTERVAL_MS  # 1400ms
        return max(1, min(SEQUENCE_LENGTH, int(SEQUENCE_LENGTH * span_ms / dibutuhkan)))

    def sequence(self) -> List[List[float]]:
        return list(self.buffer)

    def clear_buffer(self) -> None:
        self.buffer.clear()
        self._raw.clear()
        self._last_t = None
        self._last_seen_t = None
        self._candidate = None
        self._candidate_count = 0

    # ---------------- transkrip ----------------
    def commit(self, label: str, confidence: float = 0.0) -> bool:
        """
        Daftarkan hasil prediksi. Return True kalau kata BARU masuk transkrip.
        Kata baru dianggap valid kalau muncul stabil beberapa frame berturut-turut
        dan tidak sedang dalam cooldown pengulangan.

        Saat kata benar-benar masuk, potongan gerakan yang melahirkannya ikut
        disimpan (lihat KataTranskrip) — buffer akan tergulir dan bukti itu
        tidak bisa diambil lagi setelah frame berikutnya datang.
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
        self.kata.append(KataTranskrip(
            label=label,
            sequence=[list(f) for f in self.buffer],
            confidence=float(confidence),
        ))
        self._last_committed = label
        self._cooldown = self._repeat_cooldown
        self._candidate_count = 0
        return True

    def transcript_text(self) -> str:
        return " ".join(self.transcript)

    def transcript_words(self) -> List[str]:
        """
        Transkrip sebagai DAFTAR kata.

        Klien tidak boleh memecah `transcript_text()` dengan split(" ") untuk
        menandai kata mana yang mau dikoreksi: ada label yang memang berisi
        spasi ("Terima Kasih", "Hari ini"), jadi indeks hasil split tidak
        pernah cocok dengan indeks di sini.
        """
        return list(self.transcript)

    # ---------------- koreksi ----------------
    def ganti_kata(self, indeks: int, label_baru: str) -> Optional[KataTranskrip]:
        """
        Ganti kata ke-`indeks` dengan `label_baru` (pengguna membetulkan tebakan
        yang salah).

        Return KataTranskrip LAMA (label salah + bukti gerakannya) supaya
        pemanggil bisa menyimpannya sebagai data latih. None kalau indeksnya
        tidak ada.
        """
        if not (0 <= indeks < len(self.transcript)):
            return None

        lama = self.kata[indeks]
        self.transcript[indeks] = label_baru
        self.kata[indeks] = KataTranskrip(
            label=label_baru,
            sequence=lama.sequence,
            confidence=lama.confidence,
        )

        # Kata terakhir ikut berubah supaya cooldown pengulangan mengikuti apa
        # yang SEKARANG tertulis, bukan tebakan yang sudah dibuang.
        if indeks == len(self.transcript) - 1:
            self._last_committed = label_baru

        return lama

    def hapus_kata(self, indeks: int) -> Optional[KataTranskrip]:
        """
        Buang kata ke-`indeks` (model menangkap gerakan yang sebenarnya bukan
        isyarat apa pun — false positive).

        Return KataTranskrip yang dibuang, termasuk bukti gerakannya.
        """
        if not (0 <= indeks < len(self.transcript)):
            return None

        self.transcript.pop(indeks)
        dibuang = self.kata.pop(indeks)
        self._last_committed = self.transcript[-1] if self.transcript else None
        return dibuang

    def reset(self) -> None:
        """Reset total — dipakai saat user menekan tombol 'mulai ulang'."""
        self.clear_buffer()
        self.transcript.clear()
        self.kata.clear()
        self._last_committed = None
        self._cooldown = 0
