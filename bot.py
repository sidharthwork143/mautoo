import os, re, asyncio
from typing import Optional

from pyrogram import Client, filters, enums, idle
from pyrogram.errors import FloodWait
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
    workers=100,
    sleep_threshold=10
)

def parse_time_to_seconds(time_str: Optional[str]) -> Optional[int]:
    """Parse human-readable time string to seconds."""
    if not time_str:
        return None

    time_str = time_str.strip().lower()
    match = re.match(r'^(\d+)([smhdw]?)$', time_str)
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2) or 's'
    time_multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}

    total_seconds = value * time_multipliers.get(unit, 1)
    return total_seconds if 30 <= total_seconds <= 604800 else None

async def load_group_settings():
    """Preload group settings into memory to reduce database calls."""
    global GROUP_SETTINGS
    cursor = groups_collection.find({})
    async for group in cursor:
        GROUP_SETTINGS[group['group_id']] = group.get('delete_time', DEFAULT_DELETE_TIME)
    print("Group settings loaded into memory.")


async def update_group_settings(chat_id, delete_time=None):
    """Update group settings in both database and memory."""
    delete_time = delete_time or DEFAULT_DELETE_TIME
    await groups_collection.update_one(
        {"group_id": chat_id},
        {"$set": {"delete_time": delete_time}},
        upsert=True
    )
    GROUP_SETTINGS[chat_id] = delete_time

@bot.on_message(filters.command("start") & filters.private)
async def start(_, message):
    """Handle the /start command."""
    button = [[
        InlineKeyboardButton("➕ Add me in your Group", url=f"http://t.me/{bot.username}?startgroup=none&admin=delete_messages"),
    ], [
        InlineKeyboardButton("📌 Updates channel", url="https://t.me/botsync"),
    ]]
    await message.reply_text(
        f"**Hello {message.from_user.first_name}!**\n\n"
        f"I can automatically delete messages in your group after a set time.\n\n"
        f"**Default:** 10 minutes\n"
        f"**Change Time:** `/set_time <time>`\n\n"
        f"**Time formats:**\n"
        f"- `30` or `30s` = 30 seconds\n"
        f"- `5m` = 5 minutes\n"
        f"- `2h` = 2 hours\n"
        f"- `1d` = 1 day\n"
        f"- `1w` = 1 week",
        reply_markup=InlineKeyboardMarkup(button),
        parse_mode=enums.ParseMode.MARKDOWN
    )

@bot.on_message(filters.command("set_time"))
async def set_delete_time(_, message):
    """Handle the /set_time command."""
    if message.chat.type == enums.ChatType.PRIVATE:
        await message.reply("This command can only be used in groups.")
        return

    args = message.text.split()
    if len(args) == 1:
        current_time = GROUP_SETTINGS.get(message.chat.id, DEFAULT_DELETE_TIME)
        await message.reply_text(
            f"**Current delete time is {current_time // 60} minutes.**\n\n"
            f"**Usage:** `/set_time <time>`\n"
            f"**Formats:** `30s`, `5m`, `2h`, `1d`, `1w`"
        )
        return

    delete_time = parse_time_to_seconds(args[1])
    if delete_time is None:
        await message.reply_text("**Invalid time format!** Use `30s`, `5m`, `2h`, `1d`, `1w`.")
        return

    user_id = message.from_user.id
    admins = [
        member.user.id async for member in bot.get_chat_members(
            message.chat.id, filter=enums.ChatMembersFilter.ADMINISTRATORS
        )
    ]
    if user_id not in admins:
        await message.reply("Only admins can set the delete time.")
        return

    await update_group_settings(message.chat.id, delete_time)
    await message.reply_text(f"**Set delete time to {delete_time // 60} minutes.**")

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
        print(f"Error deleting message in {chat_id}: {e}")

# Quart application
app = Quart(__name__)

@app.route('/')
async def index():
    return redirect(f"https://telegram.me/AboutRazi", code=302)

async def main():
    await load_group_settings()
    quart_task = app.run_task(host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))

    async def start_bot():
        while True:
            try:
                await bot.start()
                print("Bot started successfully.")
                await idle()  # Keeps the bot running
                break  # Exit the loop if successful
            except FloodWait as e:
                print(f"FloodWait: Need to wait for {e.x} seconds before retrying.")
                await asyncio.sleep(e.x)
    await asyncio.gather(start_bot(), quart_task)


if __name__ == "__main__":
    asyncio.run(main())
