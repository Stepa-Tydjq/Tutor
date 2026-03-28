import google.generativeai as genai
import asyncio
import time
import hashlib
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple, List
from config import GEMINI_API_KEYS


PROXY_URL = None

if PROXY_URL:
    os.environ["HTTP_PROXY"] = PROXY_URL
    os.environ["HTTPS_PROXY"] = PROXY_URL
    print(f"✅ Используется прокси: {PROXY_URL}")
else:
    print("⚠️ Прокси не настроен. Если ты в России, Gemini может не работать.")


executor = ThreadPoolExecutor(max_workers=10)


class KeyPoolManager:
    """Менеджер пула ключей"""

    def __init__(self, keys: List[str], daily_limit: int = 20):
        self.keys = []
        for i, key in enumerate(keys):
            self.keys.append({
                "key": key,
                "used_today": 0,
                "last_reset": 0,
                "name": f"Ключ {i + 1}",
                "blocked": False
            })
        self.daily_limit = daily_limit
        self.current_index = 0

    def _get_today_start(self) -> float:
        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day, 0, 0, 0)
        return today_start.timestamp()

    def reset_if_needed(self):
        today_start = self._get_today_start()
        for key_data in self.keys:
            if key_data["last_reset"] < today_start:
                key_data["used_today"] = 0
                key_data["last_reset"] = today_start
                key_data["blocked"] = False

    def get_available_key(self) -> Optional[dict]:
        self.reset_if_needed()

        # Ищем не заблокированный ключ с остатком
        for i in range(len(self.keys)):
            idx = (self.current_index + i) % len(self.keys)
            key_data = self.keys[idx]

            if not key_data["blocked"] and key_data["used_today"] < self.daily_limit:
                self.current_index = idx
                return key_data

        # Если все заблокированы, ищем любой с остатком
        for key_data in self.keys:
            if key_data["used_today"] < self.daily_limit:
                key_data["blocked"] = False
                return key_data

        return None

    def mark_used(self, key_data: dict):
        self.reset_if_needed()
        key_data["used_today"] += 1
        if key_data["used_today"] >= self.daily_limit:
            key_data["blocked"] = True

    def mark_error(self, key_data: dict):
        self.reset_if_needed()
        key_data["blocked"] = True
        key_data["used_today"] = self.daily_limit

    def get_total_remaining(self) -> int:
        self.reset_if_needed()
        total = 0
        for key_data in self.keys:
            total += max(0, self.daily_limit - key_data["used_today"])
        return total

    def get_stats(self) -> str:
        self.reset_if_needed()
        lines = []
        for key_data in self.keys:
            used = key_data["used_today"]
            remaining = self.daily_limit - used
            if key_data["blocked"]:
                status = "🔴"
            elif remaining > 0:
                status = "✅"
            else:
                status = "❌"
            lines.append(f"  {status} {key_data['name']}: {used}/{self.daily_limit} (осталось {remaining})")
        return "\n".join(lines)


# Создаем менеджер
key_manager = KeyPoolManager(GEMINI_API_KEYS, daily_limit=20)


class ResponseCache:
    """Кэш ответов"""

    def __init__(self, max_size: int = 200):
        self.cache = {}
        self.max_size = max_size

    def _get_key(self, user_message: str, image_data: bytes = None, subject: str = None) -> str:
        content = f"{user_message}_{subject}"
        if image_data:
            content += f"_{hashlib.md5(image_data).hexdigest()}"
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, user_message: str, image_data: bytes = None, subject: str = None) -> Optional[str]:
        key = self._get_key(user_message, image_data, subject)
        if key in self.cache:
            response, timestamp = self.cache[key]
            if time.time() - timestamp < 86400:  # 24 часа
                return response
            else:
                del self.cache[key]
        return None

    def set(self, user_message: str, image_data: bytes, subject: str, response: str):
        key = self._get_key(user_message, image_data, subject)
        if len(self.cache) >= self.max_size:
            oldest = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            del self.cache[oldest]
        self.cache[key] = (response, time.time())


response_cache = ResponseCache()


def get_system_prompt(subject: str = None, detailed: bool = False) -> str:
    """Системный промпт"""
    format_rules = """
ВАЖНО! ЗАПРЕЩЕНО:
- Использовать * $ _ [ ] ( ) для форматирования
- LaTeX формулы, Markdown
Пиши ТОЛЬКО обычным текстом!
"""
    if subject in ("math", "physics"):
        return format_rules + """
ПРАВИЛА ДЛЯ МАТЕМАТИКИ И ФИЗИКИ:
- Каждый шаг с новой строки, нумерация: 1) 2) 3)
- Используй эмодзи: 🧮 📝 ✅
"""
    elif subject == "language":
        return format_rules + """
ПРАВИЛА ДЛЯ АНГЛИЙСКОГО:
- Отвечай ОДНИМ ЦЕЛЬНЫМ ТЕКСТОМ
- Дай полный перевод или исправление
"""
    else:
        return format_rules + """
ПРАВИЛА:
- Ты репетитор. Отвечай ТОЛЬКО на учебные вопросы!
- Математика/физика: нумерация шагов
- Английский: цельный текст
"""


