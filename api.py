"""
api.py

Flask sunucusu: tüm endpoint'ler, SSE, APScheduler, güvenlik katmanı.
"""

import json
import queue
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS

from collectors.rss import tum_kaynaklardan_cek
from core.config import get_config
from core.database import get_db
from core.logger import get_logger
from processors.duplikasyon import duplikasyon_filtrele
from processors.kategori_ayirici import kategori_belirle, ozet_belirle

logger = get_logger("gundem.api")

# ------------------------------------------------------------------ #
#  Uygulama kurulumu                                                   #
# ------------------------------------------------------------------ #

app = Flask(__name__, template_folder="templates")
cfg = get_config()

app.secret_key = cfg.flask_secret_key

CORS(app, origins=cfg.cors_origins if cfg.cors_origins else ["*"])

# SSE istemci kuyruğu
_sse_kuyruklar: list[queue.Queue] = []


# ------------------------------------------------------------------ #
#  Ana iş akışı                                                        #
# ------------------------------------------------------------------ #

def haber_isle_ve_kaydet_paralel(haberler: list[dict]) -> int:
    """
    Haberlerin metinlerini paralel çeker, özet ve kategorilerini belirler ve kaydeder.
    Geriye başarıyla kaydedilen haber sayısını döndürür.
    """
    db = get_db()

    def _isle_ve_kaydet(haber_ham: dict) -> bool:
        try:
            # URL zaten varsa atla (gereksiz işlem önlenir)
            if db.url_var_mi(haber_ham["url"]):
                return False

            # 1. Özet ve Kategori belirle (RSS özetinden doğrudan analiz)
            ozet = ozet_belirle(haber_ham.get("ozet_ham", ""), "", haber_ham["baslik"])
            kategori = kategori_belirle(haber_ham["baslik"], haber_ham.get("ozet_ham", ""))

            haber = {
                "baslik": haber_ham["baslik"],
                "url": haber_ham["url"],
                "ozet": ozet,
                "gorsel_url": haber_ham.get("gorsel_url"),
                "kaynak": haber_ham.get("kaynak"),
                "kategori": kategori,
                "ai_basarili": 0,
                "yayin_ts": haber_ham.get("yayin_ts", int(time.time())),
            }

            # 2. Veritabanına kaydet
            haber_id = db.haber_ekle(haber)
            if haber_id:
                haber["id"] = haber_id
                haber["eklenme_ts"] = int(time.time())
                _sse_bildir(haber)
                return True
        except Exception as e:
            logger.error(f"Haber işleme/kaydetme hatası ({haber_ham.get('url', '')}): {e}")
        return False

    kaydedilen = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        gelecekler = [executor.submit(_isle_ve_kaydet, h) for h in haberler]
        for gelecek in as_completed(gelecekler):
            if gelecek.result():
                kaydedilen += 1
    return kaydedilen


def rss_dongusu():
    """Scheduler tarafından 15 dk'da bir çağrılır."""
    logger.info("RSS döngüsü başladı.")
    db = get_db()

    try:
        ham_haberler = tum_kaynaklardan_cek()
        mevcut_basliklar = db.son_basliklar(saat=cfg.duplikasyon_pencere_saat)
        temiz_haberler = duplikasyon_filtrele(ham_haberler, mevcut_basliklar)

        # Veritabanında zaten var olanları ele (gereksiz metin çekme/işleme önlenir)
        yeni_haberler = [h for h in temiz_haberler if not db.url_var_mi(h["url"])]
        if not yeni_haberler:
            logger.info("RSS döngüsü bitti: yeni haber yok.")
            return

        logger.info(f"{len(yeni_haberler)} yeni haber paralel olarak işleniyor ve kaydediliyor...")
        kaydedilen = haber_isle_ve_kaydet_paralel(yeni_haberler)

        logger.info(f"RSS döngüsü bitti: {kaydedilen} yeni haber kaydedildi.")

    except Exception as e:
        logger.error(f"RSS döngüsü hatası: {e}", exc_info=True)


def haftalik_temizlik():
    get_db().eski_haberleri_sil(gun=cfg.haber_max_gun)


# ------------------------------------------------------------------ #
#  Scheduler                                                           #
# ------------------------------------------------------------------ #

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(
    rss_dongusu,
    "interval",
    minutes=cfg.rss_interval_minutes,
    id="rss_dongusu",
    next_run_time=None,  # İlk çalışma app start'ta tetiklenir
)
scheduler.add_job(
    haftalik_temizlik,
    "interval",
    days=7,
    id="temizlik",
)


