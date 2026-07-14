# Запустите этот скрипт для создания всех файлов
import os

files = {}

# config.py
files['config.py'] = '''import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8442222382"))
DATABASE_NAME = os.getenv("DATABASE_NAME", "/tmp/anonymous_bot.db")
REVEAL_COST = float(os.getenv("REVEAL_COST", "0"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен!")
'''

# database.py
files['database.py'] = '''import aiosqlite
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
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_banned INTEGER DEFAULT 0
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER NOT NULL,
                    receiver_id INTEGER NOT NULL,
                    receiver_message_id INTEGER,
                    message_type TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_revealed INTEGER DEFAULT 0,
                    is_deleted INTEGER DEFAULT 0
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS balances (
                    user_id INTEGER PRIMARY KEY,
                    amount REAL DEFAULT 0
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    target_id INTEGER,
                    details TEXT,
                    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.commit()

    async def register_user(self, user_id: int, username: str = None, 
                           first_name: str = None, last_name: str = None):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name
            """, (user_id, username, first_name, last_name))
            await db.commit()

    async def save_message(self, sender_id: int, receiver_id: int, 
                          receiver_message_id: int, message_type: str) -> int:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("""
                INSERT INTO messages (sender_id, receiver_id, receiver_message_id, message_type)
                VALUES (?, ?, ?, ?)
            """, (sender_id, receiver_id, receiver_message_id, message_type))
            await db.commit()
            return cursor.lastrowid

    async def get_sender_id(self, receiver_message_id: int) -> Optional[int]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("""
                SELECT sender_id FROM messages 
                WHERE receiver_message_id = ? AND is_deleted = 0
            """, (receiver_message_id,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_user_info(self, user_id: int) -> Optional[Tuple]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("""
                SELECT username, first_name, last_name 
                FROM users WHERE user_id = ?
            """, (user_id,))
            return await cursor.fetchone()

    async def mark_as_revealed(self, receiver_message_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""
                UPDATE messages SET is_revealed = 1 
                WHERE receiver_message_id = ?
            """, (receiver_message_id,))
            await db.commit()

    async def is_already_revealed(self, receiver_message_id: int) -> bool:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("""
                SELECT is_revealed FROM messages 
                WHERE receiver_message_id = ?
            """, (receiver_message_id,))
            result = await cursor.fetchone()
            return bool(result[0]) if result else False

    async def is_user_banned(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
            result = await cursor.fetchone()
            return bool(result[0]) if result else False

    async def ban_user(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
            return True

    async def unban_user(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
            await db.commit()
            return True

    async def get_total_stats(self) -> Dict:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM users")
            total_users = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE is_deleted = 0")
            total_messages = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE is_revealed = 1 AND is_deleted = 0")
            revealed_messages = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE date(sent_at) = date('now') AND is_deleted = 0")
            today_messages = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM users WHERE date(registered_at) = date('now')")
            today_users = (await cursor.fetchone())[0]
            
            return {
                "total_users": total_users,
                "total_messages": total_messages,
                "revealed_messages": revealed_messages,
                "today_messages": today_messages,
                "today_users": today_users
            }

    async def get_top_users(self, limit: int = 10) -> List[Dict]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("""
                SELECT u.user_id, u.username, u.first_name, COUNT(m.id) as msg_count
                FROM users u
                LEFT JOIN messages m ON u.user_id = m.receiver_id AND m.is_deleted = 0
                WHERE u.is_banned = 0
                GROUP BY u.user_id
                ORDER BY msg_count DESC
                LIMIT ?
            """, (limit,))
            
            results = await cursor.fetchall()
            return [{"user_id": r[0], "username": r[1], "first_name": r[2], "msg_count": r[3]} for r in results]

    async def search_user(self, query: str) -> List[Dict]:
        async with aiosqlite.connect(self.db_name) as db:
            if query.isdigit():
                cursor = await db.execute("""
                    SELECT user_id, username, first_name, last_name, registered_at, is_banned
                    FROM users WHERE user_id = ?
                """, (int(query),))
                result = await cursor.fetchone()
                if result:
                    return [{"user_id": result[0], "username": result[1], "first_name": result[2], 
                            "last_name": result[3], "registered_at": result[4], "is_banned": result[5]}]
            
            cursor = await db.execute("""
                SELECT user_id, username, first_name, last_name, registered_at, is_banned
                FROM users WHERE username LIKE ? OR first_name LIKE ? OR last_name LIKE ?
                LIMIT 10
            """, (f"%{query}%", f"%{query}%", f"%{query}%"))
            
            results = await cursor.fetchall()
            return [{"user_id": r[0], "username": r[1], "first_name": r[2], 
                    "last_name": r[3], "registered_at": r[4], "is_banned": r[5]} for r in results]

    async def get_user_messages(self, user_id: int, limit: int = 20) -> List[Dict]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("""
                SELECT m.id, m.sender_id, m.receiver_id, m.message_type, m.sent_at, m.is_revealed,
                       s.username as s_username, s.first_name as s_first,
                       r.username as r_username, r.first_name as r_first
                FROM messages m
                LEFT JOIN users s ON m.sender_id = s.user_id
                LEFT JOIN users r ON m.receiver_id = r.user_id
                WHERE (m.sender_id = ? OR m.receiver_id = ?) AND m.is_deleted = 0
                ORDER BY m.sent_at DESC
                LIMIT ?
            """, (user_id, user_id, limit))
            
            results = await cursor.fetchall()
            return [{"id": r[0], "sender_id": r[1], "receiver_id": r[2], "message_type": r[3],
                    "sent_at": r[4], "is_revealed": r[5], "sender_username": r[6], 
                    "sender_first_name": r[7], "receiver_username": r[8], "receiver_first_name": r[9]} 
                    for r in results]

    async def delete_message(self, message_id: int) -> bool:
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE messages SET is_deleted = 1 WHERE id = ?", (message_id,))
            await db.commit()
            return True

    async def add_admin_log(self, admin_id: int, action: str, target_id: int = None, details: str = None):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""
                INSERT INTO admin_logs (admin_id, action, target_id, details)
                VALUES (?, ?, ?, ?)
            """, (admin_id, action, target_id, details))
            await db.commit()

    async def get_admin_logs(self, limit: int = 50) -> List[Dict]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("""
                SELECT l.id, l.admin_id, l.action, l.target_id, l.details, l.performed_at,
                       a.username, a.first_name
                FROM admin_logs l
                LEFT JOIN users a ON l.admin_id = a.user_id
                ORDER BY l.performed_at DESC
                LIMIT ?
            """, (limit,))
            
            results = await cursor.fetchall()
            return [{"id": r[0], "admin_id": r[1], "action": r[2], "target_id": r[3],
                    "details": r[4], "performed_at": r[5], "admin_username": r[6], 
                    "admin_first_name": r[7]} for r in results]

    async def get_all_user_ids(self) -> List[int]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
            results = await cursor.fetchall()
            return [r[0] for r in results]
'''

