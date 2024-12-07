import os
import re
import asyncio
from typing import Optional, Dict

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram.errors import FloodWait, RPCError

class AutoDeleteBot:
    # Constants
    DEFAULT_DELETE_TIME = 600
    MIN_DELETE_TIME = 30
    MAX_DELETE_TIME = 604800
    TIME_MULTIPLIERS = {
        's': 1,       # seconds
        'm': 60,      # minutes
        'h': 3600,    # hours
        'd': 86400,   # days
        'w': 604800   # weeks
    }

    def __init__(self):
        # Environment Variables
        self.API_ID = os.environ.get("API_ID")
        self.API_HASH = os.environ.get("API_HASH")
        self.BOT_TOKEN = os.environ.get("BOT_TOKEN")
        self.DATABASE_URL = os.environ.get("DATABASE_URL")

        # In-memory cache for group settings
        self.group_settings: Dict[int, int] = {}

        # Database initialization
        self.db_client = AsyncIOMotorClient(self.DATABASE_URL)
        self.db = self.db_client['databas']
        self.groups_collection = self.db['group_id']

        # Telegram Bot Client
        self.bot = Client(
            "deletebot",
            api_id=self.API_ID,
            api_hash=self.API_HASH,
            bot_token=self.BOT_TOKEN,
            workers=200,
            sleep_threshold=5
        )

        # Register event handlers
        self.register_handlers()

    def register_handlers(self):
        """Register bot event handlers."""
        self.bot.add_handler(filters.command("start") & filters.private, self.start_command)
        self.bot.add_handler(filters.command("set_time"), self.set_delete_time)
        self.bot.add_handler(filters.group & filters.text, self.delete_message)

    @staticmethod
    def parse_time_to_seconds(time_str: Optional[str]) -> Optional[int]:
        """Parse human-readable time string to seconds."""
        if not time_str:
            return None

        time_str = time_str.strip().lower()

        # Direct digit check
        if time_str.isdigit():
            return int(time_str)

        # Regex match for time format
        match = re.match(r'^(\d+)([smhdw])?$', time_str)
        if not match:
            return None

        value = int(match.group(1))
        unit = match.group(2) or 's'

        total_seconds = value * AutoDeleteBot.TIME_MULTIPLIERS.get(unit, 1)

        # Validate time range
        if total_seconds < AutoDeleteBot.MIN_DELETE_TIME or total_seconds > AutoDeleteBot.MAX_DELETE_TIME:
            return None

        return total_seconds

    def format_time(self, seconds: int) -> str:
        """Convert seconds to human-readable time format."""
        for unit, multiplier in sorted(self.TIME_MULTIPLIERS.items(), key=lambda x: x[1], reverse=True):
            if seconds >= multiplier:
                return f"{seconds // multiplier}{unit}"
        return f"{seconds}s"

    async def load_group_settings(self):
        """Preload group settings into memory to reduce database calls."""
        self.group_settings.clear()  # Clear existing settings
        cursor = self.groups_collection.find({})
        async for group in cursor:
            self.group_settings[group['group_id']] = group.get('delete_time', self.DEFAULT_DELETE_TIME)

    async def update_group_settings(self, chat_id: int, delete_time: Optional[int] = None):
        """Update group settings in both database and in-memory cache."""
        try:
            # Use default if no time specified, otherwise use provided time
            time_to_set = delete_time if delete_time is not None else self.DEFAULT_DELETE_TIME
            
            await self.groups_collection.update_one(
                {"group_id": chat_id},
                {"$set": {"delete_time": time_to_set}},
                upsert=True
            )
            self.group_settings[chat_id] = time_to_set
        except Exception as e:
            print(f"Error updating group settings for {chat_id}: {e}")

    async def start_command(self, _, message):
        """Handle the /start command in private chat."""
        buttons = [
            [InlineKeyboardButton("➕ Add me in your Group", url=f"http://t.me/{self.bot.username}?startgroup=none&admin=delete_messages")],
            [InlineKeyboardButton("📌 Updates channel", url="https://t.me/botsync")]
        ]
        await message.reply_text(
            f"**Hello {message.from_user.first_name},\n"
            f"I am an AutoDelete Bot, I can delete your groups' messages automatically.\n\n"
            f"**Default:** Messages deleted after {self.format_time(self.DEFAULT_DELETE_TIME)}\n"
            f"**Time formats:**\n"
            f"- `30` or `30s` = 30 seconds\n"
            f"- `5m` = 5 minutes\n"
            f"- `2h` = 2 hours\n"
            f"- `1d` = 1 day\n"
            f"- `1w` = 1 week\n\n"
            f"**Usage:** `/set_time <time>`",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.MARKDOWN
        )

    async def set_delete_time(self, _, message):
        """Handle the /set_time command."""
        # Validate group context
        if message.chat.type in [enums.ChatType.PRIVATE]:
            await message.reply("This command can only be used in groups.")
            return

        # Check current time if no new time is specified
        if len(message.text.split()) == 1:
            current_time = self.group_settings.get(message.chat.id, self.DEFAULT_DELETE_TIME)
            await message.reply_text(
                f"**Current delete time is {self.format_time(current_time)}.**\n\n"
                "**Time formats:**\n"
                "- `30` or `30s` = 30 seconds\n"
                "- `5m` = 5 minutes\n"
                "- `2h` = 2 hours\n"
                "- `1d` = 1 day\n"
                "- `1w` = 1 week\n\n"
                "**Usage:** `/set_time <time>`"
            )
            return

        # Parse and validate new delete time
        delete_time = self.parse_time_to_seconds(message.text.split()[1])
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

        # Validate admin permissions
        chat_id = message.chat.id
        try:
            chat_member = await self.bot.get_chat_member(chat_id, message.from_user.id)
            if chat_member.status not in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                await message.reply("Only group admins can set delete time.")
                return
        except RPCError:
            await message.reply("Could not verify admin status.")
            return

        # Update group settings
        await self.update_group_settings(chat_id, delete_time)
        
        # Send confirmation message
        await message.reply_text(f"**Set delete time to {self.format_time(delete_time)} for this group.**")

    async def delete_message(self, _, message):
        """Delete messages based on group settings."""
        chat_id = message.chat.id
        
        # Dynamically fetch group settings if not in cache
        if chat_id not in self.group_settings:
            await self.load_group_settings()
        
        delete_time = self.group_settings.get(chat_id, self.DEFAULT_DELETE_TIME)

        try:
            await asyncio.sleep(delete_time)
            await message.delete()
        except FloodWait as e:
            await asyncio.sleep(e.x)
            try:
                await message.delete()
            except Exception:
                pass
        except Exception:
            pass

    async def start(self):
        """Start the bot."""
        await self.load_group_settings()
        await self.bot.start()
        await self.bot.idle()

def main():
    bot = AutoDeleteBot()
    asyncio.run(bot.start())

if __name__ == "__main__":
    main()

