import os
from dataclasses import dataclass, field
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class RssKaynak:
    isim: str
    url: str
    aktif: bool = True


@dataclass
class Config:
    # Turso
    turso_url: str = ""
    turso_auth_token: str = ""

    # Ollama
    ollama_model: str = "qwen2.5:7b"

    # Flask
    flask_secret_key: str = "degistir-beni"
    flask_env: str = "production"
    cors_origins: list[str] = field(default_factory=list)

    # Scheduler
    rss_interval_minutes: int = 15

    # RSS kaynakları
    rss_kaynaklar: list[RssKaynak] = field(default_factory=list)

    # Devre kesici
    circuit_breaker_threshold: int = 3
    circuit_breaker_timeout_minutes: int = 30

    # Duplikasyon
    duplikasyon_esik: float = 0.75
    duplikasyon_pencere_saat: int = 24

    # Temizlik
    haber_max_gun: int = 30

    @classmethod
    def yukle(cls, yaml_yol: str = "config.yaml") -> "Config":
        cfg = cls()

        # .env'den yükle
        cfg.turso_url = os.getenv("TURSO_URL", "")
        cfg.turso_auth_token = os.getenv("TURSO_AUTH_TOKEN", "")
        cfg.flask_secret_key = os.getenv("FLASK_SECRET_KEY", "degistir-beni")
        cfg.flask_env = os.getenv("FLASK_ENV", "production")

        # config.yaml'dan yükle
        if os.path.exists(yaml_yol):
            with open(yaml_yol, "r", encoding="utf-8") as f:
                veri: dict[str, Any] = yaml.safe_load(f) or {}

            cfg.ollama_model = veri.get("ollama_model", cfg.ollama_model)
            cfg.cors_origins = veri.get("cors_origins", ["*"])
            cfg.rss_interval_minutes = veri.get("rss_interval_minutes", 15)
            cfg.circuit_breaker_threshold = veri.get("circuit_breaker_threshold", 3)
            cfg.circuit_breaker_timeout_minutes = veri.get(
                "circuit_breaker_timeout_minutes", 30
            )
            cfg.duplikasyon_esik = veri.get("duplikasyon_esik", 0.75)
            cfg.duplikasyon_pencere_saat = veri.get("duplikasyon_pencere_saat", 24)
            cfg.haber_max_gun = veri.get("haber_max_gun", 30)

            kaynaklar = veri.get("rss_kaynaklar", [])
            cfg.rss_kaynaklar = [
                RssKaynak(
                    isim=k["isim"],
                    url=k["url"],
                    aktif=k.get("aktif", True),
                )
                for k in kaynaklar
            ]

        return cfg

    def dogrula(self) -> list[str]:
        """Eksik zorunlu ayarları döndürür."""
        hatalar = []
        if not self.turso_url:
            hatalar.append("TURSO_URL tanımlı değil")
        if not self.turso_auth_token:
            hatalar.append("TURSO_AUTH_TOKEN tanımlı değil")
        if not self.rss_kaynaklar:
            hatalar.append("config.yaml içinde rss_kaynaklar boş")
        return hatalar


# Uygulama genelinde tek instance
_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.yukle()
    return _config
