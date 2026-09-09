"""
Uji end-to-end alur voting komunitas + DELETE submission, lewat HTTP nyata.

Dijalankan terhadap server yang SEDANG berjalan (default 127.0.0.1:8000).
Semua data yang dipakai dibuat sendiri oleh skrip ini dan dibersihkan lagi di
akhir — baris milik pengguna asli tidak disentuh.

    python scripts/uji_alur_voting.py [base_url]
"""

import os
import sqlite3
import sys
import uuid
from datetime import datetime

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database.db")

lolos, gagal = 0, 0


def cek(nama: str, syarat: bool, keterangan: str = ""):
    global lolos, gagal
    if syarat:
        lolos += 1
        print(f"  OK   {nama}")
    else:
        gagal += 1
        print(f"  GAGAL {nama} {keterangan}")


def daftar(nama: str) -> tuple[int, str]:
    """Buat akun uji, kembalikan (user_id, token)."""
    # Domain sungguhan (bukan .test/.example): email-validator menolak
    # nama domain yang berstatus special-use.
    email = f"uji-{uuid.uuid4().hex[:10]}@isyaralive-uji.id"
    r = httpx.post(
        f"{BASE}/auth/register",
        json={"name": nama, "email": email, "password": "rahasia123"},
        timeout=15,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    with sqlite3.connect(DB) as c:
        uid = c.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
    return uid, token


def jadikan_admin(user_id: int):
    with sqlite3.connect(DB) as c:
        c.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user_id,))


def poin(user_id: int) -> int:
    with sqlite3.connect(DB) as c:
        return c.execute("SELECT points FROM users WHERE id = ?", (user_id,)).fetchone()[0] or 0


