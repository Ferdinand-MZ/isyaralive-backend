import os

# ============================================================
# KONFIGURASI APLIKASI
# Untuk production, pindahkan SECRET_KEY ke environment variable
# Jangan commit SECRET_KEY asli ke git
# ============================================================

SECRET_KEY = os.getenv("SECRET_KEY", "isyaralive-secret-key-ganti-saat-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 hari

DATABASE_URL = "sqlite:///./database.db"

UPLOAD_DIR = "uploads"
UPLOAD_PENDING_DIR = f"{UPLOAD_DIR}/pending"
UPLOAD_APPROVED_DIR = f"{UPLOAD_DIR}/approved"
UPLOAD_REJECTED_DIR = f"{UPLOAD_DIR}/rejected"

MAX_VIDEO_SIZE_MB = 50
ALLOWED_VIDEO_EXTENSIONS = (".mp4", ".mov", ".MP4", ".MOV")

# Buat folder kalau belum ada
for folder in [UPLOAD_PENDING_DIR, UPLOAD_APPROVED_DIR, UPLOAD_REJECTED_DIR]:
    os.makedirs(folder, exist_ok=True)
