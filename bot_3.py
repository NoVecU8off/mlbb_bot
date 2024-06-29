from contextlib import closing
import os
import logging
import sqlite3
from functools import wraps
from typing import Optional, Tuple
from dotenv import load_dotenv
from telegram import Chat, ChatMember, ChatMemberUpdated, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters, ChatMemberHandler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv('TG_BOT_TOKEN')
CREATOR_ID = os.getenv('TG_CREATOR_ID')
CHAT_ID = os.getenv('TG_CHAT_ID')

with closing(sqlite3.connect('players.db')) as conn:
    with conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY,
            username TEXT,
            nickname TEXT,
            lane TEXT,
            sublane TEXT,
            rank TEXT,
            notifications INTEGER DEFAULT 1
        )''')

LANE_REPLY_MARKUP = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Top", callback_data="Top"), InlineKeyboardButton("Jungle", callback_data="Jungle")],
        [InlineKeyboardButton("Mid", callback_data="Mid"), InlineKeyboardButton("Bot", callback_data="Bot")],
        [InlineKeyboardButton("Support", callback_data="Support")]   
    ]
)

RANK_REPLY_MARKUP = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Warrior", callback_data="Warrior"), InlineKeyboardButton("Elite", callback_data="Elite")],
        [InlineKeyboardButton("Master", callback_data="Master"), InlineKeyboardButton("Grandmaster", callback_data="Grandmaster")],
        [InlineKeyboardButton("Epic", callback_data="Epic"), InlineKeyboardButton("Legend", callback_data="Legend")],
        [InlineKeyboardButton("Mythic", callback_data="Mythic")]   
    ]
)

def creator_only(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != int(CREATOR_ID):
            await update.message.reply_text(f"Sorry, this command is only available to the bot creator, creator's id is: {CREATOR_ID}, your id is: {user_id}.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

async def uid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(f"Your Telegram ID is: {user_id}")

def extract_status_change(chat_member_update: ChatMemberUpdated) -> Optional[Tuple[bool, bool]]:
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get("is_member", (None, None))

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)
    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member

async def track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = extract_status_change(update.my_chat_member)
    if result is None:
        return
    was_member, is_member = result

    cause_name = update.effective_user.full_name

    chat = update.effective_chat
    if chat.type == Chat.PRIVATE:
        if not was_member and is_member:
            logger.info("%s unblocked the bot", cause_name)
            context.bot_data.setdefault("user_ids", set()).add(chat.id)
        elif was_member and not is_member:
            logger.info("%s blocked the bot", cause_name)
            context.bot_data.setdefault("user_ids", set()).discard(chat.id)
    elif chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        if not was_member and is_member:
            logger.info("%s added the bot to the group %s", cause_name, chat.title)
            context.bot_data.setdefault("group_ids", set()).add(chat.id)
        elif was_member and not is_member:
            logger.info("%s removed the bot from the group %s", cause_name, chat.title)
            context.bot_data.setdefault("group_ids", set()).discard(chat.id)
    elif not was_member and is_member:
        logger.info("%s added the bot to the channel %s", cause_name, chat.title)
        context.bot_data.setdefault("channel_ids", set()).add(chat.id)
    elif was_member and not is_member:
        logger.info("%s removed the bot from the channel %s", cause_name, chat.title)
        context.bot_data.setdefault("channel_ids", set()).discard(chat.id)

async def cid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Chat ID is {chat_id}")
    
async def chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_ids = ", ".join(str(uid) for uid in context.bot_data.setdefault("user_ids", set()))
    group_ids = ", ".join(str(gid) for gid in context.bot_data.setdefault("group_ids", set()))
    channel_ids = ", ".join(str(cid) for cid in context.bot_data.setdefault("channel_ids", set()))
    text = (
        f"@{context.bot.username} is currently in a conversation with the user IDs {user_ids}."
        f" Moreover it is a member of the groups with IDs {group_ids} "
        f"and administrator in the channels with IDs {channel_ids}."
    )
    await update.effective_message.reply_text(text)
    
async def greet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = extract_status_change(update.chat_member)
    if result is None:
        return

    was_member, is_member = result
    cause_name = update.chat_member.from_user.mention_html()
    member_name = update.chat_member.new_chat_member.user.mention_html()

    if not was_member and is_member:
        await update.effective_chat.send_message(
            f"{member_name} was added by {cause_name}. Welcome!",
            parse_mode=ParseMode.HTML,
        )
    elif was_member and not is_member:
        await update.effective_chat.send_message(
            f"{member_name} is no longer with us. Thanks a lot, {cause_name} ...",
            parse_mode=ParseMode.HTML,
        )
    
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.full_name
    chat = update.effective_chat
    if chat.type != Chat.PRIVATE:
        return

    logger.info("%s started a private chat with the bot", user_name)
    context.bot_data.setdefault("user_ids", set()).add(chat.id)
    await update.message.reply_text(f"Welcome {user_name}. Use /help to see what I'm capable of.")
    
async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Use /start to test this bot.")    

async def reg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('Enter your nickname')
    return 1

async def nickname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data['nickname'] = update.message.text
    await update.message.reply_text("Choose your lane:", reply_markup=LANE_REPLY_MARKUP)
    return 2

async def lane(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data['lane'] = query.data
    await query.edit_message_text(text=f"Selected lane: {query.data}")
    await query.message.reply_text("Choose your sublane:", reply_markup=LANE_REPLY_MARKUP)
    return 3

async def sublane(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data['sublane'] = query.data
    await query.edit_message_text(text=f"Selected sublane: {query.data}")
    await query.message.reply_text("Choose your rank:", reply_markup=RANK_REPLY_MARKUP)
    return 4

async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data['rank'] = query.data
    await query.edit_message_text(text=f"Selected rank: {query.data}")
    
    user = update.effective_user
    user_id = user.id
    username = user.username

    with closing(sqlite3.connect('players.db')) as conn:
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

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    with closing(sqlite3.connect('players.db')) as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM players WHERE id = ?', (user_id,))
        existing_user = c.fetchone()
        if existing_user:
            c.execute('DELETE FROM players WHERE id = ?', (user_id,))
            conn.commit()
            await update.message.reply_text("Your information has been deleted from the database.")
        else:
            await update.message.reply_text("You are not registered in the database.")
            
async def me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    with closing(sqlite3.connect('players.db')) as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM players WHERE id = ?', (user_id,))
        user_data = c.fetchone()
        
        if user_data:
            _, _, nickname, lane, sublane, rank, notifications = user_data
            message = f"Your profile:\n\n" \
                      f"Nickname: {nickname}\n" \
                      f"Lane: {lane}\n" \
                      f"Sublane: {sublane}\n" \
                      f"Rank: {rank}\n" \
                      f"Notifications: {'On' if notifications else 'Off'}"
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("You are not registered in the database. Use /register to create a profile.")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    with closing(sqlite3.connect('players.db')) as conn:
        c = conn.cursor()
        
        c.execute('SELECT * FROM players WHERE id = ?', (user_id,))
        existing_user = c.fetchone()
        
        if existing_user:
            c.execute('UPDATE players SET notifications = 0 WHERE id = ?', (user_id,))
            conn.commit()
            await update.message.reply_text("Notifications have been turned off.")
        else:
            await update.message.reply_text("You are not registered in the database. Use /register to create a profile.")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    with closing(sqlite3.connect('players.db')) as conn:
        c = conn.cursor()
        
        c.execute('SELECT * FROM players WHERE id = ?', (user_id,))
        existing_user = c.fetchone()
        
        if existing_user:
            c.execute('UPDATE players SET notifications = 1 WHERE id = ?', (user_id,))
            conn.commit()
            await update.message.reply_text("Notifications have been turned on.")
        else:
            await update.message.reply_text("You are not registered in the database. Use /register to create a profile.")
            
async def team(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    with closing(sqlite3.connect('players.db')) as conn:
        c = conn.cursor()
        
        c.execute('SELECT * FROM players WHERE id = ?', (user_id,))
        user_data = c.fetchone()
        
        if user_data:
            id, username, nickname, lane, sublane, rank, _ = user_data
            message = f"@{username} wants to join a team!\n\n" \
                      f"Nickname: {nickname}\n" \
                      f"Lane: {lane}\n" \
                      f"Sublane: {sublane}\n" \
                      f"Rank: {rank}"
            await context.bot.send_message(chat_id=CHAT_ID, text=message)
        else:
            await update.message.reply_text("You are not registered in the database. Use /register to create a profile.")
            
async def mate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Choose lane:", reply_markup=LANE_REPLY_MARKUP)
    return 1

async def select_lane(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['desired_lane'] = query.data
    await query.message.reply_text("Choose rank:", reply_markup=RANK_REPLY_MARKUP)
    return 2

async def select_rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['desired_rank'] = query.data

    with closing(sqlite3.connect('players.db')) as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM players WHERE lane = ? AND rank = ?', 
                  (context.user_data['desired_lane'], context.user_data['desired_rank']))
        players = c.fetchall()

    if players:
        message = "Players available for your criteria:\n\n"
        for player in players:
            _, username, nickname, lane, sublane, rank, _ = player
            message += f"@{username} (Nickname: {nickname}, Lane: {lane}, Sublane: {sublane}, Rank: {rank})\n"

        await query.message.reply_text(message)
    else:
        await query.message.reply_text("No players found for your criteria.")

    return ConversationHandler.END

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    application.add_handler(ChatMemberHandler(greet, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(track, ChatMemberHandler.MY_CHAT_MEMBER))
    
    application.add_handler(CommandHandler("chats", chats))
    application.add_handler(CommandHandler("cid", cid))
    application.add_handler(CommandHandler("start", start, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("help", help, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("delete", delete, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("me", me, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("mute", mute, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("unmute", unmute, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("uid", uid,  filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("team", team,  filters.ChatType.PRIVATE))
    
    register_handler = ConversationHandler(
        entry_points=[CommandHandler('reg', reg, filters.ChatType.PRIVATE)],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, nickname)],
            2: [CallbackQueryHandler(lane)],
            3: [CallbackQueryHandler(sublane)],
            4: [CallbackQueryHandler(rank)],
        },
        fallbacks=[]
    )
    application.add_handler(register_handler)
    
    find_mate_handler = ConversationHandler(
        entry_points=[CommandHandler('mate', mate, filters.ChatType.PRIVATE)],
        states={
            1: [CallbackQueryHandler(select_lane)],
            2: [CallbackQueryHandler(select_rank)],
        },
        fallbacks=[]
    )
    application.add_handler(find_mate_handler)

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
