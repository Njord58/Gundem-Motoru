"""
processors/kategori_ayirici.py

Haber başlığı ve metnini analiz ederek Türkçe anahtar kelimelere göre kategori belirler.
Ayrıca RSS'ten gelen ham özeti temizler ve gerekirse metinden kesit alır.
"""

import html
import re

KATEGORI_KEYWORDS = {
    "Spor": [
        "futbol", "basketbol", "voleybol", "tenis", "derbi", "şampiyon", "transfer", 
        "uefa", "fifa", "hakem", "antrenör", "teknik direktör", "stadyum", "stada", 
        "kupa", "puan durumu", "fenerbahçe", "galatasaray", "beşiktaş", "trabzonspor", 
        "atletizm", "güreş", "formula 1", "madalya", "olimpiyat", "gol att", "golü",
        "maç", "macta", "karşılaşma", "sahada", "oyuncu", "kadro", "süper lig", 
        "şampiyonlar ligi", "gol kralı", "penaltı", "ofsayt", "kaleci", "pas", "şut", 
        "milli takım", "euro 2024", "euro 2026", "smaç", "ribaund", "smaçör", 
        "servis", "güreşçi", "boks", "karate", "judo", "hentbol", "olimpiyatları", 
        "yarı final", "çeyrek final", "final maçı", "madalyası", "altın madalya", 
        "gümüş madalya", "bronz madalya", "dünya kupası", "la liga", "premier lig", 
        "serie a", "bundesliga", "tff", "süper kupa", "şampiyonluk", "golcü", "asist", 
        "kırmızı kart", "sarı kart", "faul", "taç çizgisi", "köşe vuruşu", "korner", 
        "uzatmalar", "penaltı atışları", "dostluk maçı", "hazırlık maçı", "deplasman", 
        "ev sahibi", "fikstür", "lig tv", "bein sports", "spor kanalı", "olimpiyat oyunları", 
        "paralimpik", "masa tenisi", "badminton", "eskrim", "okçuluk", "kürek", "yelken", 
        "yüzme", "havuz", "maraton", "yarı maraton", "dağcılık", "kayak", "snowboard", 
        "paten", "bisiklet yarışı", "velodrom", "ralli", "motosiklet", "motogp", "wrc", 
        "nba", "euroleague", "pota", "smaç vuruşu", "blok", "pasör", "libero", 
        "servis sayısı", "servis hatası", "e-spor", "gaming", "turnuva", "eşleşme", "kura çekimi"
    ],
    "Siyaset": [
        "siyaset", "tbmm", "milletvekili", "bakanlık", "bakanı", "cumhurbaşkanı", 
        "erdoğan", "özgür özel", "bahçeli", "seçim", "sandık", "oy oranı", "koalisyon", 
        "muhalefet", "iktidar", "yasa tasarı", "belediye başkanı", "kayyum", 
        "ak parti", "akp", "chp", "mhp", "iyi parti", "dem parti", "kabine", 
        "başbakan", "delege", "genel başkan", "kongre", "parlamento", "tüzük", 
        "anayasa", "diplomatik", "diplomasi", "büyükelçi", "büyükelçilik", 
        "parti sözcüsü", "meclis başkanı", "kanun teklifi", "resmi gazete", 
        "kararname", "siyasi parti", "yerel seçim", "genel seçim", "cumhurbaşkanlığı", 
        "bürokrat", "bürokrasi", "dışişleri bakanı", "içişleri bakanı", "savunma bakanı",
        "adalet bakanı", "meclis komisyonu", "gensoru", "erken seçim", "barajı", 
        "oy pusulası", "ittifak", "cumhur ittifakı", "millet ittifakı", "ata ittifakı", 
        "parti genel merkezi", "miting", "seçmen", "seçmen listesi", "anayasa mahkemesi", 
        "aym", "danıştay", "yargıtay", "ysk", "yüksek seçim kurulu", "siyasetçi", 
        "demeç", "açıklama", "parti meclisi", "il başkanı", "ilçe başkanı", 
        "belediye meclisi", "encümen", "kamu kurumu", "valilik", "kaymakamlık", 
        "protokol", "zirve toplantısı", "ikili görüşme", "heyet", "siyasi kriz", "istifa", "atama"
    ],
    "Ekonomi": [
        "ekonomi", "borsa", "dolar", "euro", "döviz", "altın fiyat", "enflasyon", 
        "merkez bankası", "tcmb", "faiz karar", "asgari ücret", "zam geldi", "ihracat", 
        "ithalat", "resesyon", "tahvil", "kripto para", "bitcoin", "cari açık", "gsyih",
        "maliye bakan", "hazine ve maliye", "vergi oranı", "kdv", "ötv", "zam yapıldı",
        "finans", "hisse senedi", "portföy", "fonu", "vergi paketi", "cari denge", 
        "cari fazla", "büyüme rakamları", "işsizlik oranı", "istihdam", "imalat", 
        "sanayi üretimi", "para politikası", "kredi faiz", "mevduat", "bankacılık", 
        "temettü", "endeks", "bist 100", "nasdaq", "sp500", "borçlanma", "iflas", 
        "konkordato", "dış ticaret", "piyasalar", "makroekonomi", "mikroekonomi", 
        "emtia", "petrol fiyatları", "brent petrol", "doğalgaz zammı", "elektrik zammı", 
        "akaryakıt fiyatları", "benzin zammı", "motorin", "mazot zammı", "gümrük vergisi", 
        "kurumlar vergisi", "gelir vergisi", "sgk", "bağkur", "emekli maaşı", "memur maaşı", 
        "promosyon", "eyt", "kıdem tazminatı", "sendika", "grev", "toplu sözleşme", 
        "gayrimenkul", "konut kredisi", "konut satışları", "tapu", "kira artışı", 
        "enflasyon oranı", "tüfe", "üfe", "tüik", "tüketici endeksi", "para birimi", 
        "devalüasyon", "kur korumalı mevduat", "kkm", "sıcak para", "portföy yatırımı", 
        "doğrudan yatırım", "serbest bölge", "kalkınma ajansı", "teşvik paketi", "hibe", 
        "kosgeb", "esnaf", "ticaret odası", "ito", "tobb"
    ],
    "Dünya": [
        "abd", "rusya", "çin", "avrupa birliği", "nato", "birleşmiş milletler", 
        "fransa", "almanya", "ingiltere", "italya", "ispanya", "yunanistan", 
        "iran", "irak", "suriye", "mısır", "azerbaycan", "ukrayna", "gazze", 
        "filistin", "israil", "dış haber", "beyaz saray", "kremlin", "washington", 
        "pekin", "moskova", "londra", "paris", "berlin", "pentagon", "avrupa parlamentosu", 
        "tokyo", "seul", "roma", "atina", "tayvan", "kuzey kore", "güney kore", 
        "brics", "g7", "g20", "uluslararası ilişkiler", "dış politika", "sınır ötesi", 
        "göçmen", "mülteci", "sığınmacı", "sınır kapısı", "elçilik", "konsolosluk", 
        "vize muafiyeti", "schengen vizesi", "sınır güvenliği", "gümrük kapısı", 
        "uluslararası mahkeme", "lahey", "adalet divanı", "unicef", "unesco", 
        "dsö", "interpol", "diplomatik kriz", "nota verildi", "yaptırım kararı", 
        "ambargo", "dış dünya", "asya-pasifik", "ortadoğu", "balkanlar", "kafkaslar", 
        "latin amerika", "afrika birliği", "arap birliği", "körfez ülkeleri", 
        "suudi arabistan", "katar", "bae", "kuveyt", "pakistan", "hindistan", 
        "japonya", "avustralya", "kanada", "brezilya"
    ],
    "Teknoloji": [
        "teknoloji", "yapay zeka", "yazılım", "donanım", "akıllı telefon", "iphone", 
        "android", "windows", "apple", "google", "microsoft", "nvidia", "intel", 
        "amd", "mikroçip", "uzay aracı", "nasa", "spacex", "robotik", "siber saldırı", 
        "hacker", "mobil uygulama", "sosyal medya", "facebook", "instagram", "tiktok", 
        "twitter", "chatgpt", "gemini", "yapay zekâ", "bilişim", "yazılımcı", 
        "kodlama", "siber güvenlik", "bulut bilişim", "veri merkezi", "otonom", 
        "yapay uydu", "teleskop", "sanal gerçeklik", "metaverse", "5g", "blockchain", 
        "blokzincir", "elektrikli araç", "tesla", "byd", "batarya", "şarj istasyonu", 
        "kuantum bilgisayar", "akıllı saat", "tablet", "dizüstü bilgisayar", "oled", 
        "amoled", "işlemci", "ekran kartı", "ram", "ssd", "depolama", "işletim sistemi", 
        "ios", "macos", "linux", "açık kaynak", "open source", "yapay zeka modeli", 
        "llm", "makine öğrenmesi", "derin öğrenme", "veri analizi", "büyük veri", 
        "big data", "nesnelerin interneti", "iot", "akıllı ev", "drone", "insansız araç", 
        "kriptografi", "şifreleme", "nft", "web3", "start-up", "teknopark", "ar-ge", 
        "inovasyon", "patent", "dijital dönüşüm", "e-ticaret", "siber casusluk", 
        "veri sızıntısı", "kvkk", "yapay zeka etiği"
    ],
    "Kültür": [
        "sanat", "sinema", "tiyatro", "konser", "festival", "sergi", "edebiyat", 
        "müze", "arkeoloji", "heykel", "ressam", "müzik albüm", "vizyona gird", 
        "oscar ödül", "roman yazar", "şarkıcı", "filmi", "oyuncu kadrosu", "galası", 
        "kültür sanat", "resim sergisi", "piyanist", "orkestra", "opera", "bale", 
        "dans", "heykeltıraş", "mimari", "arkeolog", "antik kent", "kazı çalışmaları", 
        "tarihi eser", "kütüphane", "bestseller", "şiir", "şair", "tiyatro oyunu", 
        "belgesel", "sinema salonu", "müzikal", "konser turnesi", "canlı performans", 
        "festival programı", "bienal", "tasarım", "moda haftası", "fotoğrafçılık", 
        "galeri", "heykel sanatı", "klasik müzik", "caz", "pop müzik", "rock müzik", 
        "rap müzik", "türkü", "halk müziği", "tiyatro sahnesi", "sahne sanatları", 
        "film festivali", "altın portakal", "cannes film festivali", "ödül töreni", 
        "edebiyat ödülü", "nobel edebiyat", "yazar buluşması", "imza günü", 
        "tarihi kalıntı", "lahit", "restorasyon", "kültürel miras"
    ],
    "Sağlık": [
        "doktor", "hastane", "tedavi", "ilaç", "aşı", "virüs", "salgın", "kanser", 
        "ameliyat", "klinik", "tıp", "hastalık", "grip", "diyet", "beslenme", 
        "obezite", "dsö", "ttb", "eczane", "sağlık bakan", "hasta", "tanı", 
        "teşhis", "semptom", "enfeksiyon", "pandemi", "bağışıklık", "vitamin", 
        "ruh sağlığı", "psikiyatri", "cerrah", "taburcu", "poliklinik", "yoğun bakım", 
        "acil servis", "kalp krizi", "diyabet", "tansiyon", "kolesterol", "omurga", 
        "kemoterapi", "radyoterapi", "biyopsi", "laboratuvar", "test sonucu", 
        "kan tahlili", "ultrason", "röntgen", "mr taraması", "tomografi", "anestezi", 
        "reçeteli ilaç", "yan etki", "alerji", "astım", "obezite cerrahisi", "sağlıklı yaşam", 
        "spor hekimliği", "fizik tedavi", "rehabilitasyon", "diyetisyen", "kalori", 
        "protein", "karbonhidrat", "organ bağışı", "organ nakli", "tüberküloz", "sıtma", 
        "kızamık", "çocuk felci", "mutasyon", "varyant", "fda onayı", "ilaç firması", "eczacı"
    ],
    "Savaş": [
        "savaş", "askeri harekat", "ordu", "çatışma", "füze", "bomba", "saldırı", 
        "şehit", "tsk", "pentagon", "nükleer", "cephe", "roket", "tank", 
        "hava harekatı", "ateşkes", "savunma sanayii", "iha", "siha", "savaş uçağı", 
        "donanma", "asker", "askeri birlik", "mühimmat", "karargah", "siper", 
        "mayın", "barış gücü", "zırhlı araç", "savaş gemisi", "denizaltı", 
        "savunma sistemi", "hava savunma", "patriot", "s-400", "füze savunma", 
        "hava saldırısı", "topçu ateşi", "askeri konvoy", "obüs", "uçaksavar", 
        "el bombası", "zırhlı tugay", "komando", "özel kuvvetler", "askeri üs", 
        "garnizon", "askeri ittifak", "savaş suçu", "soykırım", "kimyasal silah", 
        "biyolojik silah", "nükleer başlık", "taktik füze", "balistik füze", 
        "hava savunma şemsiyesi", "radar sistemi", "mayın tarama", "askeri tatbikat", 
        "seferberlik", "sıkıyönetim", "savaş durumu", "askeri istihbarat", "casus uçak", 
        "hava koridoru", "askeri kayıplar"
    ]
}

