import sqlite3
from datetime import datetime
import json

LOG_DB_NAME = 'logs.db'

def init_logs_db():
    """Инициализирует БД логов и создает таблицы."""
    with sqlite3.connect(LOG_DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                action_type TEXT,
                action_content TEXT,
                timestamp TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS db_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                function_name TEXT,
                query TEXT,
                parameters TEXT
            )
        ''')
        conn.commit()

def log_action(user_id: int, username: str, action_type: str, action_content: str):
    """Записывает одно действие пользователя в БД логов."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(LOG_DB_NAME) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO action_logs (user_id, username, action_type, action_content, timestamp) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, action_type, action_content, timestamp)
            )
            conn.commit()
        except Exception as e:
            print(f"!!! ОШИБКА ЛОГИРОВАНИЯ В БД: {e}")

def log_db_action(function_name: str, query: str, parameters: tuple | None = None):
    """Записывает одно действие с основной БД (users.db) в БД логов."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    params_str = json.dumps(parameters) if parameters else None
    
    with sqlite3.connect(LOG_DB_NAME) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO db_logs (timestamp, function_name, query, parameters) VALUES (?, ?, ?, ?)",
                (timestamp, function_name, query, params_str)
            )
            conn.commit()
        except Exception as e:
             print(f"!!! ОШИБКА ЛОГИРОВАНИЯ (DB): {e}")

# ! ИЗМЕНЕНИЕ: Функция теперь принимает страницу
def get_logs(page: int = 0, limit: int = 20) -> list:
    """Возвращает N логов для указанной страницы."""
    offset = page * limit
    with sqlite3.connect(LOG_DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp, user_id, username, action_type, action_content FROM action_logs ORDER BY id DESC LIMIT ? OFFSET ?", 
            (limit, offset)
        )
        return cursor.fetchall()

# ! НОВАЯ ФУНКЦИЯ
def get_log_count() -> int:
    """Возвращает общее количество логов действий."""
    with sqlite3.connect(LOG_DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(id) FROM action_logs")
        result = cursor.fetchone()
        return result[0] if result else 0

def get_all_logs() -> list:
    """Возвращает ВСЕ логи для экспорта."""
    with sqlite3.connect(LOG_DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp, user_id, username, action_type, action_content FROM action_logs ORDER BY id ASC"
        )
        return cursor.fetchall()

def get_user_logs(user_id: int, limit: int = 10) -> list:
    """Возвращает последние N действий конкретного пользователя."""
    with sqlite3.connect(LOG_DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp, action_type, action_content FROM action_logs WHERE user_id = ? ORDER BY id DESC LIMIT ?", 
            (user_id, limit)
        )
        return cursor.fetchall()

# ! НОВАЯ ФУНКЦИЯ
def clear_all_action_logs():
    """Удаляет все записи из таблицы action_logs."""
    with sqlite3.connect(LOG_DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM action_logs")
        # Также сбрасываем счетчик, чтобы ID начался с 1 (опционально, но аккуратно)
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='action_logs'")
        conn.commit()