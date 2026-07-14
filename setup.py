python3 << 'PYEOF'
import os

# Убедимся что мы в правильной папке
print(f"Creating files in: {os.getcwd()}")

# config.py
with open('config.py', 'w') as f:
    f.write('''import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8442222382"))
DATABASE_NAME = os.getenv("DATABASE_NAME", "/tmp/anonymous_bot.db")
REVEAL_COST = float(os.getenv("REVEAL_COST", "0"))
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set!")
''')

# database.py
with open('database.py', 'w') as f:
    f.write('''import aiosqlite
import os
from typing import Optional, Tuple, List, Dict
from config import DATABASE_NAME


class Database:
    def __init__(self, db_name: str = DATABASE_NAME):
        self.db_name = db_name

    async def create_tables(self):
        db_dir = os.path.dirname(self.db_name)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("""CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                last_name TEXT, registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_banned INTEGER DEFAULT 0)""")
            await db.execute("""CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL, receiver_message_id INTEGER,
                message_type TEXT, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_revealed INTEGER DEFAULT 0, is_deleted INTEGER DEFAULT 0)""")
            await db.execute("""CREATE TABLE IF NOT EXISTS balances (
                user_id INTEGER PRIMARY KEY, amount REAL DEFAULT 0)""")
            await db.execute("""CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL,
                action TEXT NOT NULL, target_id INTEGER, details TEXT,
                performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            await db.commit()

    async def register_user(self, user_id, username=None, first_name=None, last_name=None):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""INSERT INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username, first_name=excluded.first_name,
                last_name=excluded.last_name""", (user_id, username, first_name, last_name))
            await db.commit()

    async def is_user_banned(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
            result = await cursor.fetchone()
            return bool(result[0]) if result else False

    async def save_message(self, sender_id, receiver_id, receiver_message_id, message_type):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("""INSERT INTO messages (sender_id, receiver_id, receiver_message_id, message_type)
                VALUES (?, ?, ?, ?)""", (sender_id, receiver_id, receiver_message_id, message_type))
            await db.commit()
            return cursor.lastrowid

    async def get_sender_id(self, receiver_message_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("""SELECT sender_id FROM messages 
                WHERE receiver_message_id=? AND is_deleted=0""", (receiver_message_id,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_user_info(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("""SELECT username, first_name, last_name 
                FROM users WHERE user_id=?""", (user_id,))
            return await cursor.fetchone()

    async def mark_as_revealed(self, receiver_message_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE messages SET is_revealed=1 WHERE receiver_message_id=?", (receiver_message_id,))
            await db.commit()

    async def is_already_revealed(self, receiver_message_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT is_revealed FROM messages WHERE receiver_message_id=?", (receiver_message_id,))
            result = await cursor.fetchone()
            return bool(result[0]) if result else False
''')

# main.py
with open('main.py', 'w') as f:
    f.write('''import asyncio, os, logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiohttp import web
from config import BOT_TOKEN, DATABASE_NAME
from database import Database
from handlers import router

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def health_check(request):
    return web.Response(text="OK")

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Web server on port {port}")

async def main():
    db_dir = os.path.dirname(DATABASE_NAME)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    db = Database()
    await db.create_tables()
    logger.info("DB initialized")
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    asyncio.create_task(run_web_server())
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
''')

