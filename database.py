import sqlite3
from datetime import datetime
try:
    from generateshop import go_print
except ImportError:
    def go_print(text):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
        
from logs_database import log_db_action

DB_NAME = 'users.db'

def init_db():
    """Инициализирует БД и создает таблицы, если их нет."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        query_users = '''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, username TEXT, reg_date TEXT,
                is_admin INTEGER DEFAULT 0, is_blocked INTEGER DEFAULT 0)'''
        log_db_action('init_db', query_users)
        cursor.execute(query_users)
        
        query_images = '''CREATE TABLE IF NOT EXISTS shop_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT NOT NULL, file_id TEXT NOT NULL)'''
        log_db_action('init_db', query_images)
        cursor.execute(query_images)
        
        query_stats = '''CREATE TABLE IF NOT EXISTS generation_stats (
                id INTEGER PRIMARY KEY, generation_date TEXT NOT NULL, item_count INTEGER NOT NULL)'''
        log_db_action('init_db', query_stats)
        cursor.execute(query_stats)
        
        query_channels = '''CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER NOT NULL UNIQUE, title TEXT)'''
        log_db_action('init_db', query_channels)
        cursor.execute(query_channels)
        
        # ! НОВАЯ ТАБЛИЦА: Для логов рассылки
        query_broadcast_log = '''CREATE TABLE IF NOT EXISTS broadcast_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            )'''

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        log_db_action('init_db', query_broadcast_log)
        cursor.execute(query_broadcast_log)
        
        conn.commit()

# --- Функции для пользователей ---
def add_user(user_id: int, username: str):
    """Добавляет нового пользователя, если его еще нет в базе."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query_select = "SELECT id FROM users WHERE id = ?"
        params_select = (user_id,)
        log_db_action('add_user', query_select, params_select)
        cursor.execute(query_select, params_select)
        if cursor.fetchone() is None:
            reg_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            query_insert = "INSERT INTO users (id, username, reg_date) VALUES (?, ?, ?)"
            params_insert = (user_id, username, reg_date)
            log_db_action('add_user', query_insert, params_insert)
            cursor.execute(query_insert, params_insert)
            conn.commit()
            go_print(f"Новый пользователь добавлен: {username} (ID: {user_id})")

def is_exists(user_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query_select = "SELECT id FROM users WHERE id = ?"
        params_select = (user_id,)
        cursor.execute(query_select, params_select)
        if cursor.fetchone() is None:
            return False
        return True

def is_user_admin(user_id: int) -> bool:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "SELECT is_admin FROM users WHERE id = ?"
        params = (user_id,)
        log_db_action('is_user_admin', query, params)
        cursor.execute(query, params)
        result = cursor.fetchone()
        return result and result[0] == 1

def is_user_blocked(user_id: int) -> bool:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "SELECT is_blocked FROM users WHERE id = ?"
        params = (user_id,)
        log_db_action('is_user_blocked', query, params)
        cursor.execute(query, params)
        result = cursor.fetchone()
        return result and result[0] == 1

def get_all_users() -> list:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "SELECT id, username, is_blocked, is_admin FROM users"
        log_db_action('get_all_users', query)
        cursor.execute(query)
        return cursor.fetchall()

def get_user_info(user_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "SELECT id, username, reg_date, is_blocked, is_admin FROM users WHERE id = ?"
        params = (user_id,)
        log_db_action('get_user_info', query, params)
        cursor.execute(query, params)
        return cursor.fetchone()

def set_user_block_status(user_id: int, is_blocked: bool):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "UPDATE users SET is_blocked = ? WHERE id = ?"
        params = (1 if is_blocked else 0, user_id)
        log_db_action('set_user_block_status', query, params)
        cursor.execute(query, params)
        conn.commit()

def set_user_admin_status(user_id: int, is_admin: bool):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "UPDATE users SET is_admin = ? WHERE id = ?"
        params = (1 if is_admin else 0, user_id)
        log_db_action('set_user_admin_status', query, params)
        cursor.execute(query, params)
        conn.commit()

def delete_user(user_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "DELETE FROM users WHERE id = ?"
        params = (user_id,)
        log_db_action('delete_user', query, params)
        cursor.execute(query, params)
        conn.commit()

def get_config(key: str):
    """Получает значение настройки по ключу."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM bot_config WHERE key = ?", (key,))
        result = cursor.fetchone()
        return result[0] if result else None

def set_config(key: str, value: str):
    """Сохраняет или обновляет настройку."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO bot_config (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

# --- Функции для изображений магазина ---
def clear_shop_images():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "DELETE FROM shop_images"
        log_db_action('clear_shop_images', query)
        cursor.execute(query)
        conn.commit()

def add_shop_image(file_name: str, file_id: str):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "INSERT INTO shop_images (file_name, file_id) VALUES (?, ?)"
        params = (file_name, file_id)
        log_db_action('add_shop_image', query, params)
        cursor.execute(query, params)
        conn.commit()

def get_all_shop_images() -> list:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "SELECT file_id FROM shop_images ORDER BY file_name"
        log_db_action('get_all_shop_images', query)
        cursor.execute(query)
        return [row[0] for row in cursor.fetchall()]

# --- Функции для статистики ---
def log_generation(date: str, count: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        query_del = "DELETE FROM generation_stats"
        log_db_action('log_generation', query_del)
        cursor.execute(query_del)
        
        query_ins = "INSERT INTO generation_stats (generation_date, item_count) VALUES (?, ?)"
        params_ins = (date, count)
        log_db_action('log_generation', query_ins, params_ins)
        cursor.execute(query_ins, params_ins)
        
        conn.commit()

def get_latest_generation_stats() -> tuple | None:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "SELECT generation_date, item_count FROM generation_stats LIMIT 1"
        log_db_action('get_latest_generation_stats', query)
        cursor.execute(query)
        return cursor.fetchone()

# --- Функции для каналов ---
def get_all_channels() -> list:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "SELECT channel_id, title FROM channels ORDER BY title"
        log_db_action('get_all_channels', query)
        cursor.execute(query)
        return cursor.fetchall()

def add_channel(channel_id: int, title: str):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        try:
            query = "INSERT INTO channels (channel_id, title) VALUES (?, ?)"
            params = (channel_id, title)
            log_db_action('add_channel', query, params)
            cursor.execute(query, params)
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            log_db_action('add_channel', 'INSERT (failed due to UNIQUE constraint)', (channel_id, title))
            return False

def delete_channel(channel_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "DELETE FROM channels WHERE channel_id = ?"
        params = (channel_id,)
        log_db_action('delete_channel', query, params)
        cursor.execute(query, params)
        conn.commit()

# --- ! НОВЫЕ ФУНКЦИИ для логов рассылки ---
def log_broadcast_message(channel_id: int, message_id: int):
    """Логирует ID отправленного в канал сообщения."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "INSERT INTO broadcast_log (channel_id, message_id) VALUES (?, ?)"
        params = (channel_id, message_id)
        # Не логируем в db_logs, чтобы избежать бесконечного цикла
        cursor.execute(query, params)
        conn.commit()

def get_all_broadcast_messages() -> list:
    """Возвращает список всех (channel_id, message_id) из лога рассылки."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "SELECT channel_id, message_id FROM broadcast_log"
        # Не логируем
        cursor.execute(query)
        return cursor.fetchall()

def clear_broadcast_log():
    """Очищает лог рассылки."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        query = "DELETE FROM broadcast_log"
        # Не логируем
        cursor.execute(query)
        conn.commit()