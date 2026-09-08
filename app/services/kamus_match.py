"""
Pencocokan kata pengguna -> entri kamus SignPedia.

Dipisah jadi modul sendiri karena dipakai di DUA tempat yang sebelumnya
punya aturan sendiri-sendiri dan tidak konsisten:
  - app/routers/chatbot.py   (integrasi SignPedia di Asisten AI)
  - app/routers/gesture_lookup.py (teks -> peraga gestur)

MASALAH YANG DIPERBAIKI DI SINI
--------------------------------
Versi lama mengambil kata tanya dengan regex mentah lalu mencocokkannya
dengan `word.ilike(kata)` PERSIS. Dua akibatnya sering terlihat pengguna:

1. Aplikasi mengirim pertanyaan berformat  Apa makna "keju"?  (tanda kutip
   ikut dikirim, lihat alphabet_spelling_screen.dart). Regex lama menangkap
   `"keju"` LENGKAP DENGAN TANDA KUTIP, sehingga pencarian ke kamus mencari
   kata bernama '"keju"' — tidak akan pernah ketemu.

2. Pengguna mengetik "apa makna kata keju". Regex lama menangkap "kata keju",
   jadi jawabannya pun menyebut «Kata Keju» seolah itu nama katanya, dan
   pencarian kamus meleset lagi.

Karena kedua kasus itu "meleset", sistem menyimpulkan kata TIDAK ADA di kamus
lalu menawarkan ejaan abjad — padahal katanya jelas-jelas ada di data. Itulah
keluhan "ada di data sheet tapi malah bilang belum ada, terus dikembalikan
abjad".

Karena itu di sini kata dibersihkan dulu (kutip, kata pengisi seperti "kata"),
dan pencocokan dibuat bertingkat: persis -> ternormalisasi -> sebagian.
"""

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.dictionary import DictionaryEntry

# Tanda kutip yang mungkin ikut terbawa dari UI atau ketikan pengguna,
# termasuk kutip "pintar" (“ ” ‘ ’) yang dipakai aplikasi Flutter.
KUTIP = "\"'`“”‘’«»"

# Kata pengisi di DEPAN kata yang sebenarnya ditanyakan. "apa makna KATA keju"
# -> yang dicari "keju", bukan "kata keju".
PREFIKS_PENGISI = (
    "kata",
    "istilah",
    "kosakata",
    "gestur",
    "gerakan",
    "isyarat",
    "bahasa isyarat",
    "tanda",
    "sebuah",
    "suatu",
    "dari",
    "untuk",
    "tentang",
)

# Kata pengisi di BELAKANG, mis. "makna keju itu apa" / "arti keju dong".
SUFIKS_PENGISI = ("itu", "dong", "ya", "sih", "kah", "apa", "gimana", "bagaimana")

# Pola pertanyaan yang berarti "ini pencarian kosakata".
# Kelompok TERAKHIR pada setiap pola adalah kata yang ditanyakan.
POLA_TANYA = (
    r"^(?:apa|apakah)\s+(?:arti|makna|maksud|pengertian|definisi)\s+(?:dari\s+)?(.+)$",
    r"^(?:arti|makna|maksud|pengertian|definisi)\s+(?:dari\s+)?(.+)$",
    r"^(?:apa|apakah)\s+itu\s+(.+)$",
    r"^(?:apa|bagaimana|gimana)\s+bahasa\s+isyarat\s+(?:dari\s+|untuk\s+)?(.+)$",
    r"^(?:bagaimana|gimana)\s+(?:cara\s+)?(?:meng)?isyarat(?:kan)?\s+(.+)$",
    r"^cara\s+(?:meng)?isyarat(?:kan)?\s+(.+)$",
    r"^(?:isyarat|gestur|tanda)\s+(?:untuk\s+|dari\s+)?(.+)$",
    r"^(?:jelaskan|jelasin|terangkan)\s+(?:soal\s+|tentang\s+)?(.+)$",
    r"^(?:apa|apakah)\s+(?:yang\s+)?dimaksud\s+(?:dengan\s+)?(.+)$",
)


