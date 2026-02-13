"""
Обработчики административных команд
"""
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from datetime import datetime, timedelta

from database import async_session, User, BlockedUser, Product, Order
from config import settings
from utils.security import (
    SecurityValidator,
    block_user,
    unblock_user,
    is_user_blocked
)

router = Router()


class BroadcastStates(StatesGroup):
    """Состояния для рассылки"""
    waiting_for_message = State()


class ProductStates(StatesGroup):
    """Состояния для добавления товара"""
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_price = State()
    waiting_for_image = State()


def admin_only(func):
    """Декоратор для проверки прав администратора"""

    async def wrapper(message: Message, *args, **kwargs):
        if message.from_user.id != settings.ADMIN_ID:
            await message.answer("❌ У вас нет прав для выполнения этой команды.")
            return
        return await func(message, *args, **kwargs)

    return wrapper


def admin_or_tech(func):
    """Декоратор для админа или техменеджера"""

    async def wrapper(message: Message, *args, **kwargs):
        if message.from_user.id not in [settings.ADMIN_ID, settings.TECH_MANAGER_ID]:
            await message.answer("❌ У вас нет прав для выполнения этой команды.")
            return
        return await func(message, *args, **kwargs)

    return wrapper


@router.message(Command("admin"))
@admin_only
async def cmd_admin(message: Message):
    """Панель администратора"""
    async with async_session() as session:
        # Статистика пользователей
        users_query = select(func.count(User.id))
        users_result = await session.execute(users_query)
        total_users = users_result.scalar()

        # Заблокированные
        blocked_query = select(func.count(BlockedUser.id))
        blocked_result = await session.execute(blocked_query)
        total_blocked = blocked_result.scalar()

        # Заказы за сегодня
        today = datetime.utcnow().date()
        orders_query = select(func.count(Order.id)).where(
            func.date(Order.created_at) == today
        )
        orders_result = await session.execute(orders_query)
        today_orders = orders_result.scalar()

    admin_text = (
        f"🔐 Панель администратора\n\n"
        f"📊 Статистика:\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🚫 Заблокировано: {total_blocked}\n"
        f"📦 Заказов сегодня: {today_orders}\n\n"
        f"📋 Доступные команды:\n"
        f"/block [user_id] - Заблокировать пользователя\n"
        f"/unblock [user_id] - Разблокировать\n"
        f"/broadcast - Отправить рассылку\n"
        f"/stats - Подробная статистика\n"
        f"/add_product - Добавить товар\n"
        f"/orders - Список заказов"
    )

    await message.answer(admin_text)


@router.message(Command("block"))
@admin_only
async def cmd_block_user(message: Message):
    """Блокировка пользователя"""
    # Парсим аргументы
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ Использование: /block [user_id] [причина]\n"
            "Пример: /block 123456789 спам"
        )
        return

    try:
        user_id = int(args[1])
        reason = " ".join(args[2:]) if len(args) > 2 else None
    except ValueError:
        await message.answer("❌ Неверный формат ID пользователя.")
        return

    # Нельзя заблокировать админа или монитор
    if user_id in [settings.ADMIN_ID, settings.MONITOR_ID]:
        await message.answer("❌ Нельзя заблокировать этого пользователя.")
        return

    async with async_session() as session:
        success = await block_user(
            session,
            user_id,
            message.from_user.id,
            reason
        )

        if success:
            await message.answer(f"✅ Пользователь {user_id} заблокирован.")
            # Уведомляем пользователя
            try:
                await message.bot.send_message(
                    user_id,
                    "⛔ Вы были заблокированы администратором.\n"
                    f"Причина: {reason or 'не указана'}"
                )
            except:
                pass
        else:
            await message.answer(f"❌ Пользователь {user_id} уже заблокирован.")


@router.message(Command("unblock"))
@admin_only
async def cmd_unblock_user(message: Message):
    """Разблокировка пользователя"""
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "❌ Использование: /unblock [user_id]\n"
            "Пример: /unblock 123456789"
        )
        return

    try:
        user_id = int(args[1])
    except ValueError:
        await message.answer("❌ Неверный формат ID пользователя.")
        return

    async with async_session() as session:
        success = await unblock_user(session, user_id)

        if success:
            await message.answer(f"✅ Пользователь {user_id} разблокирован.")
            # Уведомляем пользователя
            try:
                await message.bot.send_message(
                    user_id,
                    "✅ Вы были разблокированы. Теперь вы можете снова использовать бота."
                )
            except:
                pass
        else:
            await message.answer(f"❌ Пользователь {user_id} не найден в списке заблокированных.")


