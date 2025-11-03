# -*- coding: utf-8 -*-
# Kind Energy v9.3 — DeepSeek Edition (финальная оптимизация, фикс прогресса, тестовый режим)

import json, asyncio, random, datetime as dt
from pathlib import Path
import httpx
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# === CONFIG ===
try:
    import config
    TELEGRAM_TOKEN = config.TELEGRAM_TOKEN
    DEEPSEEK_API_KEY = getattr(config, "DEEPSEEK_API_KEY", "")
    USE_AI = getattr(config, "USE_AI", True)
    TEST_MODE = getattr(config, "TEST_MODE", False)  # True = ускоренный тестовый режим
except Exception:
    TELEGRAM_TOKEN = "PASTE_TELEGRAM_TOKEN"
    DEEPSEEK_API_KEY = "PASTE_DEEPSEEK_KEY"
    USE_AI = True
    TEST_MODE = False

# === TIMEZONE ===
try:
    from zoneinfo import ZoneInfo
    MOSCOW_TZ = ZoneInfo("Europe/Moscow")
except Exception:
    MOSCOW_TZ = dt.timezone(dt.timedelta(hours=3))

# === STORAGE ===
DATA_PATH = Path("users.json")
def load_db():
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except:
            return {}
    return {}
def save_db(db):
    DATA_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")

DB = load_db()

def ensure_user(uid: str) -> dict:
    u = DB.get(uid) or {}
    defaults = {
        "gender": None, "profile": {}, "focus": None,
        "day": 1, "completed": False,
        "progress": {"sleep":0,"nutrition":0,"energy":0,"mindfulness":0},
        "awaiting": None, "last_morning_answer": "",
        "streak_count": 0, "last_interaction_date": None,
        "nudges_enabled": True, "menu_state": "main"
    }
    for k,v in defaults.items():
        u.setdefault(k, v)
    DB[uid] = u
    save_db(DB)
    return u

# === LABELS / CONTENT ===
FOCUS_LABELS = {
    "sleep": "сон и пробуждение",
    "nutrition": "осознанное питание",
    "energy": "движение и тело",
    "mindfulness": "внимание и дыхание",
}

QUOTES = [
    "🌿 Ты не обязана сиять. Иногда важно просто быть.",
    "💫 Твоё «достаточно» — достаточно.",
    "☁️ Тишина внутри порой громче побед.",
    "🌸 Сохраняй мягкость — даже когда день жёсткий.",
    "🔔 Нежность к себе — тоже дисциплина.",
]
PAUSES = [
    "🫁 Вдохни на 4, выдохни на 6. Два раза. Тишина между — тоже забота.",
    "💧 Налей воды и сделай один осознанный глоток.",
    "👣 Почувствуй опору под стопами 10 секунд. Просто побудь тут.",
]
TIPS = {
    "sleep": [
        "🌙 За 30 минут до сна приглуши свет, экраны — на паузу.",
        "🌙 Дыхание лёжа: вдох 4 — выдох 6, две минуты.",
    ],
    "nutrition": [
        "🥗 Стакан воды до кофе — простое «спасибо» телу.",
        "🥗 Первые пять укусов — медленно.",
    ],
    "energy": [
        "⚡️ 2 минуты: круг плечами, расправь грудь.",
        "⚡️ Пройди 300 шагов без телефона.",
    ],
    "mindfulness": [
        "🧘 Заметь 3 вещи, за которые можно сказать «спасибо».",
        "🧘 Ощути поверхность под стопами и вес тела.",
    ],
}
NUDGES = [
    "💭 Вдохни глубже. Даже 10 секунд меняют ритм.",
    "🌿 Помни: ты не на марафоне. Можно идти медленно.",
    "💧 Иногда забота — это просто допить воду.",
]
REWARD_TEXT = {
    3: "🔥 Три дня — дисциплина уже растёт.",
    5: "🌿 Пять дней внимания — тело запоминает мягкость.",
    7: "🕊 Неделя — красиво. Хочешь бонусную практику? Напиши: «бонус».",
}

# === KEYBOARDS ===
def kb_main():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🪷 Сегодня"), KeyboardButton("💚 Прогресс")],
            [KeyboardButton("🎯 Фокус"), KeyboardButton("🌿 Практики")],
            [KeyboardButton("⚙️ Управление")]
        ],
        resize_keyboard=True
    )

