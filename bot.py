"""
AI ANUAR Assistant — Telegram Bot
6 автономных ИИ-агентов на Google Gemini (бесплатно)
"""

import os
import json
import logging
import httpx
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("LawOffice")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
SHEETS_WEBHOOK = os.environ.get("SHEETS_WEBHOOK", "")

AGENTS = {
    "lexpost": {
        "name": "LexPost", "emoji": "✍️", "role": "Контент-менеджер",
        "desc": "Посты для LinkedIn по теме или новости",
        "system": "Ты — LexPost, контент-менеджер для Anuar Aitmurzin (LL.M. Competition Law, Астана). Пиши профессиональные посты для LinkedIn на русском. Структура: крючок → суть → анализ → вывод → хэштеги. 300-500 слов.",
        "examples": ["Пост о штрафе Apple за DMA", "Пост об антимонопольном Kaspi", "Пост о Цифровом кодексе РК"]
    },
    "lexmonitor": {
        "name": "LexMonitor", "emoji": "📡", "role": "Аналитик НПА",
        "desc": "Изменения законодательства КЗ/ЕС/ЕАЭС",
        "system": "Ты — LexMonitor, аналитик законодательства для Anuar Aitmurzin. Анализируй: Закон о конкуренции РК, Цифровой кодекс РК, ЕАЭС, EU DMA/DSA. Формат: ЧТО → КОГО → ПОСЛЕДСТВИЯ → РИСКИ → РЕКОМЕНДАЦИЯ.",
        "examples": ["Что нового в Цифровом кодексе?", "Последние изменения DMA 2026", "АЗРК и маркетплейсы"]
    },
    "lexstrategy": {
        "name": "LexStrategy", "emoji": "🎯", "role": "Бизнес-советник",
        "desc": "Стратегия развития практики и новые ниши",
        "system": "Ты — LexStrategy, стратег для Anuar Aitmurzin (конкурентное право, Астана). Предлагай идеи развития практики. Структура: Идея → Почему сейчас → Клиенты → 3 шага.",
        "examples": ["Ниши Цифрового кодекса для юристов", "Как привлечь tech-клиентов?", "Практика в ЕАЭС"]
    },
    "lexdocs": {
        "name": "LexDocs", "emoji": "📋", "role": "Документовед",
        "desc": "Шаблоны документов по праву РК",
        "system": "Ты — LexDocs, помощник по документам для Anuar Aitmurzin (конкурентное право, КЗ). Создавай шаблоны: жалобы в АЗРК, договоры, заключения. Ссылайся на нормы РК. Помечай [ЗАПОЛНИТЬ].",
        "examples": ["Жалоба в АЗРК на доминирование", "Договор на консалтинг", "Заключение по Цифровому кодексу"]
    },
    "lexbrief": {
        "name": "LexBrief", "emoji": "☀️", "role": "Утренний брифинг",
        "desc": "Дайджест новостей и план дня",
        "system": "Ты — LexBrief, утренний помощник Anuar Aitmurzin. Создавай брифинг: ТОП-3 новости права → Идея поста LinkedIn → Правовой инсайт дня → 1 приоритет на сегодня.",
        "examples": ["Утренний брифинг на сегодня", "Дайджест конкурентного права", "EU Competition за неделю"]
    },
    "lextask": {
        "name": "LexTask", "emoji": "📌", "role": "Менеджер задач",
        "desc": "Голос или текст → задача в Google Sheets",
        "system": """Ты — LexTask, менеджер задач для Anuar Aitmurzin. 
Твоя задача: извлечь из текста поручения структурированную задачу.

Ответь ТОЛЬКО в формате JSON (без markdown, без пояснений):
{
  "task": "чёткое описание задачи",
  "assignee": "имя исполнителя или 'Не указан'",
  "deadline": "срок в формате ДД.ММ.ГГГГ или 'Не указан'",
  "status": "Новая",
  "clarification": "вопрос если чего-то не хватает, иначе null"
}

Если исполнитель или срок не указаны явно — ставь 'Не указан' и задай уточняющий вопрос в поле clarification.""",
        "examples": ["Иванову подготовить ответ на запрос АЗРК до пятницы", "Алие проверить договор с Kaspi до 15 июня", "Напомни созвониться с клиентом завтра"]
    },
}

STATE_FILE = Path("state.json")

def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: return {}
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

