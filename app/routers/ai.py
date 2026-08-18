from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.ai import (
    AiAnalisisRequest, AiAnalisisResponse,
    SaranLanjutanRequest, SaranLanjutanResponse,
)
from app.services.ai_service import perbaiki_transkrip, saran_kata_lanjutan
from app.services.detector_instance import detector
from app.models.dictionary import DictionaryEntry
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/ai", tags=["AI - Analisis Transkrip"])


@router.post("/analisis-transkrip", response_model=AiAnalisisResponse)
async def analisis_transkrip(
    data: AiAnalisisRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Fitur "Analisis dengan AI" (screen: Hasil Analisis AI).

    Terima transkrip mentah hasil deteksi gesture (dari WebSocket /ws/detect
    yang sudah digabung jadi kalimat di Flutter), lalu kirim ke Azure OpenAI
    untuk dirapikan jadi kalimat gramatikal yang siap dibaca / di-TTS-kan.
    """
    hasil = await perbaiki_transkrip(data.transkrip)

    return AiAnalisisResponse(
        transkrip_asli=data.transkrip,
        hasil_perbaikan=hasil,
    )


@router.post("/saran-lanjutan", response_model=SaranLanjutanResponse)
async def saran_lanjutan(
    data: SaranLanjutanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Fitur SmartSign AI — saran kata berikutnya saat pengguna JEDA gestur.

    Aplikasi memanggil endpoint ini ketika tidak ada gestur terdeteksi
    selama beberapa detik, lalu menampilkan 3 chip kata. Pengguna cukup
    menekan salah satu untuk melanjutkan kalimat tanpa memperagakan gestur,
    sehingga komunikasi berlangsung lebih cepat.

    Saran selalu dibatasi pada kosakata yang tersedia di sistem, supaya
    kata yang disarankan pasti punya peraga gestur.
    """
    kosakata = list(detector.class_names)

    if not data.hanya_kosakata_model:
        kata_kamus = [w[0] for w in db.query(DictionaryEntry.word).all()]
        for w in kata_kamus:
            if w not in kosakata:
                kosakata.append(w)

    saran = await saran_kata_lanjutan(
        transkrip=data.transkrip_sementara,
        kosakata=kosakata,
        jumlah=data.jumlah,
    )

    return SaranLanjutanResponse(
        transkrip_sementara=data.transkrip_sementara,
        saran=saran,
        jumlah_kosakata_tersedia=len(kosakata),
    )