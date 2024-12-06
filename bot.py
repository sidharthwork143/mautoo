import os
import re
import asyncio
from threading import Thread

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from flask import Flask, redirect
from motor.motor_asyncio import AsyncIOMotorClient

# Environment Variables
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
BOT_USERNAME = os.environ.get("BOT_USERNAME")  # Without @

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

def parse_time_to_seconds(time_str):
    """
    Parse human-readable time string to seconds.
    Supports formats: 
    - Bare numbers (assumed seconds)
    - 's' for seconds
    - 'm' for minutes
    - 'h' for hours
    - 'd' for days
    - 'w' for weeks

    Examples:
    30 or 30s = 30 seconds
    5m = 300 seconds
    2h = 7200 seconds
    1d = 86400 seconds
    1w = 604800 seconds
    """
    if not time_str:
        return None

    # Remove whitespace
    time_str = time_str.strip().lower()

    # If it's just a number, assume seconds
    if time_str.isdigit():
        return int(time_str)

    # Regex to match number and optional unit
    match = re.match(r'^(\d+)([smhdw])?$', time_str)
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2) or 's'  # Default to seconds if no unit

    # Convert to seconds based on unit
    time_multipliers = {
        's': 1,       # seconds
        'm': 60,      # minutes
        'h': 3600,    # hours
        'd': 86400,   # days
        'w': 604800   # weeks
    }

    # Calculate total seconds
    total_seconds = value * time_multipliers.get(unit, 1)

    # Additional validation
    if total_seconds < 30:
        return None  # Minimum 30 seconds
    if total_seconds > 604800:  # Maximum 1 week
        return None

    return total_seconds

async def load_group_settings():
    """
    Preload group settings into memory to reduce database calls.
    This should be called once when the bot starts.
    """
    global GROUP_SETTINGS
    cursor = groups_collection.find({})
    async for group in cursor:
        GROUP_SETTINGS[group['group_id']] = group.get('delete_time', DEFAULT_DELETE_TIME)

async def update_group_settings(chat_id, delete_time=None):
    """
    Update group settings in both database and in-memory cache.
    
    :param chat_id: Telegram group ID
    :param delete_time: Time in seconds to delete messages (optional)
    """
    try:
        if delete_time is not None:
            # Update database
            await groups_collection.update_one(
                {"group_id": chat_id},
                {"$set": {"delete_time": delete_time}},
                upsert=True
            )
            
            # Update in-memory cache
            GROUP_SETTINGS[chat_id] = int(delete_time)
        else:
            # If no delete time provided, set to default
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
    """
    Handle bot being added to a new group.
    Set default delete time of 10 minutes.
    """
    for new_member in message.new_chat_members:
        if new_member.is_self:  # Check if the new member is the bot itself
            chat_id = message.chat.id
            
            # Set default delete time when added to a new group
            await update_group_settings(chat_id)
            
            # Send welcome message with default settings
            welcome_text = (
                "**Hello! I'm an AutoDelete Bot 🤖**\n\n"
                f"I've automatically set message auto-delete to **10 minutes** for this group.\n\n"
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
    button = [[
        InlineKeyboardButton("➕ Add me in your Group", url=f"http://t.me/{BOT_USERNAME}?startgroup=none&admin=delete_messages"),
    ],[
        InlineKeyboardButton("📌 Updates channel", url=f"https://t.me/botsync"),
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
    # Check if the message is from a private chat
    if message.chat.type in [enums.ChatType.PRIVATE]:
        await message.reply("This command can only be used in groups.")
        return

    # Extract group_id and delete_time from the message
    if len(message.text.split()) == 1:
        # Show current delete time if no new time is specified
        current_time = GROUP_SETTINGS.get(message.chat.id, DEFAULT_DELETE_TIME)
        
        # Convert seconds to human-readable format
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

    # Parse the time string
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

    # Check if the user is the group owner or an admin
    administrators = [
        member.user.id async for member in bot.get_chat_members(chat_id, filter=enums.ChatMembersFilter.ADMINISTRATORS)
    ]
    
    if user_id not in administrators:
        await message.reply("Only group admins can set delete time.")
        return

    # Update group settings
    await update_group_settings(chat_id, delete_time)

    # Convert seconds to human-readable format for response
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
    chat_id = message.chat.id
    
    # Check group settings from memory cache
    delete_time = GROUP_SETTINGS.get(chat_id, DEFAULT_DELETE_TIME)
    
    try:
        # Delete the message after specified time
        await asyncio.sleep(delete_time)
        await message.delete()
    except Exception as e:
        print(f"An error occurred: {e}\nGroup ID: {chat_id}")

# Flask configuration
app = Flask(__name__)

@app.route('/')
def index():
    return redirect(f"https://telegram.me/{BOT_USERNAME}", code=302)

def run():
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))

async def main():
    # Load group settings before starting the bot
    await load_group_settings()
    
    # Create a task to run the Flask server
    flask_thread = Thread(target=run)
    flask_thread.start()
    
    # Run the Telegram bot
    await bot.start()
    await bot.idle()

if __name__ == "__main__":
    asyncio.run(main())
