from pydantic import BaseModel
from app.models.vote import VoteType


class VoteRequest(BaseModel):
    type: VoteType  # "upvote" atau "downvote"


class VoteResponse(BaseModel):
    submission_id: int
    upvotes: int
    downvotes: int
    my_vote: str