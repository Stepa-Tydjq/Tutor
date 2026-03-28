import time
from datetime import datetime, timedelta
from collections import defaultdict
import hashlib
from typing import Optional, Tuple


class UserRateLimiter:
    """Лимиты для каждого пользователя (20 запросов в день)"""

    def __init__(self, daily_limit: int = 20):
        self.daily_limit = daily_limit
        self.user_requests = defaultdict(list)  # {user_id: [timestamps]}

    def _get_today_start(self) -> float:
        """Возвращает timestamp начала сегодняшнего дня (00:00)"""
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def get_remaining(self, user_id: int) -> int:
        """Возвращает количество оставшихся запросов для пользователя"""
        today_start = self._get_today_start()

        # Очищаем старые запросы (старше сегодняшнего дня)
        self.user_requests[user_id] = [
            ts for ts in self.user_requests[user_id]
            if ts >= today_start
        ]

        used = len(self.user_requests[user_id])
        return max(0, self.daily_limit - used)

    def can_make_request(self, user_id: int) -> Tuple[bool, int]:
        """Проверяет, может ли пользователь сделать запрос. Возвращает (можно, осталось)"""
        remaining = self.get_remaining(user_id)
        return remaining > 0, remaining

    def add_request(self, user_id: int):
        """Добавляет запрос пользователя"""
        self.user_requests[user_id].append(time.time())

    def get_reset_time(self) -> str:
        """Возвращает время до сброса лимита"""
        now = datetime.now()
        tomorrow = datetime(now.year, now.month, now.day) + timedelta(days=1)
        remaining = tomorrow - now
        hours = remaining.seconds // 3600
        minutes = (remaining.seconds % 3600) // 60
        return f"{hours}ч {minutes}мин"


class ResponseCache:
    """Кэш ответов для экономии запросов"""

    def __init__(self, max_size: int = 100, ttl_hours: int = 24):
        self.cache = {}  # {key: (response, timestamp)}
        self.max_size = max_size
        self.ttl = ttl_hours * 3600  # в секундах

    def _get_key(self, user_message: str, image_data: bytes = None, subject: str = None) -> str:
        """Создает уникальный ключ из запроса"""
        content = f"{user_message}_{subject}"
        if image_data:
            content += f"_{hashlib.md5(image_data).hexdigest()}"
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, user_message: str, image_data: bytes = None, subject: str = None) -> Optional[str]:
        """Возвращает закэшированный ответ или None"""
        key = self._get_key(user_message, image_data, subject)

        if key in self.cache:
            response, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return response
            else:
                # Удаляем просроченный кэш
                del self.cache[key]

        return None

    def set(self, user_message: str, image_data: bytes, subject: str, response: str):
        """Сохраняет ответ в кэш"""
        key = self._get_key(user_message, image_data, subject)

        # Если кэш переполнен, удаляем самый старый
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            del self.cache[oldest_key]

        self.cache[key] = (response, time.time())


class GlobalRateLimiter:
    """Отслеживает глобальные лимиты API (чтобы не ловить 429)"""

    def __init__(self):
        self.last_error_time = 0
        self.error_count = 0
        self.is_blocked = False
        self.blocked_until = 0

    def report_error(self, error_message: str) -> bool:
        """Обрабатывает ошибку API. Возвращает True если нужно заблокировать запросы"""
        now = time.time()

        if "429" in error_message or "quota" in error_message.lower():
            self.error_count += 1
            self.last_error_time = now

            # Если получили ошибку 429, блокируем на 5 секунд
            self.is_blocked = True
            self.blocked_until = now + 5

            # Если ошибок много за короткое время, блокируем дольше
            if self.error_count >= 3:
                self.blocked_until = now + 60  # блокируем на минуту
                self.error_count = 0

            return True

        return False

    def can_request(self) -> Tuple[bool, int]:
        """Проверяет, можно ли делать запрос. Возвращает (можно, секунды до разблокировки)"""
        now = time.time()

        if self.is_blocked and now < self.blocked_until:
            wait = int(self.blocked_until - now) + 1
            return False, wait

        self.is_blocked = False
        return True, 0