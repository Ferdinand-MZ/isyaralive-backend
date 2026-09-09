import os
import shutil
import uuid
from fastapi import UploadFile, HTTPException

from app.core.config import (
    UPLOAD_PENDING_DIR,
    MAX_VIDEO_SIZE_MB,
    ALLOWED_VIDEO_EXTENSIONS
)


def save_pending_video(file: UploadFile) -> str:
    """
    Simpan video upload user ke folder pending.
    Return: path file yang tersimpan.
    """
    ext = os.path.splitext(file.filename)[1]

    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format file tidak didukung. Gunakan: {ALLOWED_VIDEO_EXTENSIONS}"
        )

    # Nama file unik supaya tidak bentrok antar user
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(UPLOAD_PENDING_DIR, unique_filename)

    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Cek ukuran file setelah disimpan
    size_mb = os.path.getsize(save_path) / (1024 * 1024)
    if size_mb > MAX_VIDEO_SIZE_MB:
        os.remove(save_path)
        raise HTTPException(
            status_code=400,
            detail=f"File terlalu besar (maks {MAX_VIDEO_SIZE_MB}MB)"
        )

    return save_path


def delete_video(current_path: str) -> bool:
    """
    Hapus berkas video dari disk. Dipakai saat admin MENGHAPUS submission.

    Sengaja best-effort: berkas yang sudah lenyap (dihapus manual, atau sisa
    percobaan) tidak boleh menggagalkan penghapusan barisnya di database —
    kalau tidak, submission rusak justru mustahil dibersihkan.
    Return True bila ada berkas yang benar-benar terhapus.
    """
    if not current_path:
        return False
    try:
        os.remove(current_path)
        return True
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return False


def move_video(current_path: str, target_dir: str) -> str:
    """
    Pindahkan video dari satu folder ke folder lain.
    Dipakai saat admin approve/reject (pending -> approved/rejected).
    """
    if not os.path.exists(current_path):
        raise HTTPException(status_code=404, detail="File video tidak ditemukan")

    filename = os.path.basename(current_path)
    new_path = os.path.join(target_dir, filename)

    shutil.move(current_path, new_path)
    return new_path
