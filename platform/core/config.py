"""Cấu hình ứng dụng, đọc từ biến môi trường / file .env (spec 13.4)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env ở gốc repo (khi chạy trên laptop); trong Docker biến được nạp qua env_file
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DB
    database_url: str = "postgresql+asyncpg://greenhub:greenhub@localhost:5432/greenhub"

    # Auth
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_min: int = 720

    # MQTT
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_public_host: str = "localhost"
    mqtt_public_port: int = 8883
    mqtt_worker_user: str = "worker"
    mqtt_worker_password: str = ""
    mqtt_admin_user: str = "api-admin"
    mqtt_admin_password: str = ""

    # Web Push
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # Email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_tls: bool = False
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_from: str = "greenhub@example.com"

    # Khác
    domain: str = "localhost"
    tz: str = "Asia/Ho_Chi_Minh"
    models_dir: Path = Path("./models")
    log_level: str = "INFO"

    # Hằng số nghiệp vụ mặc định (có thể override bằng env)
    command_expire_s: int = 30
    alert_cooldown_min: int = 10
    escalate_after_min: int = 5
    yield_low_threshold: float = 0.6


@lru_cache
def get_settings() -> Settings:
    return Settings()

