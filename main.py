import asyncio
import os
import sys
import aiohttp
import shutil
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile, InputMediaPhoto, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError


from generateshop import main as generate_shop_main
from generateshop import go_print, shutil, set_bot_info_for_logging
from database import init_db as init_users_db
from database import *
from scheduler import start_scheduler
from logs_database import init_logs_db, log_action, get_logs, get_all_logs, get_log_count, clear_all_action_logs, get_user_logs


from settings import * 

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- Настройки баннера ---
BANNER_FILE_PATH = 'images/banner.png' # Убедитесь, что файл существует и расширение верное (jpg/png)
BANNER_FILE_ID = None

ADMIN_BANNER_FILE_PATH = 'images/admin_banner.png' # Убедитесь, что файл есть
ADMIN_BANNER_FILE_ID = None

# fsm
class Broadcast(StatesGroup):
    waiting_for_message = State()
    confirm_send = State()
class SendToUser(StatesGroup):
    waiting_for_message = State()
    user_id_to_send = State()
class ChannelManagement(StatesGroup):
    waiting_for_channel_id = State()
class ChannelMessage(StatesGroup):
    waiting_for_message = State()
    channel_id_to_send = State()
class UserInteraction(StatesGroup):
    messages_to_delete = State()


def escape_legacy_markdown(text: str) -> str:
    """Экранирует спецсимволы Markdown (`*`, `_`, `` ` ``, `[`, `]`)."""
    if not text:
        return ""
    text = text.replace('_', ' ')
    text = text.replace('*', '∗')
    text = text.replace('`', "'")
    text = text.replace('[', '(')
    text = text.replace(']', ')')
    return text

# middleware
class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = event.from_user.id
        if is_user_blocked(user_id): return
        if not BOT_ENABLED and not is_user_admin(user_id):
            if isinstance(event, types.CallbackQuery):
                await event.answer("🔴 Бот отключен, попробуйте позже..", show_alert=True)
            elif isinstance(event, types.Message):
                await event.answer("🔴 Бот отключен, попробуйте позже..")
            return
        return await handler(event, data)

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, (types.Message, types.CallbackQuery)):
            return await handler(event, data)
        
        user = event.from_user
        user_id = user.id
        
        if user_id in ADMIN_IDS:
            return await handler(event, data)
        
        username = user.username or "N/A"
        action_type = ""
        action_content = ""
        
        if isinstance(event, types.Message):
            action_type = "message"
            action_content = event.text or "[Non-text content]"
        elif isinstance(event, types.CallbackQuery):
            action_type = "callback_query"
            action_content = event.data
        
        go_print(f"Log: {user_id} ({username}) | Type: {action_type} | Content: {action_content}")

        try:
            await asyncio.to_thread(log_action, user_id, username, action_type, action_content)
        except Exception as e:
            go_print(f"!!! ОШИБКА АУДИТА: {e}") 
        
        return await handler(event, data)

dp.message.middleware(AccessMiddleware())
dp.callback_query.middleware(AccessMiddleware())
dp.message.middleware(LoggingMiddleware())
dp.callback_query.middleware(LoggingMiddleware())

# клавиатуры
def get_main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🏪 Посмотреть магазин", callback_data="view_shop"))
    if is_admin:
        builder.row(InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel"))
    builder.row(InlineKeyboardButton(text="💬 Поддержка", url=admin_url))
    return builder.as_markup()

def back_to_main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад в главное меню", callback_data="main_menu_delete"))
    return builder.as_markup()

def admin_panel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users"),
        InlineKeyboardButton(text="📺 Каналы", callback_data="admin_channels")
    )
    builder.row(
        InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_bot_settings")
    )
    builder.row(
        InlineKeyboardButton(text="📜 Аудит", callback_data="admin_logs_0"),
        InlineKeyboardButton(text="🌀 Генерация магазина", callback_data="admin_gen_menu")
    )
    builder.row(InlineKeyboardButton(text="✉️ Последняя рассылка", callback_data="admin_broadcast_mgmt"))
    builder.row(InlineKeyboardButton(text="🔎 Проверить обновление магазина", callback_data="admin_force_check_update"))
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="main_menu"))
    return builder.as_markup()

def adm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔺 В админ-панель", callback_data="admin_panel"))
    return builder.as_markup()

def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="broadcast_confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")
    )
    return builder.as_markup()

def bot_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    status_text = "🔴 Выключить бота" if BOT_ENABLED else "🟢 Включить бота"
    builder.row(InlineKeyboardButton(text=status_text, callback_data="toggle_bot_status"))
    autoupdate_text = "🔴 Выкл. авто-обновление" if AUTO_UPDATE_ENABLED else "🟢 Вкл. авто-обновление"
    builder.row(InlineKeyboardButton(text=autoupdate_text, callback_data="toggle_auto_update"))
    backup_text = "🔴 Выкл. бэкапы" if BACKUP_ENABLED else "🟢 Вкл. бэкапы"
    builder.row(InlineKeyboardButton(text=backup_text, callback_data="toggle_backup"))
    builder.row(InlineKeyboardButton(text="🔄 Перезагрузка бота", callback_data="admin_restart_bot"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    return builder.as_markup()

def manual_gen_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📣 Сгенерировать (с уведомлениями)", callback_data="manual_gen_post"))
    builder.row(InlineKeyboardButton(text="🔕 Сгенерировать (без уведомлений)", callback_data="manual_gen_silent"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    return builder.as_markup()

def logs_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 10:
        nav_buttons.append(InlineKeyboardButton(text="◀️ -10", callback_data=f"admin_logs_{page - 10}"))
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_logs_{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(text="ㅤ", callback_data='None'))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_logs_{page + 1}"))
    if page < total_pages - 10:
        nav_buttons.append(InlineKeyboardButton(text="+10 ▶️", callback_data=f"admin_logs_{page + 10}"))
    if nav_buttons:
        builder.row(*nav_buttons)
    builder.row(InlineKeyboardButton(text="💾 Выгрузить аудит", callback_data="export_logs"))
    builder.row(InlineKeyboardButton(text="🗑️ Очистить", callback_data="clear_logs"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    return builder.as_markup()

def confirm_clear_logs_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Да, очистить", callback_data="confirm_clear_logs"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_logs_0"))
    return builder.as_markup()

def broadcast_mgmt_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Удалить последнюю рассылку", callback_data="confirm_delete_broadcast"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    return builder.as_markup()

def confirm_delete_broadcast_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Да, удалить", callback_data="delete_broadcast_confirmed"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel"))
    return builder.as_markup()

def users_list_keyboard(users: list, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    per_page = 5
    start = page * per_page
    end = start + per_page
    for user_id, username, is_blocked, is_admin in users[start:end]:
        status_emoji = "🔴" if is_blocked else "🟢"
        admin_emoji = "👑" if is_admin else ""
        builder.row(InlineKeyboardButton(
            text=f"{status_emoji} {admin_emoji}{username or 'No Username'} ({user_id})".strip(),
            callback_data=f"view_user_{user_id}"
        ))
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"users_page_{page - 1}"))
    if end < len(users):
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"users_page_{page + 1}"))
    builder.row(*nav_buttons)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    return builder.as_markup()