def kb_practices():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("☕ Пауза"), KeyboardButton("💌 Цитата")],
            [KeyboardButton("🧭 Рекомендация дня")],
            [KeyboardButton("🏠 В меню")]
        ],
        resize_keyboard=True
    )

def kb_manage():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔁 Сменить фокус"), KeyboardButton("🆕 Начать заново")],
            [KeyboardButton("🔔 Нотификации вкл/выкл")],
            [KeyboardButton("🏠 В меню")]
        ],
        resize_keyboard=True
    )

def kb_focus_select():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🌙 Сон"), KeyboardButton("🥗 Питание")],
            [KeyboardButton("⚡️ Энергия"), KeyboardButton("🧘 Осознанность")],
            [KeyboardButton("🏠 В меню")]
        ],
        resize_keyboard=True
    )

EMOJI_MOOD_KB = ReplyKeyboardMarkup(
    [[KeyboardButton("😌"), KeyboardButton("🙂"), KeyboardButton("😣")]],
    resize_keyboard=True
)

def kb_gender():
    return ReplyKeyboardMarkup([[KeyboardButton("👩 Женщина"), KeyboardButton("👨 Мужчина")]], resize_keyboard=True)

# === AI via DeepSeek ===
async def deepseek_chat(messages: list) -> str:
    if not USE_AI or not DEEPSEEK_API_KEY:
        return random.choice([
            "Слышу тебя. Береги себя сегодня.",
            "Иногда одно признание уже облегчает.",
        ])
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "deepseek-chat", "messages": messages, "temperature": 0.7, "max_tokens": 256}
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return random.choice([
            "Сделай вдох. Иногда лучшее — дать себе минуту тишины.",
            "Я рядом. Давай бережно к себе сегодня.",
        ])

async def ai_analysis(feeling_text: str, focus_key: str, profile: dict) -> str:
    system = {"role": "system", "content": "Пиши как живой человек: коротко, тепло, без клише."}
    user = {"role": "user", "content":
        f"Ответ: «{feeling_text}». Фокус: {FOCUS_LABELS.get(focus_key,'')}. "
        f"Анкета: {profile}. Дай 2–4 предложения мягкой обратной связи и маленькую рекомендацию."}
    return await deepseek_chat([system, user])

# === HELPERS ===
def ring(v: int) -> str:
    v = max(0, min(v, 10))
    return "🟩" * v + "⬜" * (10 - v) + f" ({v}/10)"

def auto_recommend(p: dict) -> str:
    s = (p.get("sleep") or "").lower()
    e = (p.get("energy") or "").lower()
    a = (p.get("attitude") or "").lower()
    if "сложно" in s or "просыпаюсь" in s:
        return "sleep"
    if "устал" in e:
        return "energy"
    if "редко" in a:
        return "mindfulness"
    return "nutrition"

async def show_progress(update: Update, u: dict):
    p = u["progress"]
    if not any(p.values()):
        await update.message.reply_text(
            "🌿 Пока всё только начинается — выбери фокус:",
            reply_markup=kb_focus_select()
        )
        return
    msg = (
        "💚 Прогресс Kind Energy\n\n"
        f"🌙 Сон — {ring(p['sleep'])}\n"
        f"🥗 Питание — {ring(p['nutrition'])}\n"
        f"⚡️ Энергия — {ring(p['energy'])}\n"
        f"🧘 Осознанность — {ring(p['mindfulness'])}\n\n"
        f"🔥 Streak: {u.get('streak_count',0)} дней подряд"
    )
    await update.message.reply_text(msg, reply_markup=kb_main())

async def show_today(update: Update, u: dict):
    if not u.get("focus"):
        await update.message.reply_text("🌿 Сначала выбери фокус:", reply_markup=kb_focus_select()); return
    now = dt.datetime.now(MOSCOW_TZ).time()
    if now < dt.time(8,0): s = "⏳ Утро ещё не началось (08:00). Возвращаю в меню."
    elif now < dt.time(14,0): s = "✅ Утро прошло. Встретимся днём (14:00)."
    elif now < dt.time(20,30): s = "✅ День прошёл. Встретимся вечером (20:30)."
    else: s = "🌙 День завершается. Завтра начнём заново в 08:00."
    await update.message.reply_text(
        f"🪷 Сегодня — день {u['day']} · фокус: {FOCUS_LABELS[u['focus']]}\n{s}",
        reply_markup=kb_main()
    )

