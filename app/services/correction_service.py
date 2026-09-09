"""
Penyimpanan koreksi pengguna atas tebakan SignBridge.

Dipisah dari router/WebSocket karena dipanggil dari alur async (handler WS)
sementara SQLAlchemy di proyek ini sinkron: penulisannya harus dijalankan di
threadpool supaya tidak memblokir event loop yang sedang melayani stream
landmark 10 fps milik semua pengguna lain.

PRINSIP: menyimpan koreksi TIDAK BOLEH menggagalkan sesi deteksi. Kalau
database bermasalah, koreksinya hilang tapi transkrip pengguna tetap terbetulkan
di layar — bukan sebaliknya.
"""

import json
from typing import Optional

from app.core.database import SessionLocal
from app.models.correction import CorrectionKind, DetectionCorrection
from app.services.stream_session import KataTranskrip


def simpan_koreksi(
    kata: KataTranskrip,
    label_benar: Optional[str],
    user_id: Optional[int] = None,
    mode: Optional[str] = None,
) -> bool:
    """
    Simpan satu koreksi. Return True kalau tersimpan.

    `label_benar=None` berarti pengguna menghapus kata itu — model memunculkan
    kata padahal tidak ada isyarat (false positive).

    Sampel tanpa bukti gerakan SENGAJA ditolak: barisnya cuma akan jadi
    "tebakannya salah" yang tidak bisa dilatihkan, sekaligus menandakan ada bug
    di jalur penangkapan sequence yang lebih baik terlihat daripada tersimpan
    diam-diam.
    """
    if not kata.sequence:
        return False

    db = SessionLocal()
    try:
        db.add(DetectionCorrection(
            user_id=user_id,
            kind=CorrectionKind.salah_label if label_benar else CorrectionKind.bukan_kata,
            predicted_label=kata.label,
            corrected_label=label_benar,
            confidence=kata.confidence or None,
            sequence=json.dumps(kata.sequence),
            mode=mode,
        ))
        db.commit()
        return True
    except Exception as e:  # noqa: BLE001 — sengaja luas, lihat docstring modul
        db.rollback()
        print(f"Gagal menyimpan koreksi deteksi: {e}")
        return False
    finally:
        db.close()
