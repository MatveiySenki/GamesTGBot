import os
import json
import sqlite3
import zipfile
import shutil
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "31abe786231de30a340419b6745e1c30")
BASE_URL = os.environ.get("RENDER_URL", "https://gamestgbot.onrender.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admenmradmatveri$8602#67")

# База данных
DB_PATH = "leaderboard.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            game TEXT,
            score INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            file_path TEXT,
            added_by INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_score(user_id, username, game, score):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO scores (user_id, username, game, score) VALUES (?, ?, ?, ?)",
        (user_id, username, game, score)
    )
    conn.commit()
    conn.close()

def get_top_scores(game=None, limit=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if game:
        cursor.execute(
            "SELECT username, score FROM scores WHERE game = ? ORDER BY score DESC LIMIT ?",
            (game, limit)
        )
    else:
        cursor.execute(
            "SELECT username, game, score FROM scores ORDER BY score DESC LIMIT ?",
            (limit,)
        )
    results = cursor.fetchall()
    conn.close()
    return results

telegram_app = None
user_states = {}  # Для хранения состояний пользователей (админка)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🐦 Flappy Bird", web_app=WebAppInfo(url=f"{BASE_URL}/static/flappy.html"))],
        [InlineKeyboardButton("🎮 Танчики", web_app=WebAppInfo(url=f"{BASE_URL}/static/tanks.html"))],
        [InlineKeyboardButton("🏰 Империя: Армия", web_app=WebAppInfo(url=f"{BASE_URL}/static/empire.html"))],
        [InlineKeyboardButton("⚡ Разбудить сервер", callback_data="wake_up")],
        [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="leaderboard")],
        [InlineKeyboardButton("➕ Добавить игру", callback_data="add_game")]
    ]
    await update.message.reply_text(
        "🎮 Добро пожаловать в GameGamerBot!\n\nВыбери игру или действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def wake_up(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚡ Сервер просыпается...\n\nПодожди 10-15 секунд и попробуй открыть игру снова!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="menu")]])
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    top = get_top_scores(limit=10)
    if not top:
        text = "🏆 Таблица лидеров пуста.\n\nИграй и устанавливай рекорды!"
    else:
        text = "🏆 ТОП-10 игроков:\n\n"
        for i, (username, game, score) in enumerate(top, 1):
            text += f"{i}. {username} - {score} очков ({game})\n"
    
    keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def add_game_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_states[user_id] = {"step": "waiting_password"}
    
    await query.edit_message_text(
        "🔐 Введи админский пароль для загрузки игры:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="menu")]])
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or f"user_{user_id}"
    
    # Обработка данных от Web App
    if update.message and update.message.web_app_data:
        try:
            data = json.loads(update.message.web_app_data.data)
            if data.get("type") == "progress":
                save_score(user_id, username, "empire", data.get("gold", 0))
                await update.message.reply_text(f"💾 Прогресс сохранён! Золото: {data.get('gold', 0)}")
            elif data.get("type") == "conquer":
                save_score(user_id, username, "empire_conquer", data.get("army", 0))
                await update.message.reply_text(f"🏆 Завоевание! {data.get('state')} - Армия: {data.get('army')}")
        except:
            pass
        return
    
    # Обработка админских команд
    if user_id in user_states:
        state = user_states[user_id]
        
        if state["step"] == "waiting_password":
            if update.message.text == ADMIN_PASSWORD:
                state["step"] = "waiting_file"
                await update.message.reply_text(
                    "✅ Пароль принят!\n\nТеперь отправь .zip архив с игрой (должен содержать index.html)",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="menu")]])
                )
            else:
                del user_states[user_id]
                await update.message.reply_text("❌ Неверный пароль")
        
        elif state["step"] == "waiting_file":
            if update.message.document:
                file = await update.message.document.get_file()
                file_path = f"static/games/{update.message.document.file_name}"
                os.makedirs("static/games", exist_ok=True)
                await file.download_to_drive(file_path)
                
                # Если это zip, распаковываем
                if file_path.endswith(".zip"):
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall("static/games/temp")
                    # Находим index.html
                    for root, dirs, files in os.walk("static/games/temp"):
                        if "index.html" in files:
                            game_name = os.path.basename(root)
                            dest = f"static/games/{game_name}"
                            if os.path.exists(dest):
                                shutil.rmtree(dest)
                            shutil.move(root, dest)
                            break
                    shutil.rmtree("static/games/temp", ignore_errors=True)
                    os.remove(file_path)
                
                # Сохраняем в БД
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO games (name, file_path, added_by) VALUES (?, ?, ?)",
                    (update.message.document.file_name, file_path, user_id)
                )
                conn.commit()
                conn.close()
                
                del user_states[user_id]
                await update.message.reply_text("✅ Игра загружена! Она появится в меню после перезапуска бота.")
            else:
                await update.message.reply_text("❌ Ожидался файл. Попробуй ещё раз или отмени.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "wake_up":
        await wake_up(update, context)
    elif query.data == "leaderboard":
        await leaderboard(update, context)
    elif query.data == "add_game":
        await add_game_prompt(update, context)
    elif query.data == "menu":
        user_id = query.from_user.id
        if user_id in user_states:
            del user_states[user_id]
        keyboard = [
            [InlineKeyboardButton("🐦 Flappy Bird", web_app=WebAppInfo(url=f"{BASE_URL}/static/flappy.html"))],
            [InlineKeyboardButton("🎮 Танчики", web_app=WebAppInfo(url=f"{BASE_URL}/static/tanks.html"))],
            [InlineKeyboardButton("🏰 Империя: Армия", web_app=WebAppInfo(url=f"{BASE_URL}/static/empire.html"))],
            [InlineKeyboardButton("⚡ Разбудить сервер", callback_data="wake_up")],
            [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="leaderboard")],
            [InlineKeyboardButton("➕ Добавить игру", callback_data="add_game")]
        ]
        await query.edit_message_text(
            "🎮 Добро пожаловать в GameGamerBot!\n\nВыбери игру или действие:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app
    try:
        init_db()
        telegram_app = Application.builder().token(BOT_TOKEN).build()
        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CallbackQueryHandler(button_handler))
        telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        telegram_app.add_handler(MessageHandler(filters.Document.ALL, handle_message))
        await telegram_app.initialize()
        
        webhook_url = f"{BASE_URL}/webhook"
        await telegram_app.bot.set_webhook(
            url=webhook_url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=["message", "callback_query"]
        )
        print(f"✅ Бот запущен! Webhook: {webhook_url}")
        yield
    except Exception as e:
        print("❌ ОШИБКА:")
        import traceback
        traceback.print_exc()
        raise e
    finally:
        if telegram_app:
            await telegram_app.bot.delete_webhook()
            await telegram_app.shutdown()

fastapi_app = FastAPI(lifespan=lifespan)

@fastapi_app.get("/")
async def root():
    return {"status": "alive", "webhook_url": f"{BASE_URL}/webhook"}

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
