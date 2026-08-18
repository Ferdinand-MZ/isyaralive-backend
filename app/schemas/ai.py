from typing import List

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


class SaranLanjutanRequest(BaseModel):
    """
    Body request untuk POST /ai/saran-lanjutan (SmartSign AI).

    Dipanggil aplikasi saat pengguna JEDA memperagakan gestur, supaya
    sistem bisa menawarkan kata berikutnya dan pengguna cukup memilih.
    """
    transkrip_sementara: str = Field(
        default="",
        description="Kata-kata yang sudah terdeteksi sejauh ini, mis. 'Halo nama saya'",
    )
    jumlah: int = Field(default=3, ge=1, le=5, description="Berapa saran kata yang diminta")
    hanya_kosakata_model: bool = Field(
        default=False,
        description="True = saran dibatasi hanya pada kelas yang bisa dideteksi model, "
                    "False = kelas model + kamus SignPedia",
    )


class SaranLanjutanResponse(BaseModel):
    transkrip_sementara: str
    saran: List[str]
    jumlah_kosakata_tersedia: int