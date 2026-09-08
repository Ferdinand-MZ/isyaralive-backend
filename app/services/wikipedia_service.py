"""
Sumber MAKNA + FOTO untuk kata yang ditanyakan pengguna.

Kenapa perlu: kolom `meaning` dan `illustration_path` di tabel kamus
(DictionaryEntry) saat ini KOSONG untuk semua entri — kamus kita cuma punya
video peraga. Padahal pengguna bertanya "apa makna keju?" dan berharap dapat
penjelasan + foto benda yang dimaksud, bukan sekadar peraga gestur.

Wikipedia Bahasa Indonesia dipakai karena:
  - REST API publik, TANPA API key (tidak menambah rahasia yang perlu diurus),
  - punya ringkasan singkat (`extract`) yang pas untuk satu paragraf jawaban,
  - punya thumbnail foto yang URL-nya bisa langsung dipakai Flutter
    (mediaUrl() meneruskan URL http/https apa adanya).

PRINSIP: layanan ini SELALU boleh gagal. Tidak ada internet, Wikipedia lambat,
kata tidak ada — semuanya mengembalikan None, dan pemanggil tetap jalan (AI
menjawab dari pengetahuannya sendiri). Fitur chat TIDAK BOLEH ikut mati cuma
karena pelengkap ini bermasalah.
"""

import asyncio
from typing import Optional
from urllib.parse import quote

import httpx

WIKI_SUMMARY_URL = "https://id.wikipedia.org/api/rest_v1/page/summary/{judul}"
WIKI_SEARCH_URL = "https://id.wikipedia.org/w/api.php"

# Wikimedia mewajibkan User-Agent yang mengidentifikasi aplikasi pemanggil.
# Tanpa ini permintaan bisa ditolak (403).
USER_AGENT = "IsyaraLive/2.1 (https://github.com/isyaralive; kontak: tim IsyaraLive)"

TIMEOUT_DETIK = 8.0

# Cache proses (bukan DB): kata -> hasil. Pertanyaan yang sama sering diulang
# dalam satu sesi demo, dan Wikipedia tidak perlu ditanya dua kali.
# Sengaja sederhana: dibatasi jumlahnya supaya tidak tumbuh tanpa batas.
#
# ⚠️ HANYA hasil BERHASIL yang disimpan. Kegagalan sengaja TIDAK di-cache:
# penyebabnya sering sementara (jaringan putus sesaat, Wikipedia lambat), dan
# kalau ikut disimpan maka satu kegagalan singkat membuat kata itu kehilangan
# makna & fotonya SELAMANYA sampai server di-restart — persis gejala "kadang
# muncul, kadang tidak" yang paling membingungkan untuk dilacak.
_cache: dict[str, dict] = {}
_CACHE_MAKS = 500


def _simpan_cache(kunci: str, nilai: Optional[dict]) -> None:
    if nilai is None:
        return
    if len(_cache) >= _CACHE_MAKS:
        _cache.clear()
    _cache[kunci] = nilai


def _dari_summary(data: dict) -> Optional[dict]:
    """
    Ubah balasan endpoint summary jadi bentuk internal kita.

    Halaman bertipe 'disambiguation' SENGAJA ditolak: isinya cuma daftar
    "X dapat merujuk pada ..." yang tidak menjelaskan apa pun, dan lebih
    menyesatkan daripada membiarkan AI menjawab dari pengetahuannya sendiri
    (mis. 'Halo' dan 'Terima Kasih' kena kasus ini).
    """
    if data.get("type") == "disambiguation":
        return None

    makna = (data.get("extract") or "").strip()
    if not makna:
        return None

    foto = (data.get("thumbnail") or {}).get("source") or None
    judul = data.get("title") or ""

    return {
        "judul": judul,
        "makna": makna,
        "foto_url": foto,
        "sumber": f"Wikipedia Bahasa Indonesia — {judul}" if judul else "Wikipedia Bahasa Indonesia",
    }


async def _summary(client: httpx.AsyncClient, judul: str) -> Optional[dict]:
    try:
        r = await client.get(WIKI_SUMMARY_URL.format(judul=quote(judul, safe="")))
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        return _dari_summary(r.json())
    except ValueError:
        return None


async def _judul_teratas_dari_pencarian(client: httpx.AsyncClient, kata: str) -> Optional[str]:
    """
    Cari judul artikel yang paling cocok saat tebakan langsung gagal.

    Contoh: pengguna menulis "sepeda motor listrik" yang bukan judul artikel
    persis; pencarian mengembalikan judul yang benar-benar ada.
    """
    params = {
        "action": "query",
        "list": "search",
        "srsearch": kata,
        "srlimit": 1,
        "format": "json",
    }
    try:
        r = await client.get(WIKI_SEARCH_URL, params=params)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        hasil = r.json().get("query", {}).get("search", [])
    except ValueError:
        return None
    return hasil[0]["title"] if hasil else None


async def cari_ringkasan(kata: str) -> Optional[dict]:
    """
    Ambil makna + foto untuk `kata`.

    Return dict {"judul", "makna", "foto_url", "sumber"} atau None kalau tidak
    ketemu / gagal. TIDAK PERNAH melempar exception — pemanggilnya adalah alur
    chat yang wajib tetap jalan.
    """
    kunci = kata.strip().lower()
    if not kunci:
        return None

    tersimpan = _cache.get(kunci)
    if tersimpan is not None:
        return tersimpan

    hasil = None
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_DETIK,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            # 1) Tebak langsung: judul artikel sering sama dengan katanya.
            hasil = await _summary(client, kata.strip())

            # 2) Kalau meleset (404 / disambiguasi), baru pakai pencarian.
            if hasil is None:
                judul = await _judul_teratas_dari_pencarian(client, kata.strip())
                if judul:
                    hasil = await _summary(client, judul)
    except (httpx.HTTPError, asyncio.TimeoutError, OSError):
        # Offline / DNS gagal / timeout — bukan alasan untuk menggagalkan chat.
        hasil = None

    _simpan_cache(kunci, hasil)
    return hasil
