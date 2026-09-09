import enum
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey, Enum
from sqlalchemy.orm import relationship

from app.core.database import Base


class CorrectionKind(str, enum.Enum):
    """
    Dua jenis koreksi yang artinya BERBEDA untuk pelatihan model:

      salah_label : gerakannya isyarat sah, tapi model menebak kata yang keliru
                    ("Makan" padahal "Minum") -> contoh latih dengan label benar.
      bukan_kata  : model memunculkan kata padahal pengguna tidak sedang
                    berisyarat sama sekali (false positive) -> contoh NEGATIF,
                    tidak punya label benar.

    Dibedakan sejak awal karena keduanya dipakai dengan cara berbeda saat
    melatih ulang; menggabungkannya jadi satu kolom "label benar boleh kosong"
    membuat maksudnya kabur saat data dibaca berbulan-bulan kemudian.
    """
    salah_label = "salah_label"
    bukan_kata = "bukan_kata"


class DetectionCorrection(Base):
    """
    Satu koreksi pengguna atas tebakan SignBridge, LENGKAP dengan gerakan
    yang menghasilkan tebakan itu.

    KENAPA `sequence` WAJIB ADA: tanpa potongan gerakan aslinya, koreksi cuma
    berarti "tebakannya salah" — tidak bisa dipakai melatih apa pun. Kolom ini
    berisi 15 x 63 angka (jendela yang persis dilihat model saat menebak),
    disimpan sebagai JSON karena bentuknya tetap dan tidak pernah di-query
    per-elemen; yang di-query cuma labelnya.

    Nilai langsungnya, bahkan sebelum ada pelatihan ulang: pasangan
    (predicted_label -> corrected_label) menunjukkan gestur mana yang paling
    sering tertukar. Itu diagnosis konkret, bukan "modelnya kurang akurat".
    """
    __tablename__ = "detection_corrections"

    id = Column(Integer, primary_key=True, index=True)

    # Boleh NULL: /ws/detect bisa dipakai tanpa login (mode demo). Koreksi
    # anonim tetap berharga sebagai data latih.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    kind = Column(Enum(CorrectionKind), nullable=False, default=CorrectionKind.salah_label)

    predicted_label = Column(String, nullable=False, index=True)   # tebakan model
    corrected_label = Column(String, nullable=True, index=True)    # kata yang benar (NULL untuk bukan_kata)
    confidence = Column(Float, nullable=True)                      # keyakinan model saat menebak

    # 15 x 63 landmark, JSON. Lihat catatan kelas di atas.
    sequence = Column(Text, nullable=False)

    # "landmark" (ekstraksi di HP) atau "frame" (ekstraksi di server).
    # Normalisasi keduanya tidak identik, jadi saat melatih ulang perlu tahu
    # sampel ini datang dari jalur yang mana.
    mode = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User")
