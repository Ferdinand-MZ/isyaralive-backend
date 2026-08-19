"""
GENERATOR CSV KAMUS SignPedia
=============================
Membuat kerangka seed_data/dictionary.csv langsung dari 50 kelas yang
dikenali model, lalu mencocokkannya dengan video yang ADA di folder video.

Kenapa dibuat otomatis:
- Kamus sebaiknya memuat tepat kosakata yang bisa dideteksi model, supaya
  kata yang muncul di hasil terjemahan pasti punya halaman kamusnya.
- Pencocokan nama file dibuat toleran (huruf besar/kecil, spasi vs underscore,
  beberapa ekstensi), jadi kalian tidak perlu me-rename video satu per satu.

Cara pakai:
    # lihat kata mana yang videonya sudah ada dan mana yang belum
    python scripts/make_dictionary_csv.py --video-dir assets/dictionary --check

    # tulis CSV-nya
    python scripts/make_dictionary_csv.py --video-dir assets/dictionary \\
        --out seed_data/dictionary.csv

    # ikutkan juga kata yang videonya belum ada (kolom video_file dikosongkan)
    python scripts/make_dictionary_csv.py --video-dir assets/dictionary \\
        --out seed_data/dictionary.csv --include-missing

Setelah CSV jadi, ISI MANUAL kolom cara_isyarat dan meaning, lalu jalankan:
    python scripts/seed_dictionary.py --csv seed_data/dictionary.csv \\
        --video-dir assets/dictionary --illustration-dir assets/illustrations

CATATAN PENTING soal kolom cara_isyarat:
Script ini sengaja MENGOSONGKAN deskripsi cara memperagakan gestur. Deskripsi
gerakan BISINDO harus ditulis/diverifikasi oleh penutur atau komunitas
(mis. Gerkatin), bukan dikarang. Deskripsi yang salah di aplikasi kamus
lebih berbahaya daripada kolom yang kosong.
"""

import argparse
import csv
import os
import pickle
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EKSTENSI_VIDEO = (".mp4", ".mov", ".webm", ".m4v", ".mkv")

# Pengelompokan kategori. Kata di luar daftar 'sehari-hari' masuk 'umum'.
KATEGORI_SEHARI_HARI = {
    "halo", "selamat", "pagi", "siang", "malam", "hari ini",
    "terima kasih", "nama", "saya", "kamu", "dia", "kami", "kita",
    "kalian", "mereka", "anak", "ayah", "ibu", "keluarga", "teman",
    "makan", "minum", "tidur", "mandi", "duduk", "berdiri", "sekian",
}


def normalisasi(teks: str) -> str:
    """'Terima Kasih' / 'terima_kasih' / 'TerimaKasih' -> 'terimakasih'"""
    return re.sub(r"[^a-z0-9]", "", teks.lower())


def index_video(video_dir: str) -> dict:
    """Peta nama ternormalisasi -> nama file asli."""
    hasil = {}
    if not os.path.isdir(video_dir):
        return hasil
    for filename in os.listdir(video_dir):
        stem, ext = os.path.splitext(filename)
        if ext.lower() in EKSTENSI_VIDEO:
            hasil[normalisasi(stem)] = filename
    return hasil


def ambil_kosakata(encoder_path: str) -> list:
    if not os.path.isfile(encoder_path):
        print(f"label_encoder.pkl tidak ditemukan di {encoder_path}")
        sys.exit(1)
    with open(encoder_path, "rb") as f:
        le = pickle.load(f)
    return [str(c) for c in le.classes_]


def run(args):
    kosakata = ambil_kosakata(args.encoder)
    peta_video = index_video(args.video_dir)

    ada, belum = [], []
    for kata in kosakata:
        filename = peta_video.get(normalisasi(kata))
        (ada if filename else belum).append((kata, filename))

    print(f"Kosakata model      : {len(kosakata)}")
    print(f"Video sudah tersedia: {len(ada)}")
    print(f"Video belum ada     : {len(belum)}")

    if belum:
        print("\nBelum punya video peraga:")
        for kata, _ in belum:
            print(f"  - {kata}")

    # file video yang tidak dipakai kosakata mana pun
    terpakai = {normalisasi(k) for k, f in ada}
    nganggur = [f for n, f in peta_video.items() if n not in terpakai]
    if nganggur:
        print(f"\nVideo di folder tapi tidak cocok kosakata mana pun ({len(nganggur)}):")
        for f in sorted(nganggur):
            print(f"  - {f}")
        print("  (cek penamaannya, mis. 'terimakasih.mp4' untuk kata 'Terima Kasih')")

    if args.check:
        return

    baris = ada + (belum if args.include_missing else [])
    if not baris:
        print("\nTidak ada baris untuk ditulis. Isi dulu video di folder tersebut, "
              "atau pakai --include-missing.")
        return

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "word", "category", "video_file", "cara_isyarat",
            "illustration_file", "meaning", "source", "related_words",
        ])
        for kata, filename in sorted(baris):
            kategori = "sehari-hari" if kata.lower() in KATEGORI_SEHARI_HARI else "umum"
            writer.writerow([kata, kategori, filename or "", "", "", "", "", ""])

    print(f"\nCSV ditulis ke {args.out} ({len(baris)} baris).")
    print("Langkah berikutnya: isi kolom cara_isyarat dan meaning, lalu jalankan seed_dictionary.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Buat kerangka CSV kamus dari kelas model")
    parser.add_argument("--video-dir", default="assets/dictionary", help="Folder video kamus")
    parser.add_argument("--out", default="seed_data/dictionary.csv", help="Path CSV keluaran")
    parser.add_argument("--encoder", default="models/label_encoder.pkl", help="Path label encoder")
    parser.add_argument("--check", action="store_true", help="Hanya laporkan, jangan tulis CSV")
    parser.add_argument("--include-missing", action="store_true",
                        help="Ikutkan kata yang videonya belum ada")
    args = parser.parse_args()

    run(args)