def turkce_kucuk_harf(metin: str) -> str:
    """Türkçe karakterleri düzgün şekilde küçük harfe dönüştürür."""
    if not metin:
        return ""
    tablo = str.maketrans("ÇĞİÖŞÜI", "çğiöşüı")
    return metin.translate(tablo).lower()

def temizle_html(html_metin: str) -> str:
    """Metindeki HTML etiketlerini temizler ve HTML entity'lerini çözer."""
    if not html_metin:
        return ""
    temiz = re.sub(r'<[^>]+>', '', html_metin)
    temiz = html.unescape(temiz)
    temiz = re.sub(r'\s+', ' ', temiz).strip()
    return temiz

def kategori_belirle(baslik: str, metin: str) -> str:
    """
    Haber başlığı ve metnini analiz edip en uygun kategoriyi belirler.
    Başlıktaki eşleşmeler daha yüksek ağırlığa (5 kat) sahiptir.
    Hiçbir kategori eşleşmezse 'Gündem' döner.
    """
    baslik_kucuk = turkce_kucuk_harf(baslik)
    metin_kucuk = turkce_kucuk_harf(metin)
    
    skorlar = {kat: 0 for kat in KATEGORI_KEYWORDS}
    
    for kat, keywords in KATEGORI_KEYWORDS.items():
        for kw in keywords:
            kw_kucuk = turkce_kucuk_harf(kw)
            
            baslik_sayisi = baslik_kucuk.count(kw_kucuk)
            metin_sayisi = metin_kucuk.count(kw_kucuk)
            
            skorlar[kat] += baslik_sayisi * 5 + metin_sayisi
            
    en_yuksek_kat = "Gündem"
    en_yuksek_skor = 0
    
    for kat, skor in skorlar.items():
        if skor > en_yuksek_skor:
            en_yuksek_skor = skor
            en_yuksek_kat = kat
            
    return en_yuksek_kat

def ozet_belirle(ozet_ham: str, metin: str, baslik: str) -> str:
    """
    Haber özetini belirler. Öncelik temizlenmiş ham RSS özetindedir.
    RSS özeti boş veya yetersizse metinden kesit alır.
    """
    ozet = temizle_html(ozet_ham)
    if not ozet or len(ozet) < 15:
        temiz_metin = temizle_html(metin)
        if temiz_metin and len(temiz_metin) > 15:
            kesilmis = temiz_metin[:250]
            if len(temiz_metin) > 250 and ' ' in kesilmis:
                ozet = kesilmis.rsplit(' ', 1)[0] + "..."
            else:
                ozet = kesilmis
        else:
            ozet = baslik
    return ozet
