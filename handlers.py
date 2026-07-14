from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.utils.deep_linking import create_start_link
from database import Database
from keyboards import get_start_keyboard, get_reveal_keyboard, get_back_keyboard
from config import ADMIN_ID

router = Router()
db = Database()
user_states = {}

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    user_id = message.from_user.id
    await db.register_user(user_id, message.from_user.username, message.from_user.first_name)
    args = message.text.split()
    if len(args) > 1:
        try:
            target = int(args[1])
            if target != user_id:
                user_states[user_id] = target
                await message.answer("Отправь анонимное сообщение:", reply_markup=get_back_keyboard())
        except:
            pass
    else:
        await message.answer("Привет! Получи свою ссылку:", reply_markup=get_start_keyboard())

@router.callback_query(F.data == "get_link")
async def get_link(callback: CallbackQuery):
    link = await create_start_link(callback.bot, str(callback.from_user.id))
    await callback.message.edit_text(f"Твоя ссылка:\n{link}", reply_markup=get_back_keyboard())

@router.callback_query(F.data == "back_to_menu")
async def back(callback: CallbackQuery):
    await callback.message.edit_text("Меню", reply_markup=get_start_keyboard())

@router.callback_query(F.data.startswith("reveal_"))
async def reveal(callback: CallbackQuery):
    msg_id = int(callback.data.split("_")[1])
    if await db.is_already_revealed(msg_id):
        await callback.answer("Уже раскрыто")
        return
    sender_id = await db.get_sender_id(msg_id)
    if sender_id:
        user = await db.get_user_info(sender_id)
        name = f"@{user[0]}" if user[0] else user[1]
        await db.mark_as_revealed(msg_id)
        await callback.answer(f"Отправитель: {name}", show_alert=True)

@router.message(F.content_type.in_({"text", "photo", "voice"}))
async def handle_msg(message: Message, bot: Bot):
    user_id = message.from_user.id
    if user_id in user_states:
        receiver = user_states[user_id]
        try:
            if message.text:
                msg = await bot.send_message(receiver, f"📨 {message.text}", reply_markup=get_reveal_keyboard(0))
            elif message.photo:
                msg = await bot.send_photo(receiver, message.photo[-1].file_id, caption="📨 Фото", reply_markup=get_reveal_keyboard(0))
            else:
                msg = await bot.send_voice(receiver, message.voice.file_id, caption="📨 Голосовое", reply_markup=get_reveal_keyboard(0))
            await db.save_message(user_id, receiver, msg.message_id, message.content_type)
            await bot.edit_message_reply_markup(receiver, msg.message_id, reply_markup=get_reveal_keyboard(msg.message_id))
        except:
            pass
        await message.answer("✅ Отправлено!")
        del user_states[user_id]