def unggah(token: str, label: str) -> dict:
    berkas = ("uji.mp4", b"bukan-video-sungguhan-tapi-cukup-untuk-uji", "video/mp4")
    r = httpx.post(
        f"{BASE}/submissions/",
        headers={"Authorization": f"Bearer {token}"},
        data={"label": label, "category": "lainnya"},
        files={"video": berkas},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def bersihkan(user_ids: list[int], submission_ids: list[int]):
    with sqlite3.connect(DB) as c:
        for sid in submission_ids:
            baris = c.execute(
                "SELECT video_path FROM gesture_submissions WHERE id = ?", (sid,)
            ).fetchone()
            if baris:
                try:
                    os.remove(baris[0])
                except OSError:
                    pass
            c.execute("DELETE FROM votes WHERE submission_id = ?", (sid,))
            c.execute("DELETE FROM gesture_submissions WHERE id = ?", (sid,))
        for uid in user_ids:
            c.execute("DELETE FROM votes WHERE user_id = ?", (uid,))
            c.execute("DELETE FROM point_logs WHERE user_id = ?", (uid,))
            c.execute("DELETE FROM users WHERE id = ?", (uid,))


def main():
    admin_id, admin_token = daftar("Admin Uji")
    jadikan_admin(admin_id)
    kontributor_id, kontributor_token = daftar("Kontributor Uji")
    pemilih_id, pemilih_token = daftar("Pemilih Uji")

    A = {"Authorization": f"Bearer {admin_token}"}
    P = {"Authorization": f"Bearer {pemilih_token}"}

    dibuat: list[int] = []
    try:
        # ---------- 1. pending -> voting ----------
        print("\n[1] POST /admin/submissions/{id}/open-voting")
        s = unggah(kontributor_token, "uji-voting")
        dibuat.append(s["id"])
        cek("unggahan baru berstatus pending", s["status"] == "pending", s["status"])

        poin_awal = poin(kontributor_id)

        r = httpx.post(
            f"{BASE}/admin/submissions/{s['id']}/open-voting",
            headers=A, json={"admin_note": "lolos verifikasi"}, timeout=15,
        )
        cek("balasan 200", r.status_code == 200, r.text[:200])
        v = r.json()
        cek("status jadi voting", v["status"] == "voting", v.get("status"))
        cek("voting_started_at terisi", v["voting_started_at"] is not None)
        cek("voting_ends_at terisi", v["voting_ends_at"] is not None)

        mulai = datetime.fromisoformat(v["voting_started_at"])
        selesai = datetime.fromisoformat(v["voting_ends_at"])
        cek("jendela voting 7 hari", (selesai - mulai).days == 7, str(selesai - mulai))

        cek("video pindah ke uploads/voting",
            v["video_path"].replace("\\", "/").startswith("uploads/voting/"), v["video_path"])
        berkas = os.path.basename(v["video_path"])
        rs = httpx.get(f"{BASE}/static/voting/{berkas}", timeout=15)
        cek("video bisa diambil dari /static/voting", rs.status_code == 200, str(rs.status_code))

        cek("BELUM dapat poin saat voting dibuka", poin(kontributor_id) == poin_awal,
            f"{poin_awal} -> {poin(kontributor_id)}")

        # ---------- 2. tampil di feed publik & daftar admin ----------
        print("\n[2] feed status=voting")
        r = httpx.get(f"{BASE}/submissions/", params={"status": "voting"}, timeout=15)
        cek("GET /submissions/?status=voting memuat item",
            r.status_code == 200 and any(i["id"] == s["id"] for i in r.json()), r.text[:200])

        r = httpx.get(f"{BASE}/submissions/", timeout=15)
        cek("feed default (approved) TIDAK memuatnya",
            all(i["id"] != s["id"] for i in r.json()))

        r = httpx.get(f"{BASE}/admin/submissions/voting", headers=A, timeout=15)
        cek("GET /admin/submissions/voting memuat item",
            r.status_code == 200 and any(i["id"] == s["id"] for i in r.json()), r.text[:200])

        r = httpx.get(f"{BASE}/admin/submissions/voting", timeout=15)
        cek("daftar voting ditolak tanpa token", r.status_code in (401, 403), str(r.status_code))

        # ---------- 3. vote komunitas ----------
        print("\n[3] vote komunitas")
        r = httpx.post(f"{BASE}/submissions/{s['id']}/vote", headers=P,
                       json={"type": "upvote"}, timeout=15)
        cek("upvote diterima", r.status_code == 200, r.text[:200])
        cek("hitungan upvote = 1", r.json()["upvotes"] == 1, r.text[:200])

        r = httpx.get(f"{BASE}/submissions/{s['id']}", headers=P, timeout=15)
        cek("detail memuat my_vote pemilih", r.json()["my_vote"] == "upvote", r.text[:200])

        # ---------- 4. open-voting dua kali ditolak ----------
        print("\n[4] penjagaan status")
        r = httpx.post(f"{BASE}/admin/submissions/{s['id']}/open-voting",
                       headers=A, json={"admin_note": None}, timeout=15)
        cek("buka voting untuk item yang sudah voting → 409", r.status_code == 409, str(r.status_code))

        # ---------- 5. voting -> dataset ----------
        print("\n[5] voting -> approve (masuk dataset)")
        poin_sebelum = poin(kontributor_id)
        r = httpx.post(f"{BASE}/admin/submissions/{s['id']}/approve",
                       headers=A, json={"admin_note": "hasil voting bagus"}, timeout=15)
        cek("approve dari status voting berhasil", r.status_code == 200, r.text[:200])
        a = r.json()
        cek("status jadi approved", a["status"] == "approved", a.get("status"))
        cek("video pindah ke uploads/approved",
            a["video_path"].replace("\\", "/").startswith("uploads/approved/"), a["video_path"])
        cek("jejak voting tetap tersimpan", a["voting_ends_at"] is not None)
        cek("hitungan vote ikut di balasan admin", a["upvotes"] == 1, str(a["upvotes"]))
        cek("dapat +10 poin saat masuk dataset", poin(kontributor_id) == poin_sebelum + 10,
            f"{poin_sebelum} -> {poin(kontributor_id)}")

        # ---------- 6. DELETE ----------
        print("\n[6] DELETE /admin/submissions/{id}")
        s2 = unggah(kontributor_token, "uji-hapus")
        dibuat.append(s2["id"])
        httpx.post(f"{BASE}/admin/submissions/{s2['id']}/open-voting",
                   headers=A, json={"admin_note": None}, timeout=15)
        httpx.post(f"{BASE}/submissions/{s2['id']}/vote", headers=P,
                   json={"type": "upvote"}, timeout=15)
        httpx.post(f"{BASE}/admin/submissions/{s2['id']}/approve",
                   headers=A, json={"admin_note": None}, timeout=15)

        r = httpx.get(f"{BASE}/submissions/{s2['id']}", timeout=15)
        jalur = r.json()["video_path"]
        cek("berkas ada di disk sebelum dihapus", os.path.exists(jalur), jalur)
        poin_sebelum_hapus = poin(kontributor_id)

        with sqlite3.connect(DB) as c:
            vote_sebelum = c.execute(
                "SELECT COUNT(*) FROM votes WHERE submission_id = ?", (s2["id"],)
            ).fetchone()[0]
        cek("vote tercatat sebelum dihapus", vote_sebelum == 1, str(vote_sebelum))

        r = httpx.delete(f"{BASE}/admin/submissions/{s2['id']}", headers=A, timeout=15)
        cek("DELETE membalas 204", r.status_code == 204, f"{r.status_code} {r.text[:200]}")

        r = httpx.get(f"{BASE}/submissions/{s2['id']}", timeout=15)
        cek("detail jadi 404", r.status_code == 404, str(r.status_code))

        with sqlite3.connect(DB) as c:
            baris = c.execute(
                "SELECT COUNT(*) FROM gesture_submissions WHERE id = ?", (s2["id"],)
            ).fetchone()[0]
            sisa_vote = c.execute(
                "SELECT COUNT(*) FROM votes WHERE submission_id = ?", (s2["id"],)
            ).fetchone()[0]
            log_nyangkut = c.execute(
                "SELECT COUNT(*) FROM point_logs WHERE submission_id = ?", (s2["id"],)
            ).fetchone()[0]
        cek("baris submission hilang", baris == 0, str(baris))
        cek("vote ikut terhapus", sisa_vote == 0, str(sisa_vote))
        cek("point_logs dilepas, bukan menggantung", log_nyangkut == 0, str(log_nyangkut))
        cek("berkas video terhapus dari disk", not os.path.exists(jalur), jalur)

        # +10 approve dan +1 upvote lahir dari submission ini → keduanya ditarik.
        cek("poin dari submission ditarik kembali",
            poin(kontributor_id) == poin_sebelum_hapus - 11,
            f"{poin_sebelum_hapus} -> {poin(kontributor_id)}")

        r = httpx.delete(f"{BASE}/admin/submissions/{s2['id']}", headers=A, timeout=15)
        cek("DELETE ulang → 404", r.status_code == 404, str(r.status_code))

        # ---------- 7. penjagaan peran ----------
        print("\n[7] penjagaan peran")
        s3 = unggah(kontributor_token, "uji-peran")
        dibuat.append(s3["id"])
        r = httpx.delete(f"{BASE}/admin/submissions/{s3['id']}", headers=P, timeout=15)
        cek("DELETE oleh non-admin → 403", r.status_code == 403, str(r.status_code))
        r = httpx.delete(f"{BASE}/admin/submissions/{s3['id']}", timeout=15)
        cek("DELETE tanpa token → 401/403", r.status_code in (401, 403), str(r.status_code))
        r = httpx.post(f"{BASE}/admin/submissions/{s3['id']}/open-voting",
                       headers=P, json={"admin_note": None}, timeout=15)
        cek("open-voting oleh non-admin → 403", r.status_code == 403, str(r.status_code))

        r = httpx.delete(f"{BASE}/admin/submissions/999999", headers=A, timeout=15)
        cek("DELETE id tak dikenal → 404", r.status_code == 404, str(r.status_code))
    finally:
        bersihkan([admin_id, kontributor_id, pemilih_id], dibuat)
        print("\n(data uji dibersihkan)")

    print(f"\n{lolos} lolos, {gagal} gagal")
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())
