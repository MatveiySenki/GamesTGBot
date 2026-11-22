import os
import json
import sqlite3
import zipfile
import shutil
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "mysecret123")
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DB_PATH = "leaderboard.db"

telegram_app = None
user_states = {}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, game TEXT, score INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()


def save_score(user_id, username, game, score):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO scores (user_id, username, game, score) VALUES (?,?,?,?)",
              (user_id, username, game, score))
    conn.commit()
    conn.close()


def get_top_scores(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, game, score FROM scores ORDER BY score DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


def get_main_keyboard():
    kb = [
        [InlineKeyboardButton("🐦 Flappy Bird", web_app=WebAppInfo(url=f"{BASE_URL}/static/flappy.html"))],
        [InlineKeyboardButton("🎮 Танчики", web_app=WebAppInfo(url=f"{BASE_URL}/static/tanks.html"))],
        [InlineKeyboardButton("🏰 Империя: Армия", web_app=WebAppInfo(url=f"{BASE_URL}/static/empire.html"))],
        [InlineKeyboardButton("⚡ Разбудить сервер", callback_data="wake_up")],
        [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="leaderboard")],
        [InlineKeyboardButton("➕ Добавить игру", callback_data="add_game")],
    ]
    return InlineKeyboardMarkup(kb)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 Добро пожаловать в GameGamerBot!\n\nВыбери игру или действие:",
        reply_markup=get_main_keyboard()
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "wake_up":
        await query.edit_message_text(
            "⚡ Сервер просыпается...\nПодожди 10-15 секунд и попробуй снова!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="menu")]])
        )
    elif data == "leaderboard":
        rows = get_top_scores()
        if not rows:
            text = "🏆 Таблица лидеров пуста.\nИграй и устанавливай рекорды!"
        else:
            text = "🏆 ТОП-10:\n\n"
            for i, (username, game, score) in enumerate(rows, 1):
                text += f"{i}. {username} — {score} ({game})\n"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]))
    elif data == "add_game":
        user_states[query.from_user.id] = {"step": "waiting_password"}
        await query.edit_message_text(
            "🔐 Введи админский пароль:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="menu")]])
        )
    elif data == "menu":
        user_states.pop(query.from_user.id, None)
        await query.edit_message_text(
            "🎮 Выбери игру или действие:",
            reply_markup=get_main_keyboard()
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or f"user_{user_id}"

    if update.message.web_app_data:
        try:
            data = json.loads(update.message.web_app_data.data)
            if data.get("type") == "progress":
                save_score(user_id, username, "empire", data.get("gold", 0))
                await update.message.reply_text(f"💾 Прогресс сохранён! Золото: {data.get('gold', 0)}")
            elif data.get("type") == "conquer":
                save_score(user_id, username, "empire_conquer", data.get("army", 0))
                await update.message.reply_text(f"🏆 Завоевание! Армия: {data.get('army')}")
        except Exception as e:
            logger.error(f"web_app_data error: {e}")
        return

    if user_id in user_states:
        st = user_states[user_id]
        if st["step"] == "waiting_password":
            if update.message.text == ADMIN_PASSWORD:
                st["step"] = "waiting_file"
                await update.message.reply_text(
                    "✅ Пароль принят!\nОтправь .zip архив с игрой (внутри должен быть index.html)"
                )
            else:
                user_states.pop(user_id, None)
                await update.message.reply_text("❌ Неверный пароль")
        elif st["step"] == "waiting_file":
            if update.message.document:
                file = await update.message.document.get_file()
                os.makedirs("static/games", exist_ok=True)
                fname = update.message.document.file_name
                fpath = f"static/games/{fname}"
                await file.download_to_drive(fpath)
                if fname.endswith(".zip"):
                    with zipfile.ZipFile(fpath, 'r') as z:
                        z.extractall("static/games/temp")
                    for root, dirs, files in os.walk("static/games/temp"):
                        if "index.html" in files:
                            gname = os.path.basename(root)
                            dest = f"static/games/{gname}"
                            if os.path.exists(dest):
                                shutil.rmtree(dest)
                            shutil.move(root, dest)
                            break
                    shutil.rmtree("static/games/temp", ignore_errors=True)
                    os.remove(fpath)
                user_states.pop(user_id, None)
                await update.message.reply_text("✅ Игра загружена! Перезапусти бота, чтобы она появилась.")
            else:
                await update.message.reply_text("❌ Ожидался файл. Пришли .zip архив.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app
    init_db()
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CallbackQueryHandler(button_handler))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    telegram_app.add_handler(MessageHandler(filters.Document.ALL, handle_message))
    await telegram_app.initialize()
    await telegram_app.bot.set_webhook(
        url=f"{BASE_URL}/webhook",
        secret_token=WEBHOOK_SECRET,
        allowed_updates=["message", "callback_query"]
    )
    logger.info(f"✅ Бот запущен! Webhook: {BASE_URL}/webhook")
    yield
    await telegram_app.bot.delete_webhook()
    await telegram_app.shutdown()


fastapi_app = FastAPI(lifespan=lifespan)


@fastapi_app.get("/")
async def root():
    return {"status": "alive"}


@fastapi_app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return JSONResponse({"ok": True})


fastapi_app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
