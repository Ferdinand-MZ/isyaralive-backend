from sqlalchemy.orm import Session

from app.models.user import User
from app.models.point_log import PointLog

# Bobot poin, gampang diubah di satu tempat
POINTS_SUBMISSION_APPROVED = 10
POINTS_RECEIVED_UPVOTE = 1
POINTS_RECEIVED_DOWNVOTE = -1
POINTS_QUIZ_CORRECT = 2


def add_points(db: Session, user_id: int, points: int, reason: str, submission_id: int | None = None):
    """Nambah/kurang poin user, sekaligus catat log untuk leaderboard periodik."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return

    user.points = (user.points or 0) + points

    log = PointLog(
        user_id=user_id,
        points=points,
        reason=reason,
        submission_id=submission_id,
    )
    db.add(log)
    db.add(user)
    db.commit()