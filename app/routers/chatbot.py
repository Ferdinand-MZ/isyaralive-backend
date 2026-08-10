import os
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.chat import ChatConversation, ChatMessage, MessageRole
from app.models.dictionary import DictionaryEntry
from app.schemas.chat import ChatReplyResponse, ChatHistoryResponse, ChatMessageOut, DictionaryMatchInfo
from app.services.ai_service import chatbot_reply
from app.services.video_gloss_services import extract_glosses_from_video
from app.services.detector_instance import detector
from app.routers.gesture_lookup import get_alphabet_video

router = APIRouter(prefix="/ai/chatbot", tags=["AI - Chatbot (SmartSign AI)"])

UPLOAD_CHAT_VIDEO_DIR = "uploads/chat_videos"
os.makedirs(UPLOAD_CHAT_VIDEO_DIR, exist_ok=True)

# Pola sederhana buat deteksi "ini pertanyaan soal arti/kosakata" -> trigger integrasi SignPedia
LOOKUP_PATTERNS = [
    r"^apa\s+(arti|itu|makna)\s+(.+)$",
    r"^arti\s+(.+)$",
    r"^makna\s+(.+)$",
    r"^cara\s+isyarat\s+(.+)$",
]


def _try_extract_lookup_word(message: str) -> Optional[str]:
    """Kalau pesan user berpola pertanyaan kosakata, ambil kata yang ditanyakan."""
    text = message.strip().lower().rstrip("?.! ")
    for pattern in LOOKUP_PATTERNS:
        m = re.match(pattern, text)
        if m:
            return m.groups()[-1].strip()
    return None


def _lookup_dictionary(word: str, db: Session) -> DictionaryMatchInfo:
    """Integrasi SignPedia: cari kata di kamus, fallback ejaan alfabet kalau gak ada."""
    entry = db.query(DictionaryEntry).filter(DictionaryEntry.word.ilike(word)).first()

    if entry:
        return DictionaryMatchInfo(
            found=True,
            word=entry.word,
            video_path=entry.video_path,
            meaning=entry.meaning,
            illustration_path=entry.illustration_path,
        )

    letters = [ch.upper() for ch in word if ch.isalpha()]
    return DictionaryMatchInfo(found=False, word=word, alphabet_letters=letters)


def _get_or_create_conversation(db: Session, user: User, conversation_id: Optional[int]) -> ChatConversation:
    if conversation_id:
        convo = (
            db.query(ChatConversation)
            .filter(ChatConversation.id == conversation_id, ChatConversation.user_id == user.id)
            .first()
        )
        if not convo:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Percakapan tidak ditemukan")
        return convo

    convo = ChatConversation(user_id=user.id, title="Percakapan Baru")
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return convo


@router.post("/message", response_model=ChatReplyResponse)
async def send_message(
    conversation_id: Optional[int] = Form(None, description="Kosongkan untuk mulai percakapan baru"),
    message: Optional[str] = Form(None, description="Pesan teks (isi ini ATAU 'video', salah satu wajib)"),
    video: Optional[UploadFile] = File(None, description="Video gestur BISINDO sebagai pertanyaan"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Kirim pesan ke Asisten AI IsyaraLive.
    - Layar (b) & (d): kirim `message` (teks) saja.
    - Layar (c): kirim `video` (gestur) saja -> otomatis di-deteksi jadi teks dulu.
    Kalau pertanyaannya soal arti/kosakata, otomatis terintegrasi dengan SignPedia
    (cari di kamus, fallback ejaan alfabet kalau belum ada).
    """
    if not message and not video:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Isi 'message' atau upload 'video'")

    source_video_path = None
    user_text = message

    if video:
        ext = os.path.splitext(video.filename or "")[1] or ".mp4"
        source_video_path = os.path.join(UPLOAD_CHAT_VIDEO_DIR, f"{uuid.uuid4().hex}{ext}")
        with open(source_video_path, "wb") as f:
            f.write(await video.read())

        # Video -> glosses (kata dasar hasil deteksi LSTM), jadi teks pertanyaan
        user_text = extract_glosses_from_video(source_video_path, detector)

    convo = _get_or_create_conversation(db, current_user, conversation_id)

    # Cek apakah ini pertanyaan kosakata -> integrasi SignPedia
    dictionary_match = None
    dictionary_context_str = None
    lookup_word = _try_extract_lookup_word(user_text)
    if lookup_word:
        dictionary_match = _lookup_dictionary(lookup_word, db)
        if dictionary_match.found:
            dictionary_context_str = (
                f"Kata '{dictionary_match.word}' DITEMUKAN di kamus SignPedia. "
                f"Pengertian: {dictionary_match.meaning or '(belum ada deskripsi)'}"
            )
        else:
            dictionary_context_str = (
                f"Kata '{dictionary_match.word}' TIDAK ditemukan di kamus SignPedia. "
                f"Sarankan pengguna gunakan ejaan alfabet: {'-'.join(dictionary_match.alphabet_letters)}"
            )

    # Ambil riwayat percakapan sebelumnya sebagai konteks
    history = [
        {"role": m.role.value, "content": m.content}
        for m in convo.messages
    ]

    # Simpan pesan user
    db.add(ChatMessage(
        conversation_id=convo.id, role=MessageRole.user,
        content=user_text, source_video_path=source_video_path,
    ))
    db.commit()

    reply_text = await chatbot_reply(history, user_text, dictionary_context_str)

    db.add(ChatMessage(conversation_id=convo.id, role=MessageRole.assistant, content=reply_text))
    db.commit()

    return ChatReplyResponse(
        conversation_id=convo.id,
        user_message=user_text,
        reply=reply_text,
        dictionary_match=dictionary_match,
    )


@router.get("/conversations/{conversation_id}", response_model=ChatHistoryResponse)
def get_conversation_history(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ambil seluruh riwayat pesan 1 percakapan (buat buka ulang chat lama)."""
    convo = (
        db.query(ChatConversation)
        .filter(ChatConversation.id == conversation_id, ChatConversation.user_id == current_user.id)
        .first()
    )
    if not convo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Percakapan tidak ditemukan")

    return ChatHistoryResponse(
        conversation_id=convo.id,
        title=convo.title,
        messages=[ChatMessageOut.model_validate(m) for m in convo.messages],
    )


@router.get("/conversations", response_model=List[ChatHistoryResponse])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List semua sesi percakapan milik user (buat sidebar riwayat chat)."""
    convos = (
        db.query(ChatConversation)
        .filter(ChatConversation.user_id == current_user.id)
        .order_by(ChatConversation.created_at.desc())
        .all()
    )
    return [
        ChatHistoryResponse(
            conversation_id=c.id, title=c.title,
            messages=[ChatMessageOut.model_validate(m) for m in c.messages],
        )
        for c in convos
    ]