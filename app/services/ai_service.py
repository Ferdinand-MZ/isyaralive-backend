import httpx
from fastapi import HTTPException, status

from app.core.config import AZURE_OPENAI_KEY, AZURE_OPENAI_URL, AZURE_OPENAI_MODEL

# ============================================================
# AI SERVICE - Perbaikan transkrip hasil deteksi gesture BISINDO
# Dipakai fitur "Analisis dengan AI" (Isyarat -> Teks)
#
# Transkrip mentah dari LSTM detector cuma berupa kumpulan kata/label
# tanpa tanda baca & struktur kalimat yang rapi, contoh:
#   "halo nama saya budi saya mau makan terima kasih"
# AI merapikannya jadi kalimat yang gramatikal & mudah dibaca/didengar (TTS).
# ============================================================

SYSTEM_PROMPT = (
    "Anda adalah asisten AI yang membantu merapikan hasil terjemahan bahasa isyarat "
    "BISINDO (Bahasa Isyarat Indonesia) menjadi kalimat Bahasa Indonesia yang baik dan benar.\n\n"
    "Transkrip yang Anda terima adalah rangkaian kata hasil deteksi gesture secara berurutan, "
    "biasanya TANPA tanda baca, tanpa imbuhan lengkap, dan tanpa kata hubung yang natural.\n\n"
    "Tugas Anda:\n"
    "1. Susun ulang kata-kata tersebut menjadi kalimat yang gramatikal dan mengalir secara natural, "
    "tanpa mengubah makna atau menambah informasi baru yang tidak ada di transkrip asli.\n"
    "2. Tambahkan tanda baca (titik, koma) dan kapitalisasi yang sesuai.\n"
    "3. Tambahkan imbuhan/kata hubung seperlunya HANYA jika membuat kalimat lebih jelas, "
    "jangan mengarang informasi baru.\n"
    "4. Gunakan Bahasa Indonesia formal namun tetap wajar untuk percakapan sehari-hari.\n"
    "5. Jangan menambahkan salam, komentar, atau penjelasan apa pun di luar kalimat hasil perbaikan.\n\n"
    "PENTING: Jawab HANYA dengan kalimat hasil perbaikan, tanpa heading, tanpa tanda kutip, "
    "tanpa awalan seperti 'Hasil:' atau 'Berikut adalah', dan tanpa penjelasan tambahan."
)


async def perbaiki_transkrip(transkrip_asli: str) -> str:
    """
    Kirim transkrip mentah ke Azure OpenAI, kembalikan kalimat yang sudah diperbaiki.
    """
    if not AZURE_OPENAI_KEY or not AZURE_OPENAI_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Konfigurasi Azure OpenAI belum di-set (AZURE_OPENAI_KEY / AZURE_OPENAI_URL)."
        )

    payload = {
        "model": AZURE_OPENAI_MODEL,
        "max_completion_tokens": 500,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transkrip_asli.strip()},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                AZURE_OPENAI_URL,
                headers={
                    "api-key": AZURE_OPENAI_KEY,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gagal menghubungi layanan AI: {e}"
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Layanan AI tidak dapat dihubungi. Kode: {response.status_code}"
        )

    data = response.json()
    try:
        hasil = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        hasil = ""

    hasil = hasil.strip().strip('"')

    if not hasil:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI tidak menghasilkan output. Silakan coba lagi."
        )

    return hasil


# ============================================================
# AI CHATBOT - "Asisten IsyaraLive" (SmartSign AI)
# Chatbot berbasis LLM yang menjawab pertanyaan seputar BISINDO,
# bisa dari teks atau video gestur (glosses hasil deteksi SignBridge),
# terintegrasi dengan kamus SignPedia untuk pencarian kosakata.
# ============================================================

CHATBOT_SYSTEM_PROMPT = (
    "Anda adalah Asisten AI IsyaraLive, chatbot yang membantu pengguna belajar dan "
    "berkomunikasi dengan Bahasa Isyarat Indonesia (BISINDO).\n\n"
    "Kemampuan Anda:\n"
    "1. Menjawab pertanyaan seputar BISINDO, gestur, dan penggunaan aplikasi IsyaraLive.\n"
    "2. Kalau pengguna bertanya arti/cara isyarat suatu kata dan sistem memberikan "
    "'KONTEKS KAMUS' di bawah, gunakan informasi itu sebagai sumber utama jawaban Anda "
    "dan jangan mengarang informasi yang bertentangan dengannya.\n"
    "3. Kalau kata yang ditanyakan TIDAK ada di 'KONTEKS KAMUS' (ditandai 'tidak ditemukan'), "
    "beri tahu pengguna kata tersebut belum ada di kamus dan sarankan gunakan ejaan alfabet.\n"
    "4. Jawab singkat, jelas, ramah, dan dalam Bahasa Indonesia.\n"
    "5. Kalau relevan, di akhir jawaban Anda boleh menyarankan 2-3 pertanyaan/kata lanjutan "
    "yang mungkin ingin ditanyakan pengguna, tapi ini opsional dan tidak wajib."
)


async def chatbot_reply(history: list[dict], user_message: str, dictionary_context: str | None = None) -> str:
    """
    history: list of {"role": "user"|"assistant", "content": "..."}, urutan lama -> baru
    dictionary_context: hasil lookup SignPedia (kalau ada), disisipkan sebagai info tambahan
    """
    if not AZURE_OPENAI_KEY or not AZURE_OPENAI_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Konfigurasi Azure OpenAI belum di-set (AZURE_OPENAI_KEY / AZURE_OPENAI_URL)."
        )

    messages = [{"role": "system", "content": CHATBOT_SYSTEM_PROMPT}]
    # sertakan riwayat percakapan sebagai konteks (dibatasi biar hemat token)
    messages.extend(history[-10:])

    user_content = user_message
    if dictionary_context:
        user_content = f"KONTEKS KAMUS:\n{dictionary_context}\n\nPERTANYAAN PENGGUNA:\n{user_message}"

    messages.append({"role": "user", "content": user_content})

    payload = {
        "model": AZURE_OPENAI_MODEL,
        "max_completion_tokens": 600,
        "messages": messages,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                AZURE_OPENAI_URL,
                headers={"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.RequestError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Gagal menghubungi layanan AI: {e}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Layanan AI tidak dapat dihubungi. Kode: {response.status_code}"
        )

    data = response.json()
    try:
        reply = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        reply = ""

    if not reply:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI tidak menghasilkan balasan. Coba lagi.")

    return reply