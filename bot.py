"""
AI ANUAR Assistant — Telegram Bot
5 автономных ИИ-агентов на Google Gemini (бесплатно)
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import httpx

# ─── Logging ───────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("LawOffice")

# ─── Config ────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL     = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

# ─── Agents ────────────────────────────────────────────────────────
AGENTS = {
    "lexpost": {
        "name": "✍️ LexPost",
        "role": "Контент-менеджер",
        "emoji": "✍️",
        "system": """Ты — LexPost, ИИ-контент-менеджер для Anuar Aitmurzin (LL.M. in Competition Law, Астана, Казахстан).
Специализация: конкурентное право, цифровые рынки, EU DMA, Цифровой кодекс РК, АЗРК.
Пиши профессиональные живые посты для LinkedIn на русском языке.
Структура: 🔥 крючок → суть → экспертный анализ → вывод → хэштеги.
Длина 300-500 слов. Умеренно используй эмодзи. Заканчивай вопросом к аудитории.""",
        "desc": "Посты для LinkedIn по теме или новости",
        "examples": [
            "Пост о штрафе Apple за DMA",
            "Пост об антимонопольном расследовании Kaspi",
            "Пост о Цифровом кодексе РК для бизнеса",
        ]
    },
    "lexmonitor": {
        "name": "📡 LexMonitor",
        "role": "Аналитик НПА",
        "emoji": "📡",
        "system": """Ты — LexMonitor, аналитик законодательства для Anuar Aitmurzin (конкурентное право, Казахстан).
Анализируй: Закон о конкуренции РК, Цифровой кодекс РК (09.01.2026, вступает 09.07.2026), ЕАЭС, EU DMA/DSA.
Формат: ЧТО изменилось → КОГО затрагивает → ПРАКТИЧЕСКИЕ последствия → РИСКИ → РЕКОМЕНДАЦИЯ.
Ссылайся на конкретные статьи и даты. Кратко и по делу.""",
        "desc": "Изменения законодательства КЗ/ЕС/ЕАЭС",
        "examples": [
            "Что нового в Цифровом кодексе для платформ?",
            "Последние изменения DMA 2026",
            "Как АЗРК регулирует маркетплейсы?",
        ]
    },
    "lexstrategy": {
        "name": "🎯 LexStrategy",
        "role": "Бизнес-советник",
        "emoji": "🎯",
        "system": """Ты — LexStrategy, стратегический советник для Anuar Aitmurzin (конкурентное право, LL.M., Астана).
Специализация: антимонопольное право, цифровые рынки, DMA-комплаенс, ИИ-право.
Предлагай конкретные идеи развития практики с планом действий.
Структура: 💡 Идея → Почему сейчас → Целевые клиенты → Первые 3 шага.""",
        "desc": "Стратегия развития практики и новые ниши",
        "examples": [
            "Какие ниши открывает Цифровой кодекс для юристов?",
            "Как привлечь tech-клиентов в Астане?",
            "Идеи для развития практики в ЕАЭС",
        ]
    },
    "lexdocs": {
        "name": "📋 LexDocs",
        "role": "Документовед",
        "emoji": "📋",
        "system": """Ты — LexDocs, помощник по документам для Anuar Aitmurzin (конкурентное право, Казахстан).
Создавай шаблоны по казахстанскому праву: жалобы в АЗРК, договоры, заключения, письма.
Используй структуру казахстанских юридических документов.
Ссылайся на нормы: Закон о конкуренции РК, Цифровой кодекс РК, ГК РК.
Помечай [ЗАПОЛНИТЬ] для данных клиента. В конце: список «Что заполнить перед подачей».""",
        "desc": "Шаблоны документов по праву РК",
        "examples": [
            "Жалоба в АЗРК на злоупотребление доминированием",
            "Договор на юридический консалтинг",
            "Правовое заключение по Цифровому кодексу",
        ]
    },
    "lexbrief": {
        "name": "☀️ LexBrief",
        "role": "Утренний брифинг",
        "emoji": "☀️",
        "system": """Ты — LexBrief, утренний помощник Anuar Aitmurzin (конкурентное право, Астана).
