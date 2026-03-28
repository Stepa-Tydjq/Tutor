import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN
from gemini_client import ask_gemini, ask_gemini_detailed, key_manager

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=None)
)
dp = Dispatcher()

user_subjects = {}
user_last_question = {}


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def is_educational(text: str) -> bool:
    educational_keywords = [
        'реши', 'уравнение', 'пример', 'задача', 'вычисли', 'найди',
        'умножение', 'деление', 'дробь', 'корень', 'степень',
        'физика', 'скорость', 'сила', 'энергия', 'масса',
        'переведи', 'translate', 'перевод', 'английский', 'english',
        'исправь ошибку', 'грамматика'
    ]
    text_lower = text.lower()

    if len(text_lower.split()) < 3:
        if any(p in text_lower for p in ['привет', 'как дела', 'hi', 'hello']):
            return False

    return any(k in text_lower for k in educational_keywords) or bool(re.search(r'[\d\+\-\*\/\=\(\)]', text))


def clean_text(text: str) -> str:
    text = re.sub(r'\\\(.*?\\\)', '', text)
    text = re.sub(r'\$.*?\$', '', text)
    text = re.sub(r'\*\*.*?\*\*', '', text)
    text = text.replace('\\', '')
    return text.strip()


def split_text(text: str, max_length: int = 4000) -> list:
    if len(text) <= max_length:
        return [text]
    parts = []
    lines = text.split('\n')
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 <= max_length:
            current += line + "\n"
        else:
            if current:
                parts.append(current.strip())
            current = line + "\n"
    if current:
        parts.append(current.strip())
    return parts


