from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base


class PointLog(Base):
    """
    Catatan setiap perolehan poin, dipakai untuk hitung leaderboard
    per periode (mingguan/bulanan/tahunan) tanpa kehilangan histori.
    """
    __tablename__ = "point_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    points = Column(Integer, nullable=False)          # bisa negatif (misal vote dibatalkan)
    reason = Column(String, nullable=False)            # "submission_approved" / "received_upvote" / dst
    submission_id = Column(Integer, ForeignKey("gesture_submissions.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")