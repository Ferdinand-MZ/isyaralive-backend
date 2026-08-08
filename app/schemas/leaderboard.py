from pydantic import BaseModel
from typing import List


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    name: str
    points: int


class LeaderboardResponse(BaseModel):
    period: str  # "weekly" / "monthly" / "yearly"
    entries: List[LeaderboardEntry]