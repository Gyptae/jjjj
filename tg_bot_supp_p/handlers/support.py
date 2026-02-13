"""
Обработчики поддержки
"""
from aiogram import Router, F
from aiogram.types import Message, ContentType, InputMediaPhoto, InputMediaVideo, InputMediaDocument, \
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from collections import defaultdict
import asyncio

from database import async_session
from config import settings
from utils.security import SecurityValidator, RateLimiter, is_user_blocked, block_user, unblock_user
from handlers.state import waiting_for_question, user_messages, admin_reply_mode, admin_media_buffer, control_messages

router = Router()

rate_limiter = RateLimiter(
    max_per_minute=settings.MAX_MESSAGES_PER_MINUTE,
    max_per_hour=settings.MAX_MESSAGES_PER_HOUR
)

# Словарь для сбора медиа-группы от пользователей
media_groups = defaultdict(list)


def get_admin_keyboard(user_id: int, is_blocked: bool = False):
    """Получить клавиатуру для управления вопросом"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_{user_id}"),
            InlineKeyboardButton(text="🚫 Блок" if not is_blocked else "✅ Разблок",
                                 callback_data=f"block_{user_id}")
        ],
        [
            InlineKeyboardButton(text="❌ Игнор", callback_data=f"ignore_{user_id}")
        ]
    ])
    return keyboard


def get_cancel_keyboard(user_id: int):
    """Клавиатура отмены для режима ответа"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отменить ответ", callback_data=f"cancel_reply_{user_id}")
        ]
    ])
    return keyboard


async def send_question_to_admin(message: Message, user_info_text: str, media_group=None):
    """Отправка вопроса администратору"""

    print(f"[DEBUG] Отправка вопроса админу от {message.from_user.id}")

    # Проверяем заблокирован ли пользователь
    async with async_session() as session:
        is_blocked = await is_user_blocked(session, message.from_user.id)

    try:
        # Если есть медиа-группа (альбом)
        if media_group and len(media_group) > 1:
            # Сначала отправляем текст вопроса если есть
            question_text = None
            for msg in media_group:
                if msg.caption:
                    question_text = msg.caption
                    break

            # Формируем полный текст с информацией о пользователе
            if question_text:
                full_text = f"{user_info_text}\n\n💬 Вопрос:\n{question_text}"
                await message.bot.send_message(settings.ADMIN_ID, full_text)
            else:
                await message.bot.send_message(settings.ADMIN_ID, user_info_text)

            # Отправляем медиа-группу
            media_to_send = []
            for msg in media_group:
                if msg.photo:
                    media_item = InputMediaPhoto(media=msg.photo[-1].file_id)
                elif msg.video:
                    media_item = InputMediaVideo(media=msg.video.file_id)
                elif msg.document:
                    media_item = InputMediaDocument(media=msg.document.file_id)
                else:
                    continue
                media_to_send.append(media_item)

            sent_messages = await message.bot.send_media_group(
                settings.ADMIN_ID,
                media=media_to_send
            )

            if sent_messages:
                # Отправляем кнопки управления отдельным сообщением
                control_msg = await message.bot.send_message(
                    settings.ADMIN_ID,
                    "⬆️ Управление вопросом:",
                    reply_markup=get_admin_keyboard(message.from_user.id, is_blocked)
                )
                user_messages[sent_messages[0].message_id] = message.from_user.id
                user_messages[control_msg.message_id] = message.from_user.id
                # Сохраняем ID сообщения с кнопками
                control_messages[message.from_user.id] = (settings.ADMIN_ID, control_msg.message_id)
                print(f"[DEBUG] Альбом отправлен админу")

        else:
            # Одно сообщение
            forwarded = None
            if message.text:
                full_text = f"{user_info_text}\n\n💬 Вопрос:\n{message.text}"
                forwarded = await message.bot.send_message(
                    settings.ADMIN_ID,
                    full_text,
                    reply_markup=get_admin_keyboard(message.from_user.id, is_blocked)
                )
            elif message.photo:
                caption = message.caption or ""
                full_caption = f"{user_info_text}\n\n💬 Вопрос:\n{caption}" if caption else user_info_text
                forwarded = await message.bot.send_photo(
                    settings.ADMIN_ID,
                    message.photo[-1].file_id,
                    caption=full_caption,
                    reply_markup=get_admin_keyboard(message.from_user.id, is_blocked)
                )
            elif message.video:
                caption = message.caption or ""
                full_caption = f"{user_info_text}\n\n💬 Вопрос:\n{caption}" if caption else user_info_text
                forwarded = await message.bot.send_video(
                    settings.ADMIN_ID,
                    message.video.file_id,
                    caption=full_caption,
                    reply_markup=get_admin_keyboard(message.from_user.id, is_blocked)
                )
            elif message.document:
                caption = message.caption or ""
                full_caption = f"{user_info_text}\n\n💬 Вопрос:\n{caption}" if caption else user_info_text
                forwarded = await message.bot.send_document(
                    settings.ADMIN_ID,
                    message.document.file_id,
                    caption=full_caption,
                    reply_markup=get_admin_keyboard(message.from_user.id, is_blocked)
                )
            elif message.voice:
                forwarded = await message.bot.send_voice(
                    settings.ADMIN_ID,
                    message.voice.file_id,
                    caption=user_info_text,
                    reply_markup=get_admin_keyboard(message.from_user.id, is_blocked)
                )
            elif message.audio:
                forwarded = await message.bot.send_audio(
                    settings.ADMIN_ID,
                    message.audio.file_id,
                    caption=user_info_text,
                    reply_markup=get_admin_keyboard(message.from_user.id, is_blocked)
                )

            if forwarded:
                user_messages[forwarded.message_id] = message.from_user.id
                print(f"[DEBUG] Сообщение отправлено админу с кнопками")

    except Exception as e:
        print(f"[ERROR] Ошибка отправки админу: {e}")
        raise