def bersihkan_kata(teks: str) -> str:
    """
    Rapikan potongan kata hasil regex jadi kata yang benar-benar dicari.

    Membuang tanda kutip, tanda baca di ujung, dan kata pengisi seperti
    "kata"/"istilah" — sumber bug «Kata Keju» dan pencarian '"keju"'.
    """
    kata = teks.strip().strip(KUTIP).strip()
    kata = kata.strip(".,!?;:").strip()
    kata = kata.strip(KUTIP).strip()

    # Buang kata pengisi di depan, bisa bertumpuk ("kata isyarat keju").
    berubah = True
    while berubah:
        berubah = False
        rendah = kata.lower()
        for pengisi in PREFIKS_PENGISI:
            if rendah.startswith(pengisi + " "):
                sisa = kata[len(pengisi) + 1 :].strip().strip(KUTIP).strip()
                # Jangan sampai mengosongkan kata: pertanyaan "apa arti kata"
                # memang menanyakan kata "kata" itu sendiri.
                if sisa:
                    kata = sisa
                    berubah = True
                break

    # Buang kata pengisi di belakang.
    berubah = True
    while berubah:
        berubah = False
        rendah = kata.lower()
        for pengisi in SUFIKS_PENGISI:
            if rendah.endswith(" " + pengisi):
                sisa = kata[: -(len(pengisi) + 1)].strip().strip(KUTIP).strip()
                if sisa:
                    kata = sisa
                    berubah = True
                break

    return kata.strip().strip(KUTIP).strip(".,!?;:").strip()


def ekstrak_kata_tanya(pesan: str) -> Optional[str]:
    """
    Kalau `pesan` berpola pertanyaan kosakata, kembalikan kata yang ditanyakan.

    Return None kalau ini obrolan biasa (bukan pencarian kata), supaya alur
    chat normal tidak ikut memicu pencarian kamus.
    """
    if not pesan:
        return None

    teks = pesan.strip().rstrip("?.! ").strip()
    if not teks:
        return None

    for pola in POLA_TANYA:
        cocok = re.match(pola, teks, flags=re.IGNORECASE)
        if cocok:
            kata = bersihkan_kata(cocok.groups()[-1])
            # Pertanyaan yang terlalu panjang biasanya bukan "cari satu kata",
            # tapi pertanyaan bebas — biarkan AI menjawabnya tanpa lookup.
            if kata and len(kata.split()) <= 4:
                return kata
            return None

    return None


def _normal(teks: str) -> str:
    """Bentuk banding: huruf kecil, tanpa spasi & tanda baca.

    Membuat "Terima Kasih", "terima kasih", dan "terimakasih" dianggap sama.
    """
    return re.sub(r"[^a-z0-9]", "", teks.lower())


def cari_entri(db: Session, kata: str) -> Optional[DictionaryEntry]:
    """
    Cari entri kamus untuk `kata`, bertingkat dari paling ketat ke paling longgar.

    Urutannya penting: yang paling persis harus menang, supaya "makan" tidak
    tertukar dengan "memakan" hanya karena pencocokan sebagian dijalankan
    lebih dulu.
    """
    kata = (kata or "").strip()
    if not kata:
        return None

    # 1) Persis (tidak peduli huruf besar/kecil).
    entri = db.query(DictionaryEntry).filter(DictionaryEntry.word.ilike(kata)).first()
    if entri:
        return entri

    # 2) Sama setelah dinormalisasi — menangkap beda spasi/tanda baca.
    target = _normal(kata)
    if target:
        for kandidat in db.query(DictionaryEntry).all():
            if _normal(kandidat.word) == target:
                return kandidat

    # 3) Kata pengguna ada DI DALAM entri kamus ("kasih" -> "Terima Kasih").
    #    Ambil entri terpendek: paling sedikit menambah makna yang tidak diminta.
    sebagian = (
        db.query(DictionaryEntry)
        .filter(DictionaryEntry.word.ilike(f"%{kata}%"))
        .all()
    )
    if sebagian:
        return min(sebagian, key=lambda e: len(e.word))

    # 4) Entri kamus ada DI DALAM kalimat pengguna ("terima kasih banyak").
    #    Ambil yang terpanjang: paling spesifik.
    cocok_terbalik = [
        e for e in db.query(DictionaryEntry).all() if _normal(e.word) and _normal(e.word) in target
    ]
    if cocok_terbalik:
        return max(cocok_terbalik, key=lambda e: len(e.word))

    return None
