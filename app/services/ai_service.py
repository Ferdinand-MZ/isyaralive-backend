import json

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
    "tanpa awalan seperti 'Hasil:' atau 'Berikut adalah', dan tanpa penjelasan tambahan. "
    "Jangan gunakan format Markdown apa pun (tanpa **tebal**, *miring*, heading '#', bullet "
    "'-'/'*', atau blok kode) — outputnya dibaca sebagai teks polos dan bisa langsung "
    "di-TTS-kan, jadi simbol markdown akan terbaca/terdengar apa adanya."
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
    "2. Kalau pengguna bertanya arti/cara isyarat suatu kata, sistem menyisipkan "
    "'KONTEKS KAMUS' yang memuat TIGA baris: KATA YANG DITANYAKAN, PERAGA ISYARAT BISINDO, "
    "dan ARTI KATA. Pakai itu sebagai sumber utama dan jangan menyatakan hal yang "
    "bertentangan dengannya.\n"
    "3. WAJIB DIBEDAKAN — 'peraga isyaratnya belum ada di kamus' TIDAK sama dengan "
    "'katanya tidak punya arti'. Kalau peraga isyaratnya belum ada, tetap JELASKAN dulu "
    "arti katanya dengan lengkap, baru sebutkan bahwa peraga isyaratnya belum tersedia "
    "dan bisa dieja per huruf. Jangan pernah menjawab sekadar 'kata itu belum ada'.\n"
    "4. Kalau baris ARTI KATA menyatakan tidak tersedia, jelaskan arti kata itu dari "
    "pengetahuan Anda sendiri — singkat, akurat, dan jujur bila Anda tidak yakin.\n"
    "5. Sebut katanya PERSIS seperti pada baris KATA YANG DITANYAKAN. Jangan menambahkan "
    "kata 'Kata' di depannya seolah itu bagian dari namanya: tulis Keju, bukan 'Kata Keju'. "
    "Jangan pula mengubah, memperluas, atau menebak kata lain yang tidak ditanyakan.\n"
    "6. Jawab singkat, jelas, ramah, dan dalam Bahasa Indonesia.\n"
    "7. Kalau relevan, di akhir jawaban Anda boleh menyarankan 2-3 pertanyaan/kata lanjutan "
    "yang mungkin ingin ditanyakan pengguna, tapi ini opsional dan tidak wajib.\n\n"
    "PENTING: Jangan gunakan format Markdown apa pun (tanpa **tebal**, *miring*, heading '#', "
    "bullet '-'/'*', maupun blok kode ```). Jawab dengan teks polos saja — kalau perlu daftar, "
    "tulis sebagai kalimat biasa atau penomoran '1. 2. 3.' tanpa simbol markdown lain, karena "
    "jawaban ini ditampilkan apa adanya di chat dan bisa juga di-TTS-kan."
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

# ============================================================
# SARAN KATA LANJUTAN (SmartSign AI - prediksi saat jeda gestur)
#
# Saat pengguna berhenti sejenak di tengah percakapan, sistem menawarkan
# 3 kata berikutnya yang paling masuk akal berdasarkan transkrip sementara.
# Pengguna tinggal menekan salah satu, tidak perlu memperagakan gestur —
# komunikasi jadi lebih cepat.
#
# PENTING: saran DIBATASI pada kosakata yang memang bisa diperagakan /
# dikenali sistem (daftar kelas model + kamus SignPedia). Percuma
# menyarankan kata yang tidak punya peraga gestur.
# ============================================================

SARAN_SYSTEM_PROMPT = (
    "Anda membantu pengguna Bahasa Isyarat Indonesia (BISINDO) menyusun kalimat lebih cepat.\n"
    "Anda menerima transkrip sementara hasil deteksi gestur (mungkin belum selesai) "
    "dan sebuah DAFTAR KOSAKATA yang tersedia di sistem.\n\n"
    "Tugas Anda: tebak 3 kata BERIKUTNYA yang paling mungkin ingin disampaikan pengguna.\n\n"
    "Aturan wajib:\n"
    "1. Semua kata yang Anda usulkan HARUS diambil persis dari DAFTAR KOSAKATA. "
    "Dilarang mengarang kata di luar daftar.\n"
    "2. Jangan mengulang kata yang baru saja disebut kecuali memang wajar diulang.\n"
    "3. Urutkan dari yang paling mungkin.\n"
    "4. Jawab HANYA dengan array JSON berisi 3 string, tanpa penjelasan, tanpa markdown. "
    'Contoh format jawaban: ["Makan", "Minum", "Terima Kasih"]'
)


