"""
Telegram bot for assigning topics to users.

Instructions:
 - Set your bot token and admin Telegram IDs as environment variables.
 - Run: python main.py

Notes:
 - This implementation uses aiogram v3 style Dispatcher polling.
 - The bot stores state in data.json (simple JSON file).
 - For hosting on Railway, set BOT_TOKEN and ADMIN_IDS environment variables.
"""

import asyncio
import json
import logging
import os
from typing import Optional, List, Dict

from aiogram import Bot, Dispatcher, types
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получаем токен из переменной окружения
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Не установлен BOT_TOKEN")

# Получаем admin IDs из переменной окружения (разделенные запятой)
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS")
if ADMIN_IDS_STR:
    try:
        # Разбиваем строку по запятым и конвертируем в числа
        ADMIN_IDS = [int(id_str.strip()) for id_str in ADMIN_IDS_STR.split(',')]
    except ValueError:
        raise ValueError("ADMIN_IDS должен быть списком чисел, разделенных запятыми, например: 123456789,987654321")
else:
    raise ValueError("Не установлен ADMIN_IDS")

BASE_DIR = os.path.dirname(__file__)
DATA_FILE = os.path.join(BASE_DIR, "data.json")


# ------------------ Helpers for JSON storage ------------------

def load_data() -> Dict:
    if not os.path.exists(DATA_FILE) or os.path.getsize(DATA_FILE) == 0:
        # Инициализируем с admin_ids из переменной окружения
        return {"admin_ids": ADMIN_IDS, "topics": [], "time_slots": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            # Убедимся, что admin_ids всегда содержит ADMIN_IDS из переменной окружения
            for admin_id in ADMIN_IDS:
                if admin_id not in data.get("admin_ids", []):
                    data["admin_ids"] = data.get("admin_ids", [])
                    data["admin_ids"].append(admin_id)
            return data
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in {DATA_FILE}, returning default data")
            return {"admin_ids": ADMIN_IDS, "topics": [], "time_slots": []}


def save_data(data: Dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ------------------ Keyboard builders ------------------

def main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.add(KeyboardButton(text="📝 Занять тему"))
    kb.add(KeyboardButton(text="📋 Список тем"))
    if is_admin:
        kb.add(KeyboardButton(text="🔄 Обновить список тем"))
    kb.adjust(1, 1)
    return kb.as_markup(resize_keyboard=True)


def topic_actions_keyboard():
    kb = ReplyKeyboardBuilder()
    kb.add(KeyboardButton(text="🔄 Перевыбрать тему"))
    kb.add(KeyboardButton(text="⏰ Перевыбрать время"))
    kb.add(KeyboardButton(text="❌ Сбросить тему"))
    kb.add(KeyboardButton(text="🔙 Назад"))
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup(resize_keyboard=True)


def time_selection_keyboard(occupied_slots):
    kb = ReplyKeyboardBuilder()
    for i in range(1, 8):  # Слоты от 1 до 7
        if i not in [slot["slot"] for slot in occupied_slots]:
            kb.add(KeyboardButton(text=f"⏰ {i}"))
    kb.add(KeyboardButton(text="🔙 Назад"))
    kb.adjust(3, 3, 2)  # 3 + 3 + (1 или 2)
    return kb.as_markup(resize_keyboard=True)


back_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Назад")]],
    resize_keyboard=True
)

# ------------------ Bot Logic ------------------

pending = {}


async def start_bot():
    if not TOKEN:
        logger.error("Bot token not set. Set BOT_TOKEN environment variable.")
        return

    bot = Bot(token=TOKEN)
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def cmd_start(message: types.Message):
        data = load_data()
        is_admin = message.from_user.id in data.get("admin_ids", [])
        await message.answer("👋 Привет! Выберите действие:", reply_markup=main_keyboard(is_admin))

    @dp.message(lambda m: m.text == "📋 Список тем")
    async def list_topics(message: types.Message):
        data = load_data()
        if not data.get("topics"):
            await message.answer("❌ Список тем пуст.", reply_markup=back_kb)
            return

        lines = ["📚 Список тем:"]
        for t in data["topics"]:
            status = f"🔴 ЗАНЯТА ({t['user']})" if t.get("user") else "🟢 свободна"
            lines.append(f"{t['id']}. {t['name']} — {status}")

        # Время выступлений: от 1 до 7
        lines.append("\n⏰ Время выступлений:")
        for i in range(1, 8):
            slot_taken = next((slot for slot in data.get("time_slots", []) if slot["slot"] == i), None)
            if slot_taken:
                lines.append(f"{i}. 🔴 ЗАНЯТО ({slot_taken['user']})")
            else:
                lines.append(f"{i}. 🟢 свободно")

        await message.answer("\n".join(lines), reply_markup=back_kb)

    @dp.message(lambda m: m.text == "📝 Занять тему")
    async def start_take(message: types.Message):
        await message.answer("👤 Введите имя и фамилию:", reply_markup=types.ReplyKeyboardRemove())
        pending[message.from_user.id] = {"state": "await_name"}

    @dp.message(lambda m: m.from_user.id in pending and pending[m.from_user.id]["state"] == "await_name")
    async def got_name(message: types.Message):
        user_id = message.from_user.id
        name = message.text.strip()
        data = load_data()
        already = next((t for t in data["topics"] if t.get("user") == name), None)
        free = [t for t in data["topics"] if not t.get("user")]

        if already:
            if free:
                await message.answer(f"✅ Вы уже заняли тему: {already['name']}", reply_markup=topic_actions_keyboard())
            else:
                await message.answer("❌ Вы выбрали последнюю не занятую тему, перевыбрать тему нельзя(", reply_markup=back_kb)
            pending.pop(user_id, None)
            return

        if not free:
            await message.answer("❌ Нет свободных тем.", reply_markup=back_kb)
            pending.pop(user_id, None)
            return

        pending[user_id] = {"state": "choosing", "name": name}
        kb = ReplyKeyboardBuilder()
        for t in free:
            kb.add(KeyboardButton(text=t["name"]))
        kb.add(KeyboardButton(text="🔙 Назад"))
        kb.adjust(1, 1)
        await message.answer("📋 Выберите тему из доступных:", reply_markup=kb.as_markup(resize_keyboard=True))

    @dp.message(lambda m: m.from_user.id in pending and pending[m.from_user.id]["state"] == "choosing")
    async def choose_topic(message: types.Message):
        user_id = message.from_user.id
        name = pending[user_id]["name"]
        choice = message.text.strip()
        data = load_data()
        chosen = next((t for t in data["topics"] if t["name"] == choice), None)
        if choice == "🔙 Назад":
            pending.pop(user_id, None)
            is_admin = message.from_user.id in data.get("admin_ids", [])
            await message.answer("🔙 Возврат в меню.", reply_markup=main_keyboard(is_admin))
            return

        if not chosen:
            await message.answer("❌ Такой темы нет или она недоступна. Выберите другую.")
            return

        if chosen.get("user"):
            is_admin = message.from_user.id in data.get("admin_ids", [])
            await message.answer("❌ Эта тема уже занята.", reply_markup=main_keyboard(is_admin))
            pending.pop(user_id, None)
            return

        for t in data["topics"]:
            if t.get("user") == name:
                t["user"] = None

        chosen["user"] = name
        save_data(data)

        await message.answer("✅ Тема успешно занята вами! Теперь выберите время выступления:",
                             reply_markup=time_selection_keyboard(data.get("time_slots", [])))

        pending[user_id] = {"state": "choosing_time", "name": name, "topic": chosen["name"], "topic_id": chosen["id"]}

    @dp.message(lambda m: m.from_user.id in pending and pending[m.from_user.id]["state"] == "choosing_time")
    async def choose_time(message: types.Message):
        user_id = message.from_user.id
        name = pending[user_id]["name"]
        topic_name = pending[user_id]["topic"]
        topic_id = pending[user_id]["topic_id"]
        time_choice = message.text.strip()

        if time_choice == "🔙 Назад":
            data = load_data()
            for t in data["topics"]:
                if t.get("user") == name and t["id"] == topic_id:
                    t["user"] = None
                    break
            save_data(data)
            pending.pop(user_id, None)
            is_admin = message.from_user.id in data.get("admin_ids", [])
            await message.answer("🔙 Возврат в меню. Выбор темы отменен.", reply_markup=main_keyboard(is_admin))
            return

        try:
            time_slot = int(time_choice.replace("⏰ ", ""))
            if time_slot < 1 or time_slot > 7:
                await message.answer("⏰ Пожалуйста, выберите время от 1 до 7.")
                return
        except ValueError:
            await message.answer("⏰ Пожалуйста, выберите время от 1 до 7.")
            return

        data = load_data()
        existing_slot = next((slot for slot in data.get("time_slots", []) if slot["slot"] == time_slot), None)
        if existing_slot and existing_slot["user"] != name:
            await message.answer(
                f"⏰ Время {time_slot} уже занято пользователем {existing_slot['user']}. Выберите другое время:",
                reply_markup=time_selection_keyboard(data.get("time_slots", []))
            )
            return

        new_time_slots = [slot for slot in data.get("time_slots", []) if slot["user"] != name]
        new_time_slots.append({"slot": time_slot, "user": name})
        data["time_slots"] = new_time_slots
        save_data(data)

        await message.answer(f"✅ Время выступления {time_slot} успешно выбрано для темы '{topic_name}'!",
                             reply_markup=topic_actions_keyboard())
        pending.pop(user_id, None)

    # Перевыбрать тему
    @dp.message(lambda m: m.text == "🔄 Перевыбрать тему")
    async def rechoose_topic(message: types.Message):
        user_id = message.from_user.id
        data = load_data()

        user_name = None
        for topic in data["topics"]:
            if topic.get("user") and (str(message.from_user.id) in topic["user"] or message.from_user.full_name in topic["user"]):
                user_name = topic["user"]
                break

        if not user_name:
            await message.answer("👤 Введите имя и фамилию:", reply_markup=types.ReplyKeyboardRemove())
            pending[user_id] = {"state": "await_name_rechoose"}
            return

        free = [t for t in data["topics"] if not t.get("user")]
        if not free:
            await message.answer("❌ Нет свободных тем для выбора.", reply_markup=back_kb)
            return

        kb = ReplyKeyboardBuilder()
        for t in free:
            kb.add(KeyboardButton(text=t["name"]))
        kb.add(KeyboardButton(text="🔙 Назад"))
        kb.adjust(1, 1)
        await message.answer("📋 Выберите новую тему из доступных:", reply_markup=kb.as_markup(resize_keyboard=True))
        pending[user_id] = {"state": "rechoosing", "name": user_name}

    @dp.message(lambda m: m.from_user.id in pending and pending[m.from_user.id]["state"] == "rechoosing")
    async def confirm_rechoose_topic(message: types.Message):
        user_id = message.from_user.id
        name = pending[user_id]["name"]
        choice = message.text.strip()
        data = load_data()

        if choice == "🔙 Назад":
            pending.pop(user_id, None)
            is_admin = message.from_user.id in data.get("admin_ids", [])
            await message.answer("🔙 Возврат в меню.", reply_markup=main_keyboard(is_admin))
            return

        chosen = next((t for t in data["topics"] if t["name"] == choice), None)
        if not chosen:
            await message.answer("❌ Такой темы нет или она недоступна. Выберите другую.")
            return

        if chosen.get("user"):
            is_admin = message.from_user.id in data.get("admin_ids", [])
            await message.answer("❌ Эта тема уже занята.", reply_markup=main_keyboard(is_admin))
            pending.pop(user_id, None)
            return

        for t in data["topics"]:
            if t.get("user") == name:
                t["user"] = None

        chosen["user"] = name
        save_data(data)

        await message.answer("✅ Тема успешно изменена! Теперь выберите новое время выступления:",
                             reply_markup=time_selection_keyboard(data.get("time_slots", [])))
        pending[user_id] = {"state": "choosing_time", "name": name, "topic": chosen["name"], "topic_id": chosen["id"]}

    @dp.message(lambda m: m.from_user.id in pending and pending[m.from_user.id]["state"] == "await_name_rechoose")
    async def got_name_rechoose(message: types.Message):
        user_id = message.from_user.id
        name = message.text.strip()
        data = load_data()

        user_topics = [t for t in data["topics"] if t.get("user") == name]
        if not user_topics:
            is_admin = message.from_user.id in data.get("admin_ids", [])
            await message.answer("❌ У вас нет занятых тем по этому имени.", reply_markup=main_keyboard(is_admin))
            pending.pop(user_id, None)
            return

        free = [t for t in data["topics"] if not t.get("user")]
        if not free:
            await message.answer("❌ Нет свободных тем для выбора.", reply_markup=back_kb)
            pending.pop(user_id, None)
            return

        kb = ReplyKeyboardBuilder()
        for t in free:
            kb.add(KeyboardButton(text=t["name"]))
        kb.add(KeyboardButton(text="🔙 Назад"))
        kb.adjust(1, 1)
        await message.answer("📋 Выберите новую тему из доступных:", reply_markup=kb.as_markup(resize_keyboard=True))
        pending[user_id] = {"state": "rechoosing", "name": name}

    # Перевыбрать время
    @dp.message(lambda m: m.text == "⏰ Перевыбрать время")
    async def rechoose_time(message: types.Message):
        user_id = message.from_user.id
        data = load_data()

        user_time_slot = next((slot for slot in data.get("time_slots", []) if slot["user"] == message.from_user.full_name or message.from_user.full_name in slot["user"] or slot["user"] == str(message.from_user.id)), None)

        if not user_time_slot:
            await message.answer("👤 Введите имя и фамилию:", reply_markup=types.ReplyKeyboardRemove())
            pending[user_id] = {"state": "await_name_rechoose_time"}
            return

        await message.answer(
            f"⏰ Текущее время выступления: {user_time_slot['slot']}. Выберите новое время выступления:",
            reply_markup=time_selection_keyboard(data.get("time_slots", []))
        )
        pending[user_id] = {"state": "rechoosing_time", "old_slot": user_time_slot["slot"], "user": user_time_slot["user"]}

    @dp.message(lambda m: m.from_user.id in pending and pending[m.from_user.id]["state"] == "rechoosing_time")
    async def confirm_rechoose_time(message: types.Message):
        user_id = message.from_user.id
        old_slot = pending[user_id]["old_slot"]
        user_name = pending[user_id]["user"]
        time_choice = message.text.strip()

        if time_choice == "🔙 Назад":
            pending.pop(user_id, None)
            data = load_data()
            is_admin = message.from_user.id in data.get("admin_ids", [])
            await message.answer("🔙 Возврат в меню.", reply_markup=main_keyboard(is_admin))
            return

        try:
            time_slot = int(time_choice.replace("⏰ ", ""))
            if time_slot < 1 or time_slot > 7:
                await message.answer("⏰ Пожалуйста, выберите время от 1 до 7.")
                return
        except ValueError:
            await message.answer("⏰ Пожалуйста, выберите время от 1 до 7.")
            return

        data = load_data()
        existing_slot = next((slot for slot in data.get("time_slots", []) if slot["slot"] == time_slot), None)
        if existing_slot and existing_slot["user"] != user_name:
            await message.answer(
                f"⏰ Время {time_slot} уже занято пользователем {existing_slot['user']}. Выберите другое время:",
                reply_markup=time_selection_keyboard(data.get("time_slots", []))
            )
            return

        new_time_slots = [slot for slot in data.get("time_slots", []) if slot["user"] != user_name]
        new_time_slots.append({"slot": time_slot, "user": user_name})
        data["time_slots"] = new_time_slots
        save_data(data)

        await message.answer(f"✅ Время выступления успешно изменено с {old_slot} на {time_slot}!",
                             reply_markup=topic_actions_keyboard())
        pending.pop(user_id, None)

    @dp.message(lambda m: m.from_user.id in pending and pending[m.from_user.id]["state"] == "await_name_rechoose_time")
    async def got_name_rechoose_time(message: types.Message):
        user_id = message.from_user.id
        name = message.text.strip()
        data = load_data()

        user_time_slot = next((slot for slot in data.get("time_slots", []) if slot["user"] == name), None)
        if not user_time_slot:
            is_admin = message.from_user.id in data.get("admin_ids", [])
            await message.answer("❌ У вас нет занятого времени по этому имени.", reply_markup=main_keyboard(is_admin))
            pending.pop(user_id, None)
            return

        await message.answer(
            f"⏰ Текущее время выступления: {user_time_slot['slot']}. Выберите новое время выступления:",
            reply_markup=time_selection_keyboard(data.get("time_slots", []))
        )
        pending[user_id] = {"state": "rechoosing_time", "old_slot": user_time_slot["slot"], "user": user_time_slot["user"]}

    # Сбросить тему
    @dp.message(lambda m: m.text == "❌ Сбросить тему")
    async def reset_topic(message: types.Message):
        user_id = message.from_user.id
        data = load_data()

        user_topic = next((t for t in data["topics"] if t.get("user") and (str(message.from_user.id) in t.get("user") or message.from_user.full_name in t.get("user"))), None)

        if user_topic:
            user_topic["user"] = None
            data["time_slots"] = [slot for slot in data.get("time_slots", []) if slot["user"] != message.from_user.full_name and message.from_user.full_name not in slot["user"] and slot["user"] != str(message.from_user.id)]
            save_data(data)
            is_admin = message.from_user.id in data.get("admin_ids", [])
            await message.answer("✅ Ваша тема сброшена. Вы можете занять новую тему.", reply_markup=main_keyboard(is_admin))
        else:
            await message.answer("👤 Введите имя и фамилию для сброса темы:", reply_markup=types.ReplyKeyboardRemove())
            pending[user_id] = {"state": "await_name_reset"}

    @dp.message(lambda m: m.from_user.id in pending and pending[m.from_user.id]["state"] == "await_name_reset")
    async def got_name_reset(message: types.Message):
        user_id = message.from_user.id
        name = message.text.strip()
        data = load_data()

        user_topics = [t for t in data["topics"] if t.get("user") == name]
        if user_topics:
            for topic in user_topics:
                topic["user"] = None
            data["time_slots"] = [slot for slot in data.get("time_slots", []) if slot["user"] != name]
            save_data(data)
            is_admin = message.from_user.id in data.get("admin_ids", [])
            await message.answer(f"✅ Все темы, занятые под именем '{name}', были сброшены.", reply_markup=main_keyboard(is_admin))
        else:
            is_admin = message.from_user.id in data.get("admin_ids", [])
            await message.answer(f"❌ Нет тем, занятых под именем '{name}'.", reply_markup=main_keyboard(is_admin))
        pending.pop(user_id, None)

    @dp.message(lambda m: m.text == "🔄 Обновить список тем")
    async def admin_update_manual(message: types.Message):
        data = load_data()
        if message.from_user.id not in data.get("admin_ids", []):
            await message.answer("❌ У вас нет прав.", reply_markup=back_kb)
            return
        await message.answer("📋 Отправьте новый список тем, по одному на строке:",
                             reply_markup=types.ReplyKeyboardRemove())
        pending[message.from_user.id] = {"state": "admin_manual"}

    @dp.message(lambda m: m.from_user.id in pending and pending[m.from_user.id]["state"] == "admin_manual")
    async def admin_save_manual(message: types.Message):
        data = load_data()
        if message.from_user.id not in data.get("admin_ids", []):
            pending.pop(message.from_user.id, None)
            await message.answer("❌ У вас нет прав.", reply_markup=back_kb)
            return

        lines = [l.strip() for l in message.text.splitlines() if l.strip()]
        new_topics = [{"id": i + 1, "name": name, "user": None} for i, name in enumerate(lines)]

        # Очищаем все временные слоты при обновлении тем
        data["topics"] = new_topics
        data["time_slots"] = []  # Сбрасываем все временные слоты
        save_data(data)

        pending.pop(message.from_user.id, None)
        await message.answer(f"✅ Список тем обновлён вручную ({len(new_topics)} тем). Все временные слоты сброшены.",
                             reply_markup=main_keyboard(True))
    
    @dp.message(lambda m: m.text == "🔙 Назад")
    async def back_to_main(message: types.Message):
        data = load_data()
        is_admin = message.from_user.id in data.get("admin_ids", [])
        await message.answer("🏠 Главное меню:", reply_markup=main_keyboard(is_admin))

    logger.info("Bot started polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        print("Bot stopped")