# keyboards.py
files['keyboards.py'] = '''from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_start_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Получить мою ссылку", callback_data="get_link")
    builder.button(text="❓ Как это работает", callback_data="how_it_works")
    builder.adjust(1)
    return builder.as_markup()


def get_reveal_keyboard(message_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👁 Узнать отправителя", callback_data=f"reveal_{message_id}")
    return builder.as_markup()


def get_back_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ В главное меню", callback_data="back_to_menu")
    return builder.as_markup()


def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👥 Топ пользователей", callback_data="admin_top_users")
    builder.button(text="🔍 Поиск пользователя", callback_data="admin_search")
    builder.button(text="📋 Логи действий", callback_data="admin_logs")
    builder.button(text="📢 Рассылка", callback_data="admin_broadcast")
    builder.button(text="❌ Закрыть", callback_data="admin_close")
    builder.adjust(2)
    return builder.as_markup()


def get_admin_back_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад в админ-панель", callback_data="admin_back")
    builder.button(text="❌ Закрыть", callback_data="admin_close")
    builder.adjust(1)
    return builder.as_markup()


def get_user_actions_keyboard(user_id: int, is_banned: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📨 Сообщения", callback_data=f"admin_user_msgs_{user_id}")
    if is_banned:
        builder.button(text="✅ Разбанить", callback_data=f"admin_unban_{user_id}")
    else:
        builder.button(text="🚫 Забанить", callback_data=f"admin_ban_{user_id}")
    builder.button(text="◀️ Назад", callback_data="admin_back")
    builder.adjust(2)
    return builder.as_markup()


def get_broadcast_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить рассылку", callback_data="admin_confirm_broadcast")
    builder.button(text="❌ Отменить", callback_data="admin_cancel_broadcast")
    builder.adjust(1)
    return builder.as_markup()
'''

