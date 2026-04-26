import asyncio
import os
import threading
from flask import Flask
from bot import main as bot_main

app = Flask(__name__)

@app.route('/health')
def health():
    return "OK", 200

@app.route('/')
def index():
    return "Telegram bot is running!", 200

def run_flask():
    """Запускает Flask-сервер в отдельном потоке"""
    port = int(os.environ.get("PORT", 5000))
    # debug=False и use_reloader=False обязательны для работы в потоке
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    # 1. Запускаем Flask в фоновом потоке (не блокирует основной)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 2. Запускаем бота в основном потоке (здесь разрешены сигналы)
    asyncio.run(bot_main())
