"""
Главный файл Telegram бота
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config import settings
from database import init_db
from handlers import user, support, admin

from logger_telegram import setup_telegram_logger

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Главная функция запуска бота"""

    # Инициализация базы данных
    logger.info("Инициализация базы данных...")
    await init_db()

    # Создание бота и диспетчера
    from aiogram.fsm.storage.memory import MemoryStorage
    storage = MemoryStorage()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=None)
    )

    dp = Dispatcher(storage=storage)

    # Регистрация роутеров
    dp.include_router(user.router)
    dp.include_router(support.router)
    dp.include_router(admin.router)

    # TELEGRAM_ADMIN_ID = 123456789  # ваш ID
    # bot = Bot("TOKEN")

    class TelegramLogHandler(logging.Handler):
        def emit(self, record):
            log_entry = self.format(record)
            asyncio.create_task(bot.send_message(settings.TECH_MANAGER_ID, log_entry[:4000]))

    # Настройка логгера
    # logger = logging.getLogger(__name__)
    # logger.setLevel(logging.ERROR)
    # logger.addHandler(TelegramLogHandler())

    logger.info("Бот запущен и готов к работе!")

    # Уведомление админа о запуске
    # try:
    #     await bot.send_message(
    #         settings.ADMIN_ID,
    #         "🤖 Бот успешно запущен и готов к работе!"
    #     )
    # except Exception as e:
    #     logger.error(f"Не удалось отправить уведомление админу: {e}")

    # Запуск polling
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")