# utils.py
files['utils.py'] = '''from database import Database
from config import REVEAL_COST

db = Database()


async def can_reveal_sender(user_id: int) -> tuple:
    return True, "✅ Личность отправителя будет раскрыта"


def get_user_display_name(user_info: tuple) -> str:
    username, first_name, last_name = user_info
    if username:
        return f"@{username}"
    display_name = first_name or ""
    if last_name:
        display_name += f" {last_name}"
    return display_name.strip() or "Пользователь без имени"


def escape_markdown(text: str) -> str:
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', 
                    '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\\\{char}')
    return text
'''

# handlers.py
files['handlers.py'] = '''from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.utils.deep_linking import create_start_link
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError

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
    
    await db.register_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )
    
    args = message.text.split()
    
    if len(args) > 1:
        try:
            target_user_id = int(args[1])
            
            if target_user_id == user_id:
                await message.answer("❌ Нельзя отправлять сообщения самому себе!")
                return
            
            target_user = await db.get_user_info(target_user_id)
            if not target_user:
                await message.answer("❌ Пользователь не найден")
                return
            
            user_states[user_id] = target_user_id
            
            await message.answer(
                "✍️ Отправьте анонимное сообщение (текст, фото или голосовое)\\n"
                "Для отмены: /cancel",
                reply_markup=get_back_keyboard()
            )
        except ValueError:
            await message.answer("❌ Некорректная ссылка")
    else:
        text = "👋 Добро пожаловать в Анонимный Чат!\\n\\n"
        text += "🔒 Получайте анонимные сообщения\\n"
        text += "🔗 Поделитесь ссылкой с друзьями\\n"
        text += "👁 Узнайте отправителя\\n\\n"
        text += "Выберите действие:"
        
        if user_id == ADMIN_ID:
            text += "\\n\\n⚙️ Админ-панель: /admin"
        
        await message.answer(text, reply_markup=get_start_keyboard())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
        await message.answer("❌ Отправка отменена", reply_markup=get_start_keyboard())
    else:
        await message.answer("🤔 Нет активных действий")


@router.callback_query(F.data == "get_link")
async def get_user_link(callback: CallbackQuery):
    user_id = callback.from_user.id
    link = await create_start_link(callback.bot, str(user_id))
    
    await callback.message.edit_text(
        f"🔗 Ваша ссылка:\\n\\n<code>{link}</code>",
        parse_mode="HTML",
        reply_markup=get_back_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in user_states:
        del user_states[user_id]
    
    text = "👋 Добро пожаловать в Анонимный Чат!\\n\\nВыберите действие:"
    if user_id == ADMIN_ID:
        text += "\\n\\n⚙️ Админ-панель: /admin"
    
    await callback.message.edit_text(text, reply_markup=get_start_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("reveal_"))
async def reveal_sender(callback: CallbackQuery):
    user_id = callback.from_user.id
    message_id = int(callback.data.split("_")[1])
    
    if await db.is_already_revealed(message_id):
        await callback.answer("⚠️ Уже раскрыто", show_alert=True)
        return
    
    sender_id = await db.get_sender_id(message_id)
    if not sender_id:
        await callback.answer("❌ Сообщение не найдено", show_alert=True)
        return
    
    can_reveal, msg = await can_reveal_sender(user_id)
    if not can_reveal:
        await callback.answer(msg, show_alert=True)
        return
    
    sender_info = await db.get_user_info(sender_id)
    if not sender_info:
        await callback.answer("❌ Отправитель не найден", show_alert=True)
        return
    
    await db.mark_as_revealed(message_id)
    sender_name = get_user_display_name(sender_info)
    await callback.answer(f"✅ Отправитель: {sender_name}", show_alert=True)


@router.message(F.content_type.in_({"text", "photo", "voice", "video_note"}))
async def handle_anonymous_message(message: Message, bot: Bot):
    user_id = message.from_user.id
    
    if user_id in user_states:
        receiver_id = user_states[user_id]
        
        try:
            if message.text:
                sent_msg = await bot.send_message(
                    chat_id=receiver_id,
                    text=f"📨 <b>Анонимное сообщение:</b>\\n\\n{message.text}",
                    parse_mode="HTML",
                    reply_markup=get_reveal_keyboard(0)
                )
            elif message.photo:
                sent_msg = await bot.send_photo(
                    chat_id=receiver_id,
                    photo=message.photo[-1].file_id,
                    caption="📨 <b>Анонимное фото</b>",
                    parse_mode="HTML",
                    reply_markup=get_reveal_keyboard(0)
                )
            elif message.voice:
                sent_msg = await bot.send_voice(
                    chat_id=receiver_id,
                    voice=message.voice.file_id,
                    caption="📨 <b>Анонимное голосовое</b>",
                    parse_mode="HTML",
                    reply_markup=get_reveal_keyboard(0)
                )
            else:
                sent_msg = await bot.send_video_note(
                    chat_id=receiver_id,
                    video_note=message.video_note.file_id,
                    reply_markup=get_reveal_keyboard(0)
                )
            
            await db.save_message(
                sender_id=user_id,
                receiver_id=receiver_id,
                receiver_message_id=sent_msg.message_id,
                message_type=message.content_type
            )
            
            await bot.edit_message_reply_markup(
                chat_id=receiver_id,
                message_id=sent_msg.message_id,
                reply_markup=get_reveal_keyboard(sent_msg.message_id)
            )
            
        except TelegramForbiddenError:
            pass
        except Exception as e:
            print(f"Error: {e}")
        
        await message.answer("✅ Сообщение отправлено!", reply_markup=get_start_keyboard())
        del user_states[user_id]
    else:
        await message.answer(
            "🤔 Используйте /start для инструкций",
            reply_markup=get_start_keyboard()
        )
'''

# main.py
files['main.py'] = '''import asyncio
import os
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

from config import BOT_TOKEN, DATABASE_NAME
from database import Database
from handlers import router

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def health_check(request):
    return web.Response(text="OK")


async def run_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Web server started on port {port}")


async def main():
    try:
        db_dir = os.path.dirname(DATABASE_NAME)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        db = Database()
        await db.create_tables()
        logger.info("Database initialized")
        
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = Dispatcher()
        dp.include_router(router)
        
        asyncio.create_task(run_web_server())
        
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Bot started!")
        
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
'''

# requirements.txt
files['requirements.txt'] = '''aiogram==3.7.0
aiosqlite==0.20.0
python-dotenv==1.0.1
aiohttp==3.9.1
'''

# Procfile
files['Procfile'] = 'worker: python main.py'

# runtime.txt
files['runtime.txt'] = 'python-3.10.13'

# .gitignore
files['.gitignore'] = '''.env
*.db
*.sqlite
__pycache__/
venv/
data/
'''

# Создаем все файлы
for filename, content in files.items():
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Created: {filename}")

print("\\nAll files created successfully!")
