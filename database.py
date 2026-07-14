import aiosqlite
from config import DATABASE_NAME

class Database:
    def __init__(self):
        self.db_name = DATABASE_NAME

    async def create_tables(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT)""")
            await db.execute("""CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER,
                receiver_id INTEGER, receiver_message_id INTEGER,
                message_type TEXT, is_revealed INTEGER DEFAULT 0)""")
            await db.commit()

    async def register_user(self, user_id, username=None, first_name=None, last_name=None):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?)", 
                           (user_id, username, first_name))
            await db.commit()

    async def save_message(self, sender_id, receiver_id, receiver_message_id, message_type):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "INSERT INTO messages (sender_id, receiver_id, receiver_message_id, message_type) VALUES (?, ?, ?, ?)",
                (sender_id, receiver_id, receiver_message_id, message_type))
            await db.commit()
            return cursor.lastrowid

    async def get_sender_id(self, receiver_message_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT sender_id FROM messages WHERE receiver_message_id=?", 
                                    (receiver_message_id,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_user_info(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT username, first_name FROM users WHERE user_id=?", 
                                    (user_id,))
            return await cursor.fetchone()

    async def mark_as_revealed(self, receiver_message_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE messages SET is_revealed=1 WHERE receiver_message_id=?", 
                           (receiver_message_id,))
            await db.commit()

    async def is_already_revealed(self, receiver_message_id):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT is_revealed FROM messages WHERE receiver_message_id=?", 
                                    (receiver_message_id,))
            result = await cursor.fetchone()
            return bool(result[0]) if result else False
