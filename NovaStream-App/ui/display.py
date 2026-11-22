"""Ekranda gösterilen metinlerin ortak biçimlendirmesi (tablo ve ilerleme penceresi aynı kuralı kullanır)."""

import datetime
import re

STATUS_LABELS = {
    "downloading": "İndiriliyor",
    "completed": "Tamamlandı",
    "paused": "Duraklatıldı",
    "queued": "Kuyrukta",
    "error": "Hata",
}

# Kategori anahtarları veride İngilizce saklanır; ekranda Türkçe gösterilir
CATEGORY_LABELS = {
    "Videos": "Video", "Music": "Müzik", "Compressed": "Arşiv",
    "Documents": "Belge", "Programs": "Program", "Others": "Diğer",
}

_MONTHS_TR = ("Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara")
_SPEED_RE = re.compile(r"^\s*[\d.,]+\s*[KMGT]?i?B/s\s*$")
_IDLE_ETA = ("--:--", "Son işlem")


def split_stage_speed(speed_text):
    """
    İndirme motoru aşama bilgisini hız metnine gömüyor ("Ses 1/2 (TR): 312 KB/s", "Bağlanıyor...").
    Ekranda aşama durum metnine, sayı hız alanına gider. (aşama, hız) döndürür.
    """
    text = (speed_text or "").strip()
    if not text or text in ("Tamamlandı", "Hata", "Duraklatıldı"):
        return "", ""
    if _SPEED_RE.match(text):
        return "", text
    if ":" in text:
        stage, _, rest = text.rpartition(":")
        if _SPEED_RE.match(rest):
            stage = re.sub(r"\(([A-Za-z]{2,3})\)", r"· \1", stage.strip())
            return stage, rest.strip()
    return text.rstrip(". "), ""


def eta_text(task):
    """Kalan süre yalnızca inen indirmede anlamlı; aksi halde boş."""
    if task.status == "downloading" and task.eta and task.eta not in _IDLE_ETA:
        return task.eta
    return ""


def format_added(created_at):
    """'2026-11-22 17:19:11' -> 'Bugün 17:19' / 'Dün 17:19' / '20 Kas 17:19' / '20 Kas 2025'."""
    try:
        dt = datetime.datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return created_at or ""
    today = datetime.date.today()
    if dt.date() == today:
        return f"Bugün {dt:%H:%M}"
    if dt.date() == today - datetime.timedelta(days=1):
        return f"Dün {dt:%H:%M}"
    month = _MONTHS_TR[dt.month - 1]
    if dt.year == today.year:
        return f"{dt.day} {month} {dt:%H:%M}"
    return f"{dt.day} {month} {dt.year}"