Создавай чёткий брифинг на 2 минуты чтения:
📰 ТОП-3 новости (конкурентное право КЗ/ЕС/ЕАЭС, цифровые рынки, ИИ-право)
💡 Идея поста для LinkedIn — конкретная тема + почему актуально сегодня
⚖️ Правовой инсайт дня — факт, прецедент или важная норма
🎯 1 приоритет для практики на сегодня
Будь конкретным, актуальным, мотивирующим.""",
        "desc": "Дайджест новостей и план дня",
        "examples": [
            "Утренний брифинг на сегодня",
            "Дайджест конкурентного права за неделю",
            "Что важного в EU Competition на этой неделе?",
        ]
    },
}

# ─── State ─────────────────────────────────────────────────────────
STATE_FILE = Path("state.json")

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            return {}
    return {}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2))

state = load_state()

def get_user(uid):
    k = str(uid)
    if k not in state:
        state[k] = {"agent": None, "history": {}, "memory": {}, "schedule": True}
    return state[k]

def set_user(uid, data):
    state[str(uid)] = data
    save_state(state)

# ─── Gemini API call ───────────────────────────────────────────────
async def ask_gemini(system: str, history: list, user_msg: str) -> str:
    """Вызов Google Gemini API"""
    # Собираем contents из истории
    contents = []
    for msg in history[-16:]:  # последние 8 пар
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_msg}]})

    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": 1500,
            "temperature": 0.7,
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(GEMINI_URL, json=payload)
            data = r.json()
            if "candidates" in data:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            elif "error" in data:
                logger.error(f"Gemini error: {data['error']}")
                return f"⚠️ Ошибка API: {data['error'].get('message', 'неизвестная ошибка')}"
            return "⚠️ Не удалось получить ответ"
    except Exception as e:
        logger.error(f"Request error: {e}")
        return f"⚠️ Ошибка соединения: {e}"

async def ask_agent(agent_id: str, uid: int, message: str) -> str:
    agent = AGENTS[agent_id]
    usr = get_user(uid)
    history = usr["history"].get(agent_id, [])

    # Добавляем контекст из памяти в систему
    mem = usr.get("memory", {})
    system = agent["system"]
    if mem:
        mem_str = "\n".join([f"- {k}: {v}" for k, v in mem.items()])
        system += f"\n\nКонтекст о пользователе:\n{mem_str}"

    reply = await ask_gemini(system, history, message)

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    if len(history) > 30:
        history = history[-30:]

    usr["history"][agent_id] = history
    set_user(uid, usr)
    return reply

# ─── Keyboards ─────────────────────────────────────────────────────
def main_kb():
    rows = []
    items = list(AGENTS.items())
    for i in range(0, len(items), 2):
        row = []
        for aid, ag in items[i:i+2]:
            row.append(InlineKeyboardButton(ag["name"], callback_data=f"agent:{aid}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("🧠 Память", callback_data="memory"),
        InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
    ])
    return InlineKeyboardMarkup(rows)

def agent_kb(agent_id):
    agent = AGENTS[agent_id]
    rows = [[InlineKeyboardButton(f"↗ {ex[:38]}", callback_data=f"ex:{agent_id}:{ex}")] for ex in agent["examples"]]
    rows.append([
        InlineKeyboardButton("🗑 Очистить", callback_data=f"clear:{agent_id}"),
        InlineKeyboardButton("◀️ Меню", callback_data="back"),
    ])
    return InlineKeyboardMarkup(rows)

def settings_kb(uid):
    usr = get_user(uid)
    s = "✅ Вкл" if usr.get("schedule", True) else "❌ Выкл"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"☀️ Авто-брифинг 8:00: {s}", callback_data="toggle")],
        [InlineKeyboardButton("🗑 Очистить всю историю", callback_data="clear_all")],
        [InlineKeyboardButton("◀️ Меню", callback_data="back")],
    ])

# ─── Handlers ──────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "Коллега"
    text = (
        f"👋 Привет, *{name}*! Добро пожаловать в *AI ANUAR Assistant*\n\n"
        "Ваши автономные ИИ-агенты:\n\n"
        "✍️ *LexPost* — посты для LinkedIn\n"
        "📡 *LexMonitor* — анализ законодательства\n"
        "🎯 *LexStrategy* — стратегия практики\n"
        "📋 *LexDocs* — шаблоны документов\n"
        "☀️ *LexBrief* — утренний дайджест\n\n"
        "☀️ Автобрифинг каждый день в *08:00*\n"
        "Команды: /brief /post /help"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_kb())

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    d = q.data
    usr = get_user(uid)

    # Отвечаем немедленно чтобы убрать часики у кнопки
    try:
        await q.answer()
    except Exception:
        pass

    if d.startswith("agent:"):
        aid = d.split(":")[1]
        ag = AGENTS[aid]
        usr["agent"] = aid
        set_user(uid, usr)
        hist = len(usr["history"].get(aid, []))
        text = (
            f"{ag['emoji']} *{ag['name']}*\n_{ag['role']}_\n\n"
            f"{ag['desc']}\n\n"
            f"{'📚 История: ' + str(hist//2) + ' сообщ.' if hist else '🆕 Новый диалог'}\n\n"
            "Напишите запрос или выберите пример:"
        )
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb(aid))
        except Exception:
            await ctx.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb(aid))

    elif d.startswith("ex:"):
        _, aid, example = d.split(":", 2)
        usr["agent"] = aid
        set_user(uid, usr)
        try:
            await q.edit_message_text(f"⏳ {AGENTS[aid]['emoji']} Обрабатываю...", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
        reply = await ask_agent(aid, uid, example)
        text = f"{AGENTS[aid]['emoji']} *{AGENTS[aid]['name']}*\n\n{reply}"
        if len(text) > 4096:
            text = text[:4090] + "..."
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb(aid))
        except Exception:
            await ctx.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb(aid))

    elif d.startswith("clear:"):
        aid = d.split(":")[1]
        usr["history"][aid] = []
        set_user(uid, usr)
        try:
            await q.edit_message_text(f"🗑 История {AGENTS[aid]['name']} очищена", reply_markup=agent_kb(aid))
        except Exception:
            await ctx.bot.send_message(uid, f"🗑 История очищена")

    elif d == "clear_all":
        usr["history"] = {}
        set_user(uid, usr)
        try:
            await q.edit_message_text("🗑 Вся история очищена", reply_markup=settings_kb(uid))
        except Exception:
            await ctx.bot.send_message(uid, "🗑 Вся история очищена")

    elif d == "settings":
        try:
            await q.edit_message_text("⚙️ *Настройки*", parse_mode=ParseMode.MARKDOWN, reply_markup=settings_kb(uid))
        except Exception:
            await ctx.bot.send_message(uid, "⚙️ Настройки", reply_markup=settings_kb(uid))

    elif d == "toggle":
        usr["schedule"] = not usr.get("schedule", True)
        set_user(uid, usr)
        s = "включён ✅" if usr["schedule"] else "выключен ❌"
        try:
            await q.edit_message_text(f"☀️ Автобрифинг {s}", reply_markup=settings_kb(uid))
        except Exception:
            await ctx.bot.send_message(uid, f"☀️ Автобрифинг {s}")

    elif d == "memory":
        mem = usr.get("memory", {})
        text = (
            "🧠 *Память агентов*\n\n"
            "Сохраните контекст командой:\n"
            "`/mem ключ: значение`\n\n"
            "*Примеры:*\n"
            "`/mem практики: антимонопольное право, DMA`\n"
            "`/mem стиль: экспертный с личным мнением`\n"
            "`/mem цели: привлечь tech-клиентов`\n\n"
            "*Текущая память:*\n"
        )
        if mem:
            for k, v in mem.items():
                text += f"• *{k}:* {v}\n"
        else:
            text += "_Пусто_"
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back")]]))
        except Exception:
            await ctx.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back")]]))

    elif d == "back":
        usr["agent"] = None
        set_user(uid, usr)
        try:
            await q.edit_message_text(
                "🏛 *AI ANUAR Assistant*\n\nВыберите агента:",
                parse_mode=ParseMode.MARKDOWN, reply_markup=main_kb()
            )
        except Exception:
            await ctx.bot.send_message(uid, "🏛 Выберите агента:", reply_markup=main_kb())

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    usr = get_user(uid)
    text = update.message.text
    aid = usr.get("agent")

    if not aid:
        await update.message.reply_text("Выберите агента:", reply_markup=main_kb())
        return

    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    reply = await ask_agent(aid, uid, text)
    ag = AGENTS[aid]

    # Разбиваем длинные ответы
    header = f"{ag['emoji']} *{ag['name']}*\n\n"
    full = header + reply
    if len(full) <= 4096:
        await update.message.reply_text(full, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb(aid))
    else:
        chunks = [reply[i:i+3800] for i in range(0, len(reply), 3800)]
        for i, chunk in enumerate(chunks):
            kb = agent_kb(aid) if i == len(chunks)-1 else None
            h = header if i == 0 else f"{ag['emoji']} *{ag['name']}* ({i+1}/{len(chunks)})\n\n"
            await update.message.reply_text(h + chunk, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

# ─── Commands ──────────────────────────────────────────────────────
async def cmd_brief(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    usr = get_user(uid)
    usr["agent"] = "lexbrief"
    set_user(uid, usr)
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    reply = await ask_agent("lexbrief", uid, f"Сделай утренний брифинг на {datetime.now().strftime('%d.%m.%Y')}")
    await update.message.reply_text(
        f"☀️ *LexBrief — {datetime.now().strftime('%d.%m.%Y')}*\n\n{reply}",
        parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb("lexbrief")
    )

async def cmd_post(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    usr = get_user(uid)
    usr["agent"] = "lexpost"
    set_user(uid, usr)
    topic = " ".join(ctx.args) if ctx.args else ""
    if topic:
        await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
        reply = await ask_agent("lexpost", uid, topic)
        await update.message.reply_text(
            f"✍️ *LexPost*\n\n{reply}",
            parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb("lexpost")
        )
    else:
        await update.message.reply_text(
            "✍️ *LexPost* активирован\n\nНапишите тему или выберите пример:",
            parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb("lexpost")
        )

async def cmd_mem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    usr = get_user(uid)
    text = update.message.text.replace("/mem", "").strip()
    if ":" in text:
        k, _, v = text.partition(":")
        usr.setdefault("memory", {})[k.strip()] = v.strip()
        set_user(uid, usr)
        await update.message.reply_text(f"🧠 Сохранено: *{k.strip()}*", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Пример: `/mem практики: антимонопольное право`", parse_mode=ParseMode.MARKDOWN)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Команды AI ANUAR Assistant*\n\n"
        "/start — главное меню\n"
        "/brief — утренний брифинг\n"
        "/post [тема] — написать пост\n"
        "/mem ключ: значение — память агентов\n"
        "/help — эта справка",
        parse_mode=ParseMode.MARKDOWN, reply_markup=main_kb()
    )

# ─── Scheduler ─────────────────────────────────────────────────────
async def daily_brief(app):
    logger.info("⏰ Daily brief sending...")
    today = datetime.now().strftime("%d.%m.%Y")
    for uid_str, usr in list(state.items()):
        if not usr.get("schedule", True):
            continue
        try:
            reply = await ask_agent("lexbrief", int(uid_str), f"Утренний брифинг на {today}")
            await app.bot.send_message(
                int(uid_str),
                f"☀️ *Доброе утро! LexBrief — {today}*\n\n{reply}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=agent_kb("lexbrief")
            )
        except Exception as e:
            logger.error(f"Brief error {uid_str}: {e}")

# ─── Run ───────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("post", cmd_post))
    app.add_handler(CommandHandler("mem", cmd_mem))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    # Авто-брифинг в 08:00 по Астане (UTC+5)
    scheduler = AsyncIOScheduler(timezone="Asia/Almaty")
    scheduler.add_job(daily_brief, "cron", hour=8, minute=0, args=[app])
    scheduler.start()

    logger.info("✅ AI ANUAR Assistant запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