@router.callback_query(F.data.startswith("reply_"))
async def handle_reply_button(callback: CallbackQuery):
    """Обработка кнопки 'Ответить'"""

    if callback.from_user.id != settings.ADMIN_ID:
        await callback.answer("У вас нет прав!")
        return

    user_id = int(callback.data.split("_")[1])

    # Включаем режим ответа
    admin_reply_mode[callback.from_user.id] = user_id
    admin_media_buffer[callback.from_user.id] = []

    await callback.message.edit_reply_markup(
        reply_markup=get_cancel_keyboard(user_id)
    )

    await callback.answer()
    await callback.message.answer(
        f"📝 Режим ответа пользователю {user_id}\n\n"
        "Отправьте ваш ответ (текст, фото, видео, альбом).\n"
        "Нажмите 'Отменить ответ' для отмены."
    )

    print(f"[DEBUG] Админ включил режим ответа для {user_id}")


@router.callback_query(F.data.startswith("cancel_reply_"))
async def handle_cancel_reply(callback: CallbackQuery):
    """Отмена режима ответа"""

    if callback.from_user.id != settings.ADMIN_ID:
        await callback.answer("У вас нет прав!")
        return

    user_id = int(callback.data.split("_")[2])

    # Выключаем режим ответа
    if callback.from_user.id in admin_reply_mode:
        del admin_reply_mode[callback.from_user.id]
    if callback.from_user.id in admin_media_buffer:
        del admin_media_buffer[callback.from_user.id]

    async with async_session() as session:
        is_blocked = await is_user_blocked(session, user_id)

    await callback.message.edit_reply_markup(
        reply_markup=get_admin_keyboard(user_id, is_blocked)
    )

    await callback.answer("Режим ответа отменен")
    await callback.message.answer("❌ Режим ответа отменен")

    print(f"[DEBUG] Админ отменил режим ответа для {user_id}")


@router.callback_query(F.data.startswith("block_"))
async def handle_block_button(callback: CallbackQuery):
    """Обработка кнопки блокировки/разблокировки"""

    if callback.from_user.id != settings.ADMIN_ID:
        await callback.answer("У вас нет прав!")
        return

    user_id = int(callback.data.split("_")[1])

    async with async_session() as session:
        is_blocked = await is_user_blocked(session, user_id)

        if is_blocked:
            # Разблокировать
            success = await unblock_user(session, user_id)
            if success:
                await callback.message.edit_reply_markup(
                    reply_markup=get_admin_keyboard(user_id, False)
                )
                await callback.answer("✅ Пользователь разблокирован")
                try:
                    await callback.bot.send_message(
                        user_id,
                        "✅ Вы были разблокированы. Теперь вы можете снова использовать бота."
                    )
                except:
                    pass
        else:
            # Заблокировать
            success = await block_user(session, user_id, callback.from_user.id, "Заблокирован через кнопку")
            if success:
                await callback.message.edit_reply_markup(
                    reply_markup=get_admin_keyboard(user_id, True)
                )
                await callback.answer("🚫 Пользователь заблокирован")
                try:
                    await callback.bot.send_message(
                        user_id,
                        "⛔ Вы были заблокированы администратором."
                    )
                except:
                    pass

    print(f"[DEBUG] Админ {'разблокировал' if is_blocked else 'заблокировал'} {user_id}")


