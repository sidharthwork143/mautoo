import os
import re
import asyncio
from typing import Optional

from pyrogram import Client, filters, enums, idle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram.errors import FloodWait
from quart import Quart, redirect

# Environment Variables
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

# Default delete time (10 minutes = 600 seconds)
DEFAULT_DELETE_TIME = 600

# In-memory cache for group settings
GROUP_SETTINGS = {}

# Database initialization
client = AsyncIOMotorClient(DATABASE_URL)
db = client['databas']
groups_collection = db['group_id']

# Telegram Bot Client
bot = Client(
    "deletebot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=300,
    sleep_threshold=10
)

def parse_time_to_seconds(time_str: Optional[str]) -> Optional[int]:
    """Parse human-readable time string to seconds."""
    if not time_str:
        return None

    time_str = time_str.strip().lower()

    if time_str.isdigit():
        return int(time_str)

    match = re.match(r'^(\d+)([smhdw])?$', time_str)
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2) or 's'

    time_multipliers = {
        's': 1,       # seconds
        'm': 60,      # minutes
        'h': 3600,    # hours
        'd': 86400,   # days
        'w': 604800   # weeks
    }

    total_seconds = value * time_multipliers.get(unit, 1)

    if total_seconds < 30 or total_seconds > 604800:
        return None

    return total_seconds

async def load_group_settings():
    """Preload group settings into memory to reduce database calls."""
    global GROUP_SETTINGS
    cursor = groups_collection.find({})
    async for group in cursor:
        GROUP_SETTINGS[group['group_id']] = group.get('delete_time', DEFAULT_DELETE_TIME)

async def update_group_settings(chat_id, delete_time=None):
    """Update group settings in both database and in-memory cache."""
    try:
        if delete_time is not None:
            await groups_collection.update_one(
                {"group_id": chat_id},
                {"$set": {"delete_time": delete_time}},
                upsert=True
            )
            GROUP_SETTINGS[chat_id] = int(delete_time)
        else:
            await groups_collection.update_one(
                {"group_id": chat_id},
                {"$set": {"delete_time": DEFAULT_DELETE_TIME}},
                upsert=True
            )
            GROUP_SETTINGS[chat_id] = DEFAULT_DELETE_TIME
    except Exception as e:
        print(f"Error updating group settings for {chat_id}: {e}")

@bot.on_message(filters.new_chat_members)
async def handle_new_chat(_, message):
    """Handle bot being added to a new group."""
    for new_member in message.new_chat_members:
        if new_member.is_self:
            chat_id = message.chat.id
            await update_group_settings(chat_id)
            welcome_text = (
                "**Hello! I'm an AutoDelete Bot 🤖**\n\n"
                "I've automatically set message auto-delete to **10 minutes** for this group.\n\n"
                "**Time formats you can use:**\n"
                "- `30` or `30s` = 30 seconds\n"
                "- `5m` = 5 minutes\n"
                "- `2h` = 2 hours\n"
                "- `1d` = 1 day\n"
                "- `1w` = 1 week\n\n"
                "**Change time:** `/set_time <time>`"
            )
            button = [[
                InlineKeyboardButton("⏰ Change Delete Time", callback_data="change_time")
            ]]
            await message.reply_text(
                welcome_text,
                reply_markup=InlineKeyboardMarkup(button),
                parse_mode=enums.ParseMode.MARKDOWN
            )
            break

@bot.on_message(filters.command("start") & filters.private)
async def start(_, message):
    """Handle the /start command."""
    button = [[
        InlineKeyboardButton("➕ Add me in your Group", url=f"http://t.me/{bot.username}?startgroup=none&admin=delete_messages"),
    ], [
        InlineKeyboardButton("📌 Updates channel", url="https://t.me/botsync"),
    ]]
    await message.reply_text(
        f"**Hello {message.from_user.first_name},\nI am an AutoDelete Bot, I can delete your groups' messages automatically.\n\n"
        f"**Default:** Messages deleted after 10 minutes\n"
        f"**Time formats:**\n"
        f"- `30` or `30s` = 30 seconds\n"
        f"- `5m` = 5 minutes\n"
        f"- `2h` = 2 hours\n"
        f"- `1d` = 1 day\n"
        f"- `1w` = 1 week\n\n"
        f"**Usage:** `/set_time <time>`",
        reply_markup=InlineKeyboardMarkup(button),
        parse_mode=enums.ParseMode.MARKDOWN
    )

@bot.on_message(filters.command("set_time"))
async def set_delete_time(_, message):
    """Handle the /set_time command."""
    if message.chat.type in [enums.ChatType.PRIVATE]:
        await message.reply("This command can only be used in groups.")
        return

    if len(message.text.split()) == 1:
        current_time = GROUP_SETTINGS.get(message.chat.id, DEFAULT_DELETE_TIME)

        def format_time(seconds):
            if seconds >= 604800:
                return f"{seconds // 604800}w"
            elif seconds >= 86400:
                return f"{seconds // 86400}d"
            elif seconds >= 3600:
                return f"{seconds // 3600}h"
            elif seconds >= 60:
                return f"{seconds // 60}m"
            else:
                return f"{seconds}s"

        await message.reply_text(
            f"**Current delete time is {format_time(current_time)}.**\n\n"
            "**Time formats:**\n"
            "- `30` or `30s` = 30 seconds\n"
            "- `5m` = 5 minutes\n"
            "- `2h` = 2 hours\n"
            "- `1d` = 1 day\n"
            "- `1w` = 1 week\n\n"
            "**Usage:** `/set_time <time>`"
        )
        return

    delete_time = parse_time_to_seconds(message.text.split()[1])

    if delete_time is None:
        await message.reply_text(
            "**Invalid time format!**\n\n"
            "**Time formats:**\n"
            "- `30` or `30s` = 30 seconds\n"
            "- `5m` = 5 minutes\n"
            "- `2h` = 2 hours\n"
            "- `1d` = 1 day\n"
            "- `1w` = 1 week"
        )
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    administrators = [
        member.user.id async for member in bot.get_chat_members(chat_id, filter=enums.ChatMembersFilter.ADMINISTRATORS)
    ]

    if user_id not in administrators:
        await message.reply("Only group admins can set delete time.")
        return

    await update_group_settings(chat_id, delete_time)

    def format_time(seconds):
        if seconds >= 604800:
            return f"{seconds // 604800}w"
        elif seconds >= 86400:
            return f"{seconds // 86400}d"
        elif seconds >= 3600:
            return f"{seconds // 3600}h"
        elif seconds >= 60:
            return f"{seconds // 60}m"
        else:
            return f"{seconds}s"

    await message.reply_text(f"**Set delete time to {format_time(delete_time)} for this group.**")

@bot.on_message(filters.group & filters.text)
async def delete_message(_, message):
    """Delete messages based on group settings."""
    chat_id = message.chat.id

    delete_time = GROUP_SETTINGS.get(chat_id, DEFAULT_DELETE_TIME)

    try:
        await asyncio.sleep(delete_time)
        await message.delete()
    except FloodWait as e:
        await asyncio.sleep(e.x)
        await message.delete()
    except Exception as e:
        print(f"An error occurred: {e}\nGroup ID: {chat_id}")

# Quart application
app = Quart(__name__)

@app.route('/')
async def index():
    return redirect(f"https://telegram.me/AboutRazi", code=302)

async def main():
    """Start the bot and Quart server."""
    await load_group_settings()

    quart_task = asyncio.create_task(app.run_task(host="0.0.0.0", port=int(os.environ.get('PORT', 8080))))
    await bot.start()
    await idle()
    quart_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())


