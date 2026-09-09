import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.chat import ChatConversation, ChatMessage, MessageRole
from app.schemas.chat import ChatReplyResponse, ChatHistoryResponse, ChatMessageOut, DictionaryMatchInfo
from app.services.ai_service import chatbot_reply
from app.services.kamus_match import cari_entri, ekstrak_kata_tanya
from app.services.kbbi_service import cari_ringkasan
from app.services.video_gloss_services import extract_glosses_from_video
from app.services.detector_instance import detector

router = APIRouter(prefix="/ai/chatbot", tags=["AI - Chatbot (SmartSign AI)"])

UPLOAD_CHAT_VIDEO_DIR = "uploads/chat_videos"
os.makedirs(UPLOAD_CHAT_VIDEO_DIR, exist_ok=True)

# Batas panjang penjelasan yang ikut dikirim ke AI sebagai konteks.
MAKS_MAKNA_KONTEKS = 700

async def _lookup_dictionary(word: str, db: Session) -> DictionaryMatchInfo:
    """
    Integrasi SignPedia: cari peraga isyarat di kamus, DAN cari makna katanya.

    Dua hal yang sengaja dipisah (lihat DictionaryMatchInfo):
      1. PERAGA ISYARAT — hanya dari kamus SignPedia kita sendiri. Pencocokan
         dilakukan `kamus_match.cari_entri` yang toleran terhadap beda huruf
         besar/kecil, spasi, dan kata sebagian; ini yang dulu bikin kata yang
         jelas ADA di kamus malah dinyatakan tidak ada lalu dibalas ejaan abjad.
      2. MAKNA + FOTO — dari kolom kamus kalau sudah diisi, kalau belum diambil
         dari KBBI (fotonya pelengkap, dari Wikimedia). Jadi kata seperti
         "keju" tetap dapat penjelasan dan foto walau peraga isyaratnya memang
         belum ada.
    """
    entry = cari_entri(db, word)

    meaning = entry.meaning if entry else None
    illustration = entry.illustration_path if entry else None
    source = entry.source if entry else None

    # Lengkapi dari KBBI HANYA bila kamus belum punya penjelasannya —
    # konten kurasi editorial selalu menang atas sumber luar.
    if not (meaning or "").strip():
        ringkasan = await cari_ringkasan(entry.word if entry else word)
        if ringkasan:
            meaning = ringkasan["makna"]
            illustration = illustration or ringkasan["foto_url"]
            source = source or ringkasan["sumber"]

            # Simpan ke kamus supaya pencarian berikutnya instan dan layar
            # "Makna Kata" (GET /dictionary/{id}/meaning) ikut terisi.
            if entry:
                entry.meaning = meaning
                entry.illustration_path = entry.illustration_path or ringkasan["foto_url"]
                entry.source = entry.source or ringkasan["sumber"]
                db.commit()

    if entry:
        return DictionaryMatchInfo(
            found=True,
            word=entry.word,
            video_path=entry.video_path,
            meaning=meaning,
            illustration_path=illustration,
            source=source,
        )

    letters = [ch.upper() for ch in word if ch.isalpha()]
    return DictionaryMatchInfo(
        found=False,
        word=word,
        meaning=meaning,
        illustration_path=illustration,
        source=source,
        alphabet_letters=letters,
    )


def _konteks_kamus(match: DictionaryMatchInfo) -> str:
    """
    Rakit "KONTEKS KAMUS" yang dibaca AI.

    Ditulis eksplisit sebagai dua baris terpisah supaya AI tidak lagi
    mencampuradukkan "peraga isyaratnya belum ada" dengan "katanya tidak punya
    arti" — dua hal yang benar-benar berbeda bagi pengguna.
    """
    baris = [f'KATA YANG DITANYAKAN: {match.word}']

    if match.found:
        baris.append(
            "PERAGA ISYARAT BISINDO: TERSEDIA di kamus SignPedia "
            "(video peraga sudah ditampilkan otomatis di bawah jawaban Anda)."
        )
    else:
        ejaan = "-".join(match.alphabet_letters) or "(tidak ada huruf)"
        baris.append(
            "PERAGA ISYARAT BISINDO: BELUM ADA di kamus SignPedia. "
            f"Alternatifnya dieja per huruf: {ejaan}."
        )

    if (match.meaning or "").strip():
        sumber = f" (sumber: {match.source})" if match.source else ""
        # Entri KBBI bisa memuat banyak makna beserta contoh kalimatnya. AI
        # cuma butuh intinya untuk menjawab singkat, jadi dipotong supaya prompt
        # tetap hemat — teks utuhnya tetap tersimpan di kamus untuk layar
        # "Makna Kata".
        makna = match.meaning.strip()
        if len(makna) > MAKS_MAKNA_KONTEKS:
            makna = makna[:MAKS_MAKNA_KONTEKS].rsplit(" ", 1)[0] + " …"
        baris.append(f"ARTI KATA{sumber}: {makna}")
    else:
        baris.append(
            "ARTI KATA: tidak tersedia di data kami — jelaskan dari pengetahuan "
            "Anda sendiri secara singkat dan akurat."
        )

    return "\n".join(baris)


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
    lookup_word = ekstrak_kata_tanya(user_text)
    if lookup_word:
        dictionary_match = await _lookup_dictionary(lookup_word, db)
        dictionary_context_str = _konteks_kamus(dictionary_match)

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