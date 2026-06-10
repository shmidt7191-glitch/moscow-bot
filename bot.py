import os
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CLOUDRU_API_KEY = os.environ["CLOUDRU_API_KEY"]

HOME = "ул. Декабристов 10к3, Москва"
WORK = "метро Улица 1905 года, Москва"

CHOOSING_START = 1
CHOOSING_MOOD = 2

user_start = {}

async def get_weather() -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": 55.7558,
                    "longitude": 37.6173,
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                    "timezone": "Europe/Moscow",
                    "forecast_days": 7,
                    "language": "ru"
                }
            )
            data = resp.json()
            daily = data["daily"]
            codes = {0:"ясно",1:"почти ясно",2:"переменная облачность",3:"пасмурно",
                     45:"туман",48:"туман",51:"морось",53:"морось",55:"морось",
                     61:"дождь",63:"дождь",65:"сильный дождь",71:"снег",73:"снег",
                     75:"сильный снег",80:"ливень",81:"ливень",82:"сильный ливень",
                     95:"гроза",96:"гроза с градом",99:"гроза с градом"}
            days_ru = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
            result = "🌤 Погода в Москве на неделю:\n"
            from datetime import datetime
            for i in range(7):
                date = datetime.strptime(daily["time"][i], "%Y-%m-%d")
                dow = days_ru[date.weekday()]
                tmax = round(daily["temperature_2m_max"][i])
                tmin = round(daily["temperature_2m_min"][i])
                rain = daily["precipitation_sum"][i]
                code = daily["weathercode"][i]
                weather = codes.get(code, "переменно")
                rain_str = f", дождь {rain}мм" if rain > 1 else ""
                result += f"{dow} {date.strftime('%d.%m')}: {tmin}..+{tmax}°, {weather}{rain_str}\n"
            return result
    except Exception as e:
        logger.error(f"Weather error: {e}")
        return ""

async def ask_ai(prompt: str, system: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://foundation-models.api.cloud.ru/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {CLOUDRU_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "ai-sage/GigaChat3-10B-A1.8B",
                "max_tokens": 1500,
                "temperature": 0.7,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            }
        )
        data = resp.json()
        logger.info(f"Cloud.ru status: {resp.status_code}")
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        else:
            logger.error(f"Unexpected: {data}")
            return None

SYSTEM_PROMPT = """Ты — дружелюбный помощник по досугу в Москве и Подмосковье. Тебя зовут «Выходной бот».

ВАЖНЫЕ ПРАВИЛА:
- Пиши живым, человечным языком. Никакого канцелярита и AI-мусора.
- Предлагай РОВНО 3 варианта, не больше.
- У пользователя НЕТ автомобиля — только метро, МЦК, электрички, автобусы, трамваи.
- Никогда не предлагай варианты с личным авто или такси как основной транспорт.
- Для каждого места указывай ТОЧНЫЙ адрес.
- Маршрут от стартовой точки — конкретный: какое метро, какой выход, сколько минут пешком.
- Учитывай погоду при рекомендациях (если дождь — предлагай крытые места).
- Пиши кратко и по делу. Каждый вариант — максимум 5-6 строк.

ФОРМАТ каждого варианта:
🗺 **Название** — Точный адрес
Описание (2-3 живых предложения)
🚇 Маршрут от [стартовая точка]: конкретные детали
💡 Совет"""

MOOD_PROMPTS = {
    "walk": "пешая прогулка по красивым местам Москвы",
    "cafe": "уютная кофейня с атмосферой, не сетевая, для чтения книги или отдыха",
    "book": "место где приятно читать книгу — тихий парк, библиотека, антикварный книжный",
    "outside": "ближнее Подмосковье, только на электричке или автобусе",
    "surprise": "что-то необычное, чего обычный москвич может не знать",
}

MOOD_LABELS = {
    "walk": "🌿 Прогулка",
    "cafe": "☕ Кофейня",
    "book": "📚 Почитать",
    "outside": "🚂 Подмосковье",
    "surprise": "✨ Удиви меня!",
}

def start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Из дома (ул. Декабристов)", callback_data="start_home")],
        [InlineKeyboardButton("💼 С работы (м. Улица 1905 года)", callback_data="start_work")],
        [InlineKeyboardButton("📍 Другой адрес", callback_data="start_custom")],
    ])

def mood_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(MOOD_LABELS["walk"], callback_data="mood_walk"),
         InlineKeyboardButton(MOOD_LABELS["cafe"], callback_data="mood_cafe")],
        [InlineKeyboardButton(MOOD_LABELS["book"], callback_data="mood_book"),
         InlineKeyboardButton(MOOD_LABELS["outside"], callback_data="mood_outside")],
        [InlineKeyboardButton(MOOD_LABELS["surprise"], callback_data="mood_surprise")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я *Выходной бот* 🎉\nПомогу найти куда сходить в Москве и Подмосковье.\n\nОткуда стартуем?",
        parse_mode="Markdown",
        reply_markup=start_keyboard(),
    )
    return CHOOSING_START

async def handle_start_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data == "start_home":
        user_start[uid] = HOME
        await query.edit_message_text(
            f"Стартуем от дома 🏠\n\nЧто хочешь сегодня?",
            reply_markup=mood_keyboard()
        )
        return CHOOSING_MOOD
    elif query.data == "start_work":
        user_start[uid] = WORK
        await query.edit_message_text(
            f"Стартуем с работы 💼\n\nЧто хочешь сегодня?",
            reply_markup=mood_keyboard()
        )
        return CHOOSING_MOOD
    elif query.data == "start_custom":
        await query.edit_message_text("Напиши свой адрес или станцию метро:")
        return CHOOSING_START

async def handle_custom_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    user_start[uid] = update.message.text
    await update.message.reply_text(
        f"Отлично, стартуем от: {update.message.text}\n\nЧто хочешь сегодня?",
        reply_markup=mood_keyboard()
    )
    return CHOOSING_MOOD

async def handle_mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    mood_key = query.data.replace("mood_", "")
    start_point = user_start.get(uid, HOME)

    await query.edit_message_text("🔍 Ищу варианты...")

    weather = await get_weather()
    mood_desc = MOOD_PROMPTS.get(mood_key, "интересный досуг")

    prompt = f"""Найди 3 варианта для: {mood_desc}
Стартовая точка пользователя: {start_point}
{weather}
Учти погоду при выборе мест. Пиши маршрут именно от указанной стартовой точки."""

    try:
        response_text = await ask_ai(prompt, SYSTEM_PROMPT)
        if not response_text:
            response_text = "Что-то пошло не так 😔 Попробуй ещё раз."
    except Exception as e:
        logger.error(f"AI error: {e}")
        response_text = "Что-то пошло не так 😔 Попробуй ещё раз."

    await query.edit_message_text(
        response_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Ещё варианты", callback_data=f"mood_{mood_key}")],
            [InlineKeyboardButton("🏠 Сменить точку старта", callback_data="restart")],
        ])
    )
    return CHOOSING_MOOD

async def handle_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Откуда стартуем?",
        reply_markup=start_keyboard()
    )
    return CHOOSING_START

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("До встречи! Напиши /start когда захочешь найти куда сходить 👋")
    return ConversationHandler.END

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_START: [
                CallbackQueryHandler(handle_start_point, pattern="^start_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_address),
            ],
            CHOOSING_MOOD: [
                CallbackQueryHandler(handle_mood, pattern="^mood_"),
                CallbackQueryHandler(handle_restart, pattern="^restart$"),
                CallbackQueryHandler(handle_start_point, pattern="^start_"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    logger.info("Выходной бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
