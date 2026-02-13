"""
Конфигурация бота
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Настройки приложения"""

    # Telegram
    BOT_TOKEN: str
    ADMIN_ID: int
    MONITOR_ID: int
    TECH_MANAGER_ID: int  # Новый - техменеджер

    # Database
    DATABASE_URL: str

    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"

    # Rate Limiting
    MAX_MESSAGES_PER_MINUTE: int = 5
    MAX_MESSAGES_PER_HOUR: int = 30

    # Web App
    WEBAPP_URL: str = "https://your-domain.com"

    # Redis (опционально для rate limiting)
    REDIS_URL: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()