@router.callback_query(F.data.startswith("ignore_"))
async def handle_ignore_button(callback: CallbackQuery):
    """Обработка кнопки 'Игнорировать'"""

    if callback.from_user.id != settings.ADMIN_ID:
        await callback.answer("У вас нет прав!")
        return

    user_id = int(callback.data.split("_")[1])

    # Удаляем кнопки
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✅ Вопрос проигнорирован")
    await callback.answer()

    print(f"[DEBUG] Админ проигнорировал вопрос от {user_id}")


# Обработчик медиа-альбомов от пользователей
@router.message(F.media_group_id)
async def handle_media_group(message: Message):
    """Обработчик медиа-альбомов"""

    print(f"[DEBUG] Получен элемент медиа-группы от {message.from_user.id}")

    # Если это админ в режиме ответа
    if message.from_user.id == settings.ADMIN_ID and message.from_user.id in admin_reply_mode:
        admin_media_buffer[message.from_user.id].append(message)
        await asyncio.sleep(0.5)

        # Проверяем, последнее ли это сообщение
        if admin_media_buffer[message.from_user.id][-1].message_id == message.message_id:
            await send_admin_reply_media(message)
        return

    if message.from_user.id in [settings.ADMIN_ID, settings.MONITOR_ID, settings.TECH_MANAGER_ID]:
        return

    if not waiting_for_question.get(message.from_user.id, False):
        print(f"[DEBUG] Флаг ожидания не установлен для {message.from_user.id}")
        return

    async with async_session() as session:
        if await is_user_blocked(session, message.from_user.id):
            return

        allowed, error_msg = await rate_limiter.check_limit(
            session, message.from_user.id, "message"
        )

        if not allowed:
            await message.answer(f"⚠️ {error_msg}")
            return

    media_group_id = message.media_group_id
    media_groups[media_group_id].append(message)

    await asyncio.sleep(0.5)

    if media_groups[media_group_id][0].message_id == message.message_id:
        user_info_text = (
            f"👤 Вопрос от пользователя:\n"
            f"ID: {message.from_user.id}\n"
            f"Username: @{message.from_user.username or 'нет'}\n"
            f"Имя: {message.from_user.first_name or ''} {message.from_user.last_name or ''}"
        )

        try:
            await send_question_to_admin(
                message, user_info_text,
                media_group=media_groups[media_group_id]
            )

            await message.answer(
                "✅ Ваше сообщение отправлено в поддержку!\n"
                "Мы ответим вам в ближайшее время."
            )

            waiting_for_question[message.from_user.id] = False
            print(f"[DEBUG] Флаг ожидания сброшен для {message.from_user.id}")

        except Exception as e:
            print(f"[ERROR] Ошибка обработки медиа-группы: {e}")
            await message.answer(
                "❌ Произошла ошибка при отправке сообщения. Попробуйте позже."
            )

        del media_groups[media_group_id]


async def send_admin_reply_media(message: Message):
    """Отправка ответа админа с медиа"""

    user_id = admin_reply_mode.get(message.from_user.id)
    if not user_id:
        return

    media_list = admin_media_buffer[message.from_user.id]

    try:
        # Собираем весь текст из всех caption медиа
        all_text_parts = []
        for msg in media_list:
            if msg.caption:
                all_text_parts.append(msg.caption)
        
        # Объединяем весь текст
        combined_text = "\n\n".join(all_text_parts) if all_text_parts else ""
        
        # Формируем медиа для отправки
        media_to_send = []
        # В caption первого медиа оставляем только префикс, если есть текст
        first_caption = f"💬 Ответ поддержки:" if combined_text else None

        for idx, msg in enumerate(media_list):
            if msg.photo:
                media_item = InputMediaPhoto(
                    media=msg.photo[-1].file_id,
                    caption=first_caption if idx == 0 else None
                )
            elif msg.video:
                media_item = InputMediaVideo(
                    media=msg.video.file_id,
                    caption=first_caption if idx == 0 else None
                )
            elif msg.document:
                media_item = InputMediaDocument(
                    media=msg.document.file_id,
                    caption=first_caption if idx == 0 else None
                )
            else:
                continue
            media_to_send.append(media_item)

        # Отправляем медиа-группу пользователю
        await message.bot.send_media_group(user_id, media=media_to_send)
        
        # Если есть текст, отправляем его отдельным сообщением после медиа-группы
        # Небольшая задержка гарантирует, что медиа-группа доставлена первой
        if combined_text:
            await asyncio.sleep(0.3)
            await message.bot.send_message(
                user_id,
                f"💬 Ответ поддержки:\n\n{combined_text}"
            )

        # Меняем кнопки на "Ответ отправлен"
        sent_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ответ отправлен", callback_data="answered")]
        ])

        # Находим сообщение с кнопками и обновляем его
        if user_id in control_messages:
            chat_id, msg_id = control_messages[user_id]
            try:
                await message.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=msg_id,
                    reply_markup=sent_keyboard
                )
            except:
                pass

        await message.answer("✅ Ответ с медиа отправлен пользователю!")

        # Выключаем режим ответа
        del admin_reply_mode[message.from_user.id]
        del admin_media_buffer[message.from_user.id]

        print(f"[DEBUG] Админ отправил медиа-ответ пользователю {user_id}")

    except Exception as e:
        print(f"[ERROR] Ошибка отправки медиа-ответа: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")


