"""
SEEDER: Materi Pembelajaran SignPedia (LearningLevel + LearningMaterial)
==========================================================================
Cara pakai:
1. Siapkan file CSV (contoh: seed_data/learning.csv) dengan kolom:
   level_order, level_title, material_order, word, video_file, cara_isyarat

   Contoh isi CSV:
   level_order,level_title,material_order,word,video_file,cara_isyarat
   1,Sapaan Dasar,1,Selamat Pagi,pagi.mp4,"Angkat tangan setinggi bahu..."
   1,Sapaan Dasar,2,Halo,halo.mp4,
   1,Sapaan Dasar,3,Selamat Siang,siang.mp4,
   2,Keluarga,1,Ayah,ayah.mp4,
   2,Keluarga,2,Ibu,ibu.mp4,

   - level_order = angka urutan level (1, 2, 3, ...). Baris dengan level_order
     yang sama akan digabung jadi 1 level yang sama, judulnya diambil dari
     level_title baris pertama yang ditemui.
   - material_order = urutan kata di dalam level itu.
   - video_file cukup NAMA FILE (bukan path lengkap).

2. Taruh semua video materi di satu folder, contoh: assets/learning/

3. Jalankan:
   python scripts/seed_learning.py \
       --csv seed_data/learning.csv \
       --video-dir assets/learning

Perilaku:
- Kalau level_order SUDAH ADA -> title level di-update, materi baru ditambah/diupdate.
- Kalau word di level yang sama SUDAH ADA -> di-UPDATE (bukan duplikat).
- Kalau video_file tidak ketemu di --video-dir -> baris di-skip dengan warning.
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, init_db
from app.models.learning import LearningLevel, LearningMaterial


def run(csv_path: str, video_dir: str):
    init_db()
    db = SessionLocal()

    levels_created, levels_updated = 0, 0
    materials_created, materials_updated, skipped = 0, 0, 0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                level_order = int(row.get("level_order", "").strip())
                material_order = int(row.get("material_order", "").strip())
            except (ValueError, AttributeError):
                print(f"[SKIP] baris tidak valid, level_order/material_order kosong/bukan angka: {row}")
                skipped += 1
                continue

            level_title = row.get("level_title", "").strip()
            word = row.get("word", "").strip()
            video_file = row.get("video_file", "").strip()

            if not word or not video_file:
                print(f"[SKIP] baris '{row}' -> word/video_file kosong")
                skipped += 1
                continue

            video_path = os.path.join(video_dir, video_file)
            if not os.path.isfile(video_path):
                print(f"[SKIP] '{word}' (level {level_order}) -> video '{video_file}' tidak ditemukan di {video_dir}")
                skipped += 1
                continue

            # cari/buat level
            level = db.query(LearningLevel).filter(LearningLevel.order == level_order).first()
            if level:
                if level_title and level.title != level_title:
                    level.title = level_title
                    levels_updated += 1
            else:
                level = LearningLevel(order=level_order, title=level_title or f"Level {level_order}")
                db.add(level)
                db.flush()  # biar level.id kebentuk sebelum dipakai material
                levels_created += 1

            # cari/buat material dalam level ini
            material = (
                db.query(LearningMaterial)
                .filter(LearningMaterial.level_id == level.id, LearningMaterial.word.ilike(word))
                .first()
            )
            cara_isyarat = row.get("cara_isyarat") or None

            if material:
                material.order = material_order
                material.video_path = video_path
                material.cara_isyarat = cara_isyarat or material.cara_isyarat
                materials_updated += 1
            else:
                material = LearningMaterial(
                    level_id=level.id,
                    order=material_order,
                    word=word,
                    video_path=video_path,
                    cara_isyarat=cara_isyarat,
                )
                db.add(material)
                materials_created += 1

    db.commit()
    db.close()

    print(f"\nSelesai.")
    print(f"Level  -> Dibuat: {levels_created}, Diupdate: {levels_updated}")
    print(f"Materi -> Dibuat: {materials_created}, Diupdate: {materials_updated}, Dilewati: {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed level & materi pembelajaran SignPedia dari CSV + folder video")
    parser.add_argument("--csv", required=True, help="Path ke file CSV data materi")
    parser.add_argument("--video-dir", required=True, help="Folder tempat video materi disimpan")
    args = parser.parse_args()

    run(args.csv, args.video_dir)