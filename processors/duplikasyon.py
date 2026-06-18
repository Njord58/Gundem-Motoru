"""
processors/duplikasyon.py

Başlık benzerliği ile duplikasyon tespiti.
difflib.SequenceMatcher kullanır, harici bağımlılık yok.
"""

from difflib import SequenceMatcher

from core.config import get_config
from core.logger import get_logger

logger = get_logger("gundem.duplikasyon")


def _benzerlik(a: str, b: str) -> float:
    """İki başlık arasındaki benzerlik oranını 0-1 arasında döndürür."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def duplikasyon_mu(yeni_baslik: str, mevcut_basliklar: list[str]) -> bool:
    """
    Yeni başlık, mevcut başlıklardan biriyle eşik üzerinde benziyorsa True döner.

    Args:
        yeni_baslik: Kontrol edilecek yeni haber başlığı
        mevcut_basliklar: Son N saatteki mevcut başlıklar listesi

    Returns:
        True → duplike, işleme alma
        False → yeni haber, işleme devam et
    """
    if not yeni_baslik or not mevcut_basliklar:
        return False

    cfg = get_config()
    esik = cfg.duplikasyon_esik

    for mevcut in mevcut_basliklar:
        oran = _benzerlik(yeni_baslik, mevcut)
        if oran >= esik:
            logger.debug(
                f"Duplike tespit edildi ({oran:.2f}): '{yeni_baslik[:50]}'"
            )
            return True

    return False


def duplikasyon_filtrele(
    haberler: list[dict],
    mevcut_basliklar: list[str],
) -> list[dict]:
    """
    Haber listesinden duplikeleri çıkarır.
    Hem veritabanındaki mevcut başlıkları hem listenin kendi içindeki
    tekrarları kontrol eder.

    Args:
        haberler: İşlenecek ham haber listesi
        mevcut_basliklar: Veritabanındaki son 24 saatin başlıkları

    Returns:
        Duplikasyon filtresi geçmiş temiz haber listesi
    """
    if not haberler:
        return []

    temiz: list[dict] = []
    # Bu batch içinde görülen başlıkları da takip et
    bu_tur_basliklar = list(mevcut_basliklar)

    for haber in haberler:
        baslik = haber.get("baslik", "")
        if duplikasyon_mu(baslik, bu_tur_basliklar):
            continue
        temiz.append(haber)
        bu_tur_basliklar.append(baslik)

    atilan = len(haberler) - len(temiz)
    if atilan:
        logger.info(f"Duplikasyon filtresi: {atilan} haber atıldı, {len(temiz)} kaldı.")

    return temiz
