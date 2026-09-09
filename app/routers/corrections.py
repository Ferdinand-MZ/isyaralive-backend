"""
Baca-hasil koreksi pengguna atas tebakan SignBridge (admin).

Koreksi MASUK lewat WebSocket /ws/detect (pesan "edit"/"delete"), bukan lewat
router ini: hanya sesi WS yang masih memegang potongan gerakan penyebab
tebakan itu — begitu sesi ditutup, buktinya hilang.

Router ini gunanya membaca hasilnya:
  - /detection/corrections/stats  ringkasan + pasangan gestur yang tertukar
  - /detection/corrections        daftar koreksi (untuk ditinjau sebelum dipakai)
  - /detection/corrections/export data latih siap pakai (label + 15x63 landmark)

Sengaja admin-only: isinya rekaman gerakan pengguna.
"""

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_admin
from app.models.correction import CorrectionKind, DetectionCorrection
from app.models.user import User
from app.schemas.correction import CorrectionItem, CorrectionStats, PasanganTertukar

router = APIRouter(prefix="/detection/corrections", tags=["SignBridge - Koreksi Deteksi"])


@router.get("/stats", response_model=CorrectionStats)
def correction_stats(
    limit: int = Query(15, ge=1, le=100, description="Berapa pasangan teratas ditampilkan"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Ringkasan koreksi: berapa banyak, dan gestur mana yang paling sering tertukar."""
    total = db.query(func.count(DetectionCorrection.id)).scalar() or 0
    total_salah = (
        db.query(func.count(DetectionCorrection.id))
        .filter(DetectionCorrection.kind == CorrectionKind.salah_label)
        .scalar() or 0
    )

    pasangan = (
        db.query(
            DetectionCorrection.predicted_label,
            DetectionCorrection.corrected_label,
            func.count(DetectionCorrection.id).label("jumlah"),
        )
        .filter(DetectionCorrection.kind == CorrectionKind.salah_label)
        .group_by(DetectionCorrection.predicted_label, DetectionCorrection.corrected_label)
        .order_by(func.count(DetectionCorrection.id).desc())
        .limit(limit)
        .all()
    )

    per_kata = (
        db.query(
            DetectionCorrection.predicted_label,
            func.count(DetectionCorrection.id).label("jumlah"),
        )
        .group_by(DetectionCorrection.predicted_label)
        .order_by(func.count(DetectionCorrection.id).desc())
        .limit(limit)
        .all()
    )

    return CorrectionStats(
        total=total,
        total_salah_label=total_salah,
        total_bukan_kata=total - total_salah,
        # Sampel tanpa bukti gerakan tidak pernah disimpan (lihat
        # correction_service.simpan_koreksi), jadi semua baris siap dilatihkan.
        siap_latih=total,
        pasangan_tertukar=[
            PasanganTertukar(predicted_label=p, corrected_label=c, jumlah=n)
            for p, c, n in pasangan
        ],
        kata_paling_sering_salah=[
            PasanganTertukar(predicted_label=p, corrected_label=None, jumlah=n)
            for p, n in per_kata
        ],
    )


@router.get("", response_model=List[CorrectionItem])
def list_corrections(
    predicted_label: Optional[str] = Query(None, description="Saring: tebakan model"),
    corrected_label: Optional[str] = Query(None, description="Saring: kata yang benar"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """
    Daftar koreksi TANPA kolom `sequence` — isinya 945 angka per baris dan tidak
    ada gunanya dibaca manusia. Ambil lewat /export kalau mau melatih model.
    """
    q = db.query(DetectionCorrection)
    if predicted_label:
        q = q.filter(DetectionCorrection.predicted_label.ilike(predicted_label))
    if corrected_label:
        q = q.filter(DetectionCorrection.corrected_label.ilike(corrected_label))
    return (
        q.order_by(DetectionCorrection.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/export")
def export_corrections(
    kind: CorrectionKind = Query(
        CorrectionKind.salah_label,
        description="salah_label = contoh latih berlabel benar; bukan_kata = contoh negatif",
    ),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """
    Data latih siap pakai, format JSON Lines: satu baris satu sampel berisi
    {"label", "predicted", "sequence": [[...63], x15], "confidence", "mode"}.

    JSONL (bukan satu array JSON) supaya notebook pelatihan bisa membacanya
    baris demi baris tanpa memuat semuanya ke memori, dan supaya ekspor
    berikutnya bisa langsung disambung ke file yang sama.

    ⚠️ Saat melatih ulang, koreksi ini WAJIB dicampur dengan dataset asli —
    melatih HANYA dengan koreksi akan membuat model melupakan 45 kelas lainnya
    (catastrophic forgetting), dan hasilnya harus diuji ulang dengan test set
    lama sebelum dipakai.
    """
    rows = (
        db.query(DetectionCorrection)
        .filter(DetectionCorrection.kind == kind)
        .order_by(DetectionCorrection.id.asc())
        .all()
    )

    def baris():
        for r in rows:
            yield json.dumps({
                "id": r.id,
                "label": r.corrected_label,
                "predicted": r.predicted_label,
                "confidence": r.confidence,
                "mode": r.mode,
                "sequence": json.loads(r.sequence),
            }) + "\n"

    return StreamingResponse(
        baris(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="koreksi_deteksi.jsonl"'},
    )