@router.message(F.content_type.in_([
    ContentType.TEXT,
    ContentType.PHOTO,
    ContentType.VIDEO,
    ContentType.DOCUMENT,
    ContentType.VOICE,
    ContentType.AUDIO
]))
async def handle_user_message(message: Message):
    """Обработчик сообщений от пользователей и ответов админа"""

    print(f"[DEBUG] Получено сообщение от {message.from_user.id}, тип: {message.content_type}")

    # Если это админ в режиме ответа
    if message.from_user.id == settings.ADMIN_ID and message.from_user.id in admin_reply_mode:
        user_id = admin_reply_mode[message.from_user.id]

        try:
            if message.text:
                await message.bot.send_message(user_id, f"💬 Ответ поддержки:\n\n{message.text}")
            elif message.photo:
                await message.bot.send_photo(
                    user_id,
                    message.photo[-1].file_id,
                    caption=f"💬 Ответ поддержки:\n\n{message.caption or ''}"
                )
            elif message.video:
                await message.bot.send_video(
                    user_id,
                    message.video.file_id,
                    caption=f"💬 Ответ поддержки:\n\n{message.caption or ''}"
                )
            elif message.document:
                await message.bot.send_document(
                    user_id,
                    message.document.file_id,
                    caption=f"💬 Ответ поддержки:\n\n{message.caption or ''}"
                )
            elif message.voice:
                await message.bot.send_voice(user_id, message.voice.file_id)
            elif message.audio:
                await message.bot.send_audio(user_id, message.audio.file_id)

            await message.answer("✅ Ответ отправлен пользователю!")

            # Меняем кнопки на "Ответ отправлен"
            if user_id in control_messages:
                chat_id, msg_id = control_messages[user_id]
                try:
                    sent_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Ответ отправлен", callback_data="answered")]
                    ])
                    await message.bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=msg_id,
                        reply_markup=sent_keyboard
                    )
                except:
                    pass

            # Выключаем режим ответа
            del admin_reply_mode[message.from_user.id]

            print(f"[DEBUG] Админ отправил ответ пользователю {user_id}")

        except Exception as e:
            print(f"[ERROR] Ошибка отправки ответа: {e}")
            await message.answer(f"❌ Ошибка: {str(e)}")

        return

    # Игнорируем сообщения от админа, монитора и техменеджера вне режима ответа
    if message.from_user.id in [settings.ADMIN_ID, settings.MONITOR_ID, settings.TECH_MANAGER_ID]:
        print("[DEBUG] Игнорирую - это админ/монитор/техменеджер")
        return

    if not waiting_for_question.get(message.from_user.id, False):
        print(f"[DEBUG] Флаг ожидания не установлен для {message.from_user.id}, игнорирую")
        return

    print(f"[DEBUG] Флаг ожидания установлен, обрабатываю сообщение")

    async with async_session() as session:
        if await is_user_blocked(session, message.from_user.id):
            await message.answer("❌ Вы заблокированы и не можете писать в поддержку.")
            return

        allowed, error_msg = await rate_limiter.check_limit(
            session, message.from_user.id, "message"
        )

        if not allowed:
            await message.answer(f"⚠️ {error_msg}")
            return

        if message.text:
            clean_text = SecurityValidator.sanitize_text(message.text)
            if len(clean_text) == 0:
                await message.answer("❌ Сообщение содержит недопустимые символы.")
                return

        user_info_text = (
            f"👤 Вопрос от пользователя:\n"
            f"ID: {message.from_user.id}\n"
            f"Username: @{message.from_user.username or 'нет'}\n"
            f"Имя: {message.from_user.first_name or ''} {message.from_user.last_name or ''}"
        )

        try:
            await send_question_to_admin(message, user_info_text)

            await message.answer(
                "✅ Ваше сообщение отправлено в поддержку!\n"
                "Мы ответим вам в ближайшее время."
            )

            waiting_for_question[message.from_user.id] = False
            print(f"[DEBUG] Флаг ожидания сброшен для {message.from_user.id}")

        except Exception as e:
            print(f"[ERROR] Ошибка обработки сообщения: {e}")
            await message.answer(
                "❌ Произошла ошибка при отправке сообщения. Попробуйте позже."
            )