from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base


class LearningLevel(Base):
    """Level pembelajaran, mis: 'Level 1: Sapaan Dasar', 'Level 2: Keluarga'."""
    __tablename__ = "learning_levels"

    id = Column(Integer, primary_key=True, index=True)
    order = Column(Integer, nullable=False, unique=True)   # urutan tampil level 1,2,3,...
    title = Column(String, nullable=False)                   # "Sapaan Dasar"

    materials = relationship(
        "LearningMaterial", back_populates="level",
        order_by="LearningMaterial.order", cascade="all, delete-orphan"
    )


class LearningMaterial(Base):
    """Satu kata/materi di dalam sebuah level, mis: 'Selamat Pagi'."""
    __tablename__ = "learning_materials"

    id = Column(Integer, primary_key=True, index=True)
    level_id = Column(Integer, ForeignKey("learning_levels.id"), nullable=False)
    order = Column(Integer, nullable=False)  # urutan dalam level

    word = Column(String, nullable=False)              # "Selamat Pagi"
    video_path = Column(String, nullable=False)
    cara_isyarat = Column(Text, nullable=True)

    level = relationship("LearningLevel", back_populates="materials")


class UserProgress(Base):
    """Progress user: materi mana saja yang sudah 'Sudah Dipelajari'."""
    __tablename__ = "user_progress"
    __table_args__ = (UniqueConstraint("user_id", "material_id", name="uq_user_material_progress"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("learning_materials.id"), nullable=False)
    completed_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    material = relationship("LearningMaterial")