from sqlalchemy import Column, Integer, ForeignKey, DateTime, Enum, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.core.database import Base


class VoteType(str, enum.Enum):
    upvote = "upvote"
    downvote = "downvote"


class Vote(Base):
    __tablename__ = "votes"
    # 1 user hanya boleh vote 1x per submission (bisa ubah upvote<->downvote, bukan dobel)
    __table_args__ = (UniqueConstraint("user_id", "submission_id", name="uq_user_submission_vote"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    submission_id = Column(Integer, ForeignKey("gesture_submissions.id"), nullable=False)
    type = Column(Enum(VoteType), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    submission = relationship("GestureSubmission", back_populates="votes")