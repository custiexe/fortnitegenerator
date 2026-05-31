from apscheduler.schedulers.asyncio import AsyncIOScheduler
try:
    from generateshop import go_print
except ImportError:
    from datetime import datetime
    def go_print(text):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")

def start_scheduler(check_job, backup_job):
    """
    Запускает планировщик для двух задач:
    1. check_job: каждые 15 мин И ровно в 3:01 по МСК.
    2. backup_job: ровно в 3:01 по МСК.
    """
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    
    # Задача 1: Проверка магазина (каждые 15 мин)
    scheduler.add_job(
        check_job,
        trigger='interval',
        minutes=15,
        id='interval_check'
    )
    
    # Задача 2: Проверка магазина (в 3:01)
    scheduler.add_job(
        check_job,
        trigger='cron',
        hour=3,
        minute=1,
        id='daily_failsafe_check'
    )
    
    # ! НОВАЯ ЗАДАЧА: Бэкап (в 3:01)
    scheduler.add_job(
        backup_job,
        trigger='cron',
        hour=3,
        minute=1,
        id='daily_backup_job'
    )
    
    scheduler.start()
    go_print("Планировщик запущен: проверка (каждые 15 мин + 3:01 МСК), бэкап (3:01 МСК).")