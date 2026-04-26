import asyncio
import os
import re
from datetime import datetime, timedelta
from typing import Optional, List

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    Message, InaccessibleMessage
)
from dotenv import load_dotenv

import database as db


import asyncio
import logging
import os
import threading

from flask import Flask, request


app = Flask(__name__)

# ========== Flask Endpoints for Render ==========
@app.route('/health', methods=['GET'])
def health():
    """Render health check endpoint"""
    return "OK", 200

@app.route('/', methods=['GET'])
def index():
    """Home page to verify service is running"""
    return "Telegram bot is running!", 200

# ========== Run bot in background thread ==========
def run_bot():
    """Run the bot's main async function in a new event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(bot_main())
    except Exception as e:
        logging.error(f"Bot crashed: {e}")
    finally:
        loop.close()

def start_bot_thread():
    """Start bot in a daemon thread so it won't block Flask"""
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logging.info("Bot thread started")

# ========== Entry Point ==========
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Start the bot in background
    start_bot_thread()
    
    # Run Flask server (Render requires binding to PORT)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


load_dotenv()

TOKEN = os.getenv('BOT_TOKEN')

# Безопасная загрузка ADMIN_IDS
admin_ids_str = os.getenv('ADMIN_IDS', '')
ADMIN_IDS: List[int] = []
if admin_ids_str:
    for x in admin_ids_str.split(','):
        x = x.strip()
        if x:
            try:
                ADMIN_IDS.append(int(x))
            except ValueError:
                pass

