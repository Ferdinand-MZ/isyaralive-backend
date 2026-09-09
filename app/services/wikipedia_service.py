"""
Sumber FOTO pelengkap untuk kata yang ditanyakan pengguna.

Makna kata TIDAK lagi diambil dari sini — itu tugas `kbbi_service` (KBBI adalah
rujukan resmi arti kata Bahasa Indonesia, dan kata sehari-hari seperti "halo"
justru jatuh ke halaman disambiguasi di Wikipedia). Yang tersisa di sini hanya
satu hal yang tidak bisa diberikan KBBI: FOTO benda/konsep yang dimaksud, untuk
kolom `illustration_path`.

Wikipedia Bahasa Indonesia dipakai karena:
  - REST API publik, TANPA API key (tidak menambah rahasia yang perlu diurus),
  - thumbnail-nya punya URL yang bisa langsung dipakai Flutter
    (mediaUrl() meneruskan URL http/https apa adanya).

PRINSIP: layanan ini SELALU boleh gagal. Tidak ada internet, Wikipedia lambat,
kata tidak ada — semuanya mengembalikan None. Foto sifatnya pelengkap: tanpa
foto, makna dari KBBI tetap tampil.
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

# Cache proses (bukan DB): kata -> URL foto. Pertanyaan yang sama sering
# diulang dalam satu sesi demo, dan Wikipedia tidak perlu ditanya dua kali.
#
# ⚠️ HANYA hasil BERHASIL yang disimpan. Kegagalan sengaja TIDAK di-cache:
# penyebabnya sering sementara (jaringan putus sesaat, Wikipedia lambat), dan
# kalau ikut disimpan maka satu kegagalan singkat membuat kata itu kehilangan
# fotonya SELAMANYA sampai server di-restart — persis gejala "kadang muncul,
# kadang tidak" yang paling membingungkan untuk dilacak.
_cache: dict[str, str] = {}
_CACHE_MAKS = 500


def _simpan_cache(kunci: str, nilai: Optional[str]) -> None:
    if not nilai:
        return
    if len(_cache) >= _CACHE_MAKS:
        _cache.clear()
    _cache[kunci] = nilai


def _foto_dari_summary(data: dict) -> Optional[str]:
    """
    Ambil URL thumbnail dari balasan endpoint summary.

    Halaman bertipe 'disambiguation' SENGAJA ditolak: fotonya (kalau ada) milik
    salah satu makna acak yang belum tentu yang dimaksud pengguna.
    """
    if data.get("type") == "disambiguation":
        return None
    return (data.get("thumbnail") or {}).get("source") or None


async def _summary(client: httpx.AsyncClient, judul: str) -> Optional[str]:
    try:
        r = await client.get(WIKI_SUMMARY_URL.format(judul=quote(judul, safe="")))
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        return _foto_dari_summary(r.json())
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


async def cari_foto(kata: str) -> Optional[str]:
    """
    Ambil URL foto untuk `kata`, atau None kalau tidak ada / gagal.

    TIDAK PERNAH melempar exception — pemanggilnya adalah alur chat yang wajib
    tetap jalan.
    """
    kunci = kata.strip().lower()
    if not kunci:
        return None

    tersimpan = _cache.get(kunci)
    if tersimpan is not None:
        return tersimpan

    foto = None
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_DETIK,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            # 1) Tebak langsung: judul artikel sering sama dengan katanya.
            foto = await _summary(client, kata.strip())

            # 2) Kalau meleset (404 / disambiguasi), baru pakai pencarian.
            if foto is None:
                judul = await _judul_teratas_dari_pencarian(client, kata.strip())
                if judul:
                    foto = await _summary(client, judul)
    except (httpx.HTTPError, asyncio.TimeoutError, OSError):
        # Offline / DNS gagal / timeout — bukan alasan untuk menggagalkan chat.
        foto = None

    _simpan_cache(kunci, foto)
    return foto
