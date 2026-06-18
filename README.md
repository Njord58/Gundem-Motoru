# Gündem Motoru

Türkiye'deki haber akışını tek ekranda, gerçek zamanlı ve yapay zeka destekli olarak takip eden web tabanlı bir sistem. 8 farklı haber kaynağından otomatik haber çeker, Groq AI ile özetler ve kategoriler, tarayıcıya anlık olarak iletir.

![Akış Şeması](docs/akis_semasi.png)

---

## Özellikler

- 8 RSS kaynağından paralel haber çekimi (NTV, BBC Türkçe, CNN Türk, Bloomberg HT, Sabah, Hürriyet, Sözcü, Habertürk)
- Trafilatura ile tam metin çekme, Jina AI fallback
- Groq AI ile tek çağrıda haber özeti + kategori
- Duplikasyon filtresi: aynı haberin farklı kaynaklardaki kopyaları elenir
- Server-Sent Events (SSE) ile sayfayı yenilemeden gerçek zamanlı güncelleme
- Dark mode, responsive tasarım (masaüstü / tablet / mobil)
- YouTube canlı yayın slotları (4/6/8/12)
- Kategori yönetimi: ekleme, silme, yeniden adlandırma

---

## Kurulum

### Gereksinimler

- Python 3.10+
- [Groq API Key](https://console.groq.com) (ücretsiz)
- [Turso hesabı](https://turso.tech) (ücretsiz, 500 MB)

### Adımlar

**1. Repoyu klonla**

```bash
git clone https://github.com/KULLANICI_ADIN/gundem-motoru.git
cd gundem-motoru
```

**2. Sanal ortam oluştur ve bağımlılıkları yükle**

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**3. `.env` dosyasını oluştur**

```bash
cp .env.example .env
```

`.env` dosyasını aç ve aşağıdaki değerleri doldur:

```
TURSO_URL=libsql://veritabani-adin.turso.io
TURSO_AUTH_TOKEN=eyJhbGci...
GROQ_API_KEY=gsk_...
FLASK_SECRET_KEY=rastgele-uzun-bir-string
FLASK_ENV=development
```

**4. Uygulamayı başlat**

```bash
python api.py
```

Tarayıcıda `http://localhost:5000` adresine git.

---

## Kullanım

- **Sol panel:** Kategoriler arasında geçiş yap
- **Üst filtre:** Son 24 / 48 / 72 saatin haberlerini filtrele
- **Canlı butonu:** YouTube yayın slotlarını aç/kapat
- **Kategori ekle:** Sol panelin altındaki + butonu
- Haberler 15 dakikada bir otomatik güncellenir, sayfa yenilemeye gerek yok

---

## Deployment (Render.com)

1. GitHub'a push'la
2. [Render.com](https://render.com)'da "New Web Service" oluştur
3. GitHub reposunu bağla
4. **Environment Variables** sekmesine `.env` içindeki değerleri gir
5. **Start Command:** `gunicorn api:app --bind 0.0.0.0:$PORT --workers 1 --threads 4`
6. Deploy

---

## Proje Yapısı

```
gundem_motoru/
├── core/
│   ├── config.py        # YAML + .env konfigürasyon yöneticisi
│   ├── database.py      # Turso/SQLite bağlantısı, tüm CRUD işlemleri
│   └── logger.py        # Rotating log sistemi
├── collectors/
│   └── rss.py           # Paralel RSS çekimi, ETag, devre kesici
├── processors/
│   ├── metin_cekici.py  # Trafilatura → Jina → RSS fallback
│   ├── duplikasyon.py   # Başlık benzerliği ile tekrar tespiti
│   └── groq_isleyici.py # Groq API: tek çağrıda özet + kategori
├── templates/
│   └── arayuz.html      # Vanilla JS, dark mode, responsive, SSE
├── api.py               # Flask API, SSE endpoint, scheduler
├── config.yaml          # RSS kaynakları ve sistem ayarları
├── .env.example         # Ortam değişkeni şablonu
├── requirements.txt
└── Procfile             # Render.com için
```

---

## Teknolojiler

| Katman | Teknoloji |
|---|---|
| Backend | Python 3.10+, Flask |
| Zamanlama | APScheduler |
| Gerçek zamanlı | Server-Sent Events (SSE) |
| Haber çekme | feedparser, Trafilatura, Jina AI |
| AI | Groq API (Llama 3.1 / Qwen 32B) |
| Veritabanı | Turso (bulut SQLite) |
| Arayüz | Vanilla HTML/CSS/JS |
| Hosting | Render.com |

---

## Lisans

MIT
