from sqlalchemy import Column, Integer, String, Text, DateTime, Enum
from datetime import datetime
import enum

from app.core.database import Base


class DictionaryCategory(str, enum.Enum):
    sehari_hari = "sehari-hari"
    umum = "umum"
    emoji = "emoji"
    angka = "angka"


class DictionaryEntry(Base):
    """
    Kamus kosakata BISINDO (SignPedia).
    Beda dengan GestureSubmission (dataset training komunitas) — ini konten
    kurasi editorial: video peraga + penjelasan makna, dikelola admin.
    """
    __tablename__ = "dictionary_entries"

    id = Column(Integer, primary_key=True, index=True)

    word = Column(String, nullable=False, index=True, unique=True)   # "Terima Kasih"
    category = Column(Enum(DictionaryCategory), default=DictionaryCategory.umum, nullable=False)

    video_path = Column(String, nullable=False)          # video peraga gestur
    cara_isyarat = Column(Text, nullable=True)             # "Cara Isyarat" step-by-step

    # Bagian "Lihat Penjelasan" / "Makna Kata"
    illustration_path = Column(String, nullable=True)      # gambar ilustrasi konsep
    meaning = Column(Text, nullable=True)                    # "Pengertian"
    source = Column(String, nullable=True)                   # "Sumber: Wikipedia Commons"

    related_words = Column(String, nullable=True)  # comma-separated, mis: "Klorofil,Oksigen,Tumbuhan,Glukosa"

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)