def get_keyboard(has_details: bool = True) -> InlineKeyboardMarkup:
    buttons = []
    if has_details:
        buttons.append([InlineKeyboardButton(text="📖 Подробнее", callback_data="more_details")])
    buttons.append([
        InlineKeyboardButton(text="🧮 Математика", callback_data="mode_math"),
        InlineKeyboardButton(text="🗣️ Язык", callback_data="mode_language")
    ])
    buttons.append([InlineKeyboardButton(text="✨ Общий режим", callback_data="mode_general")])

    # Показываем статистику по ключам
    total_remaining = key_manager.get_total_remaining()
    buttons.append([InlineKeyboardButton(
        text=f"📊 Всего осталось: {total_remaining} запросов",
        callback_data="show_limit"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== КОМАНДЫ ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    total_remaining = key_manager.get_total_remaining()
    await message.answer(
        f"🎓 Привет! Я образовательный репетитор\n\n"
        f"Я помогаю решать задачи по:\n"
        f"🧮 Математике\n"
        f"⚡ Физике\n"
        f"🗣️ Английскому языку\n\n"
        f"📊 Всего доступно: {total_remaining} запросов\n"
        f"🔑 Загружено ключей: {len(key_manager.keys)}\n\n"
        f"💡 Повторные вопросы не тратят лимит!\n\n"
        f"Отправь задачу!",
        reply_markup=get_keyboard(has_details=False)
    )


@dp.message(Command("math"))
async def set_math_mode(message: types.Message):
    user_subjects[message.from_user.id] = "math"
    await message.answer("🧮 Режим математики включен!", reply_markup=get_keyboard())


@dp.message(Command("language"))
async def set_language_mode(message: types.Message):
    user_subjects[message.from_user.id] = "language"
    await message.answer("🗣️ Режим английского языка включен!", reply_markup=get_keyboard())


@dp.message(Command("general"))
async def set_general_mode(message: types.Message):
    user_subjects[message.from_user.id] = None
    await message.answer("✨ Общий режим включен!", reply_markup=get_keyboard())


@dp.message(Command("clear"))
async def clear_mode(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_subjects:
        del user_subjects[user_id]
    if user_id in user_last_question:
        del user_last_question[user_id]
    await message.answer("Режим сброшен.", reply_markup=get_keyboard())


@dp.message(Command("limit"))
async def show_limit(message: types.Message):
    total_remaining = key_manager.get_total_remaining()
    await message.answer(
        f"📊 Статистика API ключей:\n\n"
        f"✅ Всего ключей: {len(key_manager.keys)}\n"
        f"📊 Лимит на один ключ: {key_manager.daily_limit} запросов/день\n"
        f"💚 Осталось всего: {total_remaining} запросов\n\n"
        f"💡 Повторные вопросы не тратят лимит!",
        reply_markup=get_keyboard()
    )


# ==================== ОБРАБОТКА КНОПОК ====================
@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if callback.data == "more_details":
        if user_id in user_last_question:
            question, subject, image_data, mime_type = user_last_question[user_id]

            await callback.message.answer("📖 Подробное объяснение:")

            try:
                detailed_response, used = await ask_gemini_detailed(
                    user_message=question,
                    image_data=image_data,
                    mime_type=mime_type,
                    subject=subject
                )

                for part in split_text(clean_text(detailed_response)):
                    await callback.message.answer(part)

            except Exception as e:
                await callback.message.answer(f"Ошибка: {str(e)[:200]}")

        await callback.answer()

    elif callback.data == "mode_math":
        user_subjects[user_id] = "math"
        await callback.message.answer("🧮 Режим математики включен!", reply_markup=get_keyboard())
        await callback.answer()

    elif callback.data == "mode_language":
        user_subjects[user_id] = "language"
        await callback.message.answer("🗣️ Режим английского языка включен!", reply_markup=get_keyboard())
        await callback.answer()

    elif callback.data == "mode_general":
        user_subjects[user_id] = None
        await callback.message.answer("✨ Общий режим включен!", reply_markup=get_keyboard())
        await callback.answer()

    elif callback.data == "show_limit":
        total_remaining = key_manager.get_total_remaining()
        await callback.answer(f"Осталось всего {total_remaining} запросов", show_alert=True)


# ==================== ОСНОВНАЯ ОБРАБОТКА ====================
async def process_message(
        message: types.Message,
        text: str,
        image_bytes: bytes = None,
        mime_type: str = None
):
    if not text and not image_bytes:
        await message.answer("Отправь текст или фото с заданием.", reply_markup=get_keyboard())
        return

    user_id = message.from_user.id
    subject = user_subjects.get(user_id)

    # Проверяем учебный вопрос
    if subject is None and text and not is_educational(text):
        await message.answer(
            "📚 Я отвечаю только на учебные вопросы.\n\n"
            "Я могу помочь с:\n"
            "🧮 Математикой\n"
            "⚡ Физикой\n"
            "🗣️ Английским языком",
            reply_markup=get_keyboard()
        )
        return

    user_last_question[user_id] = (text or "", subject, image_bytes, mime_type)
    processing_msg = await message.answer("🤔 Решаю...")

    try:
        response, used = await ask_gemini(
            user_message=text or "",
            image_data=image_bytes,
            mime_type=mime_type,
            subject=subject,
        )

        await processing_msg.delete()

        for part in split_text(clean_text(response)):
            await message.answer(part, reply_markup=get_keyboard())

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await processing_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")


@dp.message(F.text)
async def handle_text(message: types.Message):
    await process_message(message, message.text, None, None)


@dp.message(F.photo)
async def handle_photo(message: types.Message):
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_bytes = await bot.download_file(file.file_path)
    await process_message(message, message.caption or "Реши задачу с фото", file_bytes.read(), "image/jpeg")


@dp.message(F.document)
async def handle_document(message: types.Message):
    doc = message.document
    if doc.file_name:
        ext = doc.file_name.split('.')[-1].lower()
        if ext not in ['jpg', 'jpeg', 'png', 'txt', 'pdf']:
            await message.answer("Поддерживаются только изображения и текстовые файлы.")
            return
    file = await bot.get_file(doc.file_id)
    file_bytes = await bot.download_file(file.file_path)
    await process_message(message, message.caption or "Проанализируй документ", file_bytes.read(), doc.mime_type)


# ==================== ЗАПУСК ====================
async def main():
    logger.info(f"Бот запускается с {len(key_manager.keys)} API ключами")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())