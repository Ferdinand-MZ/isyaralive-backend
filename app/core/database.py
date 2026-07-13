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
    from app.models import user, submission  # noqa: F401 (import agar ke-register)
    Base.metadata.create_all(bind=engine)
