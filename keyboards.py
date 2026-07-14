from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_start_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Получить ссылку", callback_data="get_link")
    return builder.as_markup()

def get_reveal_keyboard(msg_id):
    builder = InlineKeyboardBuilder()
    builder.button(text="👁 Узнать отправителя", callback_data=f"reveal_{msg_id}")
    return builder.as_markup()

def get_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="back_to_menu")
    return builder.as_markup()
