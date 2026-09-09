"""
Sumber MAKNA kata untuk pertanyaan pengguna — KBBI (Kamus Besar Bahasa Indonesia).

Kenapa perlu: kolom `meaning` di tabel kamus (DictionaryEntry) masih KOSONG
untuk hampir semua entri — kamus kita cuma punya video peraga. Padahal pengguna
bertanya "apa makna keju?" dan berharap dapat penjelasan, bukan sekadar peraga.

Kenapa KBBI dan bukan ensiklopedia umum:
  - KBBI adalah rujukan RESMI makna kata Bahasa Indonesia; yang ditanyakan
    pengguna memang ARTI KATA, bukan artikel ensiklopedis,
  - jawabannya singkat dan berbentuk definisi (pas untuk satu balasan chat),
  - kata sehari-hari seperti "halo" dan "terima kasih" punya entri yang jelas —
    di ensiklopedia kata-kata itu justru jatuh ke halaman disambiguasi yang
    tidak menjelaskan apa pun.

Kenapa kbbi.web.id dan bukan laman resmi Kemendikdasmen: laman resmi
(kbbi.kemendikdasmen.go.id) sejak "moda terbatas" diaktifkan MENOLAK semua
permintaan dari pengguna yang tidak login — tidak ada API publik tanpa akun.
kbbi.web.id menyajikan isi KBBI yang sama secara terbuka, tanpa API key.

Yang dipakai di sini adalah endpoint JSON yang dipanggil laman itu sendiri
(`/<kata>/ajax_<acak>`), bukan HTML-nya. Bedanya penting: pencariannya
menemukan kata BERIMBUHAN di dalam entri kata dasarnya — "berdiri" ada di entri
"diri²", "menulis" di "tulis" — sesuatu yang tidak bisa didapat dengan menebak
kata dasar sendiri. Isi definisinya sendiri tetap berupa potongan HTML, jadi
tetap ada parser di bawah; parser itu sengaja defensif: begitu strukturnya
berubah, hasilnya None (bukan teks sampah), dan pemanggil tetap jalan.

PRINSIP: layanan ini SELALU boleh gagal. Tidak ada internet, laman lambat, kata
tidak ada di KBBI (nama diri, merek, istilah asing) — semuanya mengembalikan
None, dan pemanggil tetap jalan (AI menjawab dari pengetahuannya sendiri).
Fitur chat TIDAK BOLEH ikut mati cuma karena pelengkap ini bermasalah.
"""

import asyncio
import html
import json
import random
import re
import string
import time
from typing import Optional
from urllib.parse import quote

import httpx

from app.services.wikipedia_service import cari_foto

# Endpoint JSON milik laman kbbi.web.id. Akhiran acak ditiru dari lamannya
# (dipakai untuk menembus cache di sisi mereka).
KBBI_URL = "https://kbbi.web.id/{kata}/ajax_{acak}"

# Beberapa laman menolak klien tanpa User-Agent yang wajar.
USER_AGENT = "IsyaraLive/2.1 (https://github.com/isyaralive; kontak: tim IsyaraLive)"

TIMEOUT_DETIK = 8.0

# Jeda minimal antar-permintaan ke KBBI, dijaga untuk SELURUH proses.
# kbbi.web.id bukan API publik berkuota; menembakinya beruntun tidak sopan dan
# berisiko diputus. Beberapa pengguna chat yang bertanya bersamaan karena itu
# diantre, bukan diparalelkan.
JEDA_DETIK = 0.5
_gerbang = asyncio.Lock()
_permintaan_terakhir = 0.0

# Pencarian KBBI menolak kata sepanjang satu huruf.
MIN_PANJANG = 2

# Batas panjang makna yang disimpan. Entri seperti "makan" punya belasan makna
# dengan contoh kalimat; kalau semuanya ikut, balasan chat jadi tembok teks.
# Pemotongan dilakukan PER MAKNA (bukan per karakter) supaya tidak pernah
# berhenti di tengah kalimat.
MAKS_MAKNA = 600

# Cache proses (bukan DB): kata -> hasil. Pertanyaan yang sama sering diulang
# dalam satu sesi demo, dan KBBI tidak perlu ditanya dua kali.
#
# ⚠️ HANYA hasil BERHASIL yang disimpan. Kegagalan jaringan sengaja TIDAK
# di-cache: penyebabnya sering sementara (jaringan putus sesaat, laman lambat),
# dan kalau ikut disimpan maka satu kegagalan singkat membuat kata itu
# kehilangan maknanya SELAMANYA sampai server di-restart — persis gejala
# "kadang muncul, kadang tidak" yang paling membingungkan untuk dilacak.
_cache: dict[str, dict] = {}
_CACHE_MAKS = 500

