from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class PasanganTertukar(BaseModel):
    """Berapa kali gestur A dikoreksi jadi gestur B."""
    predicted_label: str
    corrected_label: Optional[str] = None   # None = false positive (bukan isyarat)
    jumlah: int


class CorrectionStats(BaseModel):
    """
    Ringkasan koreksi pengguna — dipakai memutuskan APA yang perlu diperbaiki
    sebelum repot melatih ulang model.

    `pasangan_tertukar` adalah isinya yang paling berguna: kalau sebagian besar
    koreksi berbunyi "Makan -> Minum", itu masalah spesifik yang bisa
    dikerjakan, bukan sekadar "akurasi model kurang".
    """
    total: int
    total_salah_label: int
    total_bukan_kata: int
    siap_latih: int                   # koreksi yang lengkap dengan bukti gerakan
    pasangan_tertukar: List[PasanganTertukar]
    kata_paling_sering_salah: List[PasanganTertukar]


class CorrectionItem(BaseModel):
    id: int
    user_id: Optional[int] = None
    kind: str
    predicted_label: str
    corrected_label: Optional[str] = None
    confidence: Optional[float] = None
    mode: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