@router.message(Command("broadcast"))
@admin_or_tech
async def cmd_broadcast(message: Message, state: FSMContext):
    """Начало рассылки"""
    await message.answer(
        "📢 Отправьте сообщение для рассылки всем пользователям.\n"
        "Вы можете отправить текст, фото или видео.\n\n"
        "Отправьте /cancel для отмены."
    )
    await state.set_state(BroadcastStates.waiting_for_message)


@router.message(BroadcastStates.waiting_for_message)
@admin_or_tech
async def process_broadcast(message: Message, state: FSMContext):
    """Обработка сообщения для рассылки"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена.")
        return

    # Подтверждение
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_confirm"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")
        ]
    ])

    await state.update_data(broadcast_message=message)
    await message.answer(
        "Вы уверены, что хотите отправить это сообщение всем пользователям?",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "broadcast_confirm")
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext):
    """Подтверждение рассылки"""
    if callback.from_user.id not in [settings.ADMIN_ID, settings.TECH_MANAGER_ID]:
        await callback.answer("У вас нет прав!")
        return

    data = await state.get_data()
    broadcast_msg = data.get("broadcast_message")

    if not broadcast_msg:
        await callback.message.edit_text("❌ Сообщение для рассылки не найдено.")
        await state.clear()
        return

    await callback.message.edit_text("📤 Начинаю рассылку...")

    async with async_session() as session:
        # Получаем всех пользователей
        query = select(User.telegram_id)
        result = await session.execute(query)
        user_ids = [row[0] for row in result.fetchall()]

    success = 0
    failed = 0

    for user_id in user_ids:
        try:
            # Пропускаем заблокированных
            async with async_session() as session:
                if await is_user_blocked(session, user_id):
                    continue

            # Отправляем сообщение
            if broadcast_msg.text:
                await callback.bot.send_message(user_id, broadcast_msg.text)
            elif broadcast_msg.photo:
                await callback.bot.send_photo(
                    user_id,
                    broadcast_msg.photo[-1].file_id,
                    caption=broadcast_msg.caption
                )
            elif broadcast_msg.video:
                await callback.bot.send_video(
                    user_id,
                    broadcast_msg.video.file_id,
                    caption=broadcast_msg.caption
                )

            success += 1
        except Exception as e:
            failed += 1

    await callback.message.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"Отправлено: {success}\n"
        f"Не доставлено: {failed}"
    )
    await state.clear()


@router.callback_query(F.data == "broadcast_cancel")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Отмена рассылки"""
    await callback.message.edit_text("❌ Рассылка отменена.")
    await state.clear()


@router.message(Command("stats"))
@admin_or_tech
async def cmd_stats(message: Message):
    """Подробная статистика"""
    async with async_session() as session:
        # Пользователи
        total_users_query = select(func.count(User.id))
        total_users = (await session.execute(total_users_query)).scalar()

        # Новые за неделю
        week_ago = datetime.utcnow() - timedelta(days=7)
        new_users_query = select(func.count(User.id)).where(User.created_at >= week_ago)
        new_users = (await session.execute(new_users_query)).scalar()

        # Заказы
        total_orders_query = select(func.count(Order.id))
        total_orders = (await session.execute(total_orders_query)).scalar()

        # Заказы за неделю
        new_orders_query = select(func.count(Order.id)).where(Order.created_at >= week_ago)
        new_orders = (await session.execute(new_orders_query)).scalar()

        # Товары
        products_query = select(func.count(Product.id))
        total_products = (await session.execute(products_query)).scalar()

    stats_text = (
        f"📊 Подробная статистика\n\n"
        f"👥 Пользователи:\n"
        f"  • Всего: {total_users}\n"
        f"  • Новых за неделю: {new_users}\n\n"
        f"📦 Заказы:\n"
        f"  • Всего: {total_orders}\n"
        f"  • За неделю: {new_orders}\n\n"
        f"🛍️ Товары:\n"
        f"  • В каталоге: {total_products}"
    )

    await message.answer(stats_text)