async def ask_gemini(
        user_message: str,
        image_data: bytes = None,
        mime_type: str = None,
        subject: str = None,
) -> Tuple[str, bool]:
    """Отправляет запрос к Gemini"""

    # Проверяем кэш
    cached = response_cache.get(user_message, image_data, subject)
    if cached:
        return cached, False

    # Получаем доступный ключ
    key_data = key_manager.get_available_key()
    if not key_data:
        return (f"❌ Все API ключи исчерпали лимит!\n\n"
                f"📊 Статистика:\n{key_manager.get_stats()}\n\n"
                f"⏰ Сброс в 00:00\n"
                f"💡 Повторные вопросы из кэша не тратят лимит!"), False

    loop = asyncio.get_event_loop()

    def _sync_call():
        # Настраиваем Gemini с выбранным ключом
        genai.configure(api_key=key_data["key"])

        try:
            model = genai.GenerativeModel(
                model_name="models/gemini-2.5-flash",
                system_instruction=get_system_prompt(subject, detailed=False),
            )
        except Exception as e:
            print(f"System instruction error: {e}")
            model = genai.GenerativeModel(model_name="models/gemini-2.5-flash")

        contents = []
        if image_data and mime_type:
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(image_data))
                contents.append(img)
            except Exception as e:
                print(f"Ошибка обработки изображения: {e}")

        if user_message:
            contents.append(user_message)
        elif not contents:
            contents.append("Опиши изображение.")

        response = model.generate_content(contents)
        return response.text

    try:
        result = await loop.run_in_executor(executor, _sync_call)
        # Успешный запрос - увеличиваем счетчик
        key_manager.mark_used(key_data)
        # Сохраняем в кэш
        response_cache.set(user_message, image_data, subject, result)
        return result, True

    except Exception as e:
        error_msg = str(e)
        print(f"Gemini API error: {error_msg}")

        # Ошибка региона
        if "location" in error_msg.lower() or "not supported" in error_msg.lower():
            return (f"❌ Gemini API недоступен в твоем регионе.\n\n"
                    f"🔧 Решения:\n"
                    f"1. Включи VPN (ProtonVPN - бесплатно)\n"
                    f"2. Настрой прокси в коде (PROXY_URL)\n"
                    f"3. Запусти бота на сервере в США/Европе\n\n"
                    f"📊 Статистика:\n{key_manager.get_stats()}"), False

        # Ошибка 429 - лимит исчерпан
        if "429" in error_msg or "quota" in error_msg.lower():
            key_manager.mark_error(key_data)
            # Рекурсивно пробуем с другим ключом
            return await ask_gemini(user_message, image_data, mime_type, subject)

        # Неверный ключ
        if "invalid" in error_msg.lower() or "API key" in error_msg:
            key_manager.mark_error(key_data)
            return await ask_gemini(user_message, image_data, mime_type, subject)

        return f"❌ Ошибка: {error_msg[:200]}", False


async def ask_gemini_detailed(
        user_message: str,
        image_data: bytes = None,
        mime_type: str = None,
        subject: str = None,
) -> Tuple[str, bool]:
    """Подробный ответ (для кнопки 'Подробнее')"""

    cached = response_cache.get(f"{user_message}_detailed", image_data, subject)
    if cached:
        return cached, False

    key_data = key_manager.get_available_key()
    if not key_data:
        return "❌ Все ключи исчерпали лимит. Попробуй завтра.", False

    loop = asyncio.get_event_loop()

    def _sync_call():
        genai.configure(api_key=key_data["key"])
        try:
            model = genai.GenerativeModel(
                model_name="models/gemini-2.5-flash",
                system_instruction=get_system_prompt(subject, detailed=True),
            )
        except Exception as e:
            model = genai.GenerativeModel(model_name="models/gemini-2.5-flash")

        contents = []
        if image_data and mime_type:
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(image_data))
                contents.append(img)
            except Exception as e:
                print(f"Ошибка: {e}")

        if user_message:
            contents.append(f"Объясни ПОДРОБНО: {user_message}")
        else:
            contents.append("Опиши изображение подробно.")

        response = model.generate_content(contents)
        return response.text

    try:
        result = await loop.run_in_executor(executor, _sync_call)
        key_manager.mark_used(key_data)
        response_cache.set(f"{user_message}_detailed", image_data, subject, result)
        return result, True
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "quota" in error_msg.lower():
            key_manager.mark_error(key_data)
            return await ask_gemini_detailed(user_message, image_data, mime_type, subject)
        if "location" in error_msg.lower():
            return "❌ Gemini API недоступен в твоем регионе. Включи VPN или настрой прокси!", False
        return f"❌ Ошибка: {error_msg[:200]}", False