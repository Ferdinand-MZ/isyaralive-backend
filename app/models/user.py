from sqlalchemy import Column, Integer, String, DateTime, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.core.database import Base


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.user, nullable=False)
    points = Column(Integer, default=0, nullable=False)  # poin gamifikasi SignHub
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relasi: submission yang dibuat user ini
    submissions = relationship(
        "GestureSubmission",
        back_populates="user",
        foreign_keys="GestureSubmission.user_id"
    )