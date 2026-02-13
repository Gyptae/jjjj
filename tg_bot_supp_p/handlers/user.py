"""
Обработчики пользовательских команд
"""
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, ReplyKeyboardRemove, \
    InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from datetime import datetime, timedelta

from database import User, async_session, Order, Product, BlockedUser
from config import settings
from utils.security import is_user_blocked
from handlers.state import waiting_for_question, broadcast_media_buffer
from handlers.fsm_states import BroadcastStates

router = Router()


def get_user_keyboard():
    """Получить клавиатуру пользователя"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="❓ Задать вопрос"),
            ],
            # [
            #     KeyboardButton(
            #         text="🛍️ Каталог товаров",
            #         web_app=WebAppInfo(url='https://vlvl1-eupc.vercel.app')
            #         # web_app=WebAppInfo(url=f"{settings.WEBAPP_URL}/catalog")
            #     )
            # ]
        ],
        resize_keyboard=True
    )
    return keyboard


def get_admin_keyboard():
    """Получить клавиатуру администратора"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Статистика"),
                KeyboardButton(text="📢 Рассылка"),
            ],
            [
                KeyboardButton(text="🚫 Заблокированные"),
                KeyboardButton(text="❓ Задать вопрос"),
            ]
        ],
        resize_keyboard=True
    )
    return keyboard


