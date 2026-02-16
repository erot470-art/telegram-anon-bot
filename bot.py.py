import os
import logging
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен из переменных окружения Railway
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not TOKEN:
    raise ValueError("No BOT_TOKEN found in environment")
if ADMIN_ID == 0:
    raise ValueError("No ADMIN_ID found in environment")

# База данных
DB_NAME = "messages.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  username TEXT,
                  first_name TEXT,
                  date TIMESTAMP,
                  message_type TEXT,
                  text TEXT,
                  file_id TEXT,
                  admin_message_id INTEGER UNIQUE)''')
    conn.commit()
    conn.close()

def save_message(user_id, username, first_name, date, message_type, text, file_id, admin_message_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''INSERT INTO messages 
                 (user_id, username, first_name, date, message_type, text, file_id, admin_message_id)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (user_id, username, first_name, date, message_type, text, file_id, admin_message_id))
    conn.commit()
    conn.close()

def get_user_by_admin_message(admin_message_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT user_id, username, first_name, date, text FROM messages WHERE admin_message_id = ?''',
              (admin_message_id,))
    row = c.fetchone()
    conn.close()
    return row

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот для анонимных сообщений.\n"
        "Ты можешь отправить мне любое сообщение (текст, фото, видео), "
        "и оно будет анонимно передано администратору."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    
    if not msg:
        return

    # --- Сообщения от администратора ---
    if user.id == ADMIN_ID:
        if msg.reply_to_message:
            replied_msg = msg.reply_to_message
            admin_message_id = replied_msg.message_id
            user_info = get_user_by_admin_message(admin_message_id)

            if user_info:
                user_id = user_info[0]
                try:
                    await msg.copy(chat_id=user_id)
                    await msg.reply_text("✅ Ответ отправлен!")
                except Exception as e:
                    await msg.reply_text("❌ Не удалось отправить ответ")
            else:
                await msg.reply_text("❌ Автор не найден")
        return

    # --- Сообщения от пользователей ---
    date = datetime.now()
    message_type = "text"
    text = msg.text or msg.caption or ""
    file_id = None

    if msg.photo:
        message_type = "photo"
        file_id = msg.photo[-1].file_id
    elif msg.video:
        message_type = "video"
        file_id = msg.video.file_id
    elif msg.document:
        message_type = "document"
        file_id = msg.document.file_id
    elif msg.voice:
        message_type = "voice"
        file_id = msg.voice.file_id

    try:
        copied_message = await msg.copy(chat_id=ADMIN_ID, caption=msg.caption)
        admin_message_id = copied_message.message_id

        save_message(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            date=date,
            message_type=message_type,
            text=text,
            file_id=file_id,
            admin_message_id=admin_message_id
        )

        keyboard = [[InlineKeyboardButton("👤 Показать автора", callback_data=f"show_{admin_message_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.edit_message_reply_markup(
            chat_id=ADMIN_ID,
            message_id=admin_message_id,
            reply_markup=reply_markup
        )

        await msg.reply_text("✅ Сообщение доставлено админу!")
    except Exception as e:
        await msg.reply_text("❌ Ошибка при отправке")
        logger.error(f"Error: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text(text="⛔ Нет прав")
        return

    if query.data.startswith("show_"):
        admin_message_id = int(query.data.split("_")[1])
        user_info = get_user_by_admin_message(admin_message_id)

        if user_info:
            user_id, username, first_name, date, text = user_info
            
            if isinstance(date, datetime):
                date_str = date.strftime('%d.%m.%Y %H:%M')
            else:
                date_str = str(date)
            
            username_text = f"@{username}" if username else "нет"
            info = (
                f"📨 **Автор сообщения**\n"
                f"👤 Имя: {first_name}\n"
                f"🆔 ID: {user_id}\n"
                f"📱 Юзернейм: {username_text}\n"
                f"📅 Дата: {date_str}\n"
                f"💬 Текст: {text}"
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=info)
            await query.edit_message_reply_markup(reply_markup=None)
        else:
            await query.edit_message_text(text="❌ Не найдено")

def main():
    init_db()
    
    try:
        application = Application.builder().token(TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(button_callback))
        
        print("✅ Бот запущен! Администратор ID:", ADMIN_ID)
        print("🚀 Railway порт:", os.getenv("PORT", "не указан"))
        
        application.run_polling()
    except Exception as e:
        print(f"❌ Ошибка при запуске: {e}")

if __name__ == "__main__":
    main()
