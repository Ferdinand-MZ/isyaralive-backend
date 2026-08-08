from pydantic import BaseModel, Field


class AiAnalisisRequest(BaseModel):
    """
    Body request untuk POST /ai/analisis-transkrip

    transkrip: hasil mentah dari deteksi gesture (gabungan label per-kata),
               contoh: "halo nama saya budi saya mau makan terima kasih"
    """
    transkrip: str = Field(..., min_length=1, description="Transkrip mentah hasil deteksi isyarat")


class AiAnalisisResponse(BaseModel):
    transkrip_asli: str
    hasil_perbaikan: str