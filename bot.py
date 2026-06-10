import os
import logging
import httpx
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CLOUDRU_API_KEY = os.environ["CLOUDRU_API_KEY"]

HOME = "ул. Декабристов 10к3, Москва (метро Отрадное, Серпуховско-Тимирязевская линия)"
WORK = "метро Улица 1905 года, Москва"

CHOOSING_START = 1
CHOOSING_MOOD = 2
CHOOSING_ROUTE_DURATION = 3

user_start = {}

def get_season() -> str:
    month = datetime.now().month
    if month in (12, 1, 2):
        return "зима"
    elif month in (3, 4, 5):
        return "весна"
    elif month in (6, 7, 8):
        return "лето"
    else:
        return "осень"

def get_season_context() -> str:
    season = get_season()
    month = datetime.now().month
    contexts = {
        "лето": "Сейчас лето. Приоритет: парки, веранды, фонтаны, набережные, уличные кафе, пешеходные зоны. Избегай душных закрытых помещений если погода хорошая.",
        "зима": "Сейчас зима. Приоритет: тёплые уютные места, катки, новогодние/зимние украшения улиц, музеи, крытые пространства. Упоминай если место особенно красиво зимой.",
        "весна": "Сейчас весна. Приоритет: парки где расцветают деревья, открытые веранды, первые уличные мероприятия, набережные.",
        "осень": "Сейчас осень. Приоритет: парки с золотой листвой, уютные кофейни, тёплые атмосферные места, музеи.",
    }
    return contexts[season]

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
                }
            )
            data = resp.json()
            daily = data["daily"]
            codes = {0:"☀️ ясно",1:"🌤 почти ясно",2:"⛅ переменная облачность",3:"☁️ пасмурно",
                     45:"🌫 туман",48:"🌫 туман",51:"🌦 морось",53:"🌦 морось",55:"🌦 морось",
                     61:"🌧 дождь",63:"🌧 дождь",65:"🌧 сильный дождь",71:"🌨 снег",73:"🌨 снег",
                     80:"🌧 ливень",81:"🌧 ливень",82:"⛈ сильный ливень",95:"⛈ гроза"}
            days_ru = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
            result = "🌤 Погода на неделю:\n"
            for i in range(7):
                date = datetime.strptime(daily["time"][i], "%Y-%m-%d")
                dow = days_ru[date.weekday()]
                tmax = round(daily["temperature_2m_max"][i])
                tmin = round(daily["temperature_2m_min"][i])
                rain = daily["precipitation_sum"][i]
                code = daily["weathercode"][i]
                weather = codes.get(code, "⛅ переменно")
                rain_str = f", осадки {rain}мм" if rain > 1 else ""
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
                "model": "deepseek-ai/DeepSeek-V3",
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

SYSTEM_PROMPT = """Ты — помощник по досугу в Москве и Подмосковье. Тебя зовут «Выходной бот».

СТРОГИЕ ПРАВИЛА:
1. Предлагай РОВНО 3 варианта.
2. У пользователя НЕТ автомобиля — только метро, МЦК, электрички, автобусы, трамваи.
3. Пиши живым человеческим языком, без канцелярита.
4. Адрес локации — ОБЯЗАТЕЛЬНО для каждого места. Если не уверен на 100% — лучше пропусти, но старайся указывать.
5. Маршрут — ТОЛЬКО финальная часть: до какой станции метро ехать, какой конкретный выход (например "выход №3"), сколько минут пешком. НЕ пиши откуда пользователь садится — это он уже знает.
6. НЕ пиши банальных советов про зонт и одежду.
7. Учитывай погоду: если дождь — предлагай крытые или частично крытые места.
8. Учитывай сезон при выборе мест.
9. Для каждой локации добавляй ссылку на Яндекс.Карты в формате: [Посмотреть на карте](https://yandex.ru/maps/?text=НАЗВАНИЕ+АДРЕС+Москва) — вставляй реальное название и адрес в ссылку.

ФОРМАТ каждого варианта:
🗺 **Название**
📍 Адрес: [точный адрес]
[2-3 живых предложения об атмосфере и что там делать]
🚇 Метро [станция], [выход] → [N] мин пешком
🗺 [Посмотреть на карте](ссылка)"""

ROUTE_SYSTEM_PROMPT = """Ты — помощник по пешеходным маршрутам в Москве. Тебя зовут «Выходной бот».

СТРОГИЕ ПРАВИЛА:
1. Предлагай РОВНО 2-3 маршрута подходящих под указанное время.
2. У пользователя НЕТ автомобиля.
3. Пиши живым языком, без канцелярита.
4. Маршрут — конкретные улицы, бульвары, переулки по порядку. Не абстрактно.
5. НЕ пиши откуда пользователь стартует — он это знает. Сразу пиши куда ехать и откуда начинать идти пешком.
6. Для маршрутов после работы: можно предложить доехать на метро до 15 минут, указывай только станцию назначения и выход — без упоминания стартовой станции.
7. Учитывай сезон и погоду.
8. Для маршрутов на полдня и целый день — добавляй 2-3 места выпить кофе или поесть по пути (адрес + ссылка на Яндекс.Карты).
9. Для маршрутов после работы — только прогулка, без заведений.
10. Заведения — ТОЛЬКО среднего ценового уровня: Double B, Скуратов, Surf Coffee, Крем Сода и подобные. НИКОГДА не предлагай: Кофеманию, Starbucks, Coffee Bean, премиум-рестораны. Только заведения с рейтингом 4.5+ на картах.
11. Для маршрутов на целый день — можно предлагать ближнее Подмосковье: парки, нацпарки, тропы здоровья, пешеходные маршруты на природе.
12. Ссылки на Яндекс.Карты: [название](https://yandex.ru/maps/?text=НАЗВАНИЕ+Москва)"""