def viewuserbyid(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
            text=f"🔸 Перейти к пользователю",
            callback_data=f"view_user_{user_id}"
        ))
    return builder.as_markup()

def user_management_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    user_info = get_user_info(user_id)
    if not user_info: return builder.as_markup()

    button_url = f'tg://user?id={user_id}'
    
    _, _, _, is_blocked, is_admin = user_info
    block_text = "✅ Разблокировать" if is_blocked else "🚫 Заблокировать"
    admin_text = "❌ Снять права" if is_admin else "👑 Выдать администратора"
    
    builder.row(
        InlineKeyboardButton(text=block_text, callback_data=f"toggle_block_{user_id}"),
        InlineKeyboardButton(text=admin_text, callback_data=f"toggle_admin_{user_id}") 
    )
    builder.row(
        InlineKeyboardButton(text="✉️ Отправить сообщение", callback_data=f"send_message_to_{user_id}"),
        InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_user_{user_id}")
    )
    builder.row(InlineKeyboardButton(text="📜 Аудит пользователя", callback_data=f"view_userlogs_{user_id}"))
    try:
        builder.row(InlineKeyboardButton(text='🅰️', url=button_url))
    except Exception as ex:
        go_print(ex)
        builder.row(InlineKeyboardButton(text='❌ Не удалось получить', callback_data=f"admin_users"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="admin_users"))
    
    return builder.as_markup()