async def ask_gemini(system, history, user_msg):
    contents = []
    for msg in history[-16:]:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_msg}]})
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 1500, "temperature": 0.7}
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(GEMINI_URL, json=payload)
            data = r.json()
            if "candidates" in data:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            elif "error" in data:
                return f"⚠️ Ошибка: {data['error'].get('message','')}"
            return "⚠️ Нет ответа"
    except Exception as e:
        return f"⚠️ Ошибка: {e}"

async def ask_agent(agent_id, uid, message):
    agent = AGENTS[agent_id]
    usr = get_user(uid)
    history = usr["history"].get(agent_id, [])
    system = agent["system"]
    mem = usr.get("memory", {})
    if mem:
        system += "\n\nКонтекст: " + "; ".join([f"{k}: {v}" for k,v in mem.items()])
    reply = await ask_gemini(system, history, message)
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    if len(history) > 30: history = history[-30:]
    usr["history"][agent_id] = history
    set_user(uid, usr)
    return reply

async def transcribe_voice(file_path: str) -> str:
    """Распознавание голоса через Groq Whisper"""
    if not GROQ_API_KEY:
        return "⚠️ GROQ_API_KEY не настроен"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            with open(file_path, "rb") as f:
                r = await client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    files={"file": ("voice.ogg", f, "audio/ogg")},
                    data={"model": "whisper-large-v3", "language": "ru"}
                )
            data = r.json()
            return data.get("text", "⚠️ Не удалось распознать")
    except Exception as e:
        return f"⚠️ Ошибка распознавания: {e}"

async def save_to_sheets(task_data: dict) -> bool:
    """Отправка задачи в Google Sheets через Apps Script"""
    if not SHEETS_WEBHOOK:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(SHEETS_WEBHOOK, json=task_data)
            result = r.json()
            return result.get("status") == "ok"
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        return False

