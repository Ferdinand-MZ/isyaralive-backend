from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from app.core.database import get_db
from app.models.user import User
from app.models.point_log import PointLog
from app.schemas.leaderboard import LeaderboardEntry, LeaderboardResponse

router = APIRouter(prefix="/leaderboard", tags=["SignHub Leaderboard"])


def _period_start(period: str) -> datetime:
    now = datetime.utcnow()
    if period == "weekly":
        return now - timedelta(days=7)
    if period == "yearly":
        return now - timedelta(days=365)
    # default: monthly
    return now - timedelta(days=30)


@router.get("/", response_model=LeaderboardResponse)
def get_leaderboard(
    period: str = Query("monthly", pattern="^(weekly|monthly|yearly)$"),
    db: Session = Depends(get_db),
):
    """
    Leaderboard kontributor SignHub, dihitung dari akumulasi PointLog
    pada rentang waktu tertentu (mingguan/bulanan/tahunan).
    Default: bulanan (sesuai tampilan utama di UI).
    """
    start_date = _period_start(period)

    rows = (
        db.query(
            User.id.label("user_id"),
            User.name.label("name"),
            func.coalesce(func.sum(PointLog.points), 0).label("total_points"),
        )
        .join(PointLog, PointLog.user_id == User.id)
        .filter(PointLog.created_at >= start_date)
        .group_by(User.id, User.name)
        .order_by(func.sum(PointLog.points).desc())
        .all()
    )

    entries = [
        LeaderboardEntry(rank=i + 1, user_id=r.user_id, name=r.name, points=r.total_points)
        for i, r in enumerate(rows)
    ]

    return LeaderboardResponse(period=period, entries=entries)