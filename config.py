import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Собираем все ключи Gemini
GEMINI_API_KEYS = []

# Вариант 1: GEMINI_API_KEY (один ключ)
single_key = os.getenv("GEMINI_API_KEY")
if single_key:
    GEMINI_API_KEYS.append(single_key)

# Вариант 2: GEMINI_KEY_1, GEMINI_KEY_2 и т.д.
i = 1
while True:
    key = os.getenv(f"GEMINI_KEY_{i}")
    if key:
        GEMINI_API_KEYS.append(key)
        i += 1
    else:
        break

# Вариант 3: GEMINI_API_KEYS через запятую
keys_str = os.getenv("GEMINI_API_KEYS", "")
if keys_str:
    for k in keys_str.split(","):
        k = k.strip()
        if k and k not in GEMINI_API_KEYS:
            GEMINI_API_KEYS.append(k)

# Удаляем дубликаты
GEMINI_API_KEYS = list(dict.fromkeys(GEMINI_API_KEYS))

# Проверка
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле")
if not GEMINI_API_KEYS:
    raise ValueError("Не добавлено ни одного API ключа Gemini в .env файле")

print(f"✅ Загружено {len(GEMINI_API_KEYS)} API ключей Gemini")
for i, key in enumerate(GEMINI_API_KEYS):
    print(f"   Ключ {i+1}: {key[:10]}...{key[-5:]}")