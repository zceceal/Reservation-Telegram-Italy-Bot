from telebot import TeleBot, types
from datetime import datetime as dt, timedelta
import sqlite3
import threading
from keepalive import keep_alive
import pytz
import time

# Initialize bot
bot = TeleBot('8375601762:AAHpBBwKIGpYHwwnED2WcFOToQhEFbm7gfo')

# Timezone
tz = pytz.timezone('Europe/Madrid') 

# Keep alive
keep_alive()

# Thread-local SQLite connection
local_storage = threading.local()
available_time_slots = {}

def get_db_connection():
    if not hasattr(local_storage, 'db'):
        local_storage.db = sqlite3.connect('reservation.db', check_same_thread=False)
        create_reservations_table()
    return local_storage.db

def create_reservations_table():
    db_connection = get_db_connection()
    cursor = db_connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reservations (
            reservation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            full_name TEXT NOT NULL,
            restaurant_link TEXT,
            num_people INTEGER NOT NULL,
            date TEXT NOT NULL,
            reservation_time TEXT NOT NULL,
            notes TEXT,
        )
    ''')
    db_connection.commit()

def save_reservation_to_db(user_id, full_name, num_people, reservation_datetime, restaurant_link=None, notes=None):
    cursor = get_db_connection().cursor()
    cursor.execute("""
        INSERT INTO reservations (user_id, full_name, num_people, date, reservation_time, restaurant_link, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        full_name,
        num_people,
        reservation_datetime.date().strftime('%Y-%m-%d'),
        reservation_datetime.strftime('%H:%M'),
        restaurant_link,
        notes
    ))
    get_db_connection().commit()

# ---- BUTTON GENERATORS ----

def generate_main_buttons():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Reserve", callback_data="reserve"),
        types.InlineKeyboardButton("Support", url="https://t.me/axelforks")
    )
    return markup

def generate_date_selection_buttons():
    markup = types.InlineKeyboardMarkup()
    now = dt.now()
    for i in range(7):
        date = now + timedelta(days=i)
        markup.add(types.InlineKeyboardButton(date.strftime('%b %d'), callback_data=date.strftime('%Y-%m-%d')))
    return markup

def generate_half_hour_slots():
    markup = types.InlineKeyboardMarkup(row_width=4)  # 4 buttons per row
    buttons = []
    for hour in range(9, 23):
        for minute in [0, 15, 30, 45]:
            time_str = f"{hour:02d}:{minute:02d}"
            buttons.append(types.InlineKeyboardButton(time_str, callback_data=f"time_{time_str}"))
    # Add all at once, telebot will auto-break into rows of 4
    markup.add(*buttons)
    return markup

def generate_num_people_buttons():
    markup = types.InlineKeyboardMarkup(row_width=3)  # 3 per row
    buttons = []

    # Numbers 1–5
    for i in range(1, 6):
        buttons.append(types.InlineKeyboardButton(str(i), callback_data=f"num_{i}"))

    # Add "Other" option
    buttons.append(types.InlineKeyboardButton("Other", callback_data="num_other"))

    # Add all buttons, split into rows of 3
    markup.add(*buttons)
    return markup

# ---- START / MAIN MENU ----
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id

    if user_id in available_time_slots:
        del available_time_slots[user_id]
    bot.clear_step_handler_by_chat_id(message.chat.id)

    bot.send_message(
        message.chat.id,
        "✨ Golden Fork Reservation ✨\nBook effortlessly. Save £50 instantly.",
        reply_markup=generate_main_buttons()
    )


# ---- CALLBACK HANDLER ----
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    data = call.data

    # Reserve button
    if data == "reserve":
        if user_id not in available_time_slots:
            available_time_slots[user_id] = {}
        bot.send_message(chat_id, "Please select the date for your reservation:", reply_markup=generate_date_selection_buttons())
        return

    # Date selected
    if "-" in data and len(data) == 10:  # format YYYY-MM-DD
        # ✅ Store as string, not datetime.date
        available_time_slots[user_id]['date'] = data  
        bot.send_message(chat_id, f"Please select a time for {data}:", reply_markup=generate_half_hour_slots())
        return

    # Time selected
    if data.startswith("time_"):
        selected_time = data.replace("time_", "")
        available_time_slots[user_id]['time'] = selected_time
        bot.send_message(chat_id, "Please enter the name you would like the reservation under (first and surname):")
        available_time_slots[user_id]['step'] = 'full_name'
        bot.register_next_step_handler(call.message, process_full_name)
        return

    # Number of people selected
    if data.startswith("num_"):
        choice = data.replace("num_", "")

        if choice == "other":
            # Fall back to text input
            available_time_slots[user_id]['step'] = 'num_people'
            bot.send_message(chat_id, "Please enter the number of people:")
            bot.register_next_step_handler(call.message, process_num_people)
        else:
            # Save number directly
            available_time_slots[user_id]['num_people'] = int(choice)
            available_time_slots[user_id]['step'] = 'restaurant_link'
            bot.send_message(chat_id, "Please paste the restaurant link:")
            bot.register_next_step_handler(call.message, process_restaurant_link)
        return

# ---- STEP HANDLERS ----
def process_full_name(message):
    user_id = message.from_user.id

    # ✅ Fail gracefully if no session exists
    if user_id not in available_time_slots:
        bot.send_message(message.chat.id, "⚠️ Something went wrong. Please restart with /start.")
        return

    available_time_slots[user_id]['full_name'] = message.text.strip()
    available_time_slots[user_id]['step'] = 'num_people'

    bot.send_message(message.chat.id, "How many people will attend?", reply_markup=generate_num_people_buttons())

def process_num_people(message):
    user_id = message.from_user.id

    # ✅ Fail gracefully if no session
    if user_id not in available_time_slots:
        bot.send_message(message.chat.id, "⚠️ Something went wrong. Please restart with /start.")
        return

    try:
        available_time_slots[user_id]['num_people'] = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "Please enter a valid number.")
        bot.register_next_step_handler(message, process_num_people)
        return

    available_time_slots[user_id]['step'] = 'restaurant_link'
    bot.send_message(message.chat.id, "Please paste the restaurant link:")
    bot.register_next_step_handler(message, process_restaurant_link)


def process_restaurant_link(message):
    user_id = message.from_user.id

    # ✅ Fail gracefully if no session
    if user_id not in available_time_slots:
        bot.send_message(message.chat.id, "⚠️ Something went wrong. Please restart with /start.")
        return

    available_time_slots[user_id]['restaurant_link'] = message.text.strip()
    available_time_slots[user_id]['step'] = 'notes'

    bot.send_message(
        message.chat.id,
        "Any additional notes? (e.g., allergies, special requests)"
    )
    bot.register_next_step_handler(message, process_notes)


def process_notes(message):
    user_id = message.from_user.id

    # ✅ Fail gracefully instead of recreating
    if user_id not in available_time_slots:
        bot.send_message(message.chat.id, "⚠️ Something went wrong. Please restart with /start.")
        return

    data = available_time_slots[user_id]
    data['notes'] = message.text.strip()

    reservation_datetime = dt.strptime(f"{data['date']} {data['time']}", "%Y-%m-%d %H:%M")

    save_reservation_to_db(
        user_id,
        data['full_name'],
        data['num_people'],
        reservation_datetime,
        restaurant_link=data.get('restaurant_link'),
        notes=data.get('notes')
    )

    full_name_telegram = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
    telegram_username = f"@{message.from_user.username}" if message.from_user.username else "No username"

    confirmation_msg = (
        f"🌟 Reservation locked in!\n\n"
        f"📅 Date: {data['date']}\n"
        f"⏰ Time: {data['time']}\n"
        f"🙍 Name: {data['full_name']}\n"
        f"👫 People: {data['num_people']}\n"
        f"📍 Restaurant: {data.get('restaurant_link','No link')}\n"
        f"📝 Notes: {data.get('notes','')}\n\n"
        f"Our team will reach out shortly to arrange payment. We’ll be swift — and of course, you’re welcome to secure another table."
    )
    # Message to customer
    message_to_customer = ( 
        f"Thank you for choosing Golden Fork! 🍽️\n\n"
        f"💳 Once your payment is completed, we’ll reach out privately with a screenshot of your confirmed reservation — including the restaurant and time you selected.\n\n"
        f"📍 At the restaurant, simply mention you booked through TheFork. You may also mention the Yums if you prefer, but restaurants usually apply them automatically.\n\n"
        f"💸 The discount will be applied to your final bill. If it’s not, just kindly remind your waiter — sometimes they forget. Enjoy your meal!"
    )

    # Confirmation message for admin
    confirmation_msg_admin = (
        f"📅 Date: {data['date']}\n"
        f"⏰ Time: {data['time']}\n"
        f"🙍 Name: {data['full_name']}\n"
        f"👫 People: {data['num_people']}\n"
        f"📍 Restaurant: {data.get('restaurant_link','No link')}\n"
        f"📝 Notes: {data.get('notes','')}\n\n"
        f"👤 Telegram: {full_name_telegram} ({telegram_username})"
    )

    # Send messages
    bot.send_message(message.chat.id, confirmation_msg)
    time.sleep(2)
    bot.send_message(message.chat.id, message_to_customer)
    time.sleep(2)
    bot.send_message(message.chat.id, "✨ Golden Fork Reservation ✨\nBook effortlessly. Save £50 instantly.", reply_markup=generate_main_buttons())

    ADMIN_ID = 7994205774
    bot.send_message(ADMIN_ID, f"📩 New Reservation:\n\n{confirmation_msg_admin}")

    # Clear temporary data
    del available_time_slots[user_id]

# ---- START POLLING ----
if __name__ == "__main__":
    print("Bot is running...")
    bot.polling(none_stop=True)
