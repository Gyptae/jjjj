import logging
import asyncio
from aiogram import Bot


# ===================================
# КЛАСС ДЛЯ ОТПРАВКИ ЛОГОВ В ТЕЛЕГРАМ
# ===================================
class TelegramLogHandler(logging.Handler):
    def init(self, bot: Bot, chat_id: int):
        super().init()
        self.bot = bot
        self.chat_id = chat_id
        self.setLevel(logging.ERROR)  # Только ошибки и критическое

    def emit(self, record):
        """Отправляет лог в Telegram"""
        asyncio.create_task(self._send(record))

    async def _send(self, record):
        try:
            # Форматируем сообщение
            log_entry = self.format(record)
            # Обрезаем если слишком длинное
            if len(log_entry) > 3500:
                log_entry = log_entry[:3500] + "..."

            await self.bot.send_message(
                self.chat_id,
                f"🚨 <b>Ошибка в боте</b>\n<code>{log_entry}</code>",
                parse_mode="HTML"
            )
        except:
            pass  # Тихий провал, чтобы бот не падал


# ===================================
# ФУНКЦИЯ БЫСТРОЙ НАСТРОЙКИ
# ===================================
def setup_telegram_logger(bot: Bot, admin_id: int):
    """
    Включает отправку ошибок в Telegram.
    Вызывай сразу после создания bot.
    """
    # Создаем обработчик
    telegram_handler = TelegramLogHandler(bot, admin_id)

    # Красивый формат для Telegram
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s\n'
        '%(message)s\n'
        '📍 %(pathname)s:%(lineno)d',
        datefmt='%H:%M:%S'
    )
    telegram_handler.setFormatter(formatter)

    # Получаем корневой логгер
    root_logger = logging.getLogger()

    # Удаляем ВСЕ старые обработчики (включая консоль)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Добавляем только Telegram
    root_logger.addHandler(telegram_handler)
    root_logger.setLevel(logging.ERROR)

    # Отправляем тестовое сообщение
    asyncio.create_task(
        bot.send_message(admin_id, "✅ Логи переключены на Telegram")
    )

    return telegram_handler