def get_tech_manager_keyboard():
    """Получить клавиатуру техменеджера"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Статистика"),
                KeyboardButton(text="📢 Рассылка"),
            ],
            [
                KeyboardButton(text="➕ Добавить товар"),
            ]
        ],
        resize_keyboard=True
    )
    return keyboard


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""

    print(f"[DEBUG] /start от пользователя {message.from_user.id}")
    print(f"[DEBUG] ADMIN_ID = {settings.ADMIN_ID}")
    print(f"[DEBUG] Это админ? {message.from_user.id == settings.ADMIN_ID}")

    async with async_session() as session:
        # Проверка блокировки
        if await is_user_blocked(session, message.from_user.id):
            await message.answer("❌ Вы заблокированы и не можете использовать бота.")
            return

        # Получаем или создаем пользователя
        query = select(User).where(User.telegram_id == message.from_user.id)
        result = await session.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            # Создаем нового пользователя
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )
            session.add(user)
            await session.commit()

            print(f"[DEBUG] Создан новый пользователь: {message.from_user.id}")

            # Уведомляем ТОЛЬКО монитор о новом пользователе
            if message.from_user.id != settings.MONITOR_ID:
                try:
                    monitor_text = (
                        f"👤 Новый пользователь:\n"
                        f"ID: {message.from_user.id}\n"
                        f"Username: @{message.from_user.username or 'нет'}\n"
                        f"Имя: {message.from_user.first_name or ''} {message.from_user.last_name or ''}"
                    )
                    await message.bot.send_message(settings.MONITOR_ID, monitor_text)
                    print(f"[DEBUG] Уведомление отправлено монитору: {settings.MONITOR_ID}")
                except Exception as e:
                    print(f"[ERROR] Ошибка отправки монитору: {e}")

    # Проверяем, является ли пользователь администратором или техменеджером
    if message.from_user.id == settings.ADMIN_ID:
        print("[DEBUG] Отправляю админское приветствие")
        welcome_text = (
            "👋 Здравствуйте, администратор!\n\n"
            "🔐 Выберите действие с помощью кнопок ниже:"
        )
        await message.answer(welcome_text, reply_markup=get_admin_keyboard())
    elif message.from_user.id == settings.TECH_MANAGER_ID:
        print("[DEBUG] Отправляю приветствие техменеджера")
        welcome_text = (
            "👋 Здравствуйте, технический менеджер!\n\n"
            "🔧 Выберите действие с помощью кнопок ниже:"
        )
        await message.answer(welcome_text, reply_markup=get_tech_manager_keyboard())
    else:
        print("[DEBUG] Отправляю обычное приветствие с кнопками")
        welcome_text = (
            f"👋 Добро пожаловать, {message.from_user.first_name}!\n\n"
            "Я бот поддержки Vapor Launge. Вы можете:\n\n"
            "Связаться с поддержкой - ❓ Задать вопрос\n"
            "Выбрать товар - 🛍️ Каталог"
        )
        # welcome_text = (
        #     f"👋 Добро пожаловать, {message.from_user.first_name}!\n\n"
        #     "Я бот поддержки Vapor Launge. Выберите действие:\n\n"
        #     "❓ Задать вопрос - связаться с поддержкой\n"
        #     "🛍️ Каталог товаров - посмотреть наши товары"
        # )
        await message.answer(welcome_text, reply_markup=get_user_keyboard())


@router.message(F.text == "❓ Задать вопрос")
async def ask_question(message: Message):
    """Обработчик кнопки 'Задать вопрос'"""

    print(f"[DEBUG] Кнопка 'Задать вопрос' от {message.from_user.id}")

    # Игнорируем если это монитор или техменеджер
    if message.from_user.id in [settings.MONITOR_ID, settings.TECH_MANAGER_ID]:
        print(f"[DEBUG] Игнорирую - это монитор/техменеджер")
        return

    async with async_session() as session:
        # Проверка блокировки
        if await is_user_blocked(session, message.from_user.id):
            await message.answer("❌ Вы заблокированы и не можете писать в поддержку.")
            return

    # Отмечаем, что пользователь ожидает вопрос
    waiting_for_question[message.from_user.id] = True
    print(f"[DEBUG] Установлен флаг ожидания для {message.from_user.id}")

    await message.answer(
        "📝 Опишите ваш вопрос или проблему.\n"
        "Вы можете отправить текст, фото, видео или документы.\n\n"
        "Наша команда поддержки ответит вам в ближайшее время."
    )


@router.message(F.text == "📊 Статистика")
async def button_stats(message: Message):
    """Обработчик кнопки 'Статистика'"""

    if message.from_user.id not in [settings.ADMIN_ID, settings.TECH_MANAGER_ID]:
        return

    from sqlalchemy import select, func
    from datetime import datetime, timedelta
    from database import Order, Product

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
        f"📊 Статистика\n\n"
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


@router.message(F.text == "📢 Рассылка")
async def button_broadcast(message: Message, state: FSMContext):
    """Обработчик кнопки 'Рассылка'"""

    if message.from_user.id not in [settings.ADMIN_ID, settings.TECH_MANAGER_ID]:
        return

    # Очищаем буфер медиа
    broadcast_media_buffer[message.from_user.id] = []

    await message.answer(
        "📢 Отправьте сообщение для рассылки всем пользователям.\n"
        "Вы можете отправить текст, фото, видео или альбом.\n\n"
        "Отправьте /cancel для отмены."
    )
    await state.set_state(BroadcastStates.waiting_for_message)


@router.message(BroadcastStates.waiting_for_message, F.media_group_id)
async def handle_broadcast_media_group(message: Message, state: FSMContext):
    """Обработчик медиа-группы для рассылки"""

    if message.from_user.id not in [settings.ADMIN_ID, settings.TECH_MANAGER_ID]:
        return

    import asyncio

    # Добавляем сообщение в буфер
    if message.from_user.id not in broadcast_media_buffer:
        broadcast_media_buffer[message.from_user.id] = []

    broadcast_media_buffer[message.from_user.id].append(message)

    # Ждем пока соберутся все медиа
    await asyncio.sleep(0.5)

    # Проверяем что это последнее сообщение в группе
    media_list = broadcast_media_buffer[message.from_user.id]
    if media_list and media_list[-1].message_id == message.message_id:
        # Подтверждение
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_confirm"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")
            ]
        ])

        await state.update_data(broadcast_message=message)
        await message.answer(
            f"Вы уверены, что хотите отправить этот альбом ({len(media_list)} медиа) всем пользователям?",
            reply_markup=keyboard
        )


@router.message(BroadcastStates.waiting_for_message, Command("cancel"))
async def cancel_broadcast(message: Message, state: FSMContext):
    """Отмена рассылки"""
    await state.clear()
    await message.answer("❌ Рассылка отменена.")


@router.message(BroadcastStates.waiting_for_message)
async def process_broadcast(message: Message, state: FSMContext):
    """Обработка сообщения для рассылки"""

    if message.from_user.id not in [settings.ADMIN_ID, settings.TECH_MANAGER_ID]:
        return

    # Сохраняем тип контента
    content_type = message.content_type

    # Подтверждение
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_confirm"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")
        ]
    ])

    # Сохраняем сообщение и его тип
    await state.update_data(
        broadcast_message=message,
        content_type=content_type,
        media_group_id=message.media_group_id if hasattr(message, 'media_group_id') else None
    )

    await message.answer(
        "Вы уверены, что хотите отправить это сообщение всем пользователям?",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "broadcast_confirm")
async def confirm_broadcast(callback, state: FSMContext):
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

    # Проверяем есть ли медиа-группа
    media_group = broadcast_media_buffer.get(callback.from_user.id, [])

    async with async_session() as session:
        query = select(User.telegram_id)
        result = await session.execute(query)
        user_ids = [row[0] for row in result.fetchall()]

    success = 0
    failed = 0

    for user_id in user_ids:
        try:
            async with async_session() as session:
                if await is_user_blocked(session, user_id):
                    continue

            # Если есть медиа-группа (альбом)
            if media_group and len(media_group) > 1:
                from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument

                media_to_send = []
                for idx, msg in enumerate(media_group):
                    caption = msg.caption if idx == 0 else None

                    if msg.photo:
                        media_to_send.append(InputMediaPhoto(
                            media=msg.photo[-1].file_id,
                            caption=caption
                        ))
                    elif msg.video:
                        media_to_send.append(InputMediaVideo(
                            media=msg.video.file_id,
                            caption=caption
                        ))
                    elif msg.document:
                        media_to_send.append(InputMediaDocument(
                            media=msg.document.file_id,
                            caption=caption
                        ))

                if media_to_send:
                    await callback.bot.send_media_group(user_id, media=media_to_send)

            # Обычное сообщение
            elif broadcast_msg.text:
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
            print(f"[ERROR] Broadcast to {user_id}: {e}")

    # Очищаем буфер медиа
    if callback.from_user.id in broadcast_media_buffer:
        del broadcast_media_buffer[callback.from_user.id]

    await callback.message.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"Отправлено: {success}\n"
        f"Не доставлено: {failed}"
    )
    await state.clear()


@router.callback_query(F.data == "broadcast_cancel")
async def cancel_broadcast_callback(callback, state: FSMContext):
    """Отмена рассылки через callback"""
    await callback.message.edit_text("❌ Рассылка отменена.")
    await state.clear()


@router.message(F.text == "🚫 Заблокированные")
async def button_blocked_users(message: Message):
    """Обработчик кнопки 'Заблокированные'"""

    if message.from_user.id != settings.ADMIN_ID:
        return

    from sqlalchemy import select
    from database import BlockedUser

    async with async_session() as session:
        query = select(BlockedUser).order_by(BlockedUser.blocked_at.desc())
        result = await session.execute(query)
        blocked_users = result.scalars().all()

        if not blocked_users:
            await message.answer("✅ Нет заблокированных пользователей")
            return

        text = "🚫 Заблокированные пользователи:\n\n"
        for user in blocked_users:
            text += f"ID: {user.telegram_id}\n"
            if user.reason:
                text += f"Причина: {user.reason}\n"
            text += f"Дата: {user.blocked_at.strftime('%d.%m.%Y %H:%M')}\n"
            text += "─" * 30 + "\n"

        await message.answer(text)


@router.message(F.text == "➕ Добавить товар")
async def button_add_product(message: Message):
    """Обработчик кнопки 'Добавить товар'"""

    if message.from_user.id != settings.TECH_MANAGER_ID:
        return

    await message.answer(
        "📦 Добавление товара\n\n"
        "Для добавления товара используйте скрипт:\n"
        "python scripts/add_product.py\n\n"
        "Или отправьте данные в формате:\n"
        "/add_product Название | Описание | Цена | Категория"
    )
# """
# Обработчики пользовательских команд
# """
# from aiogram import Router, F
# from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, ReplyKeyboardRemove, \
#     InlineKeyboardMarkup, InlineKeyboardButton
# from aiogram.filters import CommandStart, Command
# from aiogram.fsm.context import FSMContext
# from sqlalchemy import select
# from datetime import datetime, timedelta
#
# from database import User, async_session, Order, Product, BlockedUser
# from config import settings
# from utils.security import is_user_blocked
# from handlers.state import waiting_for_question
# from handlers.fsm_states import BroadcastStates
#
# router = Router()
#
#
# def get_user_keyboard():
#     """Получить клавиатуру пользователя"""
#     keyboard = ReplyKeyboardMarkup(
#         keyboard=[
#             [
#                 KeyboardButton(text="❓ Задать вопрос"),
#             ],
#             [
#                 KeyboardButton(
#                     text="🛍️ Каталог товаров",
#                     web_app=WebAppInfo(url=f"{settings.WEBAPP_URL}/catalog")
#                 )
#             ]
#         ],
#         resize_keyboard=True
#     )
#     return keyboard
#
#
# def get_admin_keyboard():
#     """Получить клавиатуру администратора"""
#     keyboard = ReplyKeyboardMarkup(
#         keyboard=[
#             [
#                 KeyboardButton(text="📊 Статистика"),
#                 KeyboardButton(text="📢 Рассылка"),
#             ],
#             [
#                 KeyboardButton(text="🚫 Заблокированные"),
#             ]
#         ],
#         resize_keyboard=True
#     )
#     return keyboard
#
#
# def get_tech_manager_keyboard():
#     """Получить клавиатуру техменеджера"""
#     keyboard = ReplyKeyboardMarkup(
#         keyboard=[
#             [
#                 KeyboardButton(text="📊 Статистика"),
#                 KeyboardButton(text="📢 Рассылка"),
#             ],
#             [
#                 KeyboardButton(text="➕ Добавить товар"),
#             ]
#         ],
#         resize_keyboard=True
#     )
#     return keyboard
#
#
# @router.message(CommandStart())
# async def cmd_start(message: Message):
#     """Обработчик команды /start"""
#
#     print(f"[DEBUG] /start от пользователя {message.from_user.id}")
#     print(f"[DEBUG] ADMIN_ID = {settings.ADMIN_ID}")
#     print(f"[DEBUG] Это админ? {message.from_user.id == settings.ADMIN_ID}")
#
#     async with async_session() as session:
#         # Проверка блокировки
#         if await is_user_blocked(session, message.from_user.id):
#             await message.answer("❌ Вы заблокированы и не можете использовать бота.")
#             return
#
#         # Получаем или создаем пользователя
#         query = select(User).where(User.telegram_id == message.from_user.id)
#         result = await session.execute(query)
#         user = result.scalar_one_or_none()
#
#         if not user:
#             # Создаем нового пользователя
#             user = User(
#                 telegram_id=message.from_user.id,
#                 username=message.from_user.username,
#                 first_name=message.from_user.first_name,
#                 last_name=message.from_user.last_name
#             )
#             session.add(user)
#             await session.commit()
#
#             print(f"[DEBUG] Создан новый пользователь: {message.from_user.id}")
#
#             # Уведомляем ТОЛЬКО монитор о новом пользователе
#             if message.from_user.id != settings.MONITOR_ID:
#                 try:
#                     monitor_text = (
#                         f"👤 Новый пользователь:\n"
#                         f"ID: {message.from_user.id}\n"
#                         f"Username: @{message.from_user.username or 'нет'}\n"
#                         f"Имя: {message.from_user.first_name or ''} {message.from_user.last_name or ''}"
#                     )
#                     await message.bot.send_message(settings.MONITOR_ID, monitor_text)
#                     print(f"[DEBUG] Уведомление отправлено монитору: {settings.MONITOR_ID}")
#                 except Exception as e:
#                     print(f"[ERROR] Ошибка отправки монитору: {e}")
#
#     # Проверяем, является ли пользователь администратором или техменеджером
#     if message.from_user.id == settings.ADMIN_ID:
#         print("[DEBUG] Отправляю админское приветствие")
#         welcome_text = (
#             "👋 Здравствуйте, администратор!\n\n"
#             "🔐 Выберите действие с помощью кнопок ниже:"
#         )
#         await message.answer(welcome_text, reply_markup=get_admin_keyboard())
#     elif message.from_user.id == settings.TECH_MANAGER_ID:
#         print("[DEBUG] Отправляю приветствие техменеджера")
#         welcome_text = (
#             "👋 Здравствуйте, технический менеджер!\n\n"
#             "🔧 Выберите действие с помощью кнопок ниже:"
#         )
#         await message.answer(welcome_text, reply_markup=get_tech_manager_keyboard())
#     else:
#         print("[DEBUG] Отправляю обычное приветствие с кнопками")
#         welcome_text = (
#             f"👋 Добро пожаловать, {message.from_user.first_name}!\n\n"
#             "Я бот поддержки вейпшопа. Выберите действие:\n\n"
#             "❓ Задать вопрос - связаться с поддержкой\n"
#             "🛍️ Каталог товаров - посмотреть наши товары"
#         )
#         await message.answer(welcome_text, reply_markup=get_user_keyboard())
#
#
# @router.message(F.text == "❓ Задать вопрос")
# async def ask_question(message: Message):
#     """Обработчик кнопки 'Задать вопрос'"""
#
#     print(f"[DEBUG] Кнопка 'Задать вопрос' от {message.from_user.id}")
#
#     # Игнорируем если это монитор или техменеджер
#     if message.from_user.id in [settings.MONITOR_ID, settings.TECH_MANAGER_ID]:
#         print(f"[DEBUG] Игнорирую - это монитор/техменеджер")
#         return
#
#     async with async_session() as session:
#         # Проверка блокировки
#         if await is_user_blocked(session, message.from_user.id):
#             await message.answer("❌ Вы заблокированы и не можете писать в поддержку.")
#             return
#
#     # Отмечаем, что пользователь ожидает вопрос
#     waiting_for_question[message.from_user.id] = True
#     print(f"[DEBUG] Установлен флаг ожидания для {message.from_user.id}")
#
#     await message.answer(
#         "📝 Опишите ваш вопрос или проблему.\n"
#         "Вы можете отправить текст, фото, видео или документы.\n\n"
#         "Наша команда поддержки ответит вам в ближайшее время."
#     )
#
#
# @router.message(F.text == "📊 Статистика")
# async def button_stats(message: Message):
#     """Обработчик кнопки 'Статистика'"""
#
#     if message.from_user.id not in [settings.ADMIN_ID, settings.TECH_MANAGER_ID]:
#         return
#
#     from sqlalchemy import select, func
#     from datetime import datetime, timedelta
#     from database import Order, Product
#
#     async with async_session() as session:
#         # Пользователи
#         total_users_query = select(func.count(User.id))
#         total_users = (await session.execute(total_users_query)).scalar()
#
#         # Новые за неделю
#         week_ago = datetime.utcnow() - timedelta(days=7)
#         new_users_query = select(func.count(User.id)).where(User.created_at >= week_ago)
#         new_users = (await session.execute(new_users_query)).scalar()
#
#         # Заказы
#         total_orders_query = select(func.count(Order.id))
#         total_orders = (await session.execute(total_orders_query)).scalar()
#
#         # Заказы за неделю
#         new_orders_query = select(func.count(Order.id)).where(Order.created_at >= week_ago)
#         new_orders = (await session.execute(new_orders_query)).scalar()
#
#         # Товары
#         products_query = select(func.count(Product.id))
#         total_products = (await session.execute(products_query)).scalar()
#
#     stats_text = (
#         f"📊 Статистика\n\n"
#         f"👥 Пользователи:\n"
#         f"  • Всего: {total_users}\n"
#         f"  • Новых за неделю: {new_users}\n\n"
#         f"📦 Заказы:\n"
#         f"  • Всего: {total_orders}\n"
#         f"  • За неделю: {new_orders}\n\n"
#         f"🛍️ Товары:\n"
#         f"  • В каталоге: {total_products}"
#     )
#
#     await message.answer(stats_text)
#
#
# @router.message(F.text == "📢 Рассылка")
# async def button_broadcast(message: Message, state: FSMContext):
#     """Обработчик кнопки 'Рассылка'"""
#
#     if message.from_user.id not in [settings.ADMIN_ID, settings.TECH_MANAGER_ID]:
#         return
#
#     await message.answer(
#         "📢 Отправьте сообщение для рассылки всем пользователям.\n"
#         "Вы можете отправить текст, фото или видео.\n\n"
#         "Отправьте /cancel для отмены."
#     )
#     await state.set_state(BroadcastStates.waiting_for_message)
#
#
# @router.message(BroadcastStates.waiting_for_message, Command("cancel"))
# async def cancel_broadcast(message: Message, state: FSMContext):
#     """Отмена рассылки"""
#     await state.clear()
#     await message.answer("❌ Рассылка отменена.")
#
#
# @router.message(BroadcastStates.waiting_for_message)
# async def process_broadcast(message: Message, state: FSMContext):
#     """Обработка сообщения для рассылки"""
#
#     if message.from_user.id not in [settings.ADMIN_ID, settings.TECH_MANAGER_ID]:
#         return
#
#     # Подтверждение
#     keyboard = InlineKeyboardMarkup(inline_keyboard=[
#         [
#             InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_confirm"),
#             InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")
#         ]
#     ])
#
#     await state.update_data(broadcast_message=message)
#     await message.answer(
#         "Вы уверены, что хотите отправить это сообщение всем пользователям?",
#         reply_markup=keyboard
#     )
#
#
# @router.callback_query(F.data == "broadcast_confirm")
# async def confirm_broadcast(callback, state: FSMContext):
#     """Подтверждение рассылки"""
#     if callback.from_user.id not in [settings.ADMIN_ID, settings.TECH_MANAGER_ID]:
#         await callback.answer("У вас нет прав!")
#         return
#
#     data = await state.get_data()
#     broadcast_msg = data.get("broadcast_message")
#
#     if not broadcast_msg:
#         await callback.message.edit_text("❌ Сообщение для рассылки не найдено.")
#         await state.clear()
#         return
#
#     await callback.message.edit_text("📤 Начинаю рассылку...")
#
#     async with async_session() as session:
#         # Получаем всех пользователей
#         query = select(User.telegram_id)
#         result = await session.execute(query)
#         user_ids = [row[0] for row in result.fetchall()]
#
#     success = 0
#     failed = 0
#
#     for user_id in user_ids:
#         try:
#             # Пропускаем заблокированных
#             async with async_session() as session:
#                 if await is_user_blocked(session, user_id):
#                     continue
#
#             # Отправляем сообщение
#             if broadcast_msg.text:
#                 await callback.bot.send_message(user_id, broadcast_msg.text)
#             elif broadcast_msg.photo:
#                 await callback.bot.send_photo(
#                     user_id,
#                     broadcast_msg.photo[-1].file_id,
#                     caption=broadcast_msg.caption
#                 )
#             elif broadcast_msg.video:
#                 await callback.bot.send_video(
#                     user_id,
#                     broadcast_msg.video.file_id,
#                     caption=broadcast_msg.caption
#                 )
#
#             success += 1
#         except Exception as e:
#             failed += 1
#
#     await callback.message.edit_text(
#         f"✅ Рассылка завершена!\n\n"
#         f"Отправлено: {success}\n"
#         f"Не доставлено: {failed}"
#     )
#     await state.clear()
#
#
# @router.callback_query(F.data == "broadcast_cancel")
# async def cancel_broadcast_callback(callback, state: FSMContext):
#     """Отмена рассылки через callback"""
#     await callback.message.edit_text("❌ Рассылка отменена.")
#     await state.clear()
#
#
# @router.message(F.text == "🚫 Заблокированные")
# async def button_blocked_users(message: Message):
#     """Обработчик кнопки 'Заблокированные'"""
#
#     if message.from_user.id != settings.ADMIN_ID:
#         return
#
#     from sqlalchemy import select
#     from database import BlockedUser
#
#     async with async_session() as session:
#         query = select(BlockedUser).order_by(BlockedUser.blocked_at.desc())
#         result = await session.execute(query)
#         blocked_users = result.scalars().all()
#
#         if not blocked_users:
#             await message.answer("✅ Нет заблокированных пользователей")
#             return
#
#         text = "🚫 Заблокированные пользователи:\n\n"
#         for user in blocked_users:
#             text += f"ID: {user.telegram_id}\n"
#             if user.reason:
#                 text += f"Причина: {user.reason}\n"
#             text += f"Дата: {user.blocked_at.strftime('%d.%m.%Y %H:%M')}\n"
#             text += "─" * 30 + "\n"
#
#         await message.answer(text)
#
#
# @router.message(F.text == "➕ Добавить товар")
# async def button_add_product(message: Message):
#     """Обработчик кнопки 'Добавить товар'"""
#
#     if message.from_user.id != settings.TECH_MANAGER_ID:
#         return
#
#     await message.answer(
#         "📦 Добавление товара\n\n"
#         "Для добавления товара используйте скрипт:\n"
#         "python scripts/add_product.py\n\n"
#         "Или отправьте данные в формате:\n"
#         "/add_product Название | Описание | Цена | Категория"
#     )