# === JOB TEXTS ===
def text_morning(u): return f"Сегодня не нужно быть идеальной — достаточно быть живой.\nФокус: {FOCUS_LABELS[u['focus']]}\n\n💭 С чем ты просыпаешься?"
def text_day(u): return f"{random.choice(TIPS[u['focus']])}\n\nЕсли попробуешь — напиши пару слов."
def text_evening(u): return random.choice([
    "Что сегодня поддержало тебя?",
    "Где была одна маленькая победа?",
    "Что хочется отпустить до утра?"
])

# === JOBS ===
async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    uid = str(context.job.data["uid"]); chat_id = context.job.data["chat_id"]
    u = ensure_user(uid)
    if not u.get("focus") or u.get("completed"): return
    u["awaiting"] = "morning"; save_db(DB)
    await context.bot.send_message(chat_id, f"🌅 День {u['day']}\n\n{text_morning(u)}", reply_markup=EMOJI_MOOD_KB)

async def midday_job(context: ContextTypes.DEFAULT_TYPE):
    uid = str(context.job.data["uid"]); chat_id = context.job.data["chat_id"]
    u = ensure_user(uid)
    if not u.get("focus"): return
    await context.bot.send_message(chat_id, f"☀️ Дневная практика\n{text_day(u)}", reply_markup=ReplyKeyboardRemove())

async def evening_job(context: ContextTypes.DEFAULT_TYPE):
    uid = str(context.job.data["uid"]); chat_id = context.job.data["chat_id"]
    u = ensure_user(uid)
    if not u.get("focus"): return

    await context.bot.send_message(chat_id, f"🌙 Вечер\n{text_evening(u)}", reply_markup=ReplyKeyboardRemove())

    # прогресс — только если день реально прошёл
    if not u.get("completed"):
        f = u.get("focus")
        if f and u["day"] >= 1:
            u["progress"][f] = min(u["progress"][f] + 1, 10)

    # streak
    today = dt.datetime.now(MOSCOW_TZ).date()
    last = u.get("last_interaction_date")
    if last:
        last_d = dt.date.fromisoformat(last)
        u["streak_count"] = u["streak_count"] + 1 if (today - last_d).days == 1 else 1
    else:
        u["streak_count"] = 1
    u["last_interaction_date"] = today.isoformat()

    # награды
    if u["streak_count"] in REWARD_TEXT:
        await context.bot.send_message(chat_id, REWARD_TEXT[u["streak_count"]])

    # переход дня
    if u["day"] < 3:
        u["day"] += 1
        u["awaiting"] = None
        u["last_morning_answer"] = ""
    else:
        u["completed"] = True
        await context.bot.send_message(
            chat_id,
            "🎉 3-дневный цикл завершён. Хочешь продолжить — напиши «хочу продолжить».",
            reply_markup=kb_main()
        )
    save_db(DB)

async def nudge_job(context: ContextTypes.DEFAULT_TYPE):
    uid = str(context.job.data["uid"]); chat_id = context.job.data["chat_id"]
    u = ensure_user(uid)
    if not u.get("focus") or not u.get("nudges_enabled"): return
    now = dt.datetime.now(MOSCOW_TZ).time()
    if 10 <= now.hour <= 19 and random.random() < 0.25:
        await context.bot.send_message(chat_id, random.choice(NUDGES))