# handlers.py
with open('handlers.py', 'w') as f:
    f.write('''from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.utils.deep_linking import create_start_link
from aiogram.exceptions import TelegramForbiddenError
from database import Database
from keyboards import get_start_keyboard, get_reveal_keyboard, get_back_keyboard
from utils import can_reveal_sender, get_user_display_name
from config import ADMIN_ID

router = Router()
db = Database()
user_states = {}

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    user_id = message.from_user.id
    await db.register_user(user_id=user_id, username=message.from_user.username,
                          first_name=message.from_user.first_name, last_name=message.from_user.last_name)
    args = message.text.split()
    if len(args) > 1:
        try:
            target_user_id = int(args[1])
            if target_user_id == user_id:
                await message.answer("❌ Cannot send to yourself!")
                return
            target_user = await db.get_user_info(target_user_id)
            if not target_user:
                await message.answer("❌ User not found")
                return
            user_states[user_id] = target_user_id
            await message.answer("✍️ Send anonymous message (text, photo or voice)\\n/cancel to cancel",
                               reply_markup=get_back_keyboard())
        except ValueError:
            await message.answer("❌ Invalid link")
    else:
        text = "👋 Welcome to Anonymous Chat!\\n\\nChoose action:"
        if user_id == ADMIN_ID:
            text += "\\n\\n⚙️ Admin: /admin"
        await message.answer(text, reply_markup=get_start_keyboard())

@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
        await message.answer("❌ Cancelled", reply_markup=get_start_keyboard())
    else:
        await message.answer("No active actions")

@router.callback_query(F.data == "get_link")
async def get_user_link(callback: CallbackQuery):
    link = await create_start_link(callback.bot, str(callback.from_user.id))
    await callback.message.edit_text(f"🔗 Your link:\\n\\n<code>{link}</code>",
                                   parse_mode="HTML", reply_markup=get_back_keyboard())
    await callback.answer()

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in user_states:
        del user_states[user_id]
    text = "👋 Welcome!\\n\\nChoose action:"
    if user_id == ADMIN_ID:
        text += "\\n\\n⚙️ Admin: /admin"
    await callback.message.edit_text(text, reply_markup=get_start_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith("reveal_"))
async def reveal_sender(callback: CallbackQuery):
    user_id = callback.from_user.id
    message_id = int(callback.data.split("_")[1])
    if await db.is_already_revealed(message_id):
        await callback.answer("⚠️ Already revealed", show_alert=True)
        return
    sender_id = await db.get_sender_id(message_id)
    if not sender_id:
        await callback.answer("❌ Message not found", show_alert=True)
        return
    can_reveal, msg = await can_reveal_sender(user_id)
    if not can_reveal:
        await callback.answer(msg, show_alert=True)
        return
    sender_info = await db.get_user_info(sender_id)
    if not sender_info:
        await callback.answer("❌ Sender not found", show_alert=True)
        return
    await db.mark_as_revealed(message_id)
    sender_name = get_user_display_name(sender_info)
    await callback.answer(f"✅ Sender: {sender_name}", show_alert=True)

@router.message(F.content_type.in_({"text", "photo", "voice", "video_note"}))
async def handle_anonymous_message(message: Message, bot: Bot):
    user_id = message.from_user.id
    if user_id in user_states:
        receiver_id = user_states[user_id]
        try:
            if message.text:
                sent_msg = await bot.send_message(chat_id=receiver_id,
                    text=f"📨 <b>Anonymous message:</b>\\n\\n{message.text}",
                    parse_mode="HTML", reply_markup=get_reveal_keyboard(0))
            elif message.photo:
                sent_msg = await bot.send_photo(chat_id=receiver_id, photo=message.photo[-1].file_id,
                    caption="📨 <b>Anonymous photo</b>", parse_mode="HTML", reply_markup=get_reveal_keyboard(0))
            elif message.voice:
                sent_msg = await bot.send_voice(chat_id=receiver_id, voice=message.voice.file_id,
                    caption="📨 <b>Anonymous voice</b>", parse_mode="HTML", reply_markup=get_reveal_keyboard(0))
            else:
                sent_msg = await bot.send_video_note(chat_id=receiver_id,
                    video_note=message.video_note.file_id, reply_markup=get_reveal_keyboard(0))
            await db.save_message(sender_id=user_id, receiver_id=receiver_id,
                                receiver_message_id=sent_msg.message_id, message_type=message.content_type)
            await bot.edit_message_reply_markup(chat_id=receiver_id, message_id=sent_msg.message_id,
                                              reply_markup=get_reveal_keyboard(sent_msg.message_id))
        except TelegramForbiddenError:
            pass
        await message.answer("✅ Message sent!", reply_markup=get_start_keyboard())
        del user_states[user_id]
    else:
        await message.answer("🤔 Use /start for instructions", reply_markup=get_start_keyboard())
''')

# keyboards.py
with open('keyboards.py', 'w') as f:
    f.write('''from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_start_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Get my link", callback_data="get_link")
    builder.button(text="❓ How it works", callback_data="how_it_works")
    builder.adjust(1)
    return builder.as_markup()

def get_reveal_keyboard(message_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="👁 Reveal sender", callback_data=f"reveal_{message_id}")
    return builder.as_markup()

def get_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Main menu", callback_data="back_to_menu")
    return builder.as_markup()

def get_admin_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Stats", callback_data="admin_stats")
    builder.button(text="👥 Top users", callback_data="admin_top_users")
    builder.button(text="🔍 Search", callback_data="admin_search")
    builder.button(text="📋 Logs", callback_data="admin_logs")
    builder.button(text="📢 Broadcast", callback_data="admin_broadcast")
    builder.button(text="❌ Close", callback_data="admin_close")
    builder.adjust(2)
    return builder.as_markup()

def get_admin_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Back", callback_data="admin_back")
    builder.button(text="❌ Close", callback_data="admin_close")
    builder.adjust(1)
    return builder.as_markup()
''')

# utils.py
with open('utils.py', 'w') as f:
    f.write('''async def can_reveal_sender(user_id):
    return True, "✅ Sender will be revealed"

def get_user_display_name(user_info):
    username, first_name, last_name = user_info
    if username:
        return f"@{username}"
    display_name = first_name or ""
    if last_name:
        display_name += f" {last_name}"
    return display_name.strip() or "Unknown user"
''')

# requirements.txt
with open('requirements.txt', 'w') as f:
    f.write('''aiogram==3.7.0
aiosqlite==0.20.0
python-dotenv==1.0.1
aiohttp==3.9.1
''')

# Procfile
with open('Procfile', 'w') as f:
    f.write('worker: python main.py')

# runtime.txt
with open('runtime.txt', 'w') as f:
    f.write('python-3.10.13')

# .gitignore
with open('.gitignore', 'w') as f:
    f.write('''.env
*.db
*.sqlite
__pycache__/
venv/
data/
''')

print("All files created successfully!")
print("\nFiles created:")
for file in os.listdir('.'):
    if file.endswith('.py') or file in ['Procfile', 'runtime.txt', '.gitignore', 'requirements.txt']:
        print(f"  ✓ {file}")

# Проверяем что database.py содержит правильный код
with open('database.py', 'r') as f:
    content = f.read()
    if 'cat >' in content:
        print("\n❌ ERROR: database.py contains bash commands!")
    else:
        print("\n✅ database.py is clean Python code")
    
    if 'is_user_banned' in content:
        print("✅ is_user_banned method found")
    else:
        print("❌ is_user_banned method NOT found!")
PYEOF
