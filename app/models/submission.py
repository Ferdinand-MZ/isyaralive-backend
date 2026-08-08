from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.core.database import Base


class SubmissionStatus(str, enum.Enum):
    pending = "pending"      # baru diupload, menunggu vote komunitas & validator
    approved = "approved"    # sudah divalidasi validator, masuk dataset final
    rejected = "rejected"


class GestureCategory(str, enum.Enum):
    sehari_hari = "sehari-hari"
    edukasi = "edukasi"
    kesehatan = "kesehatan"
    layanan_publik = "layanan-publik"
    lainnya = "lainnya"


class GestureSubmission(Base):
    __tablename__ = "gesture_submissions"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    label = Column(String, nullable=False)          # kata/kalimat gesture
    video_path = Column(String, nullable=False)      # path file video
    status = Column(Enum(SubmissionStatus), default=SubmissionStatus.pending)

    # Field tambahan sesuai desain "Tambah Gestur Baru"
    category = Column(Enum(GestureCategory), default=GestureCategory.lainnya, nullable=False)
    description = Column(Text, nullable=True)   # "Deskripsi/Konteks"
    region = Column(String, nullable=True)       # "Daerah/Dialek", opsional

    admin_note = Column(Text, nullable=True)          # alasan reject (opsional)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)

    # Relasi
    user = relationship(
        "User", back_populates="submissions", foreign_keys=[user_id]
    )
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    votes = relationship("Vote", back_populates="submission", cascade="all, delete-orphan")