async def schedule_all(app, chat_id: int, uid: str):
    # очистить старые
    for name in (f"{uid}-morning", f"{uid}-day", f"{uid}-evening", f"{uid}-nudge"):
        for j in app.job_queue.get_jobs_by_name(name):
            j.schedule_removal()
    # поставить новые
    if TEST_MODE:
        app.job_queue.run_repeating(morning_job, interval=30, first=3,  name=f"{uid}-morning", data={"chat_id":chat_id,"uid":uid})
        app.job_queue.run_repeating(midday_job,  interval=60, first=15, name=f"{uid}-day",     data={"chat_id":chat_id,"uid":uid})
        app.job_queue.run_repeating(evening_job, interval=90, first=30, name=f"{uid}-evening", data={"chat_id":chat_id,"uid":uid})
    else:
        app.job_queue.run_daily(morning_job, time=dt.time(8,0,tzinfo=MOSCOW_TZ),   name=f"{uid}-morning", data={"chat_id":chat_id,"uid":uid})
        app.job_queue.run_daily(midday_job,  time=dt.time(14,0,tzinfo=MOSCOW_TZ),  name=f"{uid}-day",     data={"chat_id":chat_id,"uid":uid})
        app.job_queue.run_daily(evening_job, time=dt.time(20,30,tzinfo=MOSCOW_TZ), name=f"{uid}-evening", data={"chat_id":chat_id,"uid":uid})
    app.job_queue.run_repeating(nudge_job, interval=3600, first=180, name=f"{uid}-nudge", data={"chat_id":chat_id,"uid":uid})

