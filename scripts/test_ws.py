"""
PENGUJI WEBSOCKET /ws/detect
============================
Mengirim sebuah video gestur ke backend seolah-olah datang dari aplikasi,
lalu mencetak transkrip hasil deteksi + statistik latensi per frame.

Dipakai untuk dua hal:
1. Memastikan pipeline WebSocket benar-benar jalan tanpa menunggu Flutter siap.
2. Mengukur latensi nyata untuk dibandingkan dengan target < 500 ms.

Butuh: pip install websockets

Cara pakai:
    # mode landmark (MediaPipe di sisi klien, seperti rencana di aplikasi)
    python scripts/test_ws.py --video /path/video.mp4 --mode landmark

    # mode frame (JPEG dikirim ke server, server yang ekstrak landmark)
    python scripts/test_ws.py --video /path/video.mp4 --mode frame

    # bandingkan keduanya sekaligus
    python scripts/test_ws.py --video /path/video.mp4 --mode both

    # UJI LANGSUNG DARI WEBCAM (tanpa perlu file video)
    python scripts/test_ws.py --camera --mode landmark
    python scripts/test_ws.py --camera --preview       # tampilkan jendela kamera + skeleton

Catatan: pada mode landmark, script ini menjalankan MediaPipe secara lokal
untuk meniru ekstraksi on-device. Waktu ekstraksi itu TIDAK dihitung sebagai
latensi jaringan, tapi dilaporkan terpisah supaya gambarannya utuh.
"""

import argparse
import asyncio
import base64
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2

try:
    import websockets
except ImportError:
    print("Butuh paket websockets. Jalankan: pip install websockets")
    sys.exit(1)

from app.services.detector_instance import detector


