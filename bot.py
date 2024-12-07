import os
import re
import asyncio
from typing import Dict, Optional
from pyrogram import Client, filters, enums, idle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from flask import Flask, redirect
from threading import Thread
from motor.motor_asyncio import AsyncIOMotorClient

# Environment variables
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

# Database setup
client = AsyncIOMotorClient(DATABASE_URL)
db = client['databas']
groups_collection = db['group_id']

# In-memory cache for group settings
groups_data: Dict[int, Dict[str, int]] = {}

def parse_time_to_seconds(time_str: str) -> Optional[int]:
    """
    Convert human-readable time string to seconds.
    Supports formats like: 1s, 1m, 1h, 1d, 1w
    """
    time_mapping = {
        's': 1,        # seconds
        'm': 60,       # minutes
        'h': 3600,     # hours
        'd': 86400,    # days
        'w': 604800    # weeks
    }
    
    match = re.match(r'^(\d+)([smhdw])$', time_str.lower())
    if not match:
        return None
    
    value = int(match.group(1))
    unit = match.group(2)
    return value * time_mapping[unit]

async def load_groups_data():
    """
    Load all group settings into memory cache.
    """
    global groups_data
    groups_data.clear()
    async for group in groups_collection.find():
        groups_data[group['group_id']] = {
            'delete_time': group.get('delete_time', 0)
        }

# Initialize Telegram Bot
bot = Client(
    "deletebot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=300,
    sleep_threshold=10
)

@bot.on_message(filters.command("start") & filters.private)
async def start(_, message):
    """
    Handle /start command in private chat.
    """
    button = [[
        InlineKeyboardButton("➕ Add me in your Group", url=f"http://t.me/{BOT_USERNAME}?startgroup=none&admin=delete_messages"),
    ],[
        InlineKeyboardButton("📌 Updates channel", url=f"https://t.me/botsync"),
    ]]
    
    await message.reply_text(
        f"**Hello {message.from_user.first_name},\n"
        "I am an AutoDelete Bot, I can delete your group's messages automatically after a certain period of time.\n"
        "Usage:** `/set_time <time>` (e.g., `1h`, `30m`, `1d`)",
        reply_markup=InlineKeyboardMarkup(button),
        parse_mode=enums.ParseMode.MARKDOWN
    )

@bot.on_message(filters.command("set_time"))
async def set_delete_time(_, message):
    """
    Set auto-delete time for a group.
    """
    # Check if the message is from a group
    if message.chat.type in [enums.ChatType.PRIVATE]:
        await message.reply("This command can only be used in groups.")
        return
    
    # Check time argument
    if len(message.text.split()) == 1:
        await message.reply_text(
            "**Please provide the delete time. Usage:** `/set_time <time>`\n"
            "Examples: `1h` (1 hour), `30m` (30 minutes), `1d` (1 day)"
        )
        return
    
    delete_time_str = message.text.split()[1]
    delete_time = parse_time_to_seconds(delete_time_str)
    
    if delete_time is None:
        await message.reply_text(
            "Invalid time format. Use format like: `1h`, `30m`, `1d`\n"
            "Examples: `1h` (1 hour), `30m` (30 minutes), `1d` (1 day)"
        )
        return
    
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Check if user is an admin
    administrators = []
    async for m in bot.get_chat_members(chat_id, filter=enums.ChatMembersFilter.ADMINISTRATORS):
        administrators.append(m.user.id)
    
    if user_id not in administrators:
        await message.reply("Only group admins can set auto-delete time.")
        return
    
    # Save to database and in-memory cache
    await groups_collection.update_one(
        {"group_id": chat_id},
        {"$set": {"delete_time": delete_time}},
        upsert=True
    )
    
    # Update in-memory cache
    groups_data[chat_id] = {"delete_time": delete_time}
    
    await message.reply_text(f"**Set delete time to {delete_time_str} for this group.**")

@bot.on_message(filters.group & filters.text)
async def delete_message(_, message):
    chat_id = message.chat.id
    
    # Check if the group has a delete time set in cache
    group_settings = groups_data.get(chat_id)
    if not group_settings:
        return
    
    delete_time = group_settings.get("delete_time", 0)
    if delete_time <= 0:
        return
    
    try:
        # Delete the message after specified time
        await asyncio.sleep(delete_time)
        await message.delete()
    except Exception as e:
        print(f"An error occurred: {e}\nGroup ID: {chat_id}")

# Flask configuration for web ping
app = Flask(__name__)

@app.route('/')
def index():
    return redirect(f"https://telegram.me/AboutRazi", code=302)

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))

async def main():
    await load_groups_data()
    t = Thread(target=run_flask)
    t.start()
    await bot.start()
    await idle()
    await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())