def cancel_keyboard(back_callback: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отменить", callback_data=back_callback))
    return builder.as_markup()

def confirm_delete_keyboard(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{user_id}"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"view_user_{user_id}"))
    return builder.as_markup()

def channels_menu_keyboard(channels: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Подключить канал", callback_data="channel_add"))
    for channel_id, title in channels:
        builder.row(InlineKeyboardButton(text=title, callback_data=f"channel_view_{channel_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    return builder.as_markup()

def channel_view_keyboard(channel_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✉️ Отправить сообщение в канал", callback_data=f"channel_send_message_{channel_id}"))
    builder.row(InlineKeyboardButton(text="❌ Удалить канал", callback_data=f"channel_delete_{channel_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад к каналам", callback_data="admin_channels"))
    return builder.as_markup()


# --- Основные обработчики ---

@dp.message(CommandStart())
async def send_welcome(message: types.Message):
    caption_text = "👋 Привет! Это главное меню."
    is_check = is_exists(message.from_user.id)
    is_admin_user = is_user_admin(message.from_user.id)
    if is_check == False:
        add_user(user_id=message.from_user.id, username=message.from_user.username)
        await bot.send_message(ADMIN_IDS[0], f'🔺 Новый пользователь — `{message.from_user.id}`\n\nПерейдите к пользователю для подробной информации', reply_markup=viewuserbyid(message.from_user.id), parse_mode="Markdown")
    #await message.answer("👋 Привет! Это главное меню.", reply_markup=get_main_menu_keyboard(is_admin=is_admin_user))

    if BANNER_FILE_ID:
        await message.answer_photo(
            photo=BANNER_FILE_ID, 
            caption=caption_text, 
            reply_markup=get_main_menu_keyboard(is_admin=is_admin_user)
        )
    else:
        # Если баннера нет (ошибка файла), отправляем просто текст
        await message.answer(caption_text, reply_markup=get_main_menu_keyboard(is_admin=is_admin_user))
    

@dp.callback_query(F.data == "main_menu")
async def cq_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin_user = is_user_admin(callback.from_user.id)
    try:
        await callback.message.delete()
    except Exception:
        pass

    caption_text = "👋 Привет! Это главное меню."

    if BANNER_FILE_ID:
        await callback.message.answer_photo(
            photo=BANNER_FILE_ID,
            caption=caption_text, 
            reply_markup=get_main_menu_keyboard(is_admin=is_admin_user)
        )
    else:
        await callback.message.answer(caption_text, reply_markup=get_main_menu_keyboard(is_admin=is_admin_user))

@dp.callback_query(F.data == "main_menu_delete")
async def cq_main_menu_delete(callback: types.CallbackQuery, state: FSMContext):
    if is_exists(callback.from_user.id) == False:
        await callback.answer('❗️ Введите команду /start', show_alert=True)
        return
    data = await state.get_data()
    messages_to_delete = data.get('messages', [])
    await state.clear()
    for msg_id in messages_to_delete:
        try:
            await bot.delete_message(callback.from_user.id, msg_id)
        except Exception: pass 
    
    # Удаляем кнопку "Назад"
    try:
        await callback.message.delete()
    except Exception: pass

    is_admin_user = is_user_admin(callback.from_user.id)
    caption_text = "👋 Привет! Это главное меню."

    if BANNER_FILE_ID:
        await callback.message.answer_photo(
            photo=BANNER_FILE_ID,
            caption=caption_text, 
            reply_markup=get_main_menu_keyboard(is_admin=is_admin_user)
        )
    else:
        await callback.message.answer(caption_text, reply_markup=get_main_menu_keyboard(is_admin=is_admin_user))


@dp.callback_query(F.data == "view_shop")
async def cq_view_shop(callback: types.CallbackQuery, state: FSMContext):
    if is_exists(callback.from_user.id) == False:
        await callback.answer('❗️ Введите команду /start', show_alert=True)
        return
    file_ids = get_all_shop_images()
    stats = get_latest_generation_stats()
    if not file_ids or not stats:
        await callback.answer("🚫 Магазин еще не был сгенерирован сегодня. Попробуйте позже.", show_alert=True)
        return
    generation_date_str, item_count = stats
    formatted_date = datetime.strptime(generation_date_str, "%Y-%m-%d %H:%M:%S").strftime("%d %B %Y г. %H:%M")
    final_text = f"🔥 Ежедневный магазин по состоянию на {formatted_date}\n🔸 Количество предметов: {item_count}"
    await callback.answer("Загружаю изображения...")
    
    try:
        await callback.message.delete()
    except TelegramBadRequest as e:
        go_print(f"Не удалось удалить сообщение: {e}. Отправляю новое.")
        await callback.message.answer(
            "🛑 Пожалуйста, используйте /start для дальнейшего пользования ботом.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        return

    sent_message_ids = []
    try:
        for i in range(0, len(file_ids), 10):
            chunk = file_ids[i:i + 10]
            media_album = []
            is_first_chunk_and_photo = (i == 0)
            for j, file_id in enumerate(chunk):
                if is_first_chunk_and_photo and j == 0:
                    media_album.append(InputMediaPhoto(media=file_id, caption=final_text))
                else:
                    media_album.append(InputMediaPhoto(media=file_id))
            sent_messages = await bot.send_media_group(chat_id=callback.from_user.id, media=media_album)
            sent_message_ids.extend([msg.message_id for msg in sent_messages])
        if sent_messages:
            final_message = await bot.send_message(
                callback.from_user.id,
                "▶️ Нажмите, чтобы вернуться в меню.",
                reply_markup=back_to_main_menu_keyboard()
            )
        sent_message_ids.append(final_message.message_id)
        await state.set_state(UserInteraction.messages_to_delete)
        await state.update_data(messages=sent_message_ids)
    except TelegramBadRequest as e:
        go_print(f"Ошибка отправки альбома: {e}")
        await bot.send_message(callback.from_user.id, "❗️ Произошла ошибка при отправке. Возможно, file_id устарели.", reply_markup=back_to_main_menu_keyboard())


# --- Логика для генерации ---
async def post_shop_to_channels():
    go_print("Начинаю автоматическую отправку в каналы...")
    
    channel_data = get_all_channels()
    file_ids = get_all_shop_images()
    stats = get_latest_generation_stats()
    if not file_ids or not stats:
        go_print("Нет file_id или статистики для отправки в каналы.")
        return 0, 0 
    generation_date_str, item_count_stats = stats
    formatted_date = datetime.strptime(generation_date_str, "%Y-%m-%d %H:%M:%S").strftime("%d %B %Y г. %H:%M")
    final_text = f"🔥 Ежедневный магазин по состоянию на {formatted_date}\n🔸 Количество предметов: {item_count_stats}"
    if not channel_data:
        go_print("Нет подключенных каналов для отправки.")
        return 0, 0
    sent_to = 0
    failed_on = 0
    
    for channel_id, title in channel_data:
        try:
            sent_message_ids = []
            for i in range(0, len(file_ids), 10):
                chunk = file_ids[i:i + 10]
                media_album = []
                is_first_chunk_and_photo = (i == 0)
                for j, file_id in enumerate(chunk):
                    if is_first_chunk_and_photo and j == 0:
                        media_album.append(InputMediaPhoto(media=file_id, caption=final_text))
                    else:
                        media_album.append(InputMediaPhoto(media=file_id))
                sent_messages = await bot.send_media_group(chat_id=channel_id, media=media_album)
                sent_message_ids.extend([msg.message_id for msg in sent_messages])
            for msg_id in sent_message_ids:
                log_broadcast_message(channel_id, msg_id)
            go_print(f"Успешно отправлено в канал {title} ({channel_id})")
            sent_to += 1
        except Exception as e:
            go_print(f"!!! ОШИБКА отправки в канал {title} ({channel_id}): {e}.")
            failed_on += 1
    
    go_print(f"Авто-отправка завершена. Успешно: {sent_to}, Ошибки: {failed_on}")
    return sent_to, failed_on

async def run_and_save_generation(silent_post: bool = False):
    go_print("--- НАЧАЛО ГЕНЕРАЦИИ МАГАЗИНА ---")
    generated_files = []
    item_count = 0
    generation_dt = datetime.now()
    generation_date = generation_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        clear_shop_images()
        clear_broadcast_log()
        go_print("Старые file_id и записи рассылки удалены из БД.")
        generation_result = await generate_shop_main()
        if not generation_result or len(generation_result) != 3:
            go_print("Генерация не вернула полных данных.")
            await bot.send_message(ADMIN_IDS[0], "⚠️ Генерация: не удалось создать изображения.")
            return
        generated_files, item_count, _ = generation_result
        go_print(f"Отправка {len(generated_files)} файлов админу для получения file_id...")
        for file_path in generated_files:
            if os.path.exists(file_path):
                file_name = os.path.basename(file_path)
                photo = FSInputFile(path=file_path)
                message = await bot.send_photo(chat_id=ADMIN_IDS[0], photo=photo)
                file_id = message.photo[-1].file_id
                add_shop_image(file_name, file_id)
        log_generation(generation_date, item_count)
        go_print(f"Статистика сохранена: {item_count} предметов за {generation_date}")
        await bot.send_message(ADMIN_IDS[0], f"✅ Генерация завершена, file_id сохранены. Всего предметов: {item_count}.")
        if not silent_post:
            sent_count, failed_count = await post_shop_to_channels()
            await bot.send_message(ADMIN_IDS[0], f"✅ Рассылка в каналы завершена.\nУспешно: {sent_count}, Ошибки: {failed_count}")
        else:
            go_print("Ручная генерация: пропускаем рассылку в каналы.")
            await bot.send_message(ADMIN_IDS[0], "🔕 Тихая генерация завершена (без отправки в каналы)")
    except Exception as e:
        go_print(f"!!! КРИТИЧЕСКАЯ ОШИБКА в генерации: {e}")
        await bot.send_message(ADMIN_IDS[0], f"❌ Ошибка в генерации: {e}")
    finally:
        if os.path.exists('images/cache'): shutil.rmtree('images/cache')
        if generated_files:
            for file_path in generated_files:
                if os.path.exists(file_path): os.remove(file_path)
        go_print("--- ГЕНЕРАЦИЯ ЗАВЕРШЕНА ---")

async def check_shop_update(is_startup: bool = False):
    
    global LAST_SHOP_HASH, LAST_ITEM_COUNT, AUTO_UPDATE_ENABLED
    
    if not AUTO_UPDATE_ENABLED and not is_startup:
        go_print("Авто-обновление отключено, проверка пропущена.")
        return
    go_print("Проверка обновлений магазина по API...")
    combined_hash = None
    new_item_count = 0
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://fortnite-api.com/v2/shop?language=ru') as response:
                if response.status != 200:
                    go_print(f"Ошибка API при проверке hash: {response.status}")
                    return
                data = (await response.json()).get('data')
                if not data:
                    go_print("Ошибка API: 'data' отсутствует в ответе.")
                    return
                new_hash = data.get('hash')
                new_date = data.get('date')
                combined_hash = f"{new_date}_{new_hash}"
                new_item_count = len(data.get('entries', []))
    except Exception as e:
        go_print(f"Критическая ошибка при проверке хэша: {e}")
        return
    if not combined_hash:
        go_print("Не удалось получить хэш.")
        return

    if LAST_SHOP_HASH is None:
        LAST_SHOP_HASH = combined_hash
        LAST_ITEM_COUNT = new_item_count
        go_print(f"Инициализация... Хэш: {LAST_SHOP_HASH}, Кол-во: {LAST_ITEM_COUNT}")
            
    elif LAST_SHOP_HASH != combined_hash or LAST_ITEM_COUNT != new_item_count:
        if not AUTO_UPDATE_ENABLED and not is_startup:
            go_print("Авто-обновление отключено, генерация пропущена.")
            LAST_SHOP_HASH = combined_hash 
            LAST_ITEM_COUNT = new_item_count
            return
            
        go_print(f"!!! Обнаружен новый магазин! Хэш: ({LAST_SHOP_HASH} -> {combined_hash}) "
                 f"| Кол-во: ({LAST_ITEM_COUNT} -> {new_item_count})")
        await bot.send_message(ADMIN_IDS[0], f'♦️ Начинаю генерацию магазина..', parse_mode="Markdown")
        LAST_SHOP_HASH = combined_hash
        LAST_ITEM_COUNT = new_item_count
        await run_and_save_generation(silent_post=False)
    else:
        go_print("Обновлений магазина нет.")


# --- Админ-панель ---
@dp.message(Command("admin"))
async def admin_panel_cmd(message: types.Message):
    if not is_user_admin(message.from_user.id): return
    whole_users = len(get_all_users())
    lginfo = get_latest_generation_stats()

    global admin_welcome_text
    admin_welcome_text = f"🔺 Добро пожаловать в админ-панель!\n\nПользователей: {whole_users}\nGenInfo: {lginfo}"

    if ADMIN_BANNER_FILE_ID:
        await message.answer_photo(
            photo=ADMIN_BANNER_FILE_ID,
            caption=admin_welcome_text,
            reply_markup=admin_panel_keyboard()
        )
    else:
        await message.answer(admin_welcome_text, reply_markup=admin_panel_keyboard())

@dp.callback_query(F.data.startswith("admin_"))
async def admin_actions_handler(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id):
        await callback.answer("У вас нет прав доступа.", show_alert=True)
        return

    action = callback.data.split("_")
    
    try:
        if action[1] == "panel":
            await state.clear()
            #await callback.message.delete()
            whole_users = len(get_all_users())
            lginfo = get_latest_generation_stats()
            admin_welcome_text = f"🔺 Добро пожаловать в админ-панель!\n\nПользователей: {whole_users}\nGenInfo: {lginfo}"

            try:
                await callback.message.delete()
            except Exception as ex:
                await callback.answer(f"❌ Ошибка: {ex}", show_alert=True)
                go_print(ex)
                pass

            if ADMIN_BANNER_FILE_ID:
                await callback.message.answer_photo(
                    photo=ADMIN_BANNER_FILE_ID,
                    caption=admin_welcome_text, 
                    reply_markup=admin_panel_keyboard()
                )
            else:
                await callback.message.answer(admin_welcome_text, reply_markup=admin_panel_keyboard())
        elif action[1] == "users":
            await state.clear()
            users = get_all_users()
            try:
                await callback.message.edit_caption(caption=f"🔸 Всего пользователей: {len(users)}", reply_markup=users_list_keyboard(users))
            except Exception as ex:
                await callback.message.edit_text(text=f"🔸 Всего пользователей: {len(users)}", reply_markup=users_list_keyboard(users))
                go_print
        elif action[1] == "bot" and action[2] == "settings":
            try:
                await callback.message.edit_caption(caption="🔸 Настройки бота:", reply_markup=bot_settings_keyboard())
            except Exception as ex:
                await callback.message.edit_text(text="🔸 Настройки бота:", reply_markup=bot_settings_keyboard())
                go_print(ex)
        elif action[1] == "restart" and action[2] == "bot":
            await callback.message.edit_caption(caption="🔻 Перезагрузка бота...")
            os.execv(sys.executable, ['python'] + sys.argv)
        elif action[1] == "broadcast":
            if len(action) == 2:
                await state.set_state(Broadcast.waiting_for_message)
                await callback.message.edit_caption(caption="🔸 Отправьте сообщение для рассылки.", reply_markup=cancel_keyboard("admin_panel"))
            elif action[2] == "mgmt":
                await cq_broadcast_mgmt(callback)
        elif action[1] == "channels":
            await cq_admin_channels(callback, state)
        elif action[1] == "gen" and action[2] == "menu":
            await callback.message.edit_caption(caption="🔸 Генерация вручную:", reply_markup=manual_gen_keyboard())
        elif action[1] == "logs":
            await cq_admin_logs(callback, page=0)
        elif action[1] == "force" and action[2] == "check": # data="admin_force_check_update"
            await cq_force_check_update(callback)
            
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer("🔸 Меню уже открыто.")
        else:
            go_print(f"Ошибка в admin_actions_handler: {e}")
            await callback.answer("🔸 Произошла ошибка.", show_alert=True)


@dp.callback_query(F.data.startswith("admin_logs_"))
async def cq_admin_logs(callback: types.CallbackQuery, page: int = 0):
    if not is_user_admin(callback.from_user.id): return
    
    try:
        page = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        page = 0 
    
    log_count = await asyncio.to_thread(get_log_count)
    total_pages = (log_count + 19) // 20
    if total_pages == 0: total_pages = 1 # Минимум 1 страница

    logs = await asyncio.to_thread(get_logs, page=page)
    
    if not logs and page == 0:
        admin_kb = InlineKeyboardBuilder()
        admin_kb.add(InlineKeyboardButton(text="🔺 В админ-панель", callback_data="admin_panel"))
        await callback.message.delete()
        await callback.message.answer_photo(
                    photo=ADMIN_BANNER_FILE_ID,
                    caption='♦️ Аудит пока пуст', 
                    reply_markup=admin_kb.as_markup()
                )
        return

    text = f"📜 **Последние 20 записей (Стр. {page + 1}/{total_pages}):**\n\n"
    for log_entry in logs:
        timestamp, user_id, username, action_type, action_content = log_entry
        content = (action_content[:50] + '...') if len(action_content) > 50 else action_content
        safe_content = escape_legacy_markdown(content)
        text += f"`{timestamp}` | `{user_id}` | `{action_type}`: {safe_content}\n"
    
    try:
        await callback.message.delete()
        await callback.message.answer(text=text, parse_mode="Markdown", reply_markup=logs_keyboard(page, total_pages))
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer("🔸 Вы уже на этой странице.")
        else:
            fallback_text = text.replace("`", "").replace("**", "")
            await callback.message.edit_caption(caption=
                f"Ошибка парсинга (Стр. {page + 1}/{total_pages}). Текст без форматирования:\n\n" + fallback_text,
                reply_markup=logs_keyboard(page, total_pages)
            )
    await callback.answer()

@dp.callback_query(F.data == "export_logs")
async def cq_export_l(callback: types.CallbackQuery):

    if not is_user_admin(callback.from_user.id): return
    await callback.answer()
    
    await callback.message.edit_text(text="⏳ Выгружаю аудит из базы данных... Это может занять время.", reply_markup=None)
    
    log_file_path = "logs_export.txt"

    try:
        def write_logs_to_file_sync():
            all_logs = get_all_logs()
            if not all_logs:
                return False
            
            with open(log_file_path, "w", encoding="utf-8") as f:
                f.write("--- Full Logs Export ---\n\n")
                for log_entry in all_logs:
                    timestamp, user_id, username, action_type, action_content = log_entry
                    f.write(f"[{timestamp}] User: {user_id} ({username}) | Type: {action_type} | Content: {action_content}\n")
            return True
        
        success = await asyncio.to_thread(write_logs_to_file_sync)
        
        if not success:
            await callback.answer("🔻 Аудит пуст, нечего выгружать.", show_alert=True)
            await cq_admin_logs(callback, page=0)
            return

        await callback.message.edit_text(text="📤 Отправляю файл...")
        
        with open(log_file_path, 'rb') as f:
            file_data = f.read()
        
        await bot.send_document(
            callback.from_user.id, 
            BufferedInputFile(file_data, filename="logs_export.txt"), 
            caption="🔴🔴🔴 Выгрузка аудита 🔴🔴🔴"
        )
        await cq_admin_logs(callback, page=0)
    
    except Exception as e:
        go_print(f"Ошибка экспорта аудита: {e}")
        await callback.message.answer(f"Ошибка при создании файла аудита: {e}")
    finally:
        if os.path.exists(log_file_path):
            os.remove(log_file_path)

@dp.callback_query(F.data == "clear_logs")
async def cq_clear_logs(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    await callback.message.edit_text(text=
        "❗️ **Вы уверены, что хотите ПОЛНОСТЬЮ очистить весь аудит действий?** ❗️\n\n"
        "❗️ Это действие необратимо. Аудит БД (`db_logs`) затронуты не будут ❗️",
        parse_mode="Markdown",
        reply_markup=confirm_clear_logs_keyboard()
    )

@dp.callback_query(F.data == "confirm_clear_logs")
async def cq_confirm_clear_logs(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    
    await asyncio.to_thread(clear_all_action_logs)
    await callback.answer("🔺 Аудит действий успешно очищен.", show_alert=True)
    await cq_admin_logs(callback, page=0)


@dp.callback_query(F.data == "admin_broadcast_mgmt")
async def cq_broadcast_mgmt(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    
    try:
        stats = get_latest_generation_stats()
        messages = get_all_broadcast_messages()
        if not stats or not messages:
            await callback.answer("🛑 В базе нет данных о последних рассылках", show_alert=True)
            return
        
        generation_date_str, item_count = stats
        formatted_date = datetime.strptime(generation_date_str, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y в %H:%M")
        num_messages = len(messages)
        num_channels = len(set([m[0] for m in messages]))
        text = (f"**Последняя рассылка:**\n"
                f"📅 **Дата:** {formatted_date}\n"
                f"📦 **Предметов:** {item_count}\n"
                f"📺 **Каналов:** {num_channels}\n"
                f"📩 **Сообщений (альбомов) отправлено:** {num_messages}\n\n"
                f"Вы можете удалить эти сообщения из каналов. Это действие необратимо.")
        
        await callback.message.edit_caption(caption=text, parse_mode="Markdown", reply_markup=confirm_delete_broadcast_keyboard())
    
    except TelegramBadRequest as e:
        go_print(e)
        if "message is not modified" in str(e):
            await callback.answer("Меню уже открыто.")
        else:
            go_print(f"Ошибка в cq_broadcast_mgmt: {e}")
            await callback.answer("Произошла ошибка.", show_alert=True)


@dp.callback_query(F.data == "confirm_delete_broadcast")
async def cq_confirm_delete_broadcast(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    try:
        await callback.message.edit_caption(caption=
            "Вы **ТОЧНО** уверены, что хотите удалить последнюю рассылку из ВСЕХ каналов?",
            parse_mode="Markdown",
            reply_markup=confirm_delete_broadcast_keyboard()
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer("Это меню уже открыто.")
        else:
            go_print(f"Ошибка в confirm_delete_broadcast: {e}")
            await callback.answer("Произошла ошибка.", show_alert=True)


@dp.callback_query(F.data == "delete_broadcast_confirmed")
async def cq_delete_broadcast_confirmed(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    await callback.message.edit_caption(caption="⏳ Начинаю удаление сообщений из каналов...")
    messages = get_all_broadcast_messages()
    deleted_count = 0
    failed_count = 0
    for channel_id, message_id in messages:
        try:
            await bot.delete_message(chat_id=channel_id, message_id=message_id)
            deleted_count += 1
        except Exception as e:
            go_print(f"Не удалось удалить сообщение {message_id} из {channel_id}: {e}")
            failed_count += 1
    clear_broadcast_log()
    await callback.answer(f"Удалено: {deleted_count} | Ошибки: {failed_count}", show_alert=True)
    await callback.message.edit_caption(caption="🔻 Запись последней рассылки очищена.", reply_markup=admin_panel_keyboard())

# ! НОВЫЙ ХЕНДЛЕР: Принудительная проверка обновлений
@dp.callback_query(F.data == "admin_force_check_update")
async def cq_force_check_update(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    
    await callback.answer("Запускаю проверку...")
    status_msg = await callback.message.answer("🔎 Связываюсь с API Fortnite и проверяю хэши...")
    
    try:
        # Запускаем существующую функцию проверки
        # Она сама всё сделает: проверит хэш, если он новый - сгенерирует и разошлет
        await check_shop_update() 
        
        await status_msg.edit_text(text="✅ Проверка завершена.")
    except Exception as e:
        await status_msg.edit_text(text=f"❌ Ошибка при проверке: {e}")

@dp.callback_query(F.data == "manual_gen_post")
async def cq_manual_gen_post(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    await callback.answer()
    await callback.message.edit_caption(caption="⏳ Начинаю генерацию...")
    await run_and_save_generation(silent_post=False)
    await callback.message.edit_caption(caption="✅ Генерация завершена!", reply_markup=admin_panel_keyboard())

@dp.callback_query(F.data == "manual_gen_silent")
async def cq_manual_gen_silent(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    await callback.answer()
    await callback.message.edit_caption(caption="⏳ Начинаю тихую генерацию...")
    await run_and_save_generation(silent_post=True)
    await callback.message.edit_caption(caption="🔕 Тихая генерация завершена!", reply_markup=admin_panel_keyboard())


@dp.callback_query(F.data == "toggle_auto_update")
async def cq_toggle_auto_update(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    global AUTO_UPDATE_ENABLED
    AUTO_UPDATE_ENABLED = not AUTO_UPDATE_ENABLED
    await callback.answer(f"Авто-обновление {'ВКЛЮЧЕНО' if AUTO_UPDATE_ENABLED else 'ВЫКЛЮЧЕНО'}", show_alert=True)
    await callback.message.edit_caption(caption="Настройки бота:", reply_markup=bot_settings_keyboard())

# ! НОВЫЙ ХЕНДЛЕР для вкл/выкл бэкапов
@dp.callback_query(F.data == "toggle_backup")
async def cq_toggle_backup(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    global BACKUP_ENABLED
    BACKUP_ENABLED = not BACKUP_ENABLED
    await callback.answer(f"Ежедневные бэкапы {'ВКЛЮЧЕНЫ' if BACKUP_ENABLED else 'ВЫКЛЮЧЕНЫ'}", show_alert=True)
    await callback.message.edit_caption(caption="Настройки бота:", reply_markup=bot_settings_keyboard())

@dp.callback_query(F.data.startswith("users_page_"))
async def cq_users_page(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    page = int(callback.data.split("_")[2])
    users = get_all_users()
    await callback.message.edit_caption(caption=f"Всего пользователей: {len(users)}", reply_markup=users_list_keyboard(users, page))

@dp.callback_query(F.data.startswith("view_user_"))
async def cq_view_user(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    await state.clear()
    user_id = int(callback.data.split("_")[-1])
    user_info = get_user_info(user_id)
    if user_info:
        uid, uname, rdate, is_blocked, is_admin = user_info
        status = "Заблокирован" if is_blocked else "Активен"
        admin_status = "Администратор" if is_admin else "Пользователь"
        safe_uname = escape_legacy_markdown(uname or "N/A")
        text = (f"👤 **Пользователь:** {safe_uname}\n**ID:** `{uid}`\n"
                f"**Дата регистрации:** {rdate}\n**Статус:** {status}\n**Права:** {admin_status}")
        try:
            await callback.message.edit_caption(caption=text, parse_mode="Markdown", reply_markup=user_management_keyboard(uid))
        except Exception as ex:
            await callback.message.edit_text(text=text, parse_mode="Markdown", reply_markup=user_management_keyboard(uid))
            go_print(ex)

# ! НОВЫЙ ХЕНДЛЕР: Просмотр логов конкретного пользователя
@dp.callback_query(F.data.startswith("view_userlogs_"))
async def cq_view_user_logs(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    
    target_user_id = int(callback.data.split("_")[-1])
    
    # Получаем логи из БД (в отдельном потоке, чтобы не тормозить бота)
    logs = await asyncio.to_thread(get_user_logs, target_user_id, limit=10)
    
    if not logs:
        await callback.answer("Логи этого пользователя пусты.", show_alert=True)
        return

    text = f"📜 **Последние 10 действий пользователя** `{target_user_id}`:\n\n"
    for log_entry in logs:
        timestamp, action_type, action_content = log_entry
        # Обрезаем слишком длинные сообщения
        content = (action_content[:40] + '...') if len(action_content) > 40 else action_content
        safe_content = escape_legacy_markdown(content)
        
        text += f"`{timestamp}` | `{action_type}`: {safe_content}\n"
    
    # Добавляем кнопку "Назад" к управлению этим пользователем
    back_kb = InlineKeyboardBuilder()
    back_kb.row(InlineKeyboardButton(text="⬅️ Назад к пользователю", callback_data=f"view_user_{target_user_id}"))
    
    try:
        await callback.message.edit_caption(caption=text, parse_mode="Markdown", reply_markup=back_kb.as_markup())
    except TelegramBadRequest:
        # Если не удалось сформатировать (редкий случай)
        fallback_text = text.replace("`", "").replace("**", "")
        await callback.message.edit_caption(caption=
            "Ошибка отображения. Текст без форматирования:\n\n" + fallback_text,
            reply_markup=back_kb.as_markup()
        )

@dp.callback_query(F.data.startswith("toggle_block_"))
async def cq_toggle_block(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    user_id = int(callback.data.split("_")[-1])
    if user_id == callback.from_user.id:
        await callback.answer("Вы не можете заблокировать самого себя.", show_alert=True)
        return
    if is_user_admin(user_id):
        await callback.answer("Вы не можете заблокировать другого администратора.", show_alert=True)
        return
    is_blocked_now = is_user_blocked(user_id)
    set_user_block_status(user_id, not is_blocked_now)
    await cq_view_user(callback, state)

@dp.callback_query(F.data.startswith("toggle_admin_"))
async def cq_toggle_admin(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    user_id = int(callback.data.split("_")[-1])
    if user_id == callback.from_user.id:
        await callback.answer("Вы не можете изменить свои права.", show_alert=True)
        return
    is_admin_now = is_user_admin(user_id)
    set_user_admin_status(user_id, not is_admin_now)
    await cq_view_user(callback, state)

@dp.callback_query(F.data.startswith("delete_user_"))
async def cq_delete_user(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    user_id = int(callback.data.split("_")[-1])
    if user_id == callback.from_user.id:
        await callback.answer("Вы не можете удалить самого себя.", show_alert=True)
        return
    if is_user_admin(user_id):
        await callback.answer("Вы не можете удалить другого администратора.", show_alert=True)
        return
    await callback.message.edit_caption(caption=
        f"Вы уверены, что хотите удалить пользователя с ID `{user_id}`?",
        parse_mode="Markdown",
        reply_markup=confirm_delete_keyboard(user_id)
    )

@dp.callback_query(F.data.startswith("confirm_delete_"))
async def cq_confirm_delete(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    user_id = int(callback.data.split("_")[-1])
    delete_user(user_id)
    await callback.answer("Пользователь удален.", show_alert=True)
    users = get_all_users()
    await callback.message.edit_caption(caption=f"Всего пользователей: {len(users)}", reply_markup=users_list_keyboard(users))

@dp.callback_query(F.data.startswith("send_message_to_"))
async def cq_send_message_to(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    user_id = int(callback.data.split("_")[-1])
    if user_id == callback.from_user.id:
        await callback.answer("Вы не можете отправить сообщение самому себе.", show_alert=True)
        return
    await state.update_data(user_id_to_send=user_id)
    await state.set_state(SendToUser.waiting_for_message)
    await callback.message.edit_caption(caption=f"Отправьте сообщение для пользователя с ID `{user_id}`.",
                                     parse_mode="Markdown", reply_markup=cancel_keyboard(f"view_user_{user_id}"))

@dp.message(SendToUser.waiting_for_message)
async def process_send_message_to_user(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get('user_id_to_send')
    try:
        await bot.send_message(user_id, f"Сообщение от администратора:\n\n{message.text}")
        await message.answer("Сообщение успешно отправлено.")
    except Exception as e:
        await message.answer(f"Не удалось отправить сообщение: {e}")

@dp.callback_query(F.data == "toggle_bot_status")
async def cq_toggle_bot_status(callback: types.CallbackQuery):
    if not is_user_admin(callback.from_user.id): return
    global BOT_ENABLED
    BOT_ENABLED = not BOT_ENABLED
    await callback.message.edit_caption(caption="Настройки бота:", reply_markup=bot_settings_keyboard())

@dp.message(Broadcast.waiting_for_message)
async def process_broadcast_preview(message: types.Message, state: FSMContext):
    await state.update_data(msg_id=message.message_id, chat_id=message.chat.id)
    id_to_del = message.message_id - 1
    await bot.delete_message(message.from_user.id, id_to_del)
    await message.answer("📢 **Предпросмотр рассылки:**", parse_mode="Markdown")
    try:
        await bot.copy_message(chat_id=message.chat.id, from_chat_id=message.chat.id, message_id=message.message_id)
    except Exception as e:
        await message.answer("Ошибка предпросмотра (не поддерживаемый тип сообщения).")

    await state.set_state(Broadcast.confirm_send)
    await message.answer(
        "Вы уверены, что хотите отправить это сообщение всем пользователям?", 
        reply_markup=broadcast_confirm_keyboard()
    )

@dp.callback_query(Broadcast.confirm_send, F.data == "broadcast_cancel")
async def cancel_broadcast_process(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
        if ADMIN_BANNER_FILE_ID:
            await callback.message.answer_photo(
                photo=ADMIN_BANNER_FILE_ID,
                caption="❌ Рассылка отменена.",
                reply_markup=admin_panel_keyboard()
            )
        else:
            await callback.message.answer("Пропишите /start")
    except Exception as ex:
        go_print(ex)

@dp.callback_query(Broadcast.confirm_send, F.data == "broadcast_confirm")
async def execute_broadcast_process(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    msg_id = data.get('msg_id')
    from_chat_id = data.get('chat_id')
    
    await state.clear()
    await callback.message.edit_text(text="⏳ Начинаю рассылку...", reply_markup=None)

    users = get_all_users()
    sent_count = 0
    failed_count = 0

    for user_id, _, is_blocked, _ in users:
        if not is_blocked:
            try:
                await bot.copy_message(chat_id=user_id, from_chat_id=from_chat_id, message_id=msg_id)
                sent_count += 1
                await asyncio.sleep(0.05) 
            except Exception as ex:
                go_print(f'Неудалось отправить {user_id} по причине: {ex}')
                failed_count += 1
    
    await callback.message.reply(
        f"📢 **Рассылка завершена!**\n\n"
        f"✅ Успешно: {sent_count}\n"
        f"❌ Ошибки: {failed_count}",
        reply_markup=None,
        parse_mode="Markdown"
    )
    await callback.message.answer_photo(
        photo=ADMIN_BANNER_FILE_ID,
        caption='🔺 Возвращаемся в админ-панель',
        reply_markup=admin_panel_keyboard()
    )

# каналы

@dp.callback_query(F.data == "admin_channels")
async def cq_admin_channels(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    await state.clear()
    channels = get_all_channels()
    text = "Управление подключенными каналами:"
    await callback.message.edit_caption(caption=text, reply_markup=channels_menu_keyboard(channels))

@dp.callback_query(F.data == "channel_add")
async def cq_channel_add(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    await state.set_state(ChannelManagement.waiting_for_channel_id)
    text = ("Отправьте ID канала (начинается с `-100`) или его @username. "
            "**Важно:** Сначала добавьте бота в канал как администратора с правом отправки сообщений!")
    await callback.message.edit_caption(caption=text, reply_markup=cancel_keyboard("admin_channels"), parse_mode="Markdown")

@dp.message(ChannelManagement.waiting_for_channel_id)
async def process_channel_id(message: types.Message, state: FSMContext):
    channel_input = message.text.strip()
    id_to_del = message.message_id - 1
    await bot.delete_message(message.from_user.id, id_to_del)
    await state.clear()
    
    try:
        channel_id_clean = int(channel_input)
    except ValueError:
        channel_id_clean = channel_input 

    try:
        chat = await bot.get_chat(channel_id_clean)
        channel_id = chat.id
        title = chat.title

        member = await bot.get_chat_member(channel_id, bot.id)
        
        if not member.can_post_messages:
            await message.answer(f"❌ Бот **{bot.user.username}** не имеет прав на отправку сообщений в канал **{title}**.", parse_mode="Markdown")
            return

        if add_channel(channel_id, title):
            await message.answer(f"✅ Канал **{title}** успешно подключен и проверен!", parse_mode="Markdown")
        else:
            await message.answer(f"⚠️ Канал **{title}** уже был подключен ранее.", parse_mode="Markdown")

    except TelegramBadRequest as e:
        await message.answer(f"❌ Ошибка проверки канала: ID неверный или бот не является администратором.\nКод: {e}", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Неизвестная ошибка: {e}")

    if ADMIN_BANNER_FILE_ID:
        await message.answer_photo(
            photo=ADMIN_BANNER_FILE_ID,
            caption="Управление подключенными каналами:",
            reply_markup=channels_menu_keyboard(get_all_channels())
        )
    else:
        await message.answer("Пропишите /start")


@dp.callback_query(F.data.startswith("channel_view_"))
async def cq_channel_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    await state.clear()
    channel_id_str = callback.data.split("_")[-1]
    channel_id = int(channel_id_str)

    try:
        chat = await bot.get_chat(channel_id)
        member = await bot.get_chat_member(channel_id, bot.id)
        
        status_text = "✅ Бот имеет все необходимые права (отправка сообщений)."
        if not member.can_post_messages:
            status_text = "❌ У бота нет права **отправлять сообщения**."
        elif member.status not in ('administrator', 'creator'):
            status_text = "⚠️ Бот **не является администратором**."
        elif member.status == 'left' or member.status == 'kicked':
            status_text = "🔴 Бот **удален** из канала."
        
        safe_title = escape_legacy_markdown(chat.title)
        text = (f"📺 **Канал:** {safe_title}\n"
                f"**ID:** `{channel_id}`\n"
                f"**Статус бота:** {status_text}\n"
                f"**Username:** @{chat.username or 'отсутствует'}")
        
        await callback.message.edit_caption(caption=text, reply_markup=channel_view_keyboard(channel_id), parse_mode="Markdown")

    except TelegramForbiddenError:
        await callback.message.edit_caption(caption="🔴 Бот заблокирован или удален из канала. Рекомендуется удалить канал из списка.", reply_markup=channel_view_keyboard(channel_id))
    except Exception as e:
        await callback.message.edit_caption(caption=f"❌ Не удалось получить информацию о канале. Ошибка: {e}", reply_markup=channel_view_keyboard(channel_id))

@dp.callback_query(F.data.startswith("channel_delete_"))
async def cq_channel_delete(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    channel_id = int(callback.data.split("_")[-1])
    
    delete_channel(channel_id)
    await callback.answer(f"Канал {channel_id} удален из базы.", show_alert=True)
    
    await cq_admin_channels(callback, state)


@dp.callback_query(F.data.startswith("channel_send_message_"))
async def cq_channel_send_message(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_admin(callback.from_user.id): return
    channel_id = int(callback.data.split("_")[-1])
    await state.update_data(channel_id_to_send=channel_id)
    await state.set_state(ChannelMessage.waiting_for_message)
    await callback.message.edit_caption(caption=
        f"Отправьте сообщение для канала с ID `{channel_id}`.",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(f"channel_view_{channel_id}")
    )

@dp.message(ChannelMessage.waiting_for_message)
async def process_channel_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    channel_id = data.get('channel_id_to_send')
    try:
        await bot.copy_message(chat_id=channel_id, from_chat_id=message.chat.id, message_id=message.message_id)
        await message.answer("Сообщение успешно отправлено в канал.")
    except Exception as e:
        await message.answer(f"Не удалось отправить сообщение: {e}")
    finally:
        await message.answer_photo(
                    photo=ADMIN_BANNER_FILE_ID,
                    caption='♦️ Возвращаемся в админ-панель', 
                    reply_markup=admin_panel_keyboard()
                )

async def scheduled_backup():
    if not BACKUP_ENABLED:
        go_print("Создание бэкапа пропущено (отключено в настройках).")
        return
    go_print("--- НАЧАЛО ЕЖЕДНЕВНОГО БЭКАПА ---")
    backup_files = []
    try:
        db_backup_path = "users_backup.db"
        logs_backup_path = "logs_backup.db"
        
        await asyncio.to_thread(shutil.copy, 'users.db', db_backup_path)
        await asyncio.to_thread(shutil.copy, 'logs.db', logs_backup_path)
        
        backup_files = [db_backup_path, logs_backup_path]
        
        caption = f"Ежедневный бэкап баз данных от {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        for admin_id in ADMIN_IDS:
            await bot.send_document(admin_id, FSInputFile(db_backup_path), caption=caption)
            await bot.send_document(admin_id, FSInputFile(logs_backup_path))
        
        go_print("Бэкап баз данных успешно создан и отправлен админам.")

    except Exception as e:
        go_print(f"!!! ОШИБКА БЭКАПА: {e}")
        try:
            await bot.send_message(ADMIN_IDS[0], f"❌ Ошибка при создании бэкапа: {e}")
        except Exception:
            pass
    finally:
        for f in backup_files:
            if os.path.exists(f):
                os.remove(f)
        go_print("--- БЭКАП ЗАВЕРШЕН, временные файлы удалены ---")

@dp.message(F.text)
async def on_text(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        return

async def check_and_update_banner():
    """Проверяет наличие file_id для обоих баннеров."""
    global BANNER_FILE_ID, ADMIN_BANNER_FILE_ID
    
    # 1. Баннер главного меню
    go_print("Проверка баннера главного меню...")
    stored_id = get_config('main_menu_banner_id')
    
    if stored_id:
        try:
            msg = await bot.send_photo(chat_id=ADMIN_IDS[0], photo=stored_id, caption="🔄 Проверка...", disable_notification=True)
            BANNER_FILE_ID = msg.photo[-1].file_id
            await msg.delete()
        except Exception:
            go_print("Кэш главного баннера устарел.")
    
    if not BANNER_FILE_ID and os.path.exists(BANNER_FILE_PATH):
        try:
            msg = await bot.send_photo(chat_id=ADMIN_IDS[0], photo=FSInputFile(BANNER_FILE_PATH), caption="🆕 Новый баннер меню")
            BANNER_FILE_ID = msg.photo[-1].file_id
            set_config('main_menu_banner_id', BANNER_FILE_ID)
            go_print(f"Главный баннер загружен: {BANNER_FILE_ID}")
        except Exception as e:
            go_print(f"!!! Ошибка загрузки главного баннера: {e}")

    # 2. Баннер админ-панели (НОВАЯ ЧАСТЬ)
    go_print("Проверка баннера админ-панели...")
    stored_admin_id = get_config('admin_panel_banner_id')
    #print(stored_admin_id)
    if stored_admin_id:
        try:
            msg = await bot.send_photo(chat_id=ADMIN_IDS[0], photo=stored_admin_id, caption="🔄 Проверка...", disable_notification=True)
            ADMIN_BANNER_FILE_ID = msg.photo[-1].file_id
            await msg.delete()
        except Exception:
            go_print("Кэш админского баннера устарел.")

    if not ADMIN_BANNER_FILE_ID and os.path.exists(ADMIN_BANNER_FILE_PATH):
        try:
            msg = await bot.send_photo(chat_id=ADMIN_IDS[0], photo=FSInputFile(ADMIN_BANNER_FILE_PATH), caption="🆕 Новый админ-баннер")
            ADMIN_BANNER_FILE_ID = msg.photo[-1].file_id
            set_config('admin_panel_banner_id', ADMIN_BANNER_FILE_ID)
            go_print(f"Админский баннер загружен: {ADMIN_BANNER_FILE_ID}")
        except Exception as e:
            go_print(f"!!! Ошибка загрузки админского баннера: {e}")

# START
async def start_bot():
    """Инициализация и запуск бота."""
    go_print("Инициализация БД...")
    init_users_db() 
    init_logs_db()
    
    bot_info = await bot.get_me()
    set_bot_info_for_logging(bot_info.id, bot_info.username)
    
    for admin_id in ADMIN_IDS:
        admin_info = get_user_info(admin_id)
        if not admin_info:
            add_user(admin_id, "Admin")
        set_user_admin_status(admin_id, True)

    await check_and_update_banner()

    go_print("Выполняется первичная проверка хэша магазина...")
    await check_shop_update(is_startup=True) 
    
    try:
        admin_kb = InlineKeyboardBuilder()
        admin_kb.add(InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel"))
        
        startup_message = (
            "♦️ Бот запущен\n\n"
            f"Текущий хэш магазина:\n`{LAST_SHOP_HASH or 'Не удалось получить'}`"
        )
        await bot.send_message(ADMIN_IDS[0], startup_message, reply_markup=admin_kb.as_markup(), parse_mode="Markdown")
    except Exception as e:
        go_print(f"Не удалось отправить сообщение о запуске админу: {e}")

    start_scheduler(check_shop_update, scheduled_backup)

    go_print("Запуск бота...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    if not os.path.exists('settings.py'):
        print("ОШИБКА: Файл 'settings.py' не найден.")
        sys.exit()
    if not os.path.exists('generateshop.py'):
        print("ОШИБКА: Файл generateshop.py не найден!")
        sys.exit()
    if not os.path.exists('logs_database.py'):
        print("ОШИБКА: Файл logs_database.py не найден!")
        sys.exit()
    if not os.path.exists('scheduler.py'):
        print("ОШИБКА: Файл scheduler.py не найден!")
        sys.exit()
        
    try:
        import apscheduler
    except ImportError:
        print("Устанавливаю 'apscheduler'...")
        os.system(f"{sys.executable} -m pip install apscheduler")
    
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(start_bot())