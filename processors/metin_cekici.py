"""
processors/metin_cekici.py

Haber URL'sinden tam metin çeker.
Öncelik: Trafilatura → Jina AI Reader → RSS ham özeti
"""

import random
import time

import requests
import trafilatura

from core.logger import get_logger

logger = get_logger("gundem.metin")

TIMEOUT = 15
JINA_BASE = "https://r.jina.ai/"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _rastgele_ua() -> str:
    return random.choice(USER_AGENTS)


def _trafilatura_ile_cek(url: str) -> str | None:
    try:
        indirilen = trafilatura.fetch_url(
            url,
            headers={"User-Agent": _rastgele_ua()},
        )
        if not indirilen:
            return None
        metin = trafilatura.extract(
            indirilen,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if metin and len(metin.strip()) > 100:
            return metin.strip()
        return None
    except Exception as e:
        logger.debug(f"Trafilatura hatası ({url[:60]}): {e}")
        return None


def _jina_ile_cek(url: str) -> str | None:
    try:
        jina_url = f"{JINA_BASE}{url}"
        resp = requests.get(
            jina_url,
            headers={
                "User-Agent": _rastgele_ua(),
                "Accept": "text/plain",
            },
            timeout=TIMEOUT,
        )
        if resp.status_code == 200 and len(resp.text.strip()) > 100:
            # Jina markdown başlıklarını ve meta bilgilerini temizle
            satirlar = resp.text.split("\n")
            icerik_satirlar = [
                s for s in satirlar
                if s.strip() and not s.startswith("Title:")
                and not s.startswith("URL Source:")
                and not s.startswith("Published Time:")
                and not s.startswith("=====")
            ]
            temiz = "\n".join(icerik_satirlar).strip()
            if len(temiz) > 100:
                return temiz
        return None
    except Exception as e:
        logger.debug(f"Jina hatası ({url[:60]}): {e}")
        return None


def metin_cek(url: str, rss_ozet: str = "") -> dict:
    """
    Tam metni çeker.

    Dönüş:
        {
            "metin": str,
            "kaynak": "trafilatura" | "jina" | "rss_fallback"
        }
    """
    # 1. Trafilatura
    metin = _trafilatura_ile_cek(url)
    if metin:
        logger.debug(f"Trafilatura başarılı: {url[:60]}")
        return {"metin": metin, "kaynak": "trafilatura"}

    # 2. Jina AI Reader
    time.sleep(0.5)  # Agresif istek önleme
    metin = _jina_ile_cek(url)
    if metin:
        logger.debug(f"Jina başarılı: {url[:60]}")
        return {"metin": metin, "kaynak": "jina"}

    # 3. RSS fallback
    if rss_ozet and len(rss_ozet.strip()) > 20:
        logger.debug(f"RSS fallback kullanıldı: {url[:60]}")
        return {"metin": rss_ozet.strip(), "kaynak": "rss_fallback"}

    logger.warning(f"Metin çekilemedi: {url[:60]}")
    return {"metin": "", "kaynak": "bos"}