MOOD_PROMPTS = {
    "walk": "пешая прогулка по красивым местам Москвы",
    "cafe": "уютная кофейня не из сетевых, с атмосферой — для чтения или отдыха",
    "book": "тихое атмосферное место с книгой — парк, библиотека или книжный магазин",
    "outside": "ближнее Подмосковье, добраться только на электричке или автобусе",
    "surprise": "необычное место которое обычный москвич не знает",
}

ROUTE_PROMPTS = {
    "route_short": "маршрут после работы на 1-2 часа — стартуем с м. Улица 1905 года, можно доехать на метро до 15 минут и гулять пешком. Только прогулка по красивым улицам или бульварам, без заведений",
    "route_half": "маршрут на полдня (3-4 часа) — пешеходный маршрут по интересным местам + 2-3 кофейни по пути. Приоритет: Double B, Скуратов, Surf Coffee и подобные среднего уровня с высоким рейтингом. Никакой Кофемании и Starbucks.",
    "route_full": "маршрут на целый день — можно предложить Москву или ближнее Подмосковье (парки, нацпарки, тропы здоровья). Пешеходный маршрут + несколько мест поесть. Только кафе среднего уровня (Double B, Скуратов, Surf Coffee и подобные) с высоким рейтингом.",
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
        [InlineKeyboardButton("🏠 Из дома (м. Отрадное)", callback_data="start_home")],
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
        [InlineKeyboardButton("🚶 Маршруты", callback_data="mood_routes")],
        [InlineKeyboardButton("📍 Сменить точку старта", callback_data="restart")],
    ])

def route_duration_keyboard(from_work: bool = False):
    buttons = []
    if from_work:
        buttons.append([InlineKeyboardButton("🌆 После работы (1-2 часа)", callback_data="route_short")])
    else:
        buttons.append([InlineKeyboardButton("🌅 Полдня (3-4 часа)", callback_data="route_half")])
        buttons.append([InlineKeyboardButton("🌞 Целый день", callback_data="route_full")])
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_mood")])
    return InlineKeyboardMarkup(buttons)

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
        await query.edit_message_text("Стартуем от дома 🏠\n\nЧто хочешь сегодня?", reply_markup=mood_keyboard())
        return CHOOSING_MOOD
    elif query.data == "start_work":
        user_start[uid] = WORK
        await query.edit_message_text("Стартуем с работы 💼\n\nЧто хочешь сегодня?", reply_markup=mood_keyboard())
        return CHOOSING_MOOD
    elif query.data == "start_custom":
        await query.edit_message_text("Напиши свой адрес или станцию метро:")
        return CHOOSING_START

async def handle_custom_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    user_start[uid] = update.message.text
    await update.message.reply_text(
        f"Стартуем от: {update.message.text}\n\nЧто хочешь сегодня?",
        reply_markup=mood_keyboard()
    )
    return CHOOSING_MOOD

async def handle_mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data == "mood_routes":
        from_work = user_start.get(uid, HOME) == WORK
        await query.edit_message_text("На сколько времени маршрут?", reply_markup=route_duration_keyboard(from_work=from_work))
        return CHOOSING_ROUTE_DURATION

    if query.data == "back_to_mood":
        await query.edit_message_text("Что хочешь сегодня?", reply_markup=mood_keyboard())
        return CHOOSING_MOOD

    mood_key = query.data.replace("mood_", "")
    start_point = user_start.get(uid, HOME)

    await query.edit_message_text("🔍 Ищу варианты...")

    weather = await get_weather()
    season_context = get_season_context()
    mood_desc = MOOD_PROMPTS.get(mood_key, "интересный досуг")

    prompt = f"""Найди 3 варианта для: {mood_desc}
Стартовая точка пользователя: {start_point}
{season_context}
{weather}
Учти погоду и сезон. В маршруте пиши только финальную часть — станцию метро, выход, минуты пешком."""

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
        reply_markup=mood_keyboard()
    )
    return CHOOSING_MOOD

async def handle_route_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data == "back_to_mood":
        await query.edit_message_text("Что хочешь сегодня?", reply_markup=mood_keyboard())
        return CHOOSING_MOOD

    start_point = user_start.get(uid, HOME)
    await query.edit_message_text("🔍 Строю маршрут...")

    weather = await get_weather()
    season_context = get_season_context()
    route_desc = ROUTE_PROMPTS.get(query.data, "пешеходный маршрут")

    prompt = f"""Предложи {route_desc}
Стартовая точка пользователя: {start_point}
{season_context}
{weather}
Учти погоду и сезон. Маршрут должен быть конкретным — улицы, бульвары, переулки по порядку."""

    try:
        response_text = await ask_ai(prompt, ROUTE_SYSTEM_PROMPT)
        if not response_text:
            response_text = "Что-то пошло не так 😔 Попробуй ещё раз."
    except Exception as e:
        logger.error(f"AI error: {e}")
        response_text = "Что-то пошло не так 😔 Попробуй ещё раз."

    await query.edit_message_text(
        response_text,
        parse_mode="Markdown",
        reply_markup=mood_keyboard()
    )
    return CHOOSING_MOOD

async def handle_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Откуда стартуем?", reply_markup=start_keyboard())
    return CHOOSING_START

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("До встречи! Напиши /start когда захочешь 👋")
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
            CHOOSING_ROUTE_DURATION: [
                CallbackQueryHandler(handle_route_duration, pattern="^route_"),
                CallbackQueryHandler(handle_route_duration, pattern="^back_to_mood$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    logger.info("Выходной бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
