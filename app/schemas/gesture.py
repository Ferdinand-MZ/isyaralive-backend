from pydantic import BaseModel, Field


class TextToGestureRequest(BaseModel):
    """Body request untuk /gesture/text-to-video & /gesture/text-to-animation."""
    text: str = Field(..., min_length=1, description="Teks/hasil speech-to-text yang mau diperagakan")