async def saran_kata_lanjutan(transkrip: str, kosakata: list[str], jumlah: int = 3) -> list[str]:
    """
    transkrip : kata-kata yang sudah terdeteksi sejauh ini, mis. "Halo nama saya"
    kosakata  : daftar kata yang tersedia (kelas model + kamus)
    Return    : list kata saran, sudah difilter agar pasti ada di `kosakata`.
    """
    if not AZURE_OPENAI_KEY or not AZURE_OPENAI_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Konfigurasi Azure OpenAI belum di-set (AZURE_OPENAI_KEY / AZURE_OPENAI_URL)."
        )

    if not kosakata:
        return []

    user_content = (
        f"DAFTAR KOSAKATA:\n{', '.join(kosakata)}\n\n"
        f"TRANSKRIP SEMENTARA:\n{transkrip.strip() or '(belum ada kata)'}"
    )

    payload = {
        "model": AZURE_OPENAI_MODEL,
        "max_completion_tokens": 120,
        "messages": [
            {"role": "system", "content": SARAN_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                AZURE_OPENAI_URL,
                headers={"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.RequestError:
        # Saran bersifat pelengkap — jangan sampai bikin fitur utama gagal
        return []

    if response.status_code != 200:
        return []

    data = response.json()
    try:
        raw = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return []

    # Bersihkan kemungkinan pagar markdown
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []

    # Cocokkan ke kosakata resmi (case-insensitive), buang duplikat
    lookup = {k.lower(): k for k in kosakata}
    hasil = []
    for item in parsed:
        if not isinstance(item, str):
            continue
        kata = lookup.get(item.strip().lower())
        if kata and kata not in hasil:
            hasil.append(kata)

    return hasil[:jumlah]

# ============================================================
# PENJELASAN MAKNA KATA (dipakai makna_service)
#
# KBBI memberi definisi yang benar tapi ditulis dengan gaya kamus: singkatan
# kelas kata, tanda titik koma bertingkat, contoh kalimat lama. Untuk layar
# "Makna Kata" dan balasan chat, definisi itu dirapikan dulu oleh AI menjadi
# kalimat yang enak dibaca — TANPA menambah fakta di luar KBBI.
#
# Kalau KBBI tidak punya katanya (nama diri, merek, istilah asing), AI yang
# menjelaskan dari pengetahuannya sendiri, dan pemanggil menandai sumbernya
# berbeda supaya pengguna tidak dibuat mengira itu kutipan KBBI.
# ============================================================

MAKNA_SYSTEM_PROMPT = (
    "Anda menulis penjelasan arti kata untuk aplikasi IsyaraLive, dibaca pengguna umum "
    "termasuk pelajar dan Teman Tuli.\n\n"
    "Anda diberi KATA dan DEFINISI KBBI-nya. Tugas Anda menuliskan ulang definisi itu "
    "menjadi penjelasan yang mudah dipahami.\n\n"
    "Aturan:\n"
    "1. HANYA gunakan informasi dari definisi KBBI yang diberikan. Dilarang menambah "
    "fakta, sejarah, contoh, atau kaitan yang tidak ada di situ.\n"
    "2. Kalau KBBI mencantumkan beberapa makna, sebutkan yang paling umum lebih dulu, "
    "lalu makna lain secara singkat. Makna yang jarang dipakai boleh dilewati.\n"
    "3. Panjang 2-4 kalimat. Bahasa Indonesia sederhana, tanpa singkatan kelas kata "
    "(jangan tulis 'n', 'v', 'a', 'pron'), tanpa lafal, tanpa nomor makna KBBI.\n"
    "4. Jangan mengubah maknanya dan jangan menebak kalau definisinya tidak jelas.\n"
    "5. Jawab langsung isi penjelasannya saja — tanpa kalimat pembuka seperti 'Menurut "
    "KBBI' atau 'Berikut penjelasannya', tanpa tanda kutip, tanpa format Markdown."
)

MAKNA_TANPA_KBBI_SYSTEM_PROMPT = (
    "Anda menulis penjelasan arti kata untuk aplikasi IsyaraLive, dibaca pengguna umum "
    "termasuk pelajar dan Teman Tuli.\n\n"
    "Kata yang diberikan TIDAK ADA di KBBI (biasanya nama diri, merek, atau istilah "
    "asing). Jelaskan artinya dari pengetahuan Anda sendiri.\n\n"
    "Aturan:\n"
    "1. Panjang 2-3 kalimat, Bahasa Indonesia sederhana.\n"
    "2. Jujur: kalau Anda tidak yakin kata itu berarti apa, katakan bahwa artinya tidak "
    "pasti — jangan mengarang.\n"
    "3. Jawab langsung isi penjelasannya saja — tanpa kalimat pembuka, tanpa tanda "
    "kutip, tanpa format Markdown."
)


async def jelaskan_makna(kata: str, makna_kbbi: str | None) -> str | None:
    """
    Rapikan definisi KBBI jadi penjelasan yang enak dibaca (atau jelaskan sendiri
    kalau KBBI tidak punya katanya).

    Return None kalau AI tidak bisa dipakai — Azure belum dikonfigurasi, jaringan
    gagal, jawabannya kosong. SENGAJA tidak melempar exception: pemanggilnya
    adalah alur kamus & chat yang wajib tetap jalan, dan definisi KBBI mentah
    masih jauh lebih baik daripada layar kosong.
    """
    kata = (kata or "").strip()
    if not kata:
        return None
    if not AZURE_OPENAI_KEY or not AZURE_OPENAI_URL:
        return None

    if makna_kbbi:
        system = MAKNA_SYSTEM_PROMPT
        isi = f"KATA: {kata}\n\nDEFINISI KBBI:\n{makna_kbbi.strip()}"
    else:
        system = MAKNA_TANPA_KBBI_SYSTEM_PROMPT
        isi = f"KATA: {kata}"

    payload = {
        "model": AZURE_OPENAI_MODEL,
        "max_completion_tokens": 400,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": isi},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                AZURE_OPENAI_URL,
                headers={"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code != 200:
            return None
        data = response.json()
        hasil = (data["choices"][0]["message"]["content"] or "").strip().strip('"')
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
        return None

    return hasil or None
