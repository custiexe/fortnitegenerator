import asyncio
import os
import shutil
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
import aiohttp
import aiofiles
from PIL import Image, ImageFont, ImageDraw
from io import BytesIO
import time
from datetime import datetime
import locale

# ! ИЗМЕНЕНИЕ: Импортируем log_action
from logs_database import log_action

# --- НАСТРОЙКИ (заглушки для импорта из settings.py) ---
language = "ru"
textFont = "fonts/Cygre.ttf"
showItems = True
loggings = True

# ! НОВЫЕ ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ для логирования от имени бота
BOT_ID = None
BOT_USERNAME = "Bot"

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def set_bot_info_for_logging(bot_id: int, bot_username: str):
    """Устанавливает ID и username бота для функции go_print."""
    global BOT_ID, BOT_USERNAME
    BOT_ID = bot_id
    BOT_USERNAME = bot_username

def go_print(text):
    """Основная функция логирования."""
    if loggings:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_message = f"[{timestamp}] {text}"
        
        # 1. Вывод в консоль
        print(log_message)
        
        # ! ИЗМЕНЕНИЕ: 2. Запись в action_logs от имени бота
        try:
            # Используем ID и username бота, если они установлены
            log_action(
                user_id=BOT_ID or 0, 
                username=BOT_USERNAME or "Bot", 
                action_type="system_log", 
                action_content=text
            )
        except Exception as e:
            # Если логирование в БД не удалось, просто выводим ошибку в консоль
            print(f"[{timestamp}] !!! ОШИБКА go_print DB log: {e}")

try:
    locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')
except locale.Error:
    go_print("Предупреждение: Локаль ru_RU.UTF-8 не найдена.")

def sanitize_filename(name: str) -> str:
    """Удаляет недопустимые символы из имени файла."""
    name = name.replace(' ', '_')
    return re.sub(r'[\\/*?:"<>|]', "", name)

def get_font_for_text(text, font_path, max_width, initial_size):
    size = initial_size
    while size > 5:
        font = ImageFont.truetype(font_path, size)
        try:
            bbox = font.getbbox(text)
            text_width = bbox[2] - bbox[0]
        except AttributeError:
            text_width, _ = font.getsize(text)
        if text_width <= max_width:
            return font
        size -= 1
    return ImageFont.truetype(font_path, 5)

def process_image_sync(image_bytes, rarity, itemname, price, expiration_text, expiration_text_color):
    background = Image.open(BytesIO(image_bytes)).resize((512, 512), Image.LANCZOS).convert("RGBA")
    img = Image.new("RGB", (512, 625))

    try:
        item_bg = Image.open(f'images/rarities/{rarity}.png')
        img.paste(item_bg)
    except FileNotFoundError:
        pass

    img.paste(background, (0, 0), background)

    overlay_path = 'images/overlaynew.png' if expiration_text_color == '#FFA500' else 'images/1overlay.png'
    try:
        overlay = Image.open(overlay_path).convert('RGBA')
        img.paste(overlay, (0, 0), overlay)
    except FileNotFoundError:
        go_print(f"Предупреждение: оверлей '{overlay_path}' не найден.")

    draw = ImageDraw.Draw(img)
    font_name = get_font_for_text(itemname, textFont, 500, 42)
    draw.text((256, 550), itemname, font=font_name, fill='white', anchor='mm')
    
    font_date = ImageFont.truetype(textFont, 28)
    draw.text((14, 607), expiration_text, font=font_date, fill=expiration_text_color, anchor='lm')
    
    font_price = ImageFont.truetype(textFont, 28)
    draw.text((437, 607), str(price), font=font_price, fill='white', anchor='rm')

    buffer = BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()

# --- АСИНХРОННАЯ ЛОГИКА ---

async def create_item_image_async(session, item_data, current_shop_date_str):
    br_items = item_data.get('brItems')
    if not br_items:
        go_print(f"Пропуск предмета, так как 'brItems' отсутствует: {item_data.get('devName', 'N/A')}")
        return None

    try:
        item_info = br_items[0]
        rarity = item_info['rarity']['value']
        price = item_data['finalPrice']
        
        itemname = item_info['name']
        item_id = item_info['id']
        url = item_info['images'].get('icon')
        
        is_bundle = 'bundle' in item_data and item_data['bundle'] is not None
        
        if is_bundle:
            itemname = item_data['bundle']['name']
            url = item_data['bundle']['image']
        elif item_data.get('newDisplayAsset'):
            try:
                url = item_data['newDisplayAsset']['materialInstances'][0]['images']['OfferImage']
            except (KeyError, IndexError, TypeError):
                pass

        banner_value = item_data.get('banner', {}).get('value')
        is_new = (banner_value == 'Новинка!')

        if is_new:
            expiration_text = "НОВИНКА"
            expiration_text_color = '#FFA500'
        else:
            expiration_text = ""
            expiration_text_color = 'white'
            expiration_str = item_data.get('outDate')
            if expiration_str:
                try:
                    expiration_dt = datetime.fromisoformat(expiration_str.replace('Z', '+00:00'))
                    expiration_text = f"До {expiration_dt.strftime('%d %B')}"
                    current_shop_date = datetime.strptime(current_shop_date_str, "%Y-%m-%d").date()
                    expiration_date = expiration_dt.date()
                    if (expiration_date - current_shop_date).days <= 1:
                        expiration_text_color = '#FF4D4D'
                except ValueError:
                    go_print(f"Не удалось распознать дату: {expiration_str}")

        if is_bundle:
            save_name_prefix = 'z'
        else:
            new_item_prefix = '0' if is_new else '1'
            rarity_map = {'icon': '1', 'exotic': '2', 'mythic': '3', 'legendary': '4', 'epic': '5', 'rare': '6', 'uncommon': '7', 'common': '8'}
            rarity_prefix = rarity_map.get(rarity, '9')
            save_name_prefix = f"{new_item_prefix}_{rarity_prefix}"

        async with session.get(url) as response:
            response.raise_for_status()
            image_bytes = await response.read()

        loop = asyncio.get_running_loop()
        processed_image_bytes = await loop.run_in_executor(
            None, process_image_sync, image_bytes, rarity, itemname, price, expiration_text, expiration_text_color
        )

        safe_itemname = sanitize_filename(itemname)
        save_name = f"{save_name_prefix}_{item_id if not is_bundle else safe_itemname}.png"
        save_path = f'images/cache/{save_name}'
        
        async with aiofiles.open(save_path, 'wb') as f:
            await f.write(processed_image_bytes)

        if showItems:
            go_print(f'Сгенерирован: {itemname}')
        
        return save_path

    except Exception as e:
        go_print(f"Ошибка обработки предмета '{item_data.get('devName', 'N/A')}': {e}")
        return None

