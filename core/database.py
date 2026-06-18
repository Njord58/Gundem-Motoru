"""
core/database.py

Turso (libsql) bağlantısı ve tüm veritabanı işlemleri.
Yerel geliştirme için TURSO_URL boşsa standart SQLite kullanır.
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Generator

from core.logger import get_logger

logger = get_logger("gundem.db")

# Turso libsql sürücüsü varsa kullan, yoksa standart sqlite3
try:
    import libsql_experimental as libsql  # type: ignore
    LIBSQL_MEVCUT = True
except ImportError:
    LIBSQL_MEVCUT = False


import threading

_db_yol: str = ""
_lock = threading.Lock()


def _baglanti_olustur(turso_url: str, turso_token: str) -> Any:
    """Turso veya yerel SQLite bağlantısı döndürür."""
    global _db_yol
    if LIBSQL_MEVCUT and turso_url:
        conn = libsql.connect(
            database=turso_url,
            auth_token=turso_token,
        )
        logger.info("Turso bağlantısı kuruldu.")
        return conn

    # Yerel geliştirme fallback
    _db_yol = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gundem_local.db")
    conn = sqlite3.connect(_db_yol, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    logger.info(f"Yerel SQLite kullanılıyor: {_db_yol}")
    return conn


class Database:
    def __init__(self, turso_url: str = "", turso_token: str = ""):
        self._turso_url = turso_url
        self._turso_token = turso_token
        self._conn: Any = None

    def baglan(self):
        if self._conn is None:
            self._conn = _baglanti_olustur(self._turso_url, self._turso_token)

    @contextmanager
    def cursor(self) -> Generator:
        self.baglan()
        with _lock:
            # Her yazma işlemi için yeni bağlantı — thread güvenliği
            if _db_yol:
                conn = sqlite3.connect(_db_yol, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
            else:
                conn = self._conn
            cur = conn.cursor()
            try:
                yield cur
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"DB hatası: {e}")
                raise
            finally:
                cur.close()
                if _db_yol:
                    conn.close()

    # ------------------------------------------------------------------ #
    #  Şema                                                                #
    # ------------------------------------------------------------------ #

    def init_db(self):
        """Tabloları oluşturur, varsa dokunmaz."""
        with self.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS icerikler (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    baslik      TEXT    NOT NULL,
                    ozet        TEXT,
                    url         TEXT    UNIQUE NOT NULL,
                    gorsel_url  TEXT,
                    kaynak      TEXT,
                    kategori    TEXT    DEFAULT 'Gündem',
                    okundu      INTEGER DEFAULT 0,
                    ai_basarili INTEGER DEFAULT 0,
                    eklenme_ts  INTEGER NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kategoriler (
                    id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    isim  TEXT    UNIQUE NOT NULL,
                    renk  TEXT    DEFAULT '#6366f1',
                    sira  INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sistem_durum (
                    kaynak_isim     TEXT    PRIMARY KEY,
                    son_etag        TEXT,
                    son_modified    TEXT,
                    hata_sayisi     INTEGER DEFAULT 0,
                    devre_kapali_ts INTEGER DEFAULT 0,
                    son_basari_ts   INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kullanici_ayarlari (
                    anahtar TEXT PRIMARY KEY,
                    deger   TEXT
                )
            """)
            # Varsayılan kategoriler (isim, renk, sira)
            varsayilan = [
                ("Gündem",   "#06b6d4", 0),
                ("Siyaset",  "#92400e", 1),
                ("Ekonomi",  "#22c55e", 2),
                ("Dünya",    "#6b7280", 3),
                ("Spor",     "#a855f7", 4),
                ("Teknoloji","#ef4444", 5),
                ("Kültür",   "#9f1239", 6),
                ("Sağlık",   "#e8e8ec", 7),
                ("Savaş",    "#f97316", 8),
            ]
            for isim, renk, sira in varsayilan:
                cur.execute(
                    "INSERT OR IGNORE INTO kategoriler (isim, renk, sira) VALUES (?, ?, ?)",
                    (isim, renk, sira),
                )
        logger.info("Veritabanı şeması hazır.")

    # ------------------------------------------------------------------ #
    #  icerikler CRUD                                                      #
    # ------------------------------------------------------------------ #

    def haber_ekle(self, haber: dict) -> int | None:
        """Yeni haber ekler. URL zaten varsa None döner."""
        try:
            with self.cursor() as cur:
                cur.execute("""
                    INSERT INTO icerikler
                        (baslik, ozet, url, gorsel_url, kaynak, kategori, ai_basarili, eklenme_ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    haber["baslik"],
                    haber.get("ozet", haber["baslik"]),
                    haber["url"],
                    haber.get("gorsel_url"),
                    haber.get("kaynak"),
                    haber.get("kategori", "Gündem"),
                    1 if haber.get("ai_basarili") else 0,
                    int(time.time()),
                ))
                return cur.lastrowid
        except Exception:
            return None

    def haberleri_getir(
        self,
        saat: int = 24,
        kategori: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        since = int(time.time()) - saat * 3600
        with self.cursor() as cur:
            if kategori and kategori != "Tümü":
                cur.execute("""
                    SELECT * FROM icerikler
                    WHERE eklenme_ts >= ? AND kategori = ?
                    ORDER BY eklenme_ts DESC
                    LIMIT ? OFFSET ?
                """, (since, kategori, limit, offset))
            else:
                cur.execute("""
                    SELECT * FROM icerikler
                    WHERE eklenme_ts >= ?
                    ORDER BY eklenme_ts DESC
                    LIMIT ? OFFSET ?
                """, (since, limit, offset))
            satirlar = cur.fetchall()
        return [dict(r) for r in satirlar]

    def son_basliklar(self, saat: int = 24) -> list[str]:
        """Duplikasyon kontrolü için son N saatin başlıklarını döner."""
        since = int(time.time()) - saat * 3600
        with self.cursor() as cur:
            cur.execute(
                "SELECT baslik FROM icerikler WHERE eklenme_ts >= ?", (since,)
            )
            return [r[0] for r in cur.fetchall()]

    def url_var_mi(self, url: str) -> bool:
        with self.cursor() as cur:
            cur.execute("SELECT 1 FROM icerikler WHERE url = ?", (url,))
            return cur.fetchone() is not None

    def kategori_degistir(self, haber_id: int, kategori: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE icerikler SET kategori = ? WHERE id = ?",
                (kategori, haber_id),
            )
            return cur.rowcount > 0

    def okundu_isaretle(self, haber_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE icerikler SET okundu = 1 WHERE id = ?", (haber_id,)
            )
            return cur.rowcount > 0

    def eski_haberleri_sil(self, gun: int = 30):
        sinir = int(time.time()) - gun * 86400
        with self.cursor() as cur:
            cur.execute("DELETE FROM icerikler WHERE eklenme_ts < ?", (sinir,))
            silinen = cur.rowcount
        if silinen:
            logger.info(f"{silinen} eski haber silindi.")

    # ------------------------------------------------------------------ #
    #  kategoriler CRUD                                                    #
    # ------------------------------------------------------------------ #

    def kategorileri_getir(self) -> list[dict]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM kategoriler ORDER BY sira ASC")
            return [dict(r) for r in cur.fetchall()]

    def kategori_ekle(self, isim: str, renk: str = "#6366f1") -> bool:
        try:
            with self.cursor() as cur:
                cur.execute(
                    "INSERT INTO kategoriler (isim, renk) VALUES (?, ?)",
                    (isim, renk),
                )
            return True
        except Exception:
            return False

    def kategori_guncelle(self, kategori_id: int, isim: str, renk: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE kategoriler SET isim = ?, renk = ? WHERE id = ?",
                (isim, renk, kategori_id),
            )
            return cur.rowcount > 0

    def kategori_sil(self, kategori_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute("DELETE FROM kategoriler WHERE id = ?", (kategori_id,))
            return cur.rowcount > 0

    def kategori_sirasi_guncelle(self, sirali_idler: list[int]):
        with self.cursor() as cur:
            for sira, kid in enumerate(sirali_idler):
                cur.execute(
                    "UPDATE kategoriler SET sira = ? WHERE id = ?", (sira, kid)
                )

    # ------------------------------------------------------------------ #
    #  sistem_durum                                                        #
    # ------------------------------------------------------------------ #

    def kaynak_durum_getir(self, isim: str) -> dict:
        with self.cursor() as cur:
            cur.execute(
                "SELECT * FROM sistem_durum WHERE kaynak_isim = ?", (isim,)
            )
            r = cur.fetchone()
        if r:
            return dict(r)
        return {
            "kaynak_isim": isim,
            "son_etag": None,
            "son_modified": None,
            "hata_sayisi": 0,
            "devre_kapali_ts": 0,
            "son_basari_ts": 0,
        }

    def kaynak_durum_guncelle(self, isim: str, **kwargs):
        mevcut = self.kaynak_durum_getir(isim)
        mevcut.update(kwargs)
        with self.cursor() as cur:
            cur.execute("""
                INSERT INTO sistem_durum
                    (kaynak_isim, son_etag, son_modified, hata_sayisi,
                     devre_kapali_ts, son_basari_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(kaynak_isim) DO UPDATE SET
                    son_etag        = excluded.son_etag,
                    son_modified    = excluded.son_modified,
                    hata_sayisi     = excluded.hata_sayisi,
                    devre_kapali_ts = excluded.devre_kapali_ts,
                    son_basari_ts   = excluded.son_basari_ts
            """, (
                isim,
                mevcut.get("son_etag"),
                mevcut.get("son_modified"),
                mevcut.get("hata_sayisi", 0),
                mevcut.get("devre_kapali_ts", 0),
                mevcut.get("son_basari_ts", 0),
            ))

    def tum_kaynak_durumlari(self) -> list[dict]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM sistem_durum")
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------ #
    #  kullanici_ayarlari                                                  #
    # ------------------------------------------------------------------ #

    def ayar_getir(self, anahtar: str, varsayilan: str = "") -> str:
        with self.cursor() as cur:
            cur.execute(
                "SELECT deger FROM kullanici_ayarlari WHERE anahtar = ?",
                (anahtar,),
            )
            r = cur.fetchone()
        return r[0] if r else varsayilan

    def ayar_kaydet(self, anahtar: str, deger: str):
        with self.cursor() as cur:
            cur.execute("""
                INSERT INTO kullanici_ayarlari (anahtar, deger) VALUES (?, ?)
                ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger
            """, (anahtar, deger))


# Uygulama genelinde tek instance
_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        from core.config import get_config
        cfg = get_config()
        _db = Database(cfg.turso_url, cfg.turso_auth_token)
        _db.baglan()
    return _db
