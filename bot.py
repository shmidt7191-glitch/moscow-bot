import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import anthropic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Ты агент по подбору досуга в Москве и ближнем Подмосковье.

Пользователь любит: пешие прогулки, уютные кофейни, атмосферные места где можно почитать книгу.
У пользователя нет автомобиля — только метро, электрички и автобусы.

Твоя задача: предложить ровно 3 варианта досуга. Не больше — чтобы было легко выбрать.

Формат каждого варианта:
🗺 *Название места*
Короткое описание (2-3 предложения): атмосфера, что делать, почему интересно именно сейчас
🚇 Как добраться без машины
💡 Один практичный совет

Варианты должны быть разными по характеру. Будь конкретным: реальные места, реальные маршруты.
Если пользователь просит Подмосковье — предлагай только то, куда можно доехать на электричке или автобусе.
Учитывай текущий сезон (лето, июнь).
"""

def make_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🌿 Прогулка в Москве", callback_data="walk_moscow"),
            InlineKeyboardButton("☕ Кофейня", callback_data="cafe"),
        ],
        [
            InlineKeyboardButton("📚 Почитать книгу", callback_data="book"),
            InlineKeyboardButton("🚂 Подмосковье", callback_data="outside"),
        ],
        [
            InlineKeyboardButton("✨ Удиви меня!", callback_data="surprise"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

MOOD_PROMPTS = {
    "walk_moscow": "Предложи 3 варианта для пешей прогулки в Москве. Парки, интересные районы, набережные — что-то живописное и приятное в июне.",
    "cafe": "Предложи 3 уютных кофейни в Москве с атмосферой — чтобы посидеть, выпить хороший кофе, может быть почитать. Не сетевые, а камерные места.",
    "book": "Предложи 3 атмосферных места где приятно провести время с книгой — библиотеки, тихие парки, уютные кафе или антикварные книжные.",
    "outside": "Предложи 3 варианта в ближнем Подмосковье — только то, куда можно добраться на электричке или автобусе без машины. Что-то красивое и интересное летом.",
    "surprise": "Предложи 3 неожиданных варианта досуга — что-то чего обычный москвич может не знать. Смешай разные форматы: может быть прогулка + кофейня, или необычное место в Подмосковье.",
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! 👋\n\nЯ помогу найти, куда сходить в Москве и Подмосковье.\nВыбери настроение — предложу 3 варианта без машины.",
        reply_markup=make_keyboard(),
    )

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_prompt = MOOD_PROMPTS.get(query.data, "Предложи 3 интересных варианта досуга.")

    await query.edit_message_text("🔍 Ищу варианты...")

    try:
        message = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        response_text = message.content[0].text
    except Exception as e:
        logger.error(f"Anthropic error: {e}")
        response_text = "Что-то пошло не так 😔 Попробуй ещё раз."

    await query.edit_message_text(
        response_text,
        parse_mode="Markdown",
        reply_markup=make_keyboard(),
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    await update.message.reply_text("🔍 Ищу варианты...")

    try:
        message = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_text}],
        )
        response_text = message.content[0].text
    except Exception as e:
        logger.error(f"Anthropic error: {e}")
        response_text = "Что-то пошло не так 😔 Попробуй ещё раз."

    await update.message.reply_text(
        response_text,
        parse_mode="Markdown",
        reply_markup=make_keyboard(),
    )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    from telegram.ext import MessageHandler, filters
    main()