# Kata yang KBBI sendiri bilang tidak ada (nama diri, merek, istilah asing).
# Ini BEDA dengan kegagalan jaringan dan aman diingat: jawabannya tidak akan
# berubah dalam satu sesi, dan tanpa ini setiap pertanyaan berulang soal kata
# yang sama menembak KBBI lagi.
_cache_kosong: set[str] = set()

# Dijawab KBBI, tapi katanya memang bukan lema. Dibedakan dari None (gagal
# jaringan / struktur berubah) supaya cuma yang ini yang diingat.
_TIDAK_ADA = object()

# Satu entri KBBI berisi kata dasar plus lema turunannya, dipisah <br/>.
_POLA_PISAH_LEMA = re.compile(r"<br\s*/?>", re.I)
_POLA_LEMA = re.compile(r"\s*<b>(.*?)</b>", re.S)
_POLA_NOMOR_MAKNA = re.compile(r"<b>\s*(\d+)\s*</b>")
_POLA_TAG = re.compile(r"<[^>]+>")

# Dipakai untuk menguji "apakah potongan ini cuma label, bukan makna": kelas
# kata (<em>n</em>), lafal (/kéju/), dan tag apa pun dibuang — kalau tidak ada
# sisa teks, berarti memang label.
_POLA_PROSA = re.compile(r"<em>.*?</em>|/[^/<]{1,40}/|<[^>]+>|&#?\w+;", re.S)

# Peribahasa (ditandai ", pb") menempel di akhir entri tanpa pemisah, mis.
# "rumah gedang ketirisan, pb istri yang tidak mampu ...". Itu bukan makna
# katanya dan cuma membuat jawaban chat melantur, jadi dipotong.
_POLA_PERIBAHASA = re.compile(r"<em>[^<]{0,200},\s*pb\s*</em>", re.I)

# Batas akhir sebuah makna: <b> berikutnya yang BUKAN nomor makna. Itu selalu
# awal entri lain — lema kedua yang menumpang di blok yang sama
# ("li·hat v, me·li·hat v ..."), atau sublema gabungan ("~ angin", "-- adat").
_POLA_LEMA_LAIN = re.compile(r"<b>(?!\s*\d+\s*</b>)")

_PENANDA_MAKNA = "\x00"  # penanda internal batas antar-makna saat parsing


def _simpan_cache(kunci: str, nilai: Optional[dict]) -> None:
    if nilai is None:
        return
    if len(_cache) >= _CACHE_MAKS:
        _cache.clear()
    _cache[kunci] = nilai


def _teks(fragmen: str) -> str:
    """HTML -> teks polos. Titik tengah (ke·ju) dibuang: itu pemenggal suku
    kata, bukan bagian dari tulisan katanya."""
    teks = _POLA_TAG.sub("", fragmen)
    teks = html.unescape(teks)
    teks = teks.replace("·", "")
    return re.sub(r"\s+", " ", teks).strip()


def _normal(kata: str) -> str:
    """Bentuk banding: tanpa huruf besar/kecil, tanpa pemenggal suku kata."""
    return re.sub(r"\s+", " ", _teks(kata).lower()).strip()


def _potong_lema(fragmen: str, kata: str) -> Optional[str]:
    """
    Ambil bagian entri yang benar-benar mendefinisikan `kata`.

    Satu entri KBBI memuat banyak lema: kata dasarnya, lema turunan yang
    dipisah <br/> ("me·nu·lis" di entri "tulis"), dan lema kedua yang menumpang
    di blok yang sama ("li·hat v, me·li·hat v ..."). Yang dicari bisa berada di
    mana saja, jadi setiap <b> diperiksa dan potongan dimulai tepat di lema
    yang cocok.

    None kalau lema yang ditanyakan tidak ada di entri ini.
    """
    target = _normal(kata)
    for blok in _POLA_PISAH_LEMA.split(fragmen):
        for lema in re.finditer(r"<b>(.*?)</b>", blok, re.S):
            if _normal(re.sub(r"<sup>.*?</sup>", "", lema.group(1))) == target:
                return blok[lema.start():]
    return None


