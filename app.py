import os
import threading
import asyncio
import time
from flask import Flask, request
from bot import main as bot_main  # Импортируем главную функцию вашего бота

app = Flask(__name__)

# --- Health Check Endpoint для Render ---
@app.route('/health')
def health():
    return "OK", 200

# --- Главная страница, чтобы убедиться, что сервер работает ---
@app.route('/')
def index():
    return "Telegram bot is running!"

# Эта функция запустит вашего бота в отдельном потоке
def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot_main())  # Здесь вызывается ваша главная функция

if __name__ == "__main__":
    # Запускаем бота в фоновом потоке, чтобы не блокировать Flask
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()

    # Запускаем Flask-сервер, который нужен Render'у
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)