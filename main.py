import os
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

# Безопасное получение переменных
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "31abe786231de30a340419b6745e1c30")
BASE_URL = os.environ.get("RENDER_URL", "https://gamestgbot.onrender.com")

if not BOT_TOKEN:
    print("❌ ОШИБКА: Переменная BOT_TOKEN не найдена в Environment!")
    exit(1)

print(f"✅ Запуск с URL: {BASE_URL}")

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app
    try:
        telegram_app = Application.builder().token(BOT_TOKEN).build()
        telegram_app.add_handler(CommandHandler("start", start))
        await telegram_app.initialize()
        
        webhook_url = f"{BASE_URL}/webhook"
        await telegram_app.bot.set_webhook(
            url=webhook_url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=["message"]
        )
        print(f"✅ Бот запущен! Webhook: {webhook_url}")
        yield
    except Exception as e:
        print("❌ КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ:")
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
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return JSONResponse({"ok": True})

# Монтируем папку static для игр
try:
    fastapi_app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    print(f"⚠️ Не удалось подключить папку static: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