def _potong_wajar(makna_list: list[str]) -> str:
    """
    Ambil makna sebanyak yang muat di MAKS_MAKNA, minimal satu.

    Makna pertama selalu ikut walau panjang — lebih baik satu definisi utuh
    daripada tidak ada penjelasan sama sekali.
    """
    if not makna_list:
        return ""
    dipakai = [makna_list[0]]
    panjang = len(makna_list[0])
    for m in makna_list[1:]:
        if panjang + len(m) + 2 > MAKS_MAKNA:
            break
        dipakai.append(m)
        panjang += len(m) + 2
    if len(makna_list) == 1:
        return dipakai[0]
    return "; ".join(f"{i}. {m}" for i, m in enumerate(dipakai, start=1))


def _dari_entri(fragmen: str, kata: str) -> Optional[dict]:
    """
    Ubah potongan HTML definisi dari KBBI jadi bentuk internal kita.

    None kalau `kata` bukan lema di entri ini, atau strukturnya tidak dikenali.
    """
    blok = _potong_lema(fragmen, kata)
    if blok is None:
        return None

    lema = _POLA_LEMA.match(blok)
    if not lema:
        return None

    # "ma·kan<sup>1</sup>" -> "makan"; angka homonim dibuang, tidak berguna
    # untuk pengguna.
    judul = _teks(re.sub(r"<sup>.*?</sup>", "", lema.group(1)))
    sisa = blok[lema.end():]

    for pola in (_POLA_PERIBAHASA, _POLA_LEMA_LAIN):
        batas = pola.search(sisa)
        if batas:
            sisa = sisa[: batas.start()].rstrip(" ;:-–—")

    # Nomor makna (<b>2</b>, <b>3</b>, ...) jadi batas antar-makna. Makna
    # pertama memang tidak bernomor di KBBI.
    mentah = _POLA_NOMOR_MAKNA.sub(_PENANDA_MAKNA, sisa).split(_PENANDA_MAKNA)

    # Lafal (/kéju/) dan kelas kata (<em>n</em>) berdiri SEBELUM nomor "1",
    # jadi potongan pertama kadang berisi label itu saja — bukan makna. Kalau
    # dibiarkan, "halo" terbaca punya makna pertama berbunyi "p". Label itu
    # ditempelkan ke makna sesudahnya.
    awalan = ""
    if len(mentah) > 1 and not _POLA_PROSA.sub("", mentah[0]).strip(" ;:,.-"):
        awalan = _teks(mentah.pop(0)).strip(" ;:")

    potongan = [_teks(p).strip(" ;:") for p in mentah]
    potongan = [p for p in potongan if p]
    if not potongan:
        return None
    if awalan:
        potongan[0] = f"{awalan} {potongan[0]}"

    makna = _potong_wajar(potongan)

    # Di KBBI "--" (lema utama), "~" (lema turunan), dan kadang "-" berarti
    # "kata lemanya diulang di sini" — mis. "mereka -- tiga kali sehari". Di
    # luar konteks kamus itu tidak terbaca, jadi dikembalikan ke katanya.
    if judul:
        makna = re.sub(r"(?<=\s)(?:--|[-~–—])(?=\s)|(?<!\w)--(?!\w)|~", judul, makna)

    if not makna:
        return None

    return {
        "judul": judul,
        "makna": makna,
        "foto_url": None,
        "sumber": f"KBBI — {judul}",
    }


# Preposisi yang sering ditulis serangkai padahal di KBBI berdiri sendiri.
_PREPOSISI = ("di", "ke", "dari")


def _tanpa_preposisi(kata: str) -> Optional[str]:
    """
    Bagian kata yang bisa dicari di KBBI saat kata utuhnya bukan lema.

    "hari ini" -> "hari" (frasa: kata pertama yang dijelaskan),
    "dimana"   -> "mana" (baku "di mana", pengguna sering menulis serangkai).
    None kalau tidak ada yang bisa dicoba.
    """
    if " " in kata:
        return kata.split()[0]
    rendah = kata.lower()
    for prep in _PREPOSISI:
        if rendah.startswith(prep) and len(kata) - len(prep) >= 3:
            return kata[len(prep):]
    return None


