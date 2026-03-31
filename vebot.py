import telebot
import random
import time
import sqlite3
from datetime import datetime, timedelta
import string

TOKEN = "8452163384:AAE0PEmhk8eWmMga7PuUPRF3gIEDlfumCek"
bot = telebot.TeleBot(TOKEN)

# ===== НАСТРОЙКИ =====
BASE_COOLDOWN = 60
BASE_CASINO_COOLDOWN = 120
BOXES_COOLDOWN = 100
ADMIN_CODE = "Быстро открыл мне админ панель зука"

# ===== БД =====
conn = sqlite3.connect("bot.db", check_same_thread=False)

def execute(query, params=()):
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    return cur

# Создаём таблицы
execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    coins INTEGER DEFAULT 0,
    last_game INTEGER DEFAULT 0,
    casino_last INTEGER DEFAULT 0,
    reg_date TEXT,
    referrer_id INTEGER,
    wins INTEGER DEFAULT 0,
    is_passed_captcha INTEGER DEFAULT 0,
    reduction INTEGER DEFAULT 0,
    daily_last INTEGER DEFAULT 0,
    boxes_last INTEGER DEFAULT 0
)
""")

try:
    execute("ALTER TABLE users ADD COLUMN boxes_last INTEGER DEFAULT 0")
except:
    pass

try:
    execute("ALTER TABLE users ADD COLUMN username TEXT DEFAULT ''")
except:
    pass

# Таблица для банов
execute("""
CREATE TABLE IF NOT EXISTS bans (
    user_id INTEGER PRIMARY KEY,
    ban_until INTEGER,
    reason TEXT DEFAULT ''
)
""")

# Таблица для промокодов
execute("""
CREATE TABLE IF NOT EXISTS promocodes (
    code TEXT PRIMARY KEY,
    max_uses INTEGER,
    current_uses INTEGER DEFAULT 0,
    reward INTEGER,
    created_at INTEGER
)
""")

# Таблица использованных промокодов
execute("""
CREATE TABLE IF NOT EXISTS used_promocodes (
    user_id INTEGER,
    code TEXT,
    used_at INTEGER,
    PRIMARY KEY (user_id, code)
)
""")

execute("""
CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    status TEXT DEFAULT 'pending'
)
""")

# ===== МУЛЬТИПЛЕЕР С КОМНАТАМИ =====
rooms = {}
player_nicks = {}
player_room = {}

def generate_room_id():
    while True:
        letters = ''.join(random.choices(string.ascii_uppercase, k=2))
        number = random.randint(0, 9)
        room_id = f"{letters}{number}"
        if room_id not in rooms:
            return room_id

def get_user_data(user_id, referrer_id=None):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cur.fetchone()
    if not user:
        date_now = datetime.now().strftime("%Y-%m-%d")
        username = ""
        try:
            user_info = bot.get_chat(user_id)
            username = user_info.username or ""
        except:
            pass
        execute("INSERT INTO users (user_id, reg_date, referrer_id, username) VALUES (?, ?, ?, ?)", 
                (user_id, date_now, referrer_id, username))
        cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user = cur.fetchone()
    
    return {
        "user_id": user[0], "coins": user[1], "last_game": user[2],
        "casino_last": user[3], "reg_date": user[4], "referrer_id": user[5],
        "wins": user[6], "captcha": user[7], "reduction": user[8],
        "daily_last": user[9], "boxes_last": user[10], "username": user[11] if len(user) > 11 else ""
    }

def update_user(user_id, field, value):
    execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))

def safe_update_coins(user_id, delta):
    u = get_user_data(user_id)
    new_balance = u['coins'] + delta
    if new_balance < 0:
        new_balance = 0
    update_user(user_id, "coins", new_balance)

def is_user_banned(user_id):
    cur = conn.cursor()
    cur.execute("SELECT ban_until FROM bans WHERE user_id=?", (user_id,))
    result = cur.fetchone()
    if result:
        ban_until = result[0]
        if ban_until > int(time.time()):
            return True, ban_until
        else:
            execute("DELETE FROM bans WHERE user_id=?", (user_id,))
    return False, 0

def get_ban_time_text(ban_until):
    remaining = ban_until - int(time.time())
    days = remaining // 86400
    hours = (remaining % 86400) // 3600
    minutes = (remaining % 3600) // 60
    seconds = remaining % 60
    return f"{days}д {hours}ч {minutes}м {seconds}с"

# ===== КНОПКИ =====
def main_menu():
    m = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add("🎮 Мини-игры", "👤 Профиль")
    m.add("🛒 Магазин", "🎁 Ежедневный бонус")
    m.add("👥 Мультиплеер", "🎫 Промокод")
    return m

def games_menu():
    m = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add("🎯 Угадай число", "🎰 Казик")
    m.add("📦 Коробки")
    m.add("⬅️ Назад")
    return m

def admin_menu():
    m = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add("📑 Заявки", "💸 Выдать монеты")
    m.add("📋 Все пользователи", "📢 Рассылка")
    m.add("🔨 Бан мультиплеер", "📋 Список банов")
    m.add("🎫 Создать промокод", "📋 Список промокодов")
    m.add("⬅️ Назад")
    return m

def battle_menu():
    m = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = telebot.types.KeyboardButton("⚔️ Ударить")
    btn2 = telebot.types.KeyboardButton("💊 Лечиться")
    btn3 = telebot.types.KeyboardButton("🚪 Выйти из боя")
    m.add(btn1, btn2)
    m.add(btn3)
    return m

# ===== ПРОМОКОДЫ =====
@bot.message_handler(func=lambda m: m.text == "🎫 Промокод")
def promo_code_menu(message):
    msg = bot.send_message(message.chat.id, "🎫 **Введите промокод:**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_promo_code)

def process_promo_code(message):
    uid = message.from_user.id
    code = message.text.strip().upper()
    
    # Проверяем существование промокода
    cur = conn.cursor()
    cur.execute("SELECT max_uses, current_uses, reward FROM promocodes WHERE code=?", (code,))
    promo = cur.fetchone()
    
    if not promo:
        bot.send_message(message.chat.id, "❌ Промокод не найден!")
        return
    
    max_uses, current_uses, reward = promo
    
    # Проверяем, не использовал ли уже пользователь этот промокод
    cur.execute("SELECT * FROM used_promocodes WHERE user_id=? AND code=?", (uid, code))
    if cur.fetchone():
        bot.send_message(message.chat.id, "❌ Вы уже использовали этот промокод!")
        return
    
    # Проверяем лимит активаций
    if current_uses >= max_uses:
        bot.send_message(message.chat.id, "❌ Промокод больше не активен (достигнут лимит активаций)!")
        return
    
    # Активируем промокод
    safe_update_coins(uid, reward)
    execute("UPDATE promocodes SET current_uses = current_uses + 1 WHERE code=?", (code,))
    execute("INSERT INTO used_promocodes (user_id, code, used_at) VALUES (?, ?, ?)", 
            (uid, code, int(time.time())))
    
    bot.send_message(message.chat.id, f"✅ Промокод активирован! Вы получили +{reward}💰 монет!")

# ===== АДМИНКА - СОЗДАНИЕ ПРОМОКОДА =====
@bot.message_handler(func=lambda m: m.text == "🎫 Создать промокод")
def create_promo_start(message):
    msg = bot.send_message(message.chat.id, "🎫 **Создание промокода**\n\nВведите данные в формате:\n`НАЗВАНИЕ КОЛИЧЕСТВО_АКТИВАЦИЙ СУММА`\n\nПример: `SUPER100 50 500`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, create_promo_process)

def create_promo_process(message):
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.send_message(message.chat.id, "❌ Неверный формат! Используйте: НАЗВАНИЕ КОЛИЧЕСТВО_АКТИВАЦИЙ СУММА")
            return
        
        code = parts[0].upper()
        max_uses = int(parts[1])
        reward = int(parts[2])
        
        if max_uses <= 0 or reward <= 0:
            bot.send_message(message.chat.id, "❌ Количество активаций и сумма должны быть положительными!")
            return
        
        # Проверяем, не существует ли уже такой промокод
        cur = conn.cursor()
        cur.execute("SELECT * FROM promocodes WHERE code=?", (code,))
        if cur.fetchone():
            bot.send_message(message.chat.id, f"❌ Промокод `{code}` уже существует!", parse_mode="Markdown")
            return
        
        execute("INSERT INTO promocodes (code, max_uses, reward, created_at) VALUES (?, ?, ?, ?)",
                (code, max_uses, reward, int(time.time())))
        
        bot.send_message(message.chat.id, f"✅ Промокод создан!\n\nКод: `{code}`\nАктиваций: {max_uses}\nНаграда: {reward}💰", parse_mode="Markdown")
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Ошибка! Убедитесь, что количество активаций и сумма - это числа.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка! {e}")

@bot.message_handler(func=lambda m: m.text == "📋 Список промокодов")
def list_promocodes(message):
    cur = conn.cursor()
    cur.execute("SELECT code, max_uses, current_uses, reward, created_at FROM promocodes ORDER BY created_at DESC")
    promos = cur.fetchall()
    
    if not promos:
        bot.send_message(message.chat.id, "📭 Нет активных промокодов")
        return
    
    text = "🎫 **Список промокодов:**\n\n"
    for promo in promos:
        code, max_uses, current_uses, reward, created_at = promo
        text += f"Код: `{code}`\n"
        text += f"Активаций: {current_uses}/{max_uses}\n"
        text += f"Награда: {reward}💰\n"
        text += f"Создан: {datetime.fromtimestamp(created_at).strftime('%d.%m.%Y')}\n"
        text += "─" * 20 + "\n"
        
        if len(text) > 3800:
            bot.send_message(message.chat.id, text, parse_mode="Markdown")
            text = ""
    
    if text:
        bot.send_message(message.chat.id, text, parse_mode="Markdown")

# ===== МУЛЬТИПЛЕЕР =====
@bot.message_handler(func=lambda m: m.text == "👥 Мультиплеер")
def multiplayer_menu(message):
    uid = message.from_user.id
    
    banned, ban_until = is_user_banned(uid)
    if banned:
        time_text = get_ban_time_text(ban_until)
        bot.send_message(message.chat.id, f"❌ **Вы забанены в мультиплеере!**\n\nОсталось: {time_text}\nПричина: Нарушение правил", 
                        parse_mode="Markdown")
        return
    
    if uid not in player_nicks:
        msg = bot.send_message(message.chat.id, "📝 Напишите свой ник (3-20 символов):")
        bot.register_next_step_handler(msg, set_nick)
        return
    
    show_multiplayer_menu(message)

def set_nick(message):
    uid = message.from_user.id
    nick = message.text.strip()
    
    if len(nick) < 3 or len(nick) > 20:
        msg = bot.send_message(message.chat.id, "❌ Ник должен быть от 3 до 20 символов!\nПопробуйте снова:")
        bot.register_next_step_handler(msg, set_nick)
        return
    
    player_nicks[uid] = nick
    bot.send_message(message.chat.id, f"✅ Ваш ник принят: {nick}\n\nТеперь вы можете играть в мультиплеер!")
    show_multiplayer_menu(message)

def show_multiplayer_menu(message):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    btn_create = telebot.types.InlineKeyboardButton("🏠 Создать комнату", callback_data="create_room")
    btn_join = telebot.types.InlineKeyboardButton("🚪 Присоединиться", callback_data="join_room")
    kb.add(btn_create, btn_join)
    
    bot.send_message(message.chat.id, "🎮 **Мультиплеер**\n\nВыберите действие:", 
                     reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "create_room")
def create_room(call):
    uid = call.from_user.id
    
    banned, ban_until = is_user_banned(uid)
    if banned:
        time_text = get_ban_time_text(ban_until)
        bot.answer_callback_query(call.id, f"Вы забанены! Осталось: {time_text}", show_alert=True)
        return
    
    if uid in player_room:
        bot.answer_callback_query(call.id, "❌ Вы уже в комнате!", show_alert=True)
        return
    
    room_id = generate_room_id()
    
    rooms[room_id] = {
        "p1": uid,
        "p2": None,
        "p1_hp": 100,
        "p2_hp": 100,
        "turn": 0,
        "p1_nick": player_nicks[uid],
        "p2_nick": None,
        "status": "waiting"
    }
    player_room[uid] = room_id
    
    text = f"🏠 **Комната создана!**\n\n"
    text += f"ID комнаты: `{room_id}`\n"
    text += f"Ваш ник: {player_nicks[uid]}\n\n"
    text += f"📋 Отправьте этот ID другу, чтобы он присоединился!\n"
    text += f"⏳ Ожидание соперника..."
    
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_room_{room_id}"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                          reply_markup=kb, parse_mode="Markdown")
    bot.answer_callback_query(call.id, "Комната создана!")

@bot.callback_query_handler(func=lambda call: call.data == "join_room")
def ask_room_id(call):
    uid = call.from_user.id
    
    banned, ban_until = is_user_banned(uid)
    if banned:
        time_text = get_ban_time_text(ban_until)
        bot.answer_callback_query(call.id, f"Вы забанены! Осталось: {time_text}", show_alert=True)
        return
    
    msg = bot.send_message(call.message.chat.id, "🔑 Введите ID комнаты для подключения:\n(Формат: 2 буквы и 1 цифра, например: AB7)")
    bot.register_next_step_handler(msg, process_join_room)

def process_join_room(message):
    uid = message.from_user.id
    
    banned, ban_until = is_user_banned(uid)
    if banned:
        time_text = get_ban_time_text(ban_until)
        bot.send_message(message.chat.id, f"❌ Вы забанены! Осталось: {time_text}")
        return
    
    room_id = message.text.strip().upper()
    
    if uid in player_room:
        bot.send_message(message.chat.id, "❌ Вы уже в комнате!")
        return
    
    if room_id not in rooms:
        bot.send_message(message.chat.id, f"❌ Комната с ID `{room_id}` не найдена!", parse_mode="Markdown")
        return
    
    room = rooms[room_id]
    
    if room["status"] != "waiting":
        bot.send_message(message.chat.id, "❌ Эта комната уже в бою!")
        return
    
    if room["p2"] is not None:
        bot.send_message(message.chat.id, "❌ Комната уже заполнена!")
        return
    
    room["p2"] = uid
    room["p2_nick"] = player_nicks[uid]
    room["turn"] = random.randint(0, 1)
    room["status"] = "fighting"
    
    player_room[uid] = room_id
    start_battle(room_id)

def start_battle(room_id):
    room = rooms[room_id]
    
    for player_id, is_p1 in [(room["p1"], True), (room["p2"], False)]:
        try:
            turn_text = "⚔️ **ВАШ ХОД!**" if (is_p1 and room["turn"] == 0) or (not is_p1 and room["turn"] == 1) else "⏳ Ход соперника..."
            opponent = room["p2_nick"] if is_p1 else room["p1_nick"]
            
            bot.send_message(player_id, 
                f"⚔️ **БОЙ НАЧАЛСЯ!** ⚔️\n\n"
                f"Комната: `{room_id}`\n"
                f"Соперник: {opponent}\n\n"
                f"{turn_text}\n\n"
                f"{get_battle_status(room_id)}", 
                reply_markup=battle_menu(), parse_mode="Markdown")
        except Exception as e:
            print(f"Ошибка: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_room_"))
def cancel_room(call):
    uid = call.from_user.id
    room_id = call.data.split("_")[2]
    
    if room_id in rooms and rooms[room_id]["p1"] == uid:
        del rooms[room_id]
        if uid in player_room:
            del player_room[uid]
        bot.edit_message_text("✅ Комната отменена", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Комната удалена")

def get_battle_status(room_id):
    room = rooms.get(room_id)
    if not room:
        return "Бой завершён"
    
    status = f"**Статус боя:**\n"
    status += f"{room['p1_nick']}: ❤️ {room['p1_hp']}/100 HP\n"
    status += f"{room['p2_nick']}: ❤️ {room['p2_hp']}/100 HP"
    return status

@bot.message_handler(func=lambda m: m.text == "⚔️ Ударить")
def battle_attack(message):
    uid = message.from_user.id
    
    if uid not in player_room:
        bot.send_message(message.chat.id, "❌ Вы не в бою!", reply_markup=main_menu())
        return
    
    room_id = player_room[uid]
    room = rooms.get(room_id)
    
    if not room or room["status"] != "fighting":
        bot.send_message(message.chat.id, "❌ Бой завершён!", reply_markup=main_menu())
        if uid in player_room:
            del player_room[uid]
        return
    
    is_p1 = (room["p1"] == uid)
    current_turn = room["turn"]
    
    if (is_p1 and current_turn != 0) or (not is_p1 and current_turn != 1):
        bot.send_message(message.chat.id, "⏳ Сейчас не ваш ход!", reply_markup=battle_menu())
        return
    
    damage = random.randint(10, 30)
    is_critical = random.randint(1, 100) <= 20
    
    if is_critical:
        damage = int(damage * 1.5)
    
    if is_p1:
        room["p2_hp"] = max(0, room["p2_hp"] - damage)
        attacker = room["p1_nick"]
        defender = room["p2_nick"]
        target_hp = room["p2_hp"]
    else:
        room["p1_hp"] = max(0, room["p1_hp"] - damage)
        attacker = room["p2_nick"]
        defender = room["p1_nick"]
        target_hp = room["p1_hp"]
    
    crit_text = " **КРИТИЧЕСКИЙ УДАР!**" if is_critical else ""
    bot.send_message(message.chat.id, f"⚔️ {attacker}{crit_text} нанёс {damage} урона {defender}!\n\n❤️ У {defender} осталось {target_hp}/100 HP")
    
    if room["p1_hp"] <= 0:
        end_battle(room_id, room["p2"])
        return
    elif room["p2_hp"] <= 0:
        end_battle(room_id, room["p1"])
        return
    
    room["turn"] = 1 - room["turn"]
    
    for player in [room["p1"], room["p2"]]:
        try:
            is_player_p1 = (player == room["p1"])
            turn_text = "⚔️ **ВАШ ХОД!**" if (is_player_p1 and room["turn"] == 0) or (not is_player_p1 and room["turn"] == 1) else "⏳ Ход соперника..."
            bot.send_message(player, f"{turn_text}\n\n{get_battle_status(room_id)}", reply_markup=battle_menu(), parse_mode="Markdown")
        except Exception as e:
            print(f"Ошибка: {e}")

@bot.message_handler(func=lambda m: m.text == "💊 Лечиться")
def battle_heal(message):
    uid = message.from_user.id
    
    if uid not in player_room:
        bot.send_message(message.chat.id, "❌ Вы не в бою!", reply_markup=main_menu())
        return
    
    room_id = player_room[uid]
    room = rooms.get(room_id)
    
    if not room or room["status"] != "fighting":
        bot.send_message(message.chat.id, "❌ Бой завершён!", reply_markup=main_menu())
        if uid in player_room:
            del player_room[uid]
        return
    
    is_p1 = (room["p1"] == uid)
    current_turn = room["turn"]
    
    if (is_p1 and current_turn != 0) or (not is_p1 and current_turn != 1):
        bot.send_message(message.chat.id, "⏳ Сейчас не ваш ход!", reply_markup=battle_menu())
        return
    
    heal = random.randint(15, 35)
    if is_p1:
        room["p1_hp"] = min(100, room["p1_hp"] + heal)
        healed_hp = room["p1_hp"]
        healer = room["p1_nick"]
    else:
        room["p2_hp"] = min(100, room["p2_hp"] + heal)
        healed_hp = room["p2_hp"]
        healer = room["p2_nick"]
    
    bot.send_message(message.chat.id, f"💊 {healer} исцелился на {heal} HP!\n\n❤️ Теперь у {healer} {healed_hp}/100 HP")
    
    room["turn"] = 1 - room["turn"]
    
    for player in [room["p1"], room["p2"]]:
        try:
            is_player_p1 = (player == room["p1"])
            turn_text = "⚔️ **ВАШ ХОД!**" if (is_player_p1 and room["turn"] == 0) or (not is_player_p1 and room["turn"] == 1) else "⏳ Ход соперника..."
            bot.send_message(player, f"{turn_text}\n\n{get_battle_status(room_id)}", reply_markup=battle_menu(), parse_mode="Markdown")
        except Exception as e:
            print(f"Ошибка: {e}")

@bot.message_handler(func=lambda m: m.text == "🚪 Выйти из боя")
def battle_exit(message):
    uid = message.from_user.id
    
    if uid not in player_room:
        bot.send_message(message.chat.id, "❌ Вы не в бою!", reply_markup=main_menu())
        return
    
    room_id = player_room[uid]
    room = rooms.get(room_id)
    
    if room:
        # Определяем победителя
        if room["p1"] == uid:
            winner = room["p2"]
            winner_nick = room["p2_nick"] if room["p2_nick"] else "Соперник"
            loser_nick = room["p1_nick"]
        else:
            winner = room["p1"]
            winner_nick = room["p1_nick"]
            loser_nick = room["p2_nick"]
        
        # НЕ начисляем монеты за выход из боя!
        if winner:
            # Просто уведомляем, но монеты НЕ даём
            try:
                bot.send_message(winner, f"🏆 **ПОБЕДА!** 🏆\n\n{loser_nick} вышел из боя!\n\n(Победа без награды)", 
                               reply_markup=main_menu(), parse_mode="Markdown")
            except:
                pass
        
        try:
            bot.send_message(uid, f"❌ Вы вышли из боя!\n\nПобеда присуждена {winner_nick}", 
                           reply_markup=main_menu(), parse_mode="Markdown")
        except:
            pass
        
        del rooms[room_id]
    
    if uid in player_room:
        del player_room[uid]

def end_battle(room_id, winner_id):
    room = rooms.get(room_id)
    if not room:
        return
    
    winner_nick = room["p1_nick"] if room["p1"] == winner_id else room["p2_nick"]
    loser_id = room["p2"] if room["p1"] == winner_id else room["p1"]
    loser_nick = room["p2_nick"] if room["p1"] == winner_id else room["p1_nick"]
    
    # Награждаем победителя только за честную победу (не за выход)
    safe_update_coins(winner_id, 400)
    u = get_user_data(winner_id)
    update_user(winner_id, "wins", u['wins'] + 1)
    
    try:
        bot.send_message(winner_id, f"🏆 **ПОБЕДА!** 🏆\n\nВы победили {loser_nick}!\n\nВы получаете +400💰 монет!", 
                       reply_markup=main_menu(), parse_mode="Markdown")
    except:
        pass
    
    try:
        bot.send_message(loser_id, f"💀 **ПОРАЖЕНИЕ!** 💀\n\nВы проиграли {winner_nick}!\n\nПопробуйте снова!", 
                       reply_markup=main_menu(), parse_mode="Markdown")
    except:
        pass
    
    for player in [room["p1"], room["p2"]]:
        if player in player_room:
            del player_room[player]
    
    del rooms[room_id]

# ===== АДМИНКА - БАН МУЛЬТИПЛЕЕРА =====
@bot.message_handler(func=lambda m: m.text == "🔨 Бан мультиплеер")
def ban_mp_start(message):
    msg = bot.send_message(message.chat.id, "🔨 **Бан мультиплеера**\n\nВведите: ID пользователя и время бана\nФормат: `ID ДД:ЧЧ:ММ:СС`\n\nПример: `123456789 00:01:30:00` (1 день 30 часов)\n\nИли: `@username 00:00:05:00` (5 минут)", parse_mode="Markdown")
    bot.register_next_step_handler(msg, ban_mp_process)

def ban_mp_process(message):
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "❌ Неверный формат! Используйте: ID ДД:ЧЧ:ММ:СС")
            return
        
        target = parts[0]
        time_str = parts[1]
        
        time_parts = time_str.split(":")
        if len(time_parts) != 4:
            bot.send_message(message.chat.id, "❌ Неверный формат времени! Используйте: ДД:ЧЧ:ММ:СС")
            return
        
        days = int(time_parts[0])
        hours = int(time_parts[1])
        minutes = int(time_parts[2])
        seconds = int(time_parts[3])
        
        ban_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds
        ban_until = int(time.time()) + ban_seconds
        
        if target.startswith("@"):
            username = target[1:]
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE username=?", (username,))
            result = cur.fetchone()
            if result:
                user_id = result[0]
            else:
                try:
                    user_info = bot.get_chat(target)
                    user_id = user_info.id
                except:
                    bot.send_message(message.chat.id, f"❌ Пользователь @{username} не найден!")
                    return
        else:
            user_id = int(target)
        
        cur = conn.cursor()
        cur.execute("SELECT ban_until FROM bans WHERE user_id=?", (user_id,))
        existing = cur.fetchone()
        
        if existing:
            execute("UPDATE bans SET ban_until=?, reason='Нарушение правил' WHERE user_id=?", (ban_until, user_id))
        else:
            execute("INSERT INTO bans (user_id, ban_until, reason) VALUES (?, ?, ?)", (user_id, ban_until, "Нарушение правил"))
        
        if user_id in player_room:
            room_id = player_room[user_id]
            if room_id in rooms:
                room = rooms[room_id]
                if room["p1"] == user_id:
                    winner = room["p2"]
                else:
                    winner = room["p1"]
                
                if winner:
                    safe_update_coins(winner, 400)
                    u = get_user_data(winner)
                    update_user(winner, "wins", u['wins'] + 1)
                    try:
                        bot.send_message(winner, f"🏆 **ПОБЕДА!** 🏆\n\nСоперник был забанен!\n\nВы получаете +400💰 монет!", 
                                       reply_markup=main_menu(), parse_mode="Markdown")
                    except:
                        pass
                
                del rooms[room_id]
            del player_room[user_id]
        
        ban_text = f"{days}д {hours}ч {minutes}м {seconds}с" if days > 0 else f"{hours}ч {minutes}м {seconds}с"
        
        try:
            bot.send_message(user_id, f"⚠️ **Вы забанены в мультиплеере!**\n\nВремя бана: {ban_text}\nПричина: Нарушение правил\n\nПосле окончания бана вы сможете снова играть.", 
                           parse_mode="Markdown")
        except:
            pass
        
        bot.send_message(message.chat.id, f"✅ Пользователь {target} забанен в мультиплеере на {ban_text}")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка! {e}")

@bot.message_handler(func=lambda m: m.text == "📋 Список банов")
def list_bans(message):
    cur = conn.cursor()
    cur.execute("SELECT user_id, ban_until, reason FROM bans ORDER BY ban_until")
    bans = cur.fetchall()
    
    if not bans:
        bot.send_message(message.chat.id, "📭 Нет активных банов")
        return
    
    text = "🔨 **Активные баны:**\n\n"
    for ban in bans:
        user_id, ban_until, reason = ban
        if ban_until > int(time.time()):
            time_left = get_ban_time_text(ban_until)
            cur.execute("SELECT username FROM users WHERE user_id=?", (user_id,))
            user_data = cur.fetchone()
            username = f"@{user_data[0]}" if user_data and user_data[0] else str(user_id)
            text += f"👤 {username} (ID: {user_id})\n⏱️ Осталось: {time_left}\n📝 Причина: {reason}\n\n"
    
    if len(text) > 4000:
        text = text[:4000]
    
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton("🔓 Разбанить", callback_data="unban_menu"))
    
    bot.send_message(message.chat.id, text, reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "unban_menu")
def unban_menu(call):
    cur = conn.cursor()
    cur.execute("SELECT user_id, ban_until FROM bans")
    bans = cur.fetchall()
    
    if not bans:
        bot.answer_callback_query(call.id, "Нет активных банов")
        return
    
    kb = telebot.types.InlineKeyboardMarkup(row_width=1)
    for ban in bans:
        user_id, ban_until = ban
        if ban_until > int(time.time()):
            cur.execute("SELECT username FROM users WHERE user_id=?", (user_id,))
            user_data = cur.fetchone()
            username = f"@{user_data[0]}" if user_data and user_data[0] else str(user_id)
            kb.add(telebot.types.InlineKeyboardButton(f"🔓 {username}", callback_data=f"unban_{user_id}"))
    
    kb.add(telebot.types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_unban"))
    
    bot.edit_message_text("🔓 Выберите пользователя для разбана:", call.message.chat.id, call.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("unban_"))
def process_unban(call):
    user_id = int(call.data.split("_")[1])
    execute("DELETE FROM bans WHERE user_id=?", (user_id,))
    
    try:
        bot.send_message(user_id, "✅ **Вас разбанили в мультиплеере!**\n\nТеперь вы снова можете играть.", parse_mode="Markdown")
    except:
        pass
    
    bot.edit_message_text(f"✅ Пользователь {user_id} разбанен", call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id, "Пользователь разбанен")

@bot.callback_query_handler(func=lambda call: call.data == "cancel_unban")
def cancel_unban(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

# ===== ОСТАЛЬНОЙ КОД =====
captcha_data = {}
games_data = {}
boxes_data = {}

@bot.message_handler(commands=['start'])
def start(message):
    ref_id = None
    args = message.text.split()
    if len(args) > 1:
        try: ref_id = int(args[1])
        except: pass
    
    try:
        username = message.from_user.username or ""
        execute("UPDATE users SET username=? WHERE user_id=?", (username, message.from_user.id))
    except:
        pass
    
    user = get_user_data(message.from_user.id, ref_id)
    
    if user['captcha'] == 0:
        a = random.randint(1, 50)
        res = random.randint(49, 100)
        captcha_data[message.from_user.id] = res - a
        bot.send_message(message.chat.id, f"🤖 Капча!\nX + {a} = {res}\nЧему равен X?")
    else:
        bot.send_message(message.chat.id, "С возвращением!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.from_user.id in captcha_data)
def check_captcha(message):
    uid = message.from_user.id
    try:
        if int(message.text) == captcha_data[uid]:
            update_user(uid, "is_passed_captcha", 1)
            user = get_user_data(uid)
            if user['referrer_id']:
                ref = get_user_data(user['referrer_id'])
                update_user(ref['user_id'], "coins", ref['coins'] + 100)
                try: bot.send_message(ref['user_id'], "🎁 +100 монет за реферала!")
                except: pass
            del captcha_data[uid]
            bot.send_message(message.chat.id, "✅ Доступ открыт!", reply_markup=main_menu())
        else:
            bot.send_message(message.chat.id, "❌ Неверно.")
    except: pass

# ===== МАГАЗИН =====
@bot.message_handler(func=lambda m: m.text == "🛒 Магазин")
def shop(message):
    u = get_user_data(message.from_user.id)
    text = f"🛒 **Магазин улучшений**\n\nТвой баланс: {u['coins']} 💰\nТвоё КД уменьшено на: {u['reduction']} сек.\n\n" \
           f"⚡ **Ускоритель**: -5 секунд к КД во всех играх.\nЦена: 300 монет."
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton("Купить (-5с) за 300💰", callback_data="buy_rd"))
    bot.send_message(message.chat.id, text, reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "buy_rd")
def buy_reduction(call):
    u = get_user_data(call.from_user.id)
    if u['coins'] < 300:
        bot.answer_callback_query(call.id, "Недостаточно монет!", show_alert=True)
        return
    
    safe_update_coins(u['user_id'], -300)
    update_user(u['user_id'], "reduction", u['reduction'] + 5)
    bot.edit_message_text(f"✅ Успешно! КД короче на {u['reduction'] + 5} сек.", call.message.chat.id, call.message.message_id)

# ===== ПРОФИЛЬ =====
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def profile(message):
    u = get_user_data(message.from_user.id)
    reg_dt = datetime.strptime(u['reg_date'], "%Y-%m-%d")
    days = (datetime.now() - reg_dt).days
    text = (f"👤 **Профиль**\n\n💰 Баланс: `{u['coins']}`\n📅 В боте: `{max(days, 1)}` дн.\n"
            f"🏆 Побед: `{u['wins']}`\n⚡ Скидка КД: `{u['reduction']}` сек.\n\n"
            f"🔗 Рефка: `t.me/{bot.get_me().username}?start={u['user_id']}`")
    if u['username']:
        text += f"\n👤 Username: @{u['username']}"
    if u['user_id'] in player_nicks:
        text += f"\n🎮 Игровой ник: {player_nicks[u['user_id']]}"
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton("💸 Вывести (200 = 1⭐)", callback_data="withdraw"))
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == "withdraw")
def withdraw_init(call):
    u = get_user_data(call.from_user.id)
    if u['coins'] < 200:
        bot.answer_callback_query(call.id, "Минимум 200 монет!", show_alert=True)
        return
    stars = u['coins'] // 200
    execute("INSERT INTO withdrawals (user_id, amount) VALUES (?, ?)", (u['user_id'], u['coins']))
    update_user(u['user_id'], "coins", 0)
    bot.send_message(u['user_id'], f"✅ Заявка на {stars} ⭐ создана!")

# ===== ЕЖЕДНЕВНЫЙ БОНУС =====
@bot.message_handler(func=lambda m: m.text == "🎁 Ежедневный бонус")
def daily_bonus(message):
    uid = message.from_user.id
    u = get_user_data(uid)
    now = int(time.time())
    last = u['daily_last']
    if now - last < 86400:
        remaining = 86400 - (now - last)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        bot.send_message(message.chat.id, f"⏳ Бонус будет доступен через {hours} ч {minutes} мин")
        return
    
    safe_update_coins(uid, 100)
    update_user(uid, "daily_last", now)
    bot.send_message(message.chat.id, "🎉 Ежедневный бонус: +100 монет!")

# ===== ИГРЫ =====
@bot.message_handler(func=lambda m: m.text == "🎯 Угадай число")
def guess_start(message):
    u = get_user_data(message.from_user.id)
    now = int(time.time())
    cd = max(BASE_COOLDOWN - u['reduction'], 5)
    if now - u['last_game'] < cd:
        bot.send_message(message.chat.id, f"⏳ Подожди {cd - (now - u['last_game'])} сек")
        return
    games_data[u['user_id']] = {"n": random.randint(1, 10), "t": 3}
    bot.send_message(message.chat.id, "🔢 Я загадал число от 1 до 10. У тебя 3 попытки!")

@bot.message_handler(func=lambda m: m.text.isdigit() and m.from_user.id in games_data)
def guess_proc(message):
    uid = message.from_user.id
    data = games_data[uid]
    if int(message.text) == data["n"]:
        safe_update_coins(uid, 50)
        u = get_user_data(uid)
        update_user(uid, "wins", u['wins'] + 1)
        update_user(uid, "last_game", int(time.time()))
        del games_data[uid]
        bot.send_message(message.chat.id, "🎉 Правильно! +50 монет!")
    else:
        data["t"] -= 1
        if data["t"] <= 0:
            update_user(uid, "last_game", int(time.time()))
            bot.send_message(message.chat.id, f"❌ Попытки кончились! Было: {data['n']}")
            del games_data[uid]
        else:
            bot.send_message(message.chat.id, f"❌ Неверно! Осталось попыток: {data['t']}")

@bot.message_handler(func=lambda m: m.text == "🎰 Казик")
def casino(message):
    u = get_user_data(message.from_user.id)
    now = int(time.time())
    cd = max(BASE_CASINO_COOLDOWN - u['reduction'], 10)
    if now - u['casino_last'] < cd:
        bot.send_message(message.chat.id, f"⏳ Подожди {cd - (now - u['casino_last'])} сек")
        return

    syms = ["🍇", "🍋", "BAR", "7️⃣"]
    win = 0
    bot.send_message(message.chat.id, "🎰 КРУТИМ 10 РАЗ!")
    for i in range(10):
        spin = [random.choice(syms) for _ in range(3)]
        rew = 200 if spin.count("7️⃣") == 3 else 60 if len(set(spin)) == 1 else 0
        win += rew
        bot.send_message(message.chat.id, f"#{i+1}: {' '.join(spin)} (+{rew})")
        time.sleep(0.3)

    safe_update_coins(u['user_id'], win)
    if win > 0:
        update_user(u['user_id'], "wins", u['wins'] + 1)
    update_user(u['user_id'], "casino_last", now)
    bot.send_message(message.chat.id, f"🏁 Итог: +{win} 💰")

@bot.message_handler(func=lambda m: m.text == "📦 Коробки")
def boxes_start(message):
    u = get_user_data(message.from_user.id)
    now = int(time.time())

    cd = max(BOXES_COOLDOWN - u['reduction'], 5)
    if now - u['boxes_last'] < cd:
        remaining = cd - (now - u['boxes_last'])
        bot.send_message(message.chat.id, f"⏳ Подожди {remaining} сек перед следующей коробкой!")
        return

    correct_box = random.randint(1, 3)
    boxes_data[u['user_id']] = correct_box

    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(
        telebot.types.InlineKeyboardButton("📦 1", callback_data="box_1"),
        telebot.types.InlineKeyboardButton("📦 2", callback_data="box_2"),
        telebot.types.InlineKeyboardButton("📦 3", callback_data="box_3"),
    )

    bot.send_message(message.chat.id, "Выбери коробку:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("box_"))
def box_pick(call):
    uid = call.from_user.id

    if uid not in boxes_data:
        bot.answer_callback_query(call.id, "Сначала запусти игру!")
        return

    chosen = int(call.data.split("_")[1])
    correct = boxes_data[uid]

    if chosen == correct:
        safe_update_coins(uid, 100)
        u = get_user_data(uid)
        update_user(uid, "wins", u['wins'] + 1)
        result = "✅ Верно! +100 монет"
    else:
        safe_update_coins(uid, -50)
        result = "🚫 К сожалению, там не было приза, -50 монет"

    update_user(uid, "boxes_last", int(time.time()))
    del boxes_data[uid]

    bot.edit_message_text(result, call.message.chat.id, call.message.message_id)

# ===== АДМИНКА =====
@bot.message_handler(func=lambda m: m.text == ADMIN_CODE)
def adm_in(message):
    bot.send_message(message.chat.id, "🔐 Админка активна", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "📋 Все пользователи")
def adm_all_users(message):
    cur = conn.cursor()
    cur.execute("SELECT user_id, coins, reduction, username FROM users ORDER BY user_id")
    rows = cur.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "Нет пользователей")
        return
    text = "👥 Список пользователей:\n\n"
    for row in rows:
        user_id, coins, reduction, username = row
        if username:
            text += f"@{username} | ID: {user_id} | Монеты: {coins} | Скидка: {reduction}сек\n"
        else:
            text += f"ID: {user_id} | Монеты: {coins} | Скидка: {reduction}сек\n"
        if len(text) > 3800:
            bot.send_message(message.chat.id, text)
            text = ""
    if text:
        bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "📢 Рассылка")
def adm_mailing_start(message):
    msg = bot.send_message(message.chat.id, "📝 Введите текст для рассылки:")
    bot.register_next_step_handler(msg, adm_mailing_send)

def adm_mailing_send(message):
    text = message.text
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = cur.fetchall()
    success = 0
    fail = 0
    bot.send_message(message.chat.id, "🚀 Начинаю рассылку...")
    for user in users:
        try:
            bot.send_message(user[0], f"📢 **Рассылка от администратора**\n\n{text}", parse_mode="Markdown")
            success += 1
            time.sleep(0.05)
        except:
            fail += 1
    bot.send_message(message.chat.id, f"✅ Рассылка завершена!\n📨 Отправлено: {success}\n❌ Не доставлено: {fail}")

@bot.message_handler(func=lambda m: m.text == "📑 Заявки")
def adm_w(message):
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, amount FROM withdrawals WHERE status='pending'")
    rows = cur.fetchall()
    if not rows: 
        bot.send_message(message.chat.id, "📭 Нет активных заявок")
        return
    for r in rows:
        stars = r[2] // 200
        cur.execute("SELECT username FROM users WHERE user_id=?", (r[1],))
        user_data = cur.fetchone()
        username = f"@{user_data[0]}" if user_data and user_data[0] else str(r[1])
        kb = telebot.types.InlineKeyboardMarkup()
        kb.add(
            telebot.types.InlineKeyboardButton("✅ Выплатить", callback_data=f"a_y_{r[0]}"),
            telebot.types.InlineKeyboardButton("❌ Отклонить", callback_data=f"a_n_{r[0]}")
        )
        bot.send_message(message.chat.id, f"📑 **Заявка #{r[0]}**\n👤 Пользователь: {username}\n💰 Монет: {r[2]} ({stars}⭐)", reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("a_"))
def adm_call(call):
    _, act, wid = call.data.split("_")
    if act == "y":
        execute("UPDATE withdrawals SET status='ok' WHERE id=?", (wid,))
        bot.edit_message_text("✅ Выплачено", call.message.chat.id, call.message.message_id)
    else:
        cur = conn.cursor()
        cur.execute("SELECT user_id, amount FROM withdrawals WHERE id=?", (wid,))
        i = cur.fetchone()
        if i:
            safe_update_coins(i[0], i[1])
            execute("UPDATE withdrawals SET status='no' WHERE id=?", (wid,))
            bot.edit_message_text("❌ Возвращено", call.message.chat.id, call.message.message_id)

@bot.message_handler(func=lambda m: m.text == "💸 Выдать монеты")
def admin_give_start(message):
    msg = bot.send_message(message.chat.id, "💰 Введи: ID СУММА или @username СУММА\n\nПримеры:\n123456789 500\n@username 500")
    bot.register_next_step_handler(msg, admin_give_finish)

def admin_give_finish(message):
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "❌ Неверный формат! Используйте: ID СУММА или @username СУММА")
            return
        
        target = parts[0]
        amount = int(parts[1])
        
        if target.startswith("@"):
            username = target[1:]
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE username=?", (username,))
            result = cur.fetchone()
            if result:
                user_id = result[0]
            else:
                try:
                    user_info = bot.get_chat(target)
                    user_id = user_info.id
                    execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
                except:
                    bot.send_message(message.chat.id, f"❌ Пользователь @{username} не найден! Убедитесь, что он запустил бота.")
                    return
        else:
            user_id = int(target)
        
        safe_update_coins(user_id, amount)
        bot.send_message(message.chat.id, f"✅ Выдано {amount}💰 монет пользователю {target}")
        try:
            bot.send_message(user_id, f"✅ Вам начислено {amount}💰 монет администратором!")
        except:
            pass
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка! {e}")

@bot.message_handler(func=lambda m: m.text == "🎮 Мини-игры")
def g_list(message):
    bot.send_message(message.chat.id, "🎮 Выбери игру:", reply_markup=games_menu())

@bot.message_handler(func=lambda m: m.text == "⬅️ Назад")
def b_h(message):
    bot.send_message(message.chat.id, "🏠 Главное меню", reply_markup=main_menu())

# Запуск бота
print("🤖 Бот запущен!")
bot.polling(none_stop=True)