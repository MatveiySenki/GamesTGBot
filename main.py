import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.environ["9217455747:AAEFgGAsPluWOF0eScbYDUuAsuZhozxWMpI"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "31abe786231de30a340419b6745e1c30)
BASE_URL = os.environ.get("RENDER_URL", "https://gamestgbot.onrender.com")

telegram_app = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(
            "🐦 Flappy Bird",
            web_app=WebAppInfo(url=f"{BASE_URL}/static/flappy.html")
        )],
        [InlineKeyboardButton(
            "🎮 Танчики",
            web_app=WebAppInfo(url=f"{BASE_URL}/static/tanks.html")
        )]
    ]
    await update.message.reply_text(
        "🎮 Добро пожаловать!\nВыбери игру:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Напиши /start чтобы играть 🎮")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_cmd))
    await telegram_app.initialize()
    await telegram_app.start()
    print("✅ Бот инициализирован")
    yield
    await telegram_app.stop()

fastapi_app = FastAPI(lifespan=lifespan)

@fastapi_app.get("/")
async def root():
    return {"status": "bot is alive"}

@fastapi_app.get("/health")
async def health():
    return {"ok": True}

@fastapi_app.post("/webhook")
async def webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return JSONResponse({"ok": True})

fastapi_app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
