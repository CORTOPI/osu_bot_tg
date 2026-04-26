import json
import os
from datetime import datetime
from typing import Dict, List, Optional

DATA_FILE = "appointments.json"

# Услуги и цены
SERVICES = {
    "1": {"name": "💅 Маникюр классический", "price": 1500, "duration": 60},
    "2": {"name": "💅 Маникюр аппаратный", "price": 1700, "duration": 60},
    "3": {"name": "💅 Маникюр комбинированный", "price": 1800, "duration": 60},
    "4": {"name": "🎨 Покрытие гель-лак", "price": 1200, "duration": 40},
    "5": {"name": "✨ Дизайн (1 ноготь)", "price": 100, "duration": 10},
    "6": {"name": "🦶 Педикюр", "price": 2500, "duration": 90},
    "7": {"name": "💪 Снятие покрытия", "price": 500, "duration": 20},
    "8": {"name": "🌟 Комплекс (маникюр+покрытие)", "price": 2500, "duration": 100},
}

# Рабочие часы
WORK_HOURS = {
    "start": 10,  # 10:00
    "end": 20,    # 20:00
}

# Время приёма (шаг 30 минут)
TIME_SLOTS = [f"{h:02d}:{m:02d}" for h in range(10, 20) for m in (0, 30)]

def load_appointments() -> Dict:
    """Загружает записи из файла"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_appointments(data: Dict):
    """Сохраняет записи в файл"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_free_slots(date: str) -> List[str]:
    """Возвращает список свободных временных слотов на дату"""
    appointments = load_appointments()
    booked = appointments.get(date, {}).keys()
    return [slot for slot in TIME_SLOTS if slot not in booked]

def add_appointment(user_id: int, username: str, date: str, time: str, service_ids: List[str], total_price: int) -> bool:
    """Добавляет новую запись"""
    appointments = load_appointments()
    
    if date not in appointments:
        appointments[date] = {}
    
    if time in appointments[date]:
        return False
    
    appointments[date][time] = {
        "user_id": user_id,
        "username": username,
        "services": [SERVICES[sid]["name"] for sid in service_ids],
        "service_ids": service_ids,
        "total_price": total_price,
        "created_at": datetime.now().isoformat(),
        "status": "pending"  # pending, confirmed, cancelled
    }
    
    save_appointments(appointments)
    return True

def cancel_appointment(user_id: int, date: str, time: str) -> bool:
    """Отменяет запись"""
    appointments = load_appointments()
    
    if date in appointments and time in appointments[date]:
        if appointments[date][time]["user_id"] == user_id:
            del appointments[date][time]
            save_appointments(appointments)
            return True
    return False

def get_user_appointments(user_id: int) -> List[Dict]:
    """Возвращает все записи пользователя"""
    appointments = load_appointments()
    result = []
    
    for date, slots in appointments.items():
        for time, data in slots.items():
            if data["user_id"] == user_id:
                result.append({
                    "date": date,
                    "time": time,
                    "services": data["services"],
                    "total_price": data["total_price"],
                    "status": data.get("status", "pending")
                })
    
    return sorted(result, key=lambda x: (x["date"], x["time"]))

def get_all_appointments() -> Dict:
    """Возвращает все записи (для админа)"""
    return load_appointments()

def confirm_appointment(date: str, time: str) -> bool:
    """Подтверждает запись (админ)"""
    appointments = load_appointments()
    if date in appointments and time in appointments[date]:
        appointments[date][time]["status"] = "confirmed"
        save_appointments(appointments)
        return True
    return False