import os
import logging
import sqlite3
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv('TG_BOT_TOKEN')

conn = sqlite3.connect('players.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    username TEXT,
    nickname TEXT,
    lane TEXT,
    sublane TEXT,
    rank TEXT,
    notifications INTEGER DEFAULT 1
)''')
conn.commit()

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Use /start to test this bot.")
    
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('Enter your nickname')
    return 1

async def nickname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data['nickname'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("Top", callback_data="Top"), InlineKeyboardButton("Jungle", callback_data="Jungle")],
        [InlineKeyboardButton("Mid", callback_data="Mid"), InlineKeyboardButton("Bot", callback_data="Bot")],
        [InlineKeyboardButton("Support", callback_data="Support")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Choose your lane:", reply_markup=reply_markup)
    return 2

async def lane(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data['lane'] = query.data
    await query.edit_message_text(text=f"Selected lane: {query.data}")
    keyboard = [
        [InlineKeyboardButton("Top", callback_data="Top"), InlineKeyboardButton("Jungle", callback_data="Jungle")],
        [InlineKeyboardButton("Mid", callback_data="Mid"), InlineKeyboardButton("Bot", callback_data="Bot")],
        [InlineKeyboardButton("Support", callback_data="Support")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Choose your sublane:", reply_markup=reply_markup)
    return 3

async def sublane(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data['sublane'] = query.data
    await query.edit_message_text(text=f"Selected sublane: {query.data}")
    keyboard = [
        [InlineKeyboardButton("Warrior", callback_data="Warrior"), InlineKeyboardButton("Elite", callback_data="Elite")],
        [InlineKeyboardButton("Master", callback_data="Master"), InlineKeyboardButton("Grandmaster", callback_data="Grandmaster")],
        [InlineKeyboardButton("Epic", callback_data="Epic"), InlineKeyboardButton("Legend", callback_data="Legend")],
        [InlineKeyboardButton("Mythic", callback_data="Mythic")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Choose your rank:", reply_markup=reply_markup)
    return 4

async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data['rank'] = query.data
    await query.edit_message_text(text=f"Selected rank: {query.data}")
    
    user = update.effective_user
    user_id = user.id
    username = user.username

    with sqlite3.connect('players.db') as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM players WHERE id = ?', (user_id,))
        existing_user = c.fetchone()
        
        if existing_user:
            c.execute('''UPDATE players 
                         SET username = ?, nickname = ?, lane = ?, sublane = ?, rank = ? 
                         WHERE id = ?''', 
                      (username, context.user_data['nickname'], context.user_data['lane'], 
                       context.user_data['sublane'], context.user_data['rank'], user_id))
            await query.message.reply_text("Your information has been updated successfully!")
        else:
            c.execute('''INSERT INTO players (id, username, nickname, lane, sublane, rank) 
                         VALUES (?, ?, ?, ?, ?, ?)''', 
                      (user_id, username, context.user_data['nickname'], context.user_data['lane'], 
                       context.user_data['sublane'], context.user_data['rank']))
            await query.message.reply_text("You have been registered successfully!")
        
        conn.commit()

    return ConversationHandler.END

async def delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    with sqlite3.connect('players.db') as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM players WHERE id = ?', (user_id,))
        existing_user = c.fetchone()
        if existing_user:
            c.execute('DELETE FROM players WHERE id = ?', (user_id,))
            conn.commit()
            await update.message.reply_text("Your information has been deleted from the database.")
        else:
            await update.message.reply_text("You are not registered in the database.")

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("help", help_command, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("delete", delete_user, filters.ChatType.PRIVATE))
    
    register_handler = ConversationHandler(
        entry_points=[CommandHandler('register', register, filters.ChatType.PRIVATE)],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, nickname)],
            2: [CallbackQueryHandler(lane)],
            3: [CallbackQueryHandler(sublane)],
            4: [CallbackQueryHandler(rank)],
        },
        fallbacks=[]
    )

    application.add_handler(register_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
