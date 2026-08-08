from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.core.database import Base


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class ChatConversation(Base):
    """1 sesi percakapan AI Chatbot per user (bisa banyak sesi)."""
    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, default="Percakapan Baru")
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship(
        "ChatMessage", back_populates="conversation",
        order_by="ChatMessage.created_at", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("chat_conversations.id"), nullable=False)
    role = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)

    # Kalau pesan user berasal dari upload video gestur (bukan ketik teks)
    source_video_path = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("ChatConversation", back_populates="messages")