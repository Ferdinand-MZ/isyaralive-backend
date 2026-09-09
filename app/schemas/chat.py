from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


class DictionaryMatchInfo(BaseModel):
    """
    Disisipkan di respons kalau chatbot mendeteksi ini pencarian kosakata
    (integrasi SignPedia).

    PENTING — `found` dan `meaning` menjawab DUA pertanyaan berbeda:
      - `found`   : apakah PERAGA ISYARAT-nya ada di kamus SignPedia.
      - `meaning` : apa ARTI katanya dalam Bahasa Indonesia.
    Keduanya bisa terisi sendiri-sendiri. Kata "keju" punya makna (dari KBBI)
    walau peraga isyaratnya belum ada di kamus, dan itu tetap jawaban yang
    berguna — bukan sekadar "belum tersedia".
    """
    found: bool
    word: str
    video_path: Optional[str] = None
    meaning: Optional[str] = None
    illustration_path: Optional[str] = None   # gambar dari aset kamus (kalau admin menyiapkan)
    source: Optional[str] = None              # asal makna, mis. "KBBI — keju, dirapikan Asisten AI"
    alphabet_letters: List[str] = []  # fallback ejaan kalau found=False


class ChatMessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatReplyResponse(BaseModel):
    conversation_id: int
    user_message: str          # isi pesan user (teks asli atau hasil ekstraksi glosses dari video)
    reply: str
    dictionary_match: Optional[DictionaryMatchInfo] = None


class ChatHistoryResponse(BaseModel):
    conversation_id: int
    title: str
    messages: List[ChatMessageOut]