# Keyboards
def main_kb():
    rows = [
        [InlineKeyboardButton("✍️ LexPost", callback_data="a:lexpost"),
         InlineKeyboardButton("📡 LexMonitor", callback_data="a:lexmonitor")],
        [InlineKeyboardButton("🎯 LexStrategy", callback_data="a:lexstrategy"),
         InlineKeyboardButton("📋 LexDocs", callback_data="a:lexdocs")],
        [InlineKeyboardButton("☀️ LexBrief", callback_data="a:lexbrief"),
         InlineKeyboardButton("📌 LexTask", callback_data="a:lextask")],
        [InlineKeyboardButton("🧠 Память", callback_data="memory"),
         InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
    ]
    return InlineKeyboardMarkup(rows)

def agent_kb(aid):
    rows = [
        [InlineKeyboardButton(f"↗ {AGENTS[aid]['examples'][i][:40]}", callback_data=f"e:{aid}:{i}")]
        for i in range(len(AGENTS[aid]["examples"]))
    ]
    rows.append([
        InlineKeyboardButton("🗑 Очистить", callback_data=f"c:{aid}"),
        InlineKeyboardButton("◀️ Меню", callback_data="back"),
    ])
    return InlineKeyboardMarkup(rows)

def settings_kb(uid):
    usr = get_user(uid)
    s = "✅ Вкл" if usr.get("schedule", True) else "❌ Выкл"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"☀️ Авто-брифинг: {s}", callback_data="toggle")],
        [InlineKeyboardButton("🗑 Очистить историю", callback_data="clearall")],
        [InlineKeyboardButton("◀️ Меню", callback_data="back")],
    ])

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "Коллега"
    text = (f"👋 Привет, *{name}*! Добро пожаловать в *AI ANUAR Assistant*\n\n"
            "✍️ *LexPost* — посты для LinkedIn\n"
            "📡 *LexMonitor* — анализ законодательства\n"
            "🎯 *LexStrategy* — стратегия практики\n"
            "📋 *LexDocs* — шаблоны документов\n"
            "☀️ *LexBrief* — утренний дайджест\n"
            "📌 *LexTask* — голос/текст → задача в таблице\n\n"
            "☀️ Автобрифинг каждый день в *08:00*")
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_kb())

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    d = q.data
    usr = get_user(uid)
    try: await q.answer()
    except: pass
    logger.info(f"Button: {d}")

    if d.startswith("a:"):
        aid = d[2:]
        usr["agent"] = aid
        set_user(uid, usr)
        ag = AGENTS[aid]
        if aid == "lextask":
            text = (f"{ag['emoji']} *{ag['name']}* — {ag['role']}\n\n"
                    f"{ag['desc']}\n\n"
                    "🎤 Отправьте *голосовое сообщение* или напишите поручение текстом.\n\n"
                    "Пример: _«Алие проверить договор с Kaspi до 15 июня»_")
        else:
            text = f"{ag['emoji']} *{ag['name']}* — {ag['role']}\n\n{ag['desc']}\n\nНапишите запрос или выберите пример:"
        try: await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb(aid))
        except Exception as e:
            logger.error(f"edit error: {e}")
            await ctx.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb(aid))

    elif d.startswith("e:"):
        parts = d.split(":")
        aid, idx = parts[1], int(parts[2])
        example = AGENTS[aid]["examples"][idx]
        usr["agent"] = aid
        set_user(uid, usr)
        try: await q.edit_message_text(f"⏳ Обрабатываю...\n_{example}_", parse_mode=ParseMode.MARKDOWN)
        except: pass
        if aid == "lextask":
            await process_lextask(ctx.bot, uid, example, q)
        else:
            reply = await ask_agent(aid, uid, example)
            text = f"{AGENTS[aid]['emoji']} *{AGENTS[aid]['name']}*\n\n{reply}"
            if len(text) > 4096: text = text[:4090] + "..."
            try: await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb(aid))
            except: await ctx.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb(aid))

    elif d.startswith("c:"):
        aid = d[2:]
        usr["history"][aid] = []
        set_user(uid, usr)
        try: await q.edit_message_text(f"🗑 История {AGENTS[aid]['name']} очищена", reply_markup=agent_kb(aid))
        except: await ctx.bot.send_message(uid, "🗑 История очищена")

    elif d == "clearall":
        usr["history"] = {}
        set_user(uid, usr)
        try: await q.edit_message_text("🗑 Вся история очищена", reply_markup=settings_kb(uid))
        except: await ctx.bot.send_message(uid, "🗑 Очищено")

    elif d == "settings":
        try: await q.edit_message_text("⚙️ *Настройки*", parse_mode=ParseMode.MARKDOWN, reply_markup=settings_kb(uid))
        except: await ctx.bot.send_message(uid, "⚙️ Настройки", reply_markup=settings_kb(uid))

    elif d == "toggle":
        usr["schedule"] = not usr.get("schedule", True)
        set_user(uid, usr)
        s = "включён ✅" if usr["schedule"] else "выключен ❌"
        try: await q.edit_message_text(f"☀️ Автобрифинг {s}", reply_markup=settings_kb(uid))
        except: await ctx.bot.send_message(uid, f"☀️ {s}")

    elif d == "memory":
        mem = usr.get("memory", {})
        text = "🧠 *Память агентов*\n\nКоманда: `/mem ключ: значение`\n\n"
        text += "\n".join([f"• *{k}:* {v}" for k,v in mem.items()]) if mem else "_Пусто_"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back")]])
        try: await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        except: await ctx.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

    elif d == "back":
        usr["agent"] = None
        set_user(uid, usr)
        text = "🏛 *AI ANUAR Assistant*\n\nВыберите агента:"
        try: await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_kb())
        except: await ctx.bot.send_message(uid, text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_kb())

async def process_lextask(bot, uid, text, q=None):
    """Обработка поручения через LexTask"""
    reply_raw = await ask_agent("lextask", uid, text)
    try:
        # Очищаем от markdown если есть
        clean = reply_raw.strip().strip("```json").strip("```").strip()
        task_data = json.loads(clean)
    except Exception:
        msg = f"📌 *LexTask*\n\n⚠️ Не удалось разобрать поручение. Попробуйте переформулировать.\n\n_{reply_raw[:300]}_"
        await bot.send_message(uid, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb("lextask"))
        return

    clarification = task_data.get("clarification")

    if clarification:
        msg = (f"📌 *LexTask*\n\n"
               f"Понял поручение, но нужно уточнить:\n\n"
               f"❓ *{clarification}*\n\n"
               f"Что уже извлёк:\n"
               f"• Задача: {task_data.get('task','—')}\n"
               f"• Исполнитель: {task_data.get('assignee','—')}\n"
               f"• Срок: {task_data.get('deadline','—')}")
        await bot.send_message(uid, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb("lextask"))
    else:
        task_data["date"] = datetime.now().strftime("%d.%m.%Y")
        task_data["source"] = "Telegram"
        saved = await save_to_sheets(task_data)
        sheets_status = "✅ Сохранено в таблицу" if saved else "⚠️ Таблица не настроена"
        msg = (f"📌 *LexTask — задача создана*\n\n"
               f"📝 *Задача:* {task_data.get('task','—')}\n"
               f"👤 *Исполнитель:* {task_data.get('assignee','—')}\n"
               f"📅 *Срок:* {task_data.get('deadline','—')}\n"
               f"📊 {sheets_status}")
        await bot.send_message(uid, msg, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb("lextask"))