async def merge_images_to_final(date_str, images_paths, title_text, output_prefix):
    """Собирает переданный список изображений в один или несколько файлов с фиксированной сеткой."""
    if not images_paths:
        go_print(f"Нет изображений для слияния в '{output_prefix}'.")
        return []

    num_items = len(images_paths)
    
    cols = 10
    items_per_image = 100
    generated_files = []

    for i in range(0, num_items, items_per_image):
        chunk_paths = images_paths[i:i + items_per_image]
        image_index = (i // items_per_image) + 1
        
        item_w, item_h = 512, 625
        padding = 10
        footer_height = 100
        
        current_cols = cols
        if len(chunk_paths) == 0: continue

        rows = (len(chunk_paths) + current_cols - 1) // current_cols
        total_w = (item_w * current_cols) + (padding * (current_cols + 1))
        total_h = (item_h * rows) + (padding * (rows + 1)) + footer_height

        shop_image = Image.new('RGB', (total_w, total_h), color='#1c1c1c')
        draw = ImageDraw.Draw(shop_image)

        for j, path in enumerate(chunk_paths):
            row = j // current_cols
            col = j % current_cols
            x = padding + col * (item_w + padding)
            y = padding + row * (item_h + padding)
            with Image.open(path) as item_img:
                shop_image.paste(item_img, (x, y))
        
        try:
            font_footer = ImageFont.truetype(textFont, 60)
            formatted_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %B %Y г.")
            
            footer_y = total_h - (footer_height / 2)
            left_text = "@FortniteDailyStoreBot"
            draw.text((padding, footer_y), left_text, font=font_footer, fill='white', anchor='lm')
            draw.text((total_w - padding, footer_y), formatted_date, font=font_footer, fill='white', anchor='rm')

        except Exception as e:
            go_print(f"Не удалось нарисовать футер: {e}")

        telegram_limit = 10000
        if (shop_image.width + shop_image.height) > telegram_limit:
            go_print(f"Изображение {output_prefix} слишком большое ({shop_image.width}x{shop_image.height}). Уменьшение размера...")
            ratio = telegram_limit / (shop_image.width + shop_image.height)
            new_width = int(shop_image.width * ratio)
            new_height = int(shop_image.height * ratio)
            shop_image = shop_image.resize((new_width, new_height), Image.LANCZOS)
            go_print(f"Новый размер: {shop_image.width}x{shop_image.height}")
        
        output_filename = f'images/{output_prefix}_{image_index}.jpg'
        shop_image.save(output_filename, quality=95)
        generated_files.append(output_filename)
        go_print(f"Финальное изображение '{output_filename}' сохранено.")
    
    return generated_files

async def main():
    """Главная асинхронная функция."""
    if os.path.exists('images/cache'):
        shutil.rmtree('images/cache')
    os.makedirs('images/cache')

    start_time = time.time()
    
    async with aiohttp.ClientSession() as session:
        try:
            go_print("Получение данных из API магазина...")
            async with session.get(f'https://fortnite-api.com/v2/shop?language={language}') as response:
                response.raise_for_status()
                shop_data = (await response.json())['data']
        except aiohttp.ClientError as e:
            go_print(f"Не удалось получить данные магазина: {e}")
            return [], 0, "" # Возвращаем пустые данные
        
        current_date = shop_data['date'][:10]
        
        go_print('Запуск асинхронной генерации карточек...')
        tasks = []
        for item in shop_data.get('entries', []):
            if 'Jam Tracks' not in item.get('layout', {}).get('name', ''):
                tasks.append(create_item_image_async(session, item, current_date))

        results = await asyncio.gather(*tasks)
    
    valid_paths = sorted([res for res in results if res is not None])
    go_print(f'Готово. Сгенерировано "{len(valid_paths)}" карточек.')

    final_image_tasks = []
    if valid_paths:
        final_image_tasks.append(merge_images_to_final(current_date, valid_paths, "Магазин предметов", "shop"))
    
    generated_files_lists = await asyncio.gather(*final_image_tasks)
    final_images = [item for sublist in generated_files_lists for item in sublist]

    end_time = time.time()
    generation_seconds = round(end_time - start_time, 2)
    go_print(f"ГЕНЕРАЦИЯ ЗАВЕРШЕНА за {generation_seconds} секунд!")
    go_print(f"Созданные файлы: {final_images}")
    
    item_count = len(valid_paths)
    return final_images, item_count, current_date