# ------------------------------------------------------------------ #
#  SSE                                                                 #
# ------------------------------------------------------------------ #

def _sse_bildir(haber: dict):
    """Yeni haber geldiğinde tüm bağlı istemcilere bildirir."""
    veri = json.dumps(haber, ensure_ascii=False)
    oldu_kuyruklar = []
    for q in _sse_kuyruklar:
        try:
            q.put_nowait(veri)
        except queue.Full:
            oldu_kuyruklar.append(q)
    for q in oldu_kuyruklar:
        try:
            _sse_kuyruklar.remove(q)
        except ValueError:
            pass


@app.route("/api/stream")
def sse_stream():
    def generator():
        q: queue.Queue = queue.Queue(maxsize=50)
        _sse_kuyruklar.append(q)
        try:
            # Bağlantı sinyali
            yield "event: baglandi\ndata: {}\n\n"
            while True:
                try:
                    veri = q.get(timeout=25)
                    yield f"event: yeni_haber\ndata: {veri}\n\n"
                except queue.Empty:
                    # Heartbeat — bağlantıyı canlı tutar
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            try:
                _sse_kuyruklar.remove(q)
            except ValueError:
                pass

    return Response(
        generator(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ------------------------------------------------------------------ #
#  YouTube URL doğrulama                                               #
# ------------------------------------------------------------------ #

_YT_DOMAINLER = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}
_VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def youtube_url_dogrula(url: str) -> tuple[bool, str]:
    """
    Geçerli bir YouTube URL'si mi kontrol eder.
    Returns: (gecerli: bool, video_id: str)
    """
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False, ""
        if parsed.netloc not in _YT_DOMAINLER:
            return False, ""

        # SSRF: iç ağ adresleri engelle
        host = parsed.netloc.lower()
        for yasak in ("localhost", "127.", "0.0.0.0", "169.254", "::1", "internal"):
            if yasak in host:
                return False, ""

        # Video ID çıkar
        video_id = ""
        if "youtu.be" in parsed.netloc:
            video_id = parsed.path.lstrip("/").split("?")[0]
        else:
            from urllib.parse import parse_qs
            qs = parse_qs(parsed.query)
            video_id = qs.get("v", [""])[0]
            if not video_id:
                # /live/XXXXX veya /shorts/XXXXX formatları
                parts = parsed.path.strip("/").split("/")
                if len(parts) >= 2 and parts[0] in ("live", "shorts", "embed"):
                    video_id = parts[1]

        if video_id and _VIDEO_ID_RE.match(video_id):
            return True, video_id
        # Canlı yayın URL'leri bazen farklı formatta olabilir
        # Video ID yoksa ama domain doğruysa izin ver
        return True, ""

    except Exception:
        return False, ""


# ------------------------------------------------------------------ #
#  Rate limiting (basit IP tabanlı)                                    #
# ------------------------------------------------------------------ #

_rate_sayac: dict[str, list[float]] = {}


def _rate_limit_kontrol(ip: str, limit: int, pencere: int = 60) -> bool:
    """True → istek kabul, False → limit aşıldı."""
    simdi = time.time()
    kayitlar = _rate_sayac.get(ip, [])
    kayitlar = [t for t in kayitlar if simdi - t < pencere]
    if len(kayitlar) >= limit:
        return False
    kayitlar.append(simdi)
    _rate_sayac[ip] = kayitlar
    return True


def okuma_limiti():
    ip = request.remote_addr or "unknown"
    if not _rate_limit_kontrol(ip, limit=60):
        return jsonify({"hata": "Çok fazla istek"}), 429
    return None


def yazma_limiti():
    ip = request.remote_addr or "unknown"
    if not _rate_limit_kontrol(ip, limit=10):
        return jsonify({"hata": "Çok fazla istek"}), 429
    return None


# ------------------------------------------------------------------ #
#  Endpoint'ler                                                        #
# ------------------------------------------------------------------ #

@app.route("/")
def anasayfa():
    return render_template("arayuz.html")


@app.route("/api/haberler")
def haberler():
    hata = okuma_limiti()
    if hata:
        return hata
    try:
        saat = min(int(request.args.get("saat", 24)), 168)
        kategori = request.args.get("kategori", "Tümü")
        limit = min(int(request.args.get("limit", 50)), 100)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (ValueError, TypeError):
        return jsonify({"hata": "Geçersiz parametre"}), 400

    sonuclar = get_db().haberleri_getir(saat=saat, kategori=kategori, limit=limit, offset=offset)
    return jsonify(sonuclar)


@app.route("/api/kategoriler")
def kategoriler_getir():
    hata = okuma_limiti()
    if hata:
        return hata
    try:
        saat = min(max(int(request.args.get("saat", 24)), 1), 168)
    except (ValueError, TypeError):
        saat = 24

    db = get_db()
    kategoriler = db.kategorileri_getir()
    
    since = int(time.time()) - saat * 3600
    
    with db.cursor() as cur:
        cur.execute(
            "SELECT kategori, COUNT(*) as adet FROM icerikler WHERE eklenme_ts >= ? GROUP BY kategori",
            (since,)
        )
        sayilar = {row["kategori"]: row["adet"] for row in cur.fetchall()}
        
        cur.execute(
            "SELECT COUNT(*) as adet FROM icerikler WHERE eklenme_ts >= ?",
            (since,)
        )
        toplam = cur.fetchone()["adet"]

    for k in kategoriler:
        k["sayi"] = sayilar.get(k["isim"], 0)

    return jsonify({
        "kategoriler": kategoriler,
        "toplam": toplam
    })


@app.route("/api/kategoriler/ekle", methods=["POST"])
def kategori_ekle():
    hata = yazma_limiti()
    if hata:
        return hata
    veri = request.get_json(silent=True) or {}
    isim = str(veri.get("isim", "")).strip()[:50]
    renk = str(veri.get("renk", "#6366f1")).strip()[:20]
    if not isim:
        return jsonify({"hata": "İsim zorunlu"}), 400
    if get_db().kategori_ekle(isim, renk):
        return jsonify({"mesaj": "Eklendi"})
    return jsonify({"hata": "Kategori zaten var"}), 409


@app.route("/api/kategoriler/guncelle", methods=["POST"])
def kategori_guncelle():
    hata = yazma_limiti()
    if hata:
        return hata
    veri = request.get_json(silent=True) or {}
    try:
        kid = int(veri["id"])
    except (KeyError, ValueError):
        return jsonify({"hata": "Geçersiz id"}), 400
    isim = str(veri.get("isim", "")).strip()[:50]
    renk = str(veri.get("renk", "#6366f1")).strip()[:20]
    if not isim:
        return jsonify({"hata": "İsim zorunlu"}), 400
    if get_db().kategori_guncelle(kid, isim, renk):
        return jsonify({"mesaj": "Güncellendi"})
    return jsonify({"hata": "Bulunamadı"}), 404


@app.route("/api/kategoriler/sil", methods=["POST"])
def kategori_sil():
    hata = yazma_limiti()
    if hata:
        return hata
    veri = request.get_json(silent=True) or {}
    try:
        kid = int(veri["id"])
    except (KeyError, ValueError):
        return jsonify({"hata": "Geçersiz id"}), 400
    if get_db().kategori_sil(kid):
        return jsonify({"mesaj": "Silindi"})
    return jsonify({"hata": "Bulunamadı"}), 404


@app.route("/api/kategoriler/sirayi-guncelle", methods=["POST"])
def kategori_sira():
    hata = yazma_limiti()
    if hata:
        return hata
    veri = request.get_json(silent=True) or {}
    idler = veri.get("idler", [])
    if not isinstance(idler, list):
        return jsonify({"hata": "idler listesi gerekli"}), 400
    try:
        idler = [int(i) for i in idler]
    except (ValueError, TypeError):
        return jsonify({"hata": "Geçersiz id listesi"}), 400
    get_db().kategori_sirasi_guncelle(idler)
    return jsonify({"mesaj": "Sıra güncellendi"})


@app.route("/api/icerik/kategori-degistir", methods=["POST"])
def icerik_kategori():
    hata = yazma_limiti()
    if hata:
        return hata
    veri = request.get_json(silent=True) or {}
    try:
        haber_id = int(veri["id"])
    except (KeyError, ValueError):
        return jsonify({"hata": "Geçersiz id"}), 400
    kategori = str(veri.get("kategori", "")).strip()[:50]
    if not kategori:
        return jsonify({"hata": "Kategori zorunlu"}), 400
    if get_db().kategori_degistir(haber_id, kategori):
        return jsonify({"mesaj": "Güncellendi"})
    return jsonify({"hata": "Bulunamadı"}), 404


@app.route("/api/icerik/okundu-isaretle", methods=["POST"])
def icerik_okundu():
    hata = yazma_limiti()
    if hata:
        return hata
    veri = request.get_json(silent=True) or {}
    try:
        haber_id = int(veri["id"])
    except (KeyError, ValueError):
        return jsonify({"hata": "Geçersiz id"}), 400
    if get_db().okundu_isaretle(haber_id):
        return jsonify({"mesaj": "İşaretlendi"})
    return jsonify({"hata": "Bulunamadı"}), 404


@app.route("/api/youtube/kanallar")
def youtube_kanallar():
    hata = okuma_limiti()
    if hata:
        return hata
    import json as _json
    ham = get_db().ayar_getir("youtube_slotlar", "[]")
    try:
        return jsonify(_json.loads(ham))
    except Exception:
        return jsonify([])


@app.route("/api/youtube/kanal-guncelle", methods=["POST"])
def youtube_guncelle():
    hata = yazma_limiti()
    if hata:
        return hata
    import json as _json
    veri = request.get_json(silent=True) or {}
    slotlar = veri.get("slotlar", [])

    if not isinstance(slotlar, list) or len(slotlar) > 12:
        return jsonify({"hata": "Geçersiz slot listesi"}), 400

    temiz = []
    for slot in slotlar:
        url = str(slot.get("url", "")).strip()
        if not url:
            temiz.append({"url": "", "baslik": ""})
            continue
        gecerli, _ = youtube_url_dogrula(url)
        if not gecerli:
            return jsonify({"hata": f"Geçersiz YouTube URL: {url[:80]}"}), 400
        temiz.append({
            "url": url,
            "baslik": str(slot.get("baslik", "")).strip()[:100],
        })

    get_db().ayar_kaydet("youtube_slotlar", _json.dumps(temiz, ensure_ascii=False))
    return jsonify({"mesaj": "Güncellendi"})


@app.route("/api/durum")
def durum():
    hata = okuma_limiti()
    if hata:
        return hata
    return jsonify({
        "kaynak_durumlari": get_db().tum_kaynak_durumlari(),
        "scheduler_aktif": scheduler.running,
        "sse_bagli_istemci": len(_sse_kuyruklar),
    })


@app.route("/api/ayarlar")
def ayarlar_getir():
    hata = okuma_limiti()
    if hata:
        return hata
    db = get_db()
    return jsonify({
        "zaman_filtresi_saat": int(db.ayar_getir("zaman_filtresi_saat", "24")),
        "youtube_slot_sayisi": int(db.ayar_getir("youtube_slot_sayisi", "6")),
    })


@app.route("/api/ayarlar", methods=["POST"])
def ayarlar_kaydet():
    hata = yazma_limiti()
    if hata:
        return hata
    veri = request.get_json(silent=True) or {}
    db = get_db()
    if "zaman_filtresi_saat" in veri:
        try:
            saat = min(max(int(veri["zaman_filtresi_saat"]), 1), 168)
            db.ayar_kaydet("zaman_filtresi_saat", str(saat))
        except (ValueError, TypeError):
            pass
    if "youtube_slot_sayisi" in veri:
        try:
            slot = int(veri["youtube_slot_sayisi"])
            if slot in (4, 6, 8, 12):
                db.ayar_kaydet("youtube_slot_sayisi", str(slot))
        except (ValueError, TypeError):
            pass
    return jsonify({"mesaj": "Ayarlar kaydedildi"})


# ------------------------------------------------------------------ #
#  Hata yakalayıcılar                                                  #
# ------------------------------------------------------------------ #

@app.errorhandler(404)
def not_found(_):
    return jsonify({"hata": "Bulunamadı"}), 404


@app.errorhandler(500)
def server_error(e):
    logger.error(f"Sunucu hatası: {e}")
    return jsonify({"hata": "Sunucu hatası"}), 500


# ------------------------------------------------------------------ #
#  Başlangıç                                                           #
# ------------------------------------------------------------------ #

import threading

_baslatildi = False
_baslatildi_lock = threading.Lock()


@app.before_request
def before_request_init():
    global _baslatildi
    if not _baslatildi:
        with _baslatildi_lock:
            if not _baslatildi:
                baslat()
                _baslatildi = True


def baslat():
    db = get_db()
    db.init_db()

    hatalar = cfg.dogrula()
    if hatalar:
        for h in hatalar:
            logger.warning(f"Konfigürasyon uyarısı: {h}")

    scheduler.start()
    logger.info("Scheduler başlatıldı.")

    # İlk RSS çekimini hemen tetikle
    threading.Thread(target=rss_dongusu, daemon=True).start()
    logger.info("Gündem Motoru başlatıldı.")


if __name__ == "__main__":
    baslat()
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=(cfg.flask_env == "development"),
        use_reloader=False,  # Scheduler çift başlamasın
    )