# === START / HANDLERS ===
WELCOME = (
    "Kind Energy — твой тёплый спутник заботы о себе 💚\n\n"
    "Ритм дня (мск): 08:00 / 14:00 / 20:30.\n"
    "Направления: 🌙 сон · 🥗 питание · ⚡️ энергия · 🧘 осознанность.\n\n"
    "Сначала пару вопросов, чтобы почувствовать тебя."
)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    ensure_user(uid)
    await update.message.reply_text(WELCOME, reply_markup=ReplyKeyboardMarkup(
        [[KeyboardButton("👩 Женщина"), KeyboardButton("👨 Мужчина")]], resize_keyboard=True
    ))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    u = ensure_user(uid)
    txt = (update.message.text or "").strip()

    # выбор пола
    if txt in ["👩 Женщина", "👨 Мужчина"]:
        u["gender"] = "female" if "Женщина" in txt else "male"
        u["awaiting"] = "q1"; save_db(DB)
        kb = ReplyKeyboardMarkup([["Сплю хорошо"],["Сложно заснуть"],["Часто просыпаюсь"]], resize_keyboard=True)
        await update.message.reply_text("🛌 Как ты обычно спишь?", reply_markup=kb)
        return

    # анкета
    if u["awaiting"] == "q1":
        u["profile"]["sleep"] = txt; u["awaiting"] = "q2"; save_db(DB)
        kb = ReplyKeyboardMarkup([["Стабильно"],["Иногда падает"],["Почти всегда усталость"]], resize_keyboard=True)
        await update.message.reply_text("⚡️ Как с энергией днём?", reply_markup=kb)
        return
    if u["awaiting"] == "q2":
        u["profile"]["energy"] = txt; u["awaiting"] = "q3"; save_db(DB)
        kb = ReplyKeyboardMarkup([["Забочусь о себе"],["Мог(ла) бы внимательнее"],["Редко думаю об этом"]], resize_keyboard=True)
        await update.message.reply_text("🍀 Как сейчас относишься к себе?", reply_markup=kb)
        return
    if u["awaiting"] == "q3":
        u["profile"]["attitude"] = txt; u["awaiting"] = None; save_db(DB)
        rec = auto_recommend(u["profile"])
        rec_btn = {"sleep":"🌙 Сон","nutrition":"🥗 Питание","energy":"⚡️ Энергия","mindfulness":"🧘 Осознанность"}[rec]
        await update.message.reply_text(
            f"Мой взгляд: начать лучше с «{FOCUS_LABELS[rec]}». Нажми {rec_btn}, или выбери свой вариант ниже.",
            reply_markup=kb_focus_select()
        )
        return

    # навигация меню
    if txt == "🏠 В меню":
        await update.message.reply_text("Главное меню:", reply_markup=kb_main()); return
    if txt == "🌿 Практики":
        await update.message.reply_text("Практики:", reply_markup=kb_practices()); return
    if txt == "⚙️ Управление":
        await update.message.reply_text("Управление:", reply_markup=kb_manage()); return
    if txt == "🎯 Фокус":
        await update.message.reply_text("Выбери направление:", reply_markup=kb_focus_select()); return

    # выбор фокуса
    if txt in ["🌙 Сон","🥗 Питание","⚡️ Энергия","🧘 Осознанность"]:
        m = {"🌙 Сон":"sleep","🥗 Питание":"nutrition","⚡️ Энергия":"energy","🧘 Осознанность":"mindfulness"}
        u["focus"] = m[txt]; u["day"] = 1; u["completed"] = False
        save_db(DB)
        await update.message.reply_text(
            "🕰 Стартуем завтра в 08:00 (мск). Днём — короткая практика, вечером — тихий выдох.",
            reply_markup=kb_main()
        )
        await schedule_all(context.application, update.effective_chat.id, uid)
        return

    # сервисные кнопки
    if txt == "🪷 Сегодня":
        await show_today(update, u); return
    if txt == "💚 Прогресс":
        await show_progress(update, u); return

    # практики
    if txt == "☕ Пауза":
        await update.message.reply_text(random.choice(PAUSES), reply_markup=kb_practices()); return
    if txt == "💌 Цитата":
        await update.message.reply_text(random.choice(QUOTES), reply_markup=kb_practices()); return
    if txt == "🧭 Рекомендация дня":
        if not u.get("focus"):
            await update.message.reply_text("Сначала выбери фокус 🌿", reply_markup=kb_focus_select()); return
        await update.message.reply_text("🧭 Рекомендация: " + random.choice(TIPS[u["focus"]]), reply_markup=kb_practices()); return

    # управление
    if txt == "🔁 Сменить фокус":
        u["focus"] = None; u["completed"] = False; save_db(DB)
        await update.message.reply_text("Выбери новое направление:", reply_markup=kb_focus_select()); return
    if txt == "🆕 Начать заново":
        DB[uid] = {
            "gender": None, "profile": {}, "focus": None, "day": 1, "completed": False,
            "progress": {"sleep":0,"nutrition":0,"energy":0,"mindfulness":0},
            "awaiting": None, "last_morning_answer": "", "streak_count": 0, "last_interaction_date": None,
            "nudges_enabled": True, "menu_state":"main"
        }
        save_db(DB)
        await update.message.reply_text("Начнём с нуля. Скажи немного о себе:", reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("👩 Женщина"), KeyboardButton("👨 Мужчина")]], resize_keyboard=True
        ))
        return
    if txt == "🔔 Нотификации вкл/выкл":
        u["nudges_enabled"] = not u.get("nudges_enabled", True); save_db(DB)
        state = "включены 🔔" if u["nudges_enabled"] else "выключены 🔕"
        await update.message.reply_text(f"Нотификации {state}.", reply_markup=kb_manage()); return

    # утренний личный ответ (персональный фидбек + AI)
    if u.get("awaiting") == "morning":
        u["last_morning_answer"] = txt
        u["awaiting"] = None
        # streak отметка
        today = dt.datetime.now(MOSCOW_TZ).date()
        last = u.get("last_interaction_date")
        if last:
            last_d = dt.date.fromisoformat(last)
            u["streak_count"] = u["streak_count"] + 1 if (today - last_d).days == 1 else 1
        else:
            u["streak_count"] = 1
        u["last_interaction_date"] = today.isoformat()
        save_db(DB)

        fb = await ai_analysis(txt, u.get("focus"), u.get("profile", {}))
        await update.message.reply_text(fb)
        await asyncio.sleep(6)
        await update.message.reply_text("Если хочешь — загляни в меню 🌿", reply_markup=kb_main())
        return

    # свободные сообщения — короткая тёплая реакция
    if u.get("focus"):
        resp = await deepseek_chat([
            {"role": "system", "content": "Отвечай как спокойный живой человек, коротко и тепло."},
            {"role": "user", "content": f"Пользователь пишет: «{txt}». Дай короткий тёплый ответ без клише."}
        ])
        await update.message.reply_text(resp, reply_markup=kb_main())
        return

    # дефолт
    await update.message.reply_text("Выбери пункт меню или нажми «🎯 Фокус».", reply_markup=kb_main())

# === MAIN ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Kind Energy v9.3 started 🌿 (TEST_MODE =", TEST_MODE, ")")

    # Планировщик запускается после выбора фокуса. Для мгновенной отладки включи TEST_MODE=True в config.py
    app.run_polling()