async def _minta(client: httpx.AsyncClient, kata: str) -> httpx.Response:
    """Satu permintaan ke KBBI, diantre dan diberi jeda (lihat JEDA_DETIK)."""
    global _permintaan_terakhir
    acak = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    url = KBBI_URL.format(kata=quote(kata, safe=""), acak=acak)
    async with _gerbang:
        selisih = time.monotonic() - _permintaan_terakhir
        if selisih < JEDA_DETIK:
            await asyncio.sleep(JEDA_DETIK - selisih)
        try:
            return await client.get(url, headers={"X-Requested-With": "XMLHttpRequest"})
        finally:
            _permintaan_terakhir = time.monotonic()


async def _ambil(client: httpx.AsyncClient, kata: str):
    """
    Cari `kata` di KBBI.

    Return dict kalau ketemu, `_TIDAK_ADA` kalau KBBI menjawab tapi katanya
    bukan lema, None kalau gagal (jaringan / bentuk jawaban berubah).

    Pencarian KBBI mengembalikan SEMUA entri yang memuat kata itu, termasuk
    yang cuma menyinggungnya di contoh kalimat. Karena itu setiap entri masih
    diverifikasi: yang diambil hanya entri yang benar-benar punya lema `kata`.
    """
    if len(kata) < MIN_PANJANG:
        return _TIDAK_ADA
    try:
        r = await _minta(client, kata)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    try:
        entri = json.loads(r.text or "[]")
    except ValueError:
        return None
    if not isinstance(entri, list):
        return None

    target = _normal(kata)

    def _prioritas(e: dict) -> tuple:
        # Entri yang JUDULNYA memang kata itu didahulukan, lalu entri berjenis
        # "kata dasar" (x == 1). Tanpa ini "kamu" bisa terjawab dari entri
        # "-mu" yang kebetulan menyebut "kamu" di dalamnya.
        judul = _normal(re.sub(r"<sup>.*?</sup>", "", e.get("w") or ""))
        return (judul != target, e.get("x") != 1)

    for e in sorted((e for e in entri if isinstance(e, dict)), key=_prioritas):
        hasil = _dari_entri(e.get("d") or "", kata)
        if hasil:
            return hasil
    return _TIDAK_ADA


async def cari_ringkasan(kata: str) -> Optional[dict]:
    """
    Ambil makna (KBBI) + foto pelengkap untuk `kata`.

    Return dict {"judul", "makna", "foto_url", "sumber"} atau None kalau tidak
    ketemu / gagal. TIDAK PERNAH melempar exception — pemanggilnya adalah alur
    chat yang wajib tetap jalan.

    Fotonya bukan dari KBBI (KBBI kamus teks, tidak punya gambar) melainkan
    dari Wikimedia; sifatnya pelengkap — gagal ambil foto tidak membatalkan
    maknanya.
    """
    kunci = kata.strip().lower()
    if not kunci:
        return None

    tersimpan = _cache.get(kunci)
    if tersimpan is not None:
        return tersimpan
    if kunci in _cache_kosong:
        return None

    hasil = None
    pasti_kosong = False
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_DETIK,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            bersih = kata.strip()
            percobaan = [await _ambil(client, bersih)]

            # Cadangan: kata yang di KBBI sebenarnya dua kata. Frasa
            # ("hari ini") diwakili kata pertamanya; kata berpreposisi yang
            # ditulis serangkai ("dimana", yang baku "di mana") diwakili kata
            # sesudah preposisinya. `judul`/`sumber` tetap jujur menyebut kata
            # mana yang sebenarnya didefinisikan.
            if not isinstance(percobaan[-1], dict):
                sisa = _tanpa_preposisi(bersih)
                if sisa:
                    percobaan.append(await _ambil(client, sisa))

            if isinstance(percobaan[-1], dict):
                hasil = percobaan[-1]
            else:
                # Semua percobaan dijawab "bukan lema" (bukan gagal jaringan) —
                # baru boleh diingat sebagai kata yang memang tidak ada di KBBI.
                pasti_kosong = all(p is _TIDAK_ADA for p in percobaan)
    except (httpx.HTTPError, asyncio.TimeoutError, OSError):
        # Offline / DNS gagal / timeout — bukan alasan untuk menggagalkan chat.
        hasil = None

    if hasil is not None:
        foto = await cari_foto(hasil["judul"] or kata.strip())
        if foto:
            hasil["foto_url"] = foto
            hasil["sumber"] = f"{hasil['sumber']} · foto: Wikimedia"

    if hasil is None and pasti_kosong:
        _cache_kosong.add(kunci)

    _simpan_cache(kunci, hasil)
    return hasil
