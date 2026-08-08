from fastapi import APIRouter, Depends

from app.schemas.ai import AiAnalisisRequest, AiAnalisisResponse
from app.services.ai_service import perbaiki_transkrip
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