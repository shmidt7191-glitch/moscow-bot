import os
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

SYSTEM_PROMPT = """Ты агент по подбору досуга в Москве и ближнем Подмосковье.

Пользователь любит: пешие прогулки, уютные кофейни, атмосферные места где можно почитать книгу.
У пользователя нет автомобиля — только метро, электрички и автобусы.

Твоя задача: предложить ровно 3 варианта досуга. Не больше — чтобы было легко выбрать.

Формат каждого варианта:
🗺 Название места
Короткое описание (2-3 предложения): атмосфера, что делать, почему интересно именно сейчас
🚇 Как добраться без машины
💡 Один практичный совет

Варианты должны быть разными по характеру. Будь конкретным: реальные места, реальные маршруты.
Если пользователь просит Подмосковье — предлагай только то, куда можно доехать на электричке или автобусе.
Учитывай текущий сезон (лето, июнь)."""

MOOD_PROMPTS = {
    "walk_moscow": "Предложи 3 варианта для пешей прогулки в Москве. Парки, интересные районы, набережные — что-то живописное и приятное в июне.",
    "cafe": "Предложи 3 уютных кофейни в Москве с атмосферой — чтобы посидеть, выпить хороший кофе, может быть почитать. Не сетевые, а камерные места.",
    "book": "Предложи 3 атмосферных места где приятно провести время с книгой — библиотеки, тихие парки, уютные кафе или антикварные книжные.",
    "outside": "Предложи 3 варианта в ближнем Подмосковье — только то, куда можно добраться на электричке или автобусе без машины. Что-то красивое и интересное летом.",
    "surprise": "Предложи 3 неожиданных варианта досуга — что-то чего обычный москвич может не знать. Смешай разные форматы.",
}

async def ask_ai(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "mistralai/mistral-7b-instruct:free",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            }
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"]

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
        response_text = await ask_ai(user_prompt)
    except Exception as e:
        logger.error(f"AI error: {e}")
        response_text = "Что-то пошло не так 😔 Попробуй ещё раз."
    await query.edit_message_text(response_text, reply_markup=make_keyboard())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    await update.message.reply_text("🔍 Ищу варианты...")
    try:
        response_text = await ask_ai(user_text)
    except Exception as e:
        logger.error(f"AI error: {e}")
        response_text = "Что-то пошло не так 😔 Попробуй ещё раз."
    await update.message.reply_text(response_text, reply_markup=make_keyboard())

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
