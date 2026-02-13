"""
Утилиты безопасности
"""
import re
from typing import Optional
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from database import RateLimit, BlockedUser


class SecurityValidator:
    """Валидатор данных для безопасности"""

    @staticmethod
    def sanitize_text(text: str, max_length: int = 4000) -> str:
        """
        Очистка текста от потенциально опасных символов

        Args:
            text: Входной текст
            max_length: Максимальная длина

        Returns:
            Очищенный текст
        """
        if not text:
            return ""

        # Ограничение длины
        text = text[:max_length]

        # Удаление потенциально опасных HTML/SQL символов
        # (SQLAlchemy защищает от SQL injection, но дополнительная очистка не помешает)
        dangerous_patterns = [
            r'<script[^>]*>.*?</script>',
            r'javascript:',
            r'onerror=',
            r'onclick=',
        ]

        for pattern in dangerous_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)

        return text.strip()

    @staticmethod
    def validate_telegram_id(telegram_id: int) -> bool:
        """
        Валидация Telegram ID

        Args:
            telegram_id: ID пользователя

        Returns:
            True если ID валиден
        """
        # Telegram ID - это положительное целое число
        return isinstance(telegram_id, int) and telegram_id > 0

    @staticmethod
    def validate_price(price: float) -> bool:
        """
        Валидация цены

        Args:
            price: Цена товара

        Returns:
            True если цена валидна
        """
        return isinstance(price, (int, float)) and price >= 0 and price < 1000000


class RateLimiter:
    """Ограничитель частоты запросов"""

    def __init__(
            self,
            max_per_minute: int = 5,
            max_per_hour: int = 30
    ):
        self.max_per_minute = max_per_minute
        self.max_per_hour = max_per_hour

    async def check_limit(
            self,
            session: AsyncSession,
            telegram_id: int,
            action_type: str = "message"
    ) -> tuple[bool, Optional[str]]:
        """
        Проверка лимита запросов

        Args:
            session: Сессия БД
            telegram_id: ID пользователя
            action_type: Тип действия

        Returns:
            (разрешено, сообщение об ошибке)
        """
        now = datetime.utcnow()
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)

        # Проверка за минуту
        minute_query = select(func.count(RateLimit.id)).where(
            RateLimit.telegram_id == telegram_id,
            RateLimit.action_type == action_type,
            RateLimit.timestamp >= minute_ago
        )
        minute_result = await session.execute(minute_query)
        minute_count = minute_result.scalar()

        if minute_count >= self.max_per_minute:
            return False, "Слишком много сообщений. Подождите минуту."

        # Проверка за час
        hour_query = select(func.count(RateLimit.id)).where(
            RateLimit.telegram_id == telegram_id,
            RateLimit.action_type == action_type,
            RateLimit.timestamp >= hour_ago
        )
        hour_result = await session.execute(hour_query)
        hour_count = hour_result.scalar()

        if hour_count >= self.max_per_hour:
            return False, "Превышен лимит сообщений в час. Попробуйте позже."

        # Записываем действие
        rate_limit = RateLimit(
            telegram_id=telegram_id,
            action_type=action_type,
            timestamp=now
        )
        session.add(rate_limit)
        await session.commit()

        return True, None

    async def cleanup_old_records(self, session: AsyncSession, days: int = 7):
        """
        Очистка старых записей

        Args:
            session: Сессия БД
            days: Количество дней для хранения
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = select(RateLimit).where(RateLimit.timestamp < cutoff)
        result = await session.execute(query)
        old_records = result.scalars().all()

        for record in old_records:
            await session.delete(record)

        await session.commit()


async def is_user_blocked(session: AsyncSession, telegram_id: int) -> bool:
    """
    Проверка блокировки пользователя

    Args:
        session: Сессия БД
        telegram_id: ID пользователя

    Returns:
        True если пользователь заблокирован
    """
    query = select(BlockedUser).where(BlockedUser.telegram_id == telegram_id)
    result = await session.execute(query)
    return result.scalar_one_or_none() is not None


async def block_user(
        session: AsyncSession,
        telegram_id: int,
        blocked_by: int,
        reason: Optional[str] = None
) -> bool:
    """
    Блокировка пользователя

    Args:
        session: Сессия БД
        telegram_id: ID пользователя
        blocked_by: ID администратора
        reason: Причина блокировки

    Returns:
        True если успешно заблокирован
    """
    # Проверяем, не заблокирован ли уже
    if await is_user_blocked(session, telegram_id):
        return False

    blocked_user = BlockedUser(
        telegram_id=telegram_id,
        blocked_by=blocked_by,
        reason=SecurityValidator.sanitize_text(reason) if reason else None
    )
    session.add(blocked_user)
    await session.commit()
    return True


async def unblock_user(session: AsyncSession, telegram_id: int) -> bool:
    """
    Разблокировка пользователя

    Args:
        session: Сессия БД
        telegram_id: ID пользователя

    Returns:
        True если успешно разблокирован
    """
    query = select(BlockedUser).where(BlockedUser.telegram_id == telegram_id)
    result = await session.execute(query)
    blocked_user = result.scalar_one_or_none()

    if not blocked_user:
        return False

    await session.delete(blocked_user)
    await session.commit()
    return True