def baca_frame(video_path: str, frame_skip: int):
    """Ambil frame dari video dengan pola yang sama seperti saat training (10%-90%)."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Video tidak bisa dibuka: {video_path}")
        sys.exit(1)

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    start, end = int(total * 0.10), int(total * 0.90)

    frames = []
    idx = 0
    while True:
        ret = cap.grab()
        if not ret:
            break
        if start <= idx <= end and (idx - start) % frame_skip == 0:
            ok, frame = cap.retrieve()
            if ok:
                frames.append(frame)
        idx += 1
    cap.release()
    return frames


async def jalankan_kamera(url: str, mode: str, token: str | None,
                          device: int, preview: bool, durasi: int):
    """
    Streaming langsung dari webcam sampai Ctrl+C (atau tombol q di jendela preview).
    Ini paling mendekati kondisi demo: pencahayaan ruangan, jarak tangan ke kamera,
    dan kecepatan gerak yang sebenarnya.
    """
    uri = f"{url}/ws/detect" + (f"?token={token}" if token else "")

    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        print(f"Kamera index {device} tidak bisa dibuka. Coba --device 1 atau 2.")
        return None

    latensi = []
    kata_terdeteksi = []
    transkrip_akhir = ""
    t_mulai = time.time()
    n_frame = 0

    print("\n  Peragakan gestur ke kamera. Tekan Ctrl+C untuk berhenti"
          + (" (atau 'q' di jendela preview)." if preview else "."))
    print("  " + "-" * 50)

    async with websockets.connect(uri, max_size=None) as ws:
        awal = json.loads(await ws.recv())
        if awal.get("type") == "auth_error":
            print(f"Token ditolak: {awal.get('message')}")
            cap.release()
            return None

        try:
            while True:
                if durasi and (time.time() - t_mulai) > durasi:
                    break

                ok, frame = cap.read()
                if not ok:
                    break
                n_frame += 1

                lm = None
                if mode == "landmark":
                    lm = detector.extract_landmarks(frame)
                    payload = {
                        "landmarks": None if lm is None else [float(v) for v in lm],
                        "t": time.time() * 1000,
                    }
                else:
                    ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if not ok2:
                        continue
                    payload = {"frame": base64.b64encode(buf).decode()}

                t0 = time.perf_counter()
                await ws.send(json.dumps(payload))
                balasan = json.loads(await ws.recv())
                latensi.append((time.perf_counter() - t0) * 1000)

                if balasan.get("is_new_word"):
                    kata_terdeteksi.append(balasan["label"])
                    print(f"  >> {balasan['label']}  (confidence {balasan['confidence']})")
                transkrip_akhir = balasan.get("transcript", transkrip_akhir)

                if preview:
                    gambar_overlay(frame, lm if lm is not None else balasan.get("landmarks"),
                                   balasan, n_frame)
                    cv2.imshow("IsyaraLive - uji WebSocket (tekan q untuk keluar)", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                await asyncio.sleep(0)  # beri ruang ke event loop
        except KeyboardInterrupt:
            print("\n  Dihentikan.")
        finally:
            cap.release()
            if preview:
                cv2.destroyAllWindows()

    return {
        "mode": mode + " (kamera)",
        "frame": n_frame,
        "latensi": latensi,
        "ekstraksi": [],
        "transkrip": transkrip_akhir,
        "kata": kata_terdeteksi,
    }


def gambar_overlay(frame, landmarks, balasan, n_frame):
    """Skeleton + status buffer di atas frame kamera, untuk pengecekan visual."""
    h, w = frame.shape[:2]

    if landmarks and len(landmarks) == 63:
        titik = [(int(landmarks[i * 3] * w), int(landmarks[i * 3 + 1] * h)) for i in range(21)]
        koneksi = [(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),
                   (10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),
                   (17,18),(18,19),(19,20),(0,17)]
        for a, b in koneksi:
            cv2.line(frame, titik[a], titik[b], (166, 166, 0), 2)
        for p in titik:
            cv2.circle(frame, p, 4, (110, 118, 15), -1)

    buffer_size = balasan.get("buffer_size", 0)
    label = balasan.get("label") or "-"
    conf = balasan.get("confidence", 0)

    cv2.rectangle(frame, (0, 0), (w, 70), (0, 0, 0), -1)
    cv2.putText(frame, f"buffer {buffer_size}/15", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    warna = (0, 220, 0) if balasan.get("detected") else (140, 140, 140)
    cv2.putText(frame, f"{label}  ({conf})", (10, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, warna, 2)

    transkrip = balasan.get("transcript", "")
    if transkrip:
        cv2.rectangle(frame, (0, h - 40), (w, h), (0, 0, 0), -1)
        cv2.putText(frame, transkrip[-60:], (10, h - 13),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)


async def jalankan(url: str, frames: list, mode: str, token: str | None):
    uri = f"{url}/ws/detect" + (f"?token={token}" if token else "")

    latensi = []
    waktu_ekstraksi = []
    transkrip_akhir = ""
    kata_terdeteksi = []

    async with websockets.connect(uri, max_size=None) as ws:
        pesan_awal = json.loads(await ws.recv())
        if pesan_awal.get("type") == "auth_error":
            print(f"Token ditolak: {pesan_awal.get('message')}")
            return None
        print(f"  Terhubung. model_loaded={pesan_awal.get('model_loaded')}")

        for frame in frames:
            if mode == "landmark":
                t_ext = time.perf_counter()
                lm = detector.extract_landmarks(frame)
                waktu_ekstraksi.append((time.perf_counter() - t_ext) * 1000)
                payload = {
                    "landmarks": None if lm is None else [float(v) for v in lm],
                    "t": time.time() * 1000,
                }
            else:
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    continue
                payload = {"frame": base64.b64encode(buf).decode()}

            t0 = time.perf_counter()
            await ws.send(json.dumps(payload))
            balasan = json.loads(await ws.recv())
            latensi.append((time.perf_counter() - t0) * 1000)

            if balasan.get("is_new_word"):
                kata_terdeteksi.append(balasan["label"])
                print(f"    + {balasan['label']} (confidence {balasan['confidence']})")

            transkrip_akhir = balasan.get("transcript", transkrip_akhir)

    return {
        "mode": mode,
        "frame": len(frames),
        "latensi": latensi,
        "ekstraksi": waktu_ekstraksi,
        "transkrip": transkrip_akhir,
        "kata": kata_terdeteksi,
    }


def cetak_ringkasan(hasil: dict, ukuran_payload_kb: float | None = None):
    lat = hasil["latensi"]
    if not lat:
        print("  Tidak ada balasan sama sekali.")
        return

    print(f"\n  === MODE {hasil['mode'].upper()} ===")
    print(f"  Frame dikirim      : {hasil['frame']}")
    print(f"  Latensi rata-rata  : {statistics.mean(lat):.1f} ms")
    print(f"  Latensi median     : {statistics.median(lat):.1f} ms")
    if len(lat) >= 20:
        p95 = sorted(lat)[int(len(lat) * 0.95)]
        print(f"  Latensi p95        : {p95:.1f} ms")
    print(f"  Latensi maksimum   : {max(lat):.1f} ms")

    if hasil["ekstraksi"]:
        print(f"  Ekstraksi on-device: {statistics.mean(hasil['ekstraksi']):.1f} ms/frame (di luar latensi jaringan)")

    target = 500
    rata = statistics.mean(lat)
    status = "LOLOS" if rata < target else "TIDAK LOLOS"
    print(f"  Target < {target} ms     : {status}")

    print(f"  Transkrip          : {hasil['transkrip'] or '(kosong)'}")


async def main():
    parser = argparse.ArgumentParser(description="Uji WebSocket /ws/detect")
    parser.add_argument("--video", help="Path video gestur untuk diuji")
    parser.add_argument("--camera", action="store_true", help="Uji langsung dari webcam")
    parser.add_argument("--device", type=int, default=0, help="Index kamera (default 0)")
    parser.add_argument("--preview", action="store_true", help="Tampilkan jendela kamera + skeleton")
    parser.add_argument("--durasi", type=int, default=0, help="Batas detik untuk mode kamera (0 = tanpa batas)")
    parser.add_argument("--url", default="ws://localhost:8000", help="Alamat backend")
    parser.add_argument("--mode", default="landmark", choices=["landmark", "frame", "both"])
    parser.add_argument("--frame-skip", type=int, default=2, help="Sama seperti RAW_FRAME_SKIP saat training")
    parser.add_argument("--token", default=None, help="JWT opsional")
    args = parser.parse_args()

    if args.camera:
        if args.mode == "both":
            print("Mode 'both' hanya untuk file video. Untuk kamera pilih landmark atau frame.")
            return
        print(f"Menguji dari kamera (mode: {args.mode})")
        hasil = await jalankan_kamera(args.url, args.mode, args.token,
                                      args.device, args.preview, args.durasi)
        if hasil:
            cetak_ringkasan(hasil)
            if hasil["kata"]:
                print(f"  Kata terdeteksi    : {len(hasil['kata'])} -> {', '.join(hasil['kata'])}")
        return

    if not args.video:
        print("Pilih salah satu: --video <path> atau --camera")
        return

    print(f"Membaca video: {args.video}")
    frames = baca_frame(args.video, args.frame_skip)
    print(f"Frame terkumpul: {len(frames)}\n")

    if len(frames) < 15:
        print("Frame kurang dari 15 — buffer tidak akan pernah penuh, tidak ada prediksi.")
        return

    mode_list = ["landmark", "frame"] if args.mode == "both" else [args.mode]
    semua = []

    for mode in mode_list:
        print(f"Menguji mode: {mode}")
        hasil = await jalankan(args.url, frames, mode, args.token)
        if hasil:
            semua.append(hasil)

    for hasil in semua:
        cetak_ringkasan(hasil)

    if len(semua) == 2:
        a = statistics.mean(semua[0]["latensi"])
        b = statistics.mean(semua[1]["latensi"])
        lebih_cepat = semua[0] if a < b else semua[1]
        selisih = abs(a - b)
        print(f"\n  Mode {lebih_cepat['mode']} lebih cepat {selisih:.1f} ms per frame "
              f"({max(a, b) / max(min(a, b), 0.001):.1f}x).")


if __name__ == "__main__":
    asyncio.run(main())