"""
Registrasi seluruh model SQLAlchemy.

PENTING: semua model harus diimpor di sini, bukan sebagian saja.

Alasannya, relasi antar model ditulis sebagai STRING — misalnya
GestureSubmission punya relationship("Vote"). SQLAlchemy baru
menerjemahkan string itu ke class saat mapper dikonfigurasi, dan ia
hanya bisa menemukannya kalau modulnya sudah pernah diimpor.

Kalau ada model yang belum terdaftar, query yang sama sekali tidak
menyentuh model itu tetap bisa gagal dengan:

    InvalidRequestError: expression 'Vote' failed to locate a name

Gejalanya membingungkan karena error muncul di query DictionaryEntry,
padahal penyebabnya Vote yang belum diimpor.
"""

from app.models.user import User, UserRole  # noqa: F401
from app.models.submission import (  # noqa: F401
    GestureSubmission,
    SubmissionStatus,
    GestureCategory,
)
from app.models.vote import Vote, VoteType  # noqa: F401
from app.models.point_log import PointLog  # noqa: F401
from app.models.dictionary import DictionaryEntry, DictionaryCategory  # noqa: F401
from app.models.learning import (  # noqa: F401
    LearningLevel,
    LearningMaterial,
    UserProgress,
)
from app.models.chat import (  # noqa: F401
    ChatConversation,
    ChatMessage,
    MessageRole,
)

__all__ = [
    "User", "UserRole",
    "GestureSubmission", "SubmissionStatus", "GestureCategory",
    "Vote", "VoteType",
    "PointLog",
    "DictionaryEntry", "DictionaryCategory",
    "LearningLevel", "LearningMaterial", "UserProgress",
    "ChatConversation", "ChatMessage", "MessageRole",
]