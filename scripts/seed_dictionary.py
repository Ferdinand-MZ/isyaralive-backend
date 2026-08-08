"""
SEEDER: Kamus SignPedia (DictionaryEntry)
==========================================
Cara pakai:
1. Siapkan file CSV (contoh: seed_data/dictionary.csv) dengan kolom:
   word, category, video_file, cara_isyarat, illustration_file, meaning, source, related_words

   Contoh isi CSV:
   word,category,video_file,cara_isyarat,illustration_file,meaning,source,related_words
   Terima Kasih,sehari-hari,terima_kasih.mp4,"Letakkan ujung jari di dekat dagu...",,"Ucapan syukur atas bantuan orang lain.",,"Tolong,Sama-sama"
   Fotosintesis,umum,fotosintesis.mp4,"Peragakan gestur F-O-T-O...",fotosintesis.png,"Proses tumbuhan mengubah cahaya matahari...","Sumber: Wikipedia Commons","Klorofil,Oksigen,Tumbuhan,Glukosa"

   - category HARUS salah satu dari: sehari-hari, umum, emoji, angka
   - video_file & illustration_file cukup NAMA FILE saja (bukan path lengkap),
     script yang akan gabungkan dengan folder video/gambar di bawah.
   - related_words dipisah koma dalam SATU kolom (pakai tanda kutip kalau ada koma).

2. Taruh semua video kamus di satu folder, contoh: assets/dictionary/
   Taruh semua gambar ilustrasi di folder lain, contoh: assets/illustrations/

3. Jalankan:
   python scripts/seed_dictionary.py \
       --csv seed_data/dictionary.csv \
       --video-dir assets/dictionary \
       --illustration-dir assets/illustrations

Perilaku:
- Kalau 'word' SUDAH ADA di database -> di-UPDATE (bukan duplikat).
- Kalau video_file yang disebut di CSV TIDAK KETEMU di --video-dir -> baris itu
  di-skip dengan pesan warning (tidak bikin entry setengah jadi tanpa video).
- illustration_file boleh kosong (tidak wajib).
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, init_db
from app.models.dictionary import DictionaryEntry, DictionaryCategory


def run(csv_path: str, video_dir: str, illustration_dir: str):
    init_db()
    db = SessionLocal()

    created, updated, skipped = 0, 0, 0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = row.get("word", "").strip()
            if not word:
                continue

            video_file = row.get("video_file", "").strip()
            video_path = os.path.join(video_dir, video_file) if video_file else ""

            if not video_file or not os.path.isfile(video_path):
                print(f"[SKIP] '{word}' -> video '{video_file}' tidak ditemukan di {video_dir}")
                skipped += 1
                continue

            category_raw = row.get("category", "umum").strip()
            try:
                category = DictionaryCategory(category_raw)
            except ValueError:
                print(f"[SKIP] '{word}' -> category '{category_raw}' tidak valid "
                      f"(harus salah satu: {[c.value for c in DictionaryCategory]})")
                skipped += 1
                continue

            illustration_file = row.get("illustration_file", "").strip()
            illustration_path = None
            if illustration_file:
                full_illust = os.path.join(illustration_dir, illustration_file)
                if os.path.isfile(full_illust):
                    illustration_path = full_illust
                else:
                    print(f"[WARN] '{word}' -> ilustrasi '{illustration_file}' tidak ditemukan, dilewati (tetap lanjut tanpa ilustrasi)")

            entry = db.query(DictionaryEntry).filter(DictionaryEntry.word.ilike(word)).first()

            if entry:
                entry.category = category
                entry.video_path = video_path
                entry.cara_isyarat = row.get("cara_isyarat") or entry.cara_isyarat
                entry.illustration_path = illustration_path or entry.illustration_path
                entry.meaning = row.get("meaning") or entry.meaning
                entry.source = row.get("source") or entry.source
                entry.related_words = row.get("related_words") or entry.related_words
                updated += 1
            else:
                entry = DictionaryEntry(
                    word=word,
                    category=category,
                    video_path=video_path,
                    cara_isyarat=row.get("cara_isyarat") or None,
                    illustration_path=illustration_path,
                    meaning=row.get("meaning") or None,
                    source=row.get("source") or None,
                    related_words=row.get("related_words") or None,
                )
                db.add(entry)
                created += 1

    db.commit()
    db.close()

    print(f"\nSelesai. Dibuat: {created}, Diupdate: {updated}, Dilewati: {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed kamus SignPedia dari CSV + folder video")
    parser.add_argument("--csv", required=True, help="Path ke file CSV data kamus")
    parser.add_argument("--video-dir", required=True, help="Folder tempat video kamus disimpan")
    parser.add_argument("--illustration-dir", default="", help="Folder tempat gambar ilustrasi (opsional)")
    args = parser.parse_args()

    run(args.csv, args.video_dir, args.illustration_dir)