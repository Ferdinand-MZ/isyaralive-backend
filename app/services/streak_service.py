from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.user import User


def bump_streak(db: Session, user: User) -> None:
    """
    Update winstreak belajar user. Dipanggil tiap ada aktivitas belajar
    (materi ditandai 'Sudah Dipelajari' / jawaban kuis benar).

    Aturan:
    - Aktivitas PERTAMA di suatu hari, dan kemarin juga ada aktivitas
      -> current_streak +1 (streak lanjut).
    - Aktivitas pertama di suatu hari, tapi kemarin TIDAK ada aktivitas
      (atau ini aktivitas pertama user) -> current_streak reset ke 1.
    - Aktivitas kedua dst di HARI YANG SAMA -> tidak ada perubahan
      (winstreak dihitung per hari, bukan per aksi).
    """
    today = date.today()

    if user.last_activity_date == today:
        return  # sudah dihitung hari ini, tidak ada perubahan

    if user.last_activity_date == today - timedelta(days=1):
        user.current_streak = (user.current_streak or 0) + 1
    else:
        user.current_streak = 1

    user.longest_streak = max(user.longest_streak or 0, user.current_streak)
    user.last_activity_date = today

    db.add(user)
    db.commit()
