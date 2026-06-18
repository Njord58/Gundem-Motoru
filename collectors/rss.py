"""
collectors/rss.py

Paralel RSS çekimi, ETag/Last-Modified optimizasyonu, devre kesici.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser
import requests

from core.config import get_config, RssKaynak
from core.database import get_db
from core.logger import get_logger

logger = get_logger("gundem.rss")

TIMEOUT = 10
USER_AGENT = (
    "Mozilla/5.0 (compatible; GundemMotoru/1.0; +https://github.com/gundem-motoru)"
)


def _devre_acik_mi(isim: str) -> bool:
    """Kaynağın devre kesici durumunu kontrol eder."""
    cfg = get_config()
    durum = get_db().kaynak_durum_getir(isim)
    kapali_ts = durum.get("devre_kapali_ts", 0)
    if kapali_ts == 0:
        return True
    gecen = time.time() - kapali_ts
    timeout_sn = cfg.circuit_breaker_timeout_minutes * 60
    if gecen >= timeout_sn:
        # Süre doldu, devreyi sıfırla
        get_db().kaynak_durum_guncelle(
            isim, hata_sayisi=0, devre_kapali_ts=0
        )
        logger.info(f"[{isim}] Devre yeniden açıldı.")
        return True
    kalan = int((timeout_sn - gecen) / 60)
    logger.debug(f"[{isim}] Devre kapalı, {kalan} dk kaldı.")
    return False


def _hata_kaydet(isim: str):
    cfg = get_config()
    db = get_db()
    durum = db.kaynak_durum_getir(isim)
    yeni_hata = durum.get("hata_sayisi", 0) + 1
    kapali_ts = durum.get("devre_kapali_ts", 0)

    if yeni_hata >= cfg.circuit_breaker_threshold and kapali_ts == 0:
        kapali_ts = int(time.time())
        logger.warning(
            f"[{isim}] {yeni_hata} ardışık hata → devre kesildi, "
            f"{cfg.circuit_breaker_timeout_minutes} dk bekleniyor."
        )

    db.kaynak_durum_guncelle(
        isim, hata_sayisi=yeni_hata, devre_kapali_ts=kapali_ts
    )


def _basari_kaydet(isim: str, etag: str | None, modified: str | None):
    get_db().kaynak_durum_guncelle(
        isim,
        son_etag=etag,
        son_modified=modified,
        hata_sayisi=0,
        devre_kapali_ts=0,
        son_basari_ts=int(time.time()),
    )


def _kaynak_cek(kaynak: RssKaynak) -> list[dict]:
    """Tek bir RSS kaynağını çeker ve ham haber listesi döndürür."""
    isim = kaynak.isim

    if not _devre_acik_mi(isim):
        return []

    db = get_db()
    durum = db.kaynak_durum_getir(isim)

    headers = {"User-Agent": USER_AGENT}
    if durum.get("son_etag"):
        headers["If-None-Match"] = durum["son_etag"]
    if durum.get("son_modified"):
        headers["If-Modified-Since"] = durum["son_modified"]

    try:
        resp = requests.get(kaynak.url, headers=headers, timeout=TIMEOUT)

        if resp.status_code == 304:
            logger.debug(f"[{isim}] Feed değişmemiş (304), atlandı.")
            return []

        if resp.status_code != 200:
            logger.warning(f"[{isim}] HTTP {resp.status_code}")
            _hata_kaydet(isim)
            return []

        feed = feedparser.parse(resp.content)

        if feed.bozo and not feed.entries:
            logger.warning(f"[{isim}] Geçersiz feed: {feed.bozo_exception}")
            _hata_kaydet(isim)
            return []

        etag = resp.headers.get("ETag") or getattr(feed, "etag", None)
        modified = resp.headers.get("Last-Modified") or getattr(feed, "modified", None)
        _basari_kaydet(isim, etag, modified)

        haberler = []
        for entry in feed.entries:
            url = entry.get("link", "").strip()
            baslik = entry.get("title", "").strip()
            if not url or not baslik:
                continue

            # Ham özet — metin_cekici bunu daha sonra genişletecek
            ozet = (
                entry.get("summary", "")
                or entry.get("description", "")
                or ""
            ).strip()

            # Görsel: media_content veya enclosure
            gorsel = None
            if entry.get("media_content"):
                gorsel = entry["media_content"][0].get("url")
            elif entry.get("enclosures"):
                enc = entry["enclosures"][0]
                if enc.get("type", "").startswith("image"):
                    gorsel = enc.get("href")

            # Yayın tarihi
            yayin_ts = None
            if entry.get("published_parsed"):
                try:
                    yayin_ts = int(time.mktime(entry["published_parsed"]))
                except Exception:
                    pass
            if not yayin_ts and entry.get("updated_parsed"):
                try:
                    yayin_ts = int(time.mktime(entry["updated_parsed"]))
                except Exception:
                    pass
            if not yayin_ts:
                yayin_ts = int(time.time())

            haberler.append({
                "baslik": baslik,
                "url": url,
                "ozet_ham": ozet,
                "gorsel_url": gorsel,
                "kaynak": isim,
                "yayin_ts": yayin_ts,
            })

        logger.info(f"[{isim}] {len(haberler)} haber alındı.")
        return haberler

    except requests.Timeout:
        logger.warning(f"[{isim}] Zaman aşımı.")
        _hata_kaydet(isim)
        return []
    except Exception as e:
        logger.error(f"[{isim}] Beklenmeyen hata: {e}")
        _hata_kaydet(isim)
        return []


def tum_kaynaklardan_cek() -> list[dict]:
    """Tüm aktif RSS kaynaklarını paralel çeker, birleşik liste döndürür."""
    cfg = get_config()
    aktif = [k for k in cfg.rss_kaynaklar if k.aktif]

    if not aktif:
        logger.warning("Aktif RSS kaynağı yok.")
        return []

    sonuclar: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(aktif)) as executor:
        gelecekler = {executor.submit(_kaynak_cek, k): k.isim for k in aktif}
        for gelecek in as_completed(gelecekler):
            isim = gelecekler[gelecek]
            try:
                haberler = gelecek.result()
                sonuclar.extend(haberler)
            except Exception as e:
                logger.error(f"[{isim}] Thread hatası: {e}")

    logger.info(f"Toplam {len(sonuclar)} ham haber çekildi.")
    return sonuclar