async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка голосовых сообщений"""
    uid = update.effective_user.id
    usr = get_user(uid)
    aid = usr.get("agent")

    if aid != "lextask":
        await update.message.reply_text(
            "🎤 Голосовые сообщения поддерживает только *LexTask*.\n\nПерейдите в 📌 LexTask и отправьте голосовое.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=main_kb())
        return

    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    status_msg = await update.message.reply_text("🎤 Распознаю речь...")

    voice = update.message.voice
    file = await ctx.bot.get_file(voice.file_id)
    file_path = f"/tmp/voice_{uid}.ogg"
    await file.download_to_drive(file_path)

    transcribed = await transcribe_voice(file_path)

    try: os.remove(file_path)
    except: pass

    if transcribed.startswith("⚠️"):
        await status_msg.edit_text(transcribed)
        return

    await status_msg.edit_text(f"🎤 Распознано: _{transcribed}_\n\n⏳ Создаю задачу...", parse_mode=ParseMode.MARKDOWN)
    await process_lextask(ctx.bot, uid, transcribed)

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    usr = get_user(uid)
    text = update.message.text
    aid = usr.get("agent")
    if not aid:
        await update.message.reply_text("Выберите агента:", reply_markup=main_kb())
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    if aid == "lextask":
        await process_lextask(ctx.bot, uid, text)
    else:
        reply = await ask_agent(aid, uid, text)
        ag = AGENTS[aid]
        header = f"{ag['emoji']} *{ag['name']}*\n\n"
        full = header + reply
        if len(full) <= 4096:
            await update.message.reply_text(full, parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb(aid))
        else:
            chunks = [reply[i:i+3800] for i in range(0, len(reply), 3800)]
            for i, chunk in enumerate(chunks):
                kb = agent_kb(aid) if i == len(chunks)-1 else None
                h = header if i == 0 else f"{ag['emoji']} ({i+1}/{len(chunks)})\n\n"
                await update.message.reply_text(h + chunk, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

async def cmd_brief(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user(uid)["agent"] = "lexbrief"; set_user(uid, get_user(uid))
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    reply = await ask_agent("lexbrief", uid, f"Утренний брифинг на {datetime.now().strftime('%d.%m.%Y')}")
    await update.message.reply_text(f"☀️ *LexBrief*\n\n{reply}", parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb("lexbrief"))

async def cmd_post(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user(uid)["agent"] = "lexpost"; set_user(uid, get_user(uid))
    topic = " ".join(ctx.args) if ctx.args else ""
    if topic:
        await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
        reply = await ask_agent("lexpost", uid, topic)
        await update.message.reply_text(f"✍️ *LexPost*\n\n{reply}", parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb("lexpost"))
    else:
        await update.message.reply_text("✍️ Напишите тему поста:", parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb("lexpost"))

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
        "📖 *Команды*\n\n/start — меню\n/brief — брифинг\n/post тема — пост\n/mem ключ: значение — память\n/help — справка\n\n📌 *LexTask*: отправь голосовое или текст поручения",
        parse_mode=ParseMode.MARKDOWN, reply_markup=main_kb())

async def daily_brief(app):
    today = datetime.now().strftime("%d.%m.%Y")
    for uid_str, usr in list(state.items()):
        if not usr.get("schedule", True): continue
        try:
            reply = await ask_agent("lexbrief", int(uid_str), f"Утренний брифинг на {today}")
            await app.bot.send_message(int(uid_str), f"☀️ *LexBrief — {today}*\n\n{reply}",
                parse_mode=ParseMode.MARKDOWN, reply_markup=agent_kb("lexbrief"))
        except Exception as e:
            logger.error(f"Brief error {uid_str}: {e}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(CommandHandler("post", cmd_post))
    app.add_handler(CommandHandler("mem", cmd_mem))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    scheduler = AsyncIOScheduler(timezone="Asia/Almaty")
    scheduler.add_job(daily_brief, "cron", hour=8, minute=0, args=[app])
    scheduler.start()
    logger.info("✅ AI ANUAR Assistant запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
