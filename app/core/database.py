from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import DATABASE_URL

# ============================================================
# SETUP DATABASE (SQLite)
# File database.db akan otomatis terbuat di root project
# ============================================================

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # khusus SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    Dependency untuk FastAPI — kasih session database per request,
    otomatis ditutup setelah request selesai.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Buat semua tabel kalau belum ada. Dipanggil saat startup."""
    from app.models import user, submission, vote, point_log, dictionary, learning, chat, correction  # noqa: F401 (import agar ke-register)
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_columns()


def _migrate_sqlite_columns():
    """
    Proyek ini belum pakai Alembic, dan create_all() TIDAK menambah kolom
    baru ke tabel yang sudah ada (cuma bikin tabel yang belum ada). Jadi
    kolom baru yang ditambahkan ke model butuh ALTER TABLE manual di sini.
    Aman dijalankan berkali-kali — tiap kolom dicek dulu sebelum di-ALTER.
    """
    if not DATABASE_URL.startswith("sqlite"):
        return

    # (nama_tabel, [(nama_kolom, definisi_tipe_sql), ...])
    pending_columns = [
        ("users", [
            ("current_streak", "INTEGER DEFAULT 0"),
            ("longest_streak", "INTEGER DEFAULT 0"),
            ("last_activity_date", "DATE"),
        ]),
        # Jendela voting komunitas (status "voting"). Kolom `status` sendiri
        # TIDAK perlu diubah: SQLAlchemy menulisnya sebagai VARCHAR tanpa CHECK
        # constraint, jadi nilai enum baru langsung sah tanpa bongkar tabel.
        ("gesture_submissions", [
            ("voting_started_at", "DATETIME"),
            ("voting_ends_at", "DATETIME"),
        ]),
    ]

    with engine.connect() as conn:
        for table, columns in pending_columns:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for column_name, column_def in columns:
                if column_name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_def}")
        conn.commit()
