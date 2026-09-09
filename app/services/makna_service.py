"""
Satu pintu untuk "apa arti kata ini" — dipakai chatbot dan layar Makna Kata.

Alurnya dua lapis, dan urutannya disengaja:

  1. KBBI  — rujukan resmi arti kata Bahasa Indonesia. Ini SUMBER FAKTANYA.
  2. Azure OpenAI — hanya MENULIS ULANG definisi KBBI itu supaya enak dibaca
     (KBBI menulis dengan gaya kamus: "1 pron kata tanya untuk ...").

Untuk kata yang memang tidak ada di KBBI (nama diri, merek, istilah asing),
barulah AI menjelaskan dari pengetahuannya sendiri — dan `sumber` menyebutnya
apa adanya, supaya pengguna tidak mengira itu kutipan KBBI.

Tidak ada sumber lain. Ensiklopedia (Wikipedia) SENGAJA tidak dipakai lagi:
untuk pertanyaan "apa arti kata X" isinya artikel ensiklopedis, bukan definisi,
kata sehari-hari jatuh ke halaman disambiguasi, dan pencarian judul termiripnya
pernah memasang poster film "Apa Artinya Cinta?" sebagai ilustrasi kata "apa".

PRINSIP: layanan ini SELALU boleh gagal dan tidak pernah melempar exception.
AI mati -> definisi KBBI mentah tetap dipakai. KBBI mati -> AI yang menjelaskan.
Dua-duanya mati -> None, dan chat tetap jalan (AI menjawab dari pengetahuannya
sendiri lewat alur chat biasa).
"""

from typing import Optional

from app.services.ai_service import jelaskan_makna
from app.services.kbbi_service import cari_ringkasan

SUMBER_KBBI = "KBBI"
SUMBER_AI = "Asisten AI IsyaraLive"


async def cari_makna(kata: str) -> Optional[dict]:
    """
    Ambil penjelasan makna `kata`.

    Return {"judul", "makna", "sumber"} atau None kalau tidak ada yang bisa
    menjelaskan. `sumber` selalu jujur menyebut dari mana isinya berasal:

      "KBBI — keju"                     definisi KBBI apa adanya (AI sedang mati)
      "KBBI — keju, dirapikan Asisten AI" definisi KBBI yang ditulis ulang AI
      "Asisten AI IsyaraLive"            kata tidak ada di KBBI
    """
    kata = (kata or "").strip()
    if not kata:
        return None

    kbbi = await cari_ringkasan(kata)

    if kbbi:
        penjelasan = await jelaskan_makna(kbbi["judul"], kbbi["makna"])
        return {
            "judul": kbbi["judul"],
            "makna": penjelasan or kbbi["makna"],
            "sumber": (
                f"{SUMBER_KBBI} — {kbbi['judul']}, dirapikan {SUMBER_AI}"
                if penjelasan
                else f"{SUMBER_KBBI} — {kbbi['judul']}"
            ),
        }

    # Tidak ada di KBBI — AI menjelaskan sendiri, dan sumbernya ditandai jelas.
    penjelasan = await jelaskan_makna(kata, None)
    if not penjelasan:
        return None
    return {"judul": kata, "makna": penjelasan, "sumber": SUMBER_AI}