if not TOKEN:
    raise ValueError("BOT_TOKEN not found")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def escape_markdown(text: str) -> str:
    """Экранирует спецсимволы для Markdown"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def get_service_names(service_ids: List[str]) -> List[str]:
    """Преобразует список ID услуг в список названий"""
    names = []
    for sid in service_ids:
        if sid in db.SERVICES:
            names.append(db.SERVICES[sid]['name'])
        else:
            names.append(sid)
    return names

def get_user_id(message: types.Message) -> Optional[int]:
    if message.from_user is None:
        return None
    return message.from_user.id

def get_user_id_from_callback(callback: types.CallbackQuery) -> Optional[int]:
    if callback.from_user is None:
        return None
    return callback.from_user.id

def safe_split(text: Optional[str], delimiter: str = "_") -> List[str]:
    """Безопасно разбивает строку, возвращает пустой список если text None"""
    if not text:
        return []
    return text.split(delimiter)

async def safe_edit_text(callback: types.CallbackQuery, text: str, **kwargs):
    """Безопасно редактирует сообщение или отправляет новое"""
    if callback.message is None:
        await safe_answer_callback(callback, "❌ Не удалось отобразить сообщение")
        return

    # Проверяем, что сообщение обычное (не InaccessibleMessage)
    if isinstance(callback.message, Message) and not isinstance(callback.message, InaccessibleMessage):
        try:
            await callback.message.edit_text(text, **kwargs)
            return
        except Exception:
            pass

    # Если редактирование не удалось или сообщение недоступно – отправляем новое
    try:
        await callback.message.answer(text, **kwargs)
    except Exception:
        pass

async def safe_answer_callback(callback: types.CallbackQuery, text: Optional[str] = None, show_alert: bool = False):
    """Безопасно отвечает на callback"""
    try:
        if text:
            await callback.answer(text, show_alert=show_alert)
        else:
            await callback.answer()
    except Exception:
        pass

# ==================== FSM СОСТОЯНИЯ ====================
class BookingState(StatesGroup):
    choosing_service = State()
    choosing_date = State()
    choosing_time = State()
    confirm = State()

class CancelState(StatesGroup):
    choosing_appointment = State()

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard(user_id=None):
    buttons = [
        [KeyboardButton(text="📋 Услуги и цены")],
        [KeyboardButton(text="📅 Записаться")],
        [KeyboardButton(text="📝 Мои записи")],
        [KeyboardButton(text="❌ Отменить запись")],
        [KeyboardButton(text="ℹ️ О салоне")]
    ]
    if user_id and user_id in ADMIN_IDS:
        buttons.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_services_keyboard():
    buttons = []
    for sid, service in db.SERVICES.items():
        buttons.append([InlineKeyboardButton(
            text=f"{service['name']} - {service['price']}₽",
            callback_data=f"service_{sid}"
        )])
    buttons.append([InlineKeyboardButton(text="✅ Готово", callback_data="services_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_date_keyboard():
    buttons = []
    for i in range(14):
        date = datetime.now() + timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        display = date.strftime("%d.%m.%Y (%a)")
        if db.get_free_slots(date_str):
            buttons.append([InlineKeyboardButton(text=f"✅ {display}", callback_data=f"date_{date_str}")])
        else:
            buttons.append([InlineKeyboardButton(text=f"❌ {display} (нет мест)", callback_data="noop")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_time_keyboard(date: str):
    free_slots = db.get_free_slots(date)
    buttons = []
    for slot in db.TIME_SLOTS:
        if slot in free_slots:
            buttons.append([InlineKeyboardButton(text=f"🟢 {slot}", callback_data=f"time_{slot}")])
        else:
            buttons.append([InlineKeyboardButton(text=f"🔴 {slot} (занято)", callback_data="noop")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_appointments_keyboard(user_id: int):
    appointments = db.get_user_appointments(user_id)
    buttons = []
    for apt in appointments:
        if apt["status"] == "pending":
            service_names = get_service_names(apt['services'])
            service_name = service_names[0] if service_names else "услуга"
            short_name = service_name[:20] if len(service_name) > 20 else service_name
            buttons.append([InlineKeyboardButton(
                text=f"❌ {apt['date']} {apt['time']} - {short_name}",
                callback_data=f"cancel_{apt['date']}_{apt['time']}"
            )])
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard():
    buttons = [
        [KeyboardButton(text="📅 Все записи")],
        [KeyboardButton(text="✅ Подтвердить запись")],
        [KeyboardButton(text="🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ==================== ОБРАБОТЧИКИ ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = get_user_id(message)
    if user_id is None:
        await message.answer("❌ Ошибка: не удалось определить пользователя")
        return
    await message.answer(
        "✨ Добро пожаловать в бот маникюрного салона!\n\n"
        "💅 Здесь вы можете:\n"
        "• Посмотреть услуги и цены\n"
        "• Записаться на удобное время\n"
        "• Просмотреть/отменить свои записи\n\n"
        "Выберите действие в меню 👇",
        reply_markup=get_main_keyboard(user_id)
    )

@dp.message(lambda message: message.text == "📋 Услуги и цены")
async def show_services(message: types.Message):
    text = "💅 **Наши услуги и цены**\n\n"
    for sid, service in db.SERVICES.items():
        safe_name = escape_markdown(service['name'])
        text += f"• {safe_name} — {service['price']} ₽\n"
    text += "\n⏰ Длительность зависит от выбранных услуг\n💰 Оплата на месте"
    await message.answer(text, parse_mode="Markdown")

@dp.message(lambda message: message.text == "📅 Записаться")
async def start_booking(message: types.Message, state: FSMContext):
    await state.clear()
    await state.update_data(services=[], total_price=0)
    await message.answer(
        "Выберите услуги, которые вам нужны:\n\n"
        "Вы можете выбрать несколько. После выбора нажмите ✅ Готово",
        reply_markup=get_services_keyboard()
    )
    await state.set_state(BookingState.choosing_service)

@dp.callback_query(lambda c: c.data and c.data.startswith("service_") and c.data != "services_done")
async def add_service(callback: types.CallbackQuery, state: FSMContext):
    parts = safe_split(callback.data, "_")
    if len(parts) < 2:
        await safe_answer_callback(callback, "❌ Ошибка")
        return
    service_id = parts[1]
    data = await state.get_data()
    services = data.get("services", [])
    total_price = data.get("total_price", 0)
    if service_id not in services:
        services.append(service_id)
        total_price += db.SERVICES[service_id]["price"]
        await safe_answer_callback(callback, f"✅ {db.SERVICES[service_id]['name']} добавлена")
    else:
        await safe_answer_callback(callback, "❌ Услуга уже добавлена")
    await state.update_data(services=services, total_price=total_price)
    selected = "\n".join([f"• {db.SERVICES[sid]['name']}" for sid in services])
    new_text = f"Выбранные услуги:\n{selected}\n\n💰 Итого: {total_price} ₽\n\nДобавьте ещё или нажмите ✅ Готово"
    await safe_edit_text(callback, new_text, reply_markup=get_services_keyboard())

@dp.callback_query(lambda c: c.data == "services_done")
async def done_services(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    services = data.get("services", [])
    if not services:
        await safe_answer_callback(callback, "❌ Выберите хотя бы одну услугу!", show_alert=True)
        return
    await safe_edit_text(callback, "✅ Отлично! Теперь выберите дату:")
    if callback.message:
        await callback.message.answer("📅 Выберите удобную дату:", reply_markup=get_date_keyboard())
    await state.set_state(BookingState.choosing_date)
    await safe_answer_callback(callback)

@dp.callback_query(lambda c: c.data and c.data.startswith("date_") and c.data != "noop")
async def choose_date(callback: types.CallbackQuery, state: FSMContext):
    parts = safe_split(callback.data, "_")
    if len(parts) < 2:
        await safe_answer_callback(callback, "❌ Ошибка")
        return
    date = parts[1]
    free_slots = db.get_free_slots(date)
    if not free_slots:
        await safe_answer_callback(callback, "❌ На эту дату нет свободных окошек", show_alert=True)
        return
    await state.update_data(date=date)
    await safe_edit_text(callback, f"📅 Выбрана дата: {date}\n\n🕐 Выберите удобное время:")
    if callback.message:
        await callback.message.answer("🕐 Выберите время:", reply_markup=get_time_keyboard(date))
    await state.set_state(BookingState.choosing_time)
    await safe_answer_callback(callback)

@dp.callback_query(lambda c: c.data and c.data.startswith("time_") and c.data != "noop")
async def choose_time(callback: types.CallbackQuery, state: FSMContext):
    parts = safe_split(callback.data, "_")
    if len(parts) < 2:
        await safe_answer_callback(callback, "❌ Ошибка")
        return
    time = parts[1]
    data = await state.get_data()
    date = data.get("date")
    if not date:
        await safe_answer_callback(callback, "❌ Сначала выберите дату", show_alert=True)
        return
    if time not in db.get_free_slots(date):
        await safe_answer_callback(callback, "❌ Это время уже занято! Выберите другое", show_alert=True)
        return
    await state.update_data(time=time)
    services = data.get("services", [])
    total_price = data.get("total_price", 0)
    services_text = "\n".join([f"• {db.SERVICES[sid]['name']}" for sid in services])
    text = (
        f"📝 **Подтверждение записи**\n\n"
        f"📅 Дата: {date}\n"
        f"🕐 Время: {time}\n"
        f"💅 Услуги:\n{services_text}\n"
        f"💰 Итого: {total_price} ₽\n\n"
        f"Всё верно? Нажмите ✅ Подтвердить"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="confirm_no")]
    ])
    await safe_edit_text(callback, text, parse_mode="Markdown", reply_markup=kb)
    await state.set_state(BookingState.confirm)
    await safe_answer_callback(callback)

@dp.callback_query(lambda c: c.data == "confirm_yes")
async def confirm_booking(callback: types.CallbackQuery, state: FSMContext):
    user_id = get_user_id_from_callback(callback)
    if user_id is None:
        await safe_edit_text(callback, "❌ Ошибка: не удалось определить пользователя")
        return
    username = callback.from_user.username or callback.from_user.full_name or str(user_id)
    data = await state.get_data()
    date = data.get("date")
    time = data.get("time")
    services = data.get("services", [])
    total_price = data.get("total_price", 0)
    if not date or not time or not services:
        await safe_edit_text(callback, "❌ Ошибка: не все данные выбраны. Начните заново /start")
        await state.clear()
        return
    success = db.add_appointment(user_id, username, date, time, services, total_price)
    if success:
        await safe_edit_text(
            callback,
            f"✅ Вы успешно записаны!\n\n"
            f"📅 {date} в {time}\n"
            f"💰 Сумма: {total_price} ₽\n\n"
            f"До встречи! 💅"
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🆕 Новая запись!\n\n"
                    f"👤 {username}\n"
                    f"📅 {date} в {time}\n"
                    f"💰 {total_price} ₽"
                )
            except Exception:
                pass
    else:
        await safe_edit_text(callback, "❌ Время уже занято. Попробуйте другое время.")
    await state.clear()
    await safe_answer_callback(callback)

@dp.callback_query(lambda c: c.data == "confirm_no")
async def cancel_booking(callback: types.CallbackQuery, state: FSMContext):
    await safe_edit_text(callback, "❌ Запись отменена. Можете начать заново: /start")
    await state.clear()
    await safe_answer_callback(callback)

@dp.message(lambda message: message.text == "📝 Мои записи")
async def my_appointments(message: types.Message):
    user_id = get_user_id(message)
    if user_id is None:
        await message.answer("❌ Ошибка: не удалось определить пользователя")
        return
    appointments = db.get_user_appointments(user_id)
    if not appointments:
        await message.answer("📭 У вас пока нет записей. Хотите записаться? /start")
        return
    text = "📋 **Ваши записи**\n\n"
    for apt in appointments:
        status_emoji = "✅" if apt["status"] == "confirmed" else "⏳"
        service_names = get_service_names(apt['services'])
        services_short = ', '.join(service_names[:2])
        if len(service_names) > 2:
            services_short += "..."
        text += (
            f"{status_emoji} **{apt['date']} в {apt['time']}**\n"
            f"Услуги: {services_short}\n"
            f"Сумма: {apt['total_price']} ₽\n"
            f"Статус: {'Подтверждена' if apt['status'] == 'confirmed' else 'Ожидает подтверждения'}\n\n"
        )
    await message.answer(text, parse_mode="Markdown")

@dp.message(lambda message: message.text == "❌ Отменить запись")
async def cancel_menu(message: types.Message, state: FSMContext):
    user_id = get_user_id(message)
    if user_id is None:
        await message.answer("❌ Ошибка: не удалось определить пользователя")
        return
    kb = get_appointments_keyboard(user_id)
    if not kb:
        await message.answer("❌ У вас нет активных записей для отмены.")
        return
    await message.answer("Выберите запись для отмены:", reply_markup=kb)
    await state.set_state(CancelState.choosing_appointment)

@dp.callback_query(lambda c: c.data and c.data.startswith("cancel_"))
async def cancel_appointment_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = get_user_id_from_callback(callback)
    if user_id is None:
        await safe_edit_text(callback, "❌ Ошибка")
        return
    parts = safe_split(callback.data, "_")
    if len(parts) < 3:
        await safe_answer_callback(callback, "❌ Ошибка")
        return
    date = parts[1]
    time = parts[2]
    success = db.cancel_appointment(user_id, date, time)
    if success:
        await safe_edit_text(callback, f"✅ Запись на {date} в {time} отменена.")
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, f"❌ Пользователь отменил запись на {date} в {time}")
            except Exception:
                pass
    else:
        await safe_edit_text(callback, "❌ Не удалось отменить запись.")
    await state.clear()
    await safe_answer_callback(callback)

@dp.message(lambda message: message.text == "👑 Админ-панель")
async def admin_panel(message: types.Message):
    user_id = get_user_id(message)
    if user_id is None or user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к админ-панели")
        return
    await message.answer("👑 Добро пожаловать в админ-панель!\n\nВыберите действие:", reply_markup=get_admin_keyboard())

@dp.message(lambda message: message.text == "📅 Все записи")
async def admin_all_appointments(message: types.Message):
    user_id = get_user_id(message)
    if user_id is None or user_id not in ADMIN_IDS:
        return
    appointments = db.get_all_appointments()
    if not appointments:
        await message.answer("📭 Записей пока нет")
        return
    text = "📅 **Все записи**\n\n"
    for date, slots in appointments.items():
        text += f"📌 **{date}**\n"
        for time, data in slots.items():
            status = "✅" if data["status"] == "confirmed" else "⏳"
            text += f"  {status} {time} — {data['username']} — {data['total_price']} ₽\n"
        text += "\n"
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i+4000], parse_mode="Markdown")
    else:
        await message.answer(text, parse_mode="Markdown")

@dp.message(lambda message: message.text == "✅ Подтвердить запись")
async def admin_confirm_menu(message: types.Message):
    user_id = get_user_id(message)
    if user_id is None or user_id not in ADMIN_IDS:
        return
    appointments = db.get_all_appointments()
    pending = []
    for date, slots in appointments.items():
        for time, data in slots.items():
            if data["status"] == "pending":
                pending.append((date, time, data))
    if not pending:
        await message.answer("⏳ Нет записей, ожидающих подтверждения")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for date, time, data in pending:
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"✅ {date} {time} - {data['username']}",
                callback_data=f"confirm_app_{date}_{time}"
            )
        ])
    await message.answer("Выберите запись для подтверждения:", reply_markup=kb)

@dp.callback_query(lambda c: c.data and c.data.startswith("confirm_app_"))
async def admin_confirm_appointment(callback: types.CallbackQuery):
    admin_id = get_user_id_from_callback(callback)
    if admin_id is None or admin_id not in ADMIN_IDS:
        await safe_answer_callback(callback, "❌ Нет доступа")
        return
    parts = safe_split(callback.data, "_")
    if len(parts) < 3:
        await safe_answer_callback(callback, "❌ Ошибка")
        return
    date = parts[2]
    time = parts[3] if len(parts) > 3 else ""
    success = db.confirm_appointment(date, time)
    if success:
        await safe_edit_text(callback, f"✅ Запись на {date} в {time} подтверждена!")
        appointments = db.get_all_appointments()
        appointment = appointments.get(date, {}).get(time, {})
        client_id = appointment.get("user_id")
        if client_id:
            try:
                await bot.send_message(client_id, f"✅ Ваша запись на {date} в {time} подтверждена! Ждём вас 💅")
            except Exception:
                pass
    else:
        await safe_edit_text(callback, f"❌ Не удалось подтвердить запись")
    await safe_answer_callback(callback)

@dp.message(lambda message: message.text == "ℹ️ О салоне")
async def about_salon(message: types.Message):
    text = (
        "✨ **О нашем салоне** ✨\n\n"
        "📍 Адрес: ул. Примерная, д. 123\n"
        "🕐 Работаем: ежедневно с 10:00 до 20:00\n"
        "📞 Телефон: +7 (XXX) XXX-XX-XX\n"
        "💰 Оплата: наличные, карты, перевод\n\n"
        "🌟 Мы используем только профессиональные материалы\n"
        "🌟 Стерилизация инструментов после каждого клиента\n"
        "🌟 Уютная атмосфера и чай/кофе\n\n"
        "Ждём вас! 💅"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(lambda message: message.text == "🔙 Назад")
async def back_to_main(message: types.Message):
    user_id = get_user_id(message)
    await message.answer("Главное меню:", reply_markup=get_main_keyboard(user_id))

@dp.callback_query(lambda c: c.data == "noop")
async def noop_callback(callback: types.CallbackQuery):
    await safe_answer_callback(callback, "❌ Эта опция недоступна", show_alert=True)

@dp.message()
async def unknown(message: types.Message):
    user_id = get_user_id(message)
    await message.answer(
        "❓ Не понимаю. Используйте кнопки меню 👇",
        reply_markup=get_main_keyboard(user_id)
    )

async def main():
    print("🤖 Бот для маникюрного салона запущен!")
    print(f"👑 Админы: {ADMIN_IDS}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
