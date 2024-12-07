import os
import re
import asyncio
import logging
from typing import Dict, Optional

from pyrogram import Client, filters, enums, idle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait, MessageDeleteForbidden

from motor.motor_asyncio import AsyncIOMotorClient
from flask import Flask, redirect
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables with type hints and validation
def get_env_var(var_name: str, default: Optional[str] = None) -> str:
    """Safely retrieve environment variables with optional default."""
    value = os.environ.get(var_name, default)
    if value is None:
        raise ValueError(f"Missing required environment variable: {var_name}")
    return value

# Configuration constants
API_ID = get_env_var("API_ID")
API_HASH = get_env_var("API_HASH")
BOT_TOKEN = get_env_var("BOT_TOKEN")
DATABASE_URL = get_env_var("DATABASE_URL")

class AutoDeleteBot:
    def __init__(self):
        # Database setup
        self.mongo_client = AsyncIOMotorClient(DATABASE_URL)
        self.db = self.mongo_client['databas']
        self.groups_collection = self.db['group_id']
        
        # In-memory cache for group settings
        self.groups_data: Dict[int, Dict[str, int]] = {}
        
        # Initialize Telegram Bot
        self.bot = Client(
            "deletebot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workers=200,
            sleep_threshold=10
        )
        
        # Register message handlers
        self.register_handlers()
        
        # Flask app for web ping
        self.flask_app = Flask(__name__)
        self.setup_flask_routes()

    @staticmethod
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

    async def load_groups_data(self):
        """
        Load all group settings into memory cache.
        """
        try:
            self.groups_data.clear()
            async for group in self.groups_collection.find():
                self.groups_data[group['group_id']] = {
                    'delete_time': group.get('delete_time', 0)
                }
            logger.info(f"Loaded {len(self.groups_data)} group settings")
        except Exception as e:
            logger.error(f"Error loading group data: {e}")

    def register_handlers(self):
        """Register bot message handlers."""
        @self.bot.on_message(filters.command("start") & filters.private)
        async def start(_, message):
            button = [[
                InlineKeyboardButton("➕ Add me in your Group", 
                                     url=f"http://t.me/{BOT_USERNAME}?startgroup=none&admin=delete_messages"),
            ],[
                InlineKeyboardButton("📌 Updates channel", url="https://t.me/botsync"),
            ]]
            
            await message.reply_text(
                f"**Hello {message.from_user.first_name},\n"
                "I am an AutoDelete Bot, I can delete your group's messages automatically after a certain period of time.\n"
                "Usage:** `/set_time <time>` (e.g., `1h`, `30m`, `1d`)",
                reply_markup=InlineKeyboardMarkup(button),
                parse_mode=enums.ParseMode.MARKDOWN
            )

        @self.bot.on_message(filters.command("set_time"))
        async def set_delete_time(_, message):
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
            delete_time = self.parse_time_to_seconds(delete_time_str)
            
            if delete_time is None:
                await message.reply_text(
                    "Invalid time format. Use format like: `1h`, `30m`, `1d`\n"
                    "Examples: `1h` (1 hour), `30m` (30 minutes), `1d` (1 day)"
                )
                return
            
            chat_id = message.chat.id
            user_id = message.from_user.id
            
            # Check if user is an admin (more efficient method)
            try:
                chat_member = await self.bot.get_chat_member(chat_id, user_id)
                if chat_member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                    await message.reply("Only group admins can set auto-delete time.")
                    return
            except Exception as e:
                logger.error(f"Error checking admin status: {e}")
                await message.reply("Could not verify admin status.")
                return
            
            # Save to database and in-memory cache
            await self.groups_collection.update_one(
                {"group_id": chat_id},
                {"$set": {"delete_time": delete_time}},
                upsert=True
            )
            
            # Update in-memory cache
            self.groups_data[chat_id] = {"delete_time": delete_time}
            
            await message.reply_text(f"**Set delete time to {delete_time_str} for this group.**")

        @self.bot.on_message(filters.group & filters.text)
        async def delete_message(_, message):
            chat_id = message.chat.id
            
            # Check if the group has a delete time set in cache
            group_settings = self.groups_data.get(chat_id)
            if not group_settings:
                return
            
            delete_time = group_settings.get("delete_time", 600)
            
            try:
                # Delete the message after specified time
                await asyncio.sleep(delete_time)
                await message.delete()
            except FloodWait as e:
                # Handle Telegram's flood wait
                logger.warning(f"Flood wait encountered. Sleeping for {e.x} seconds.")
                await asyncio.sleep(e.x)
            except MessageDeleteForbidden:
                logger.info(f"Cannot delete message in chat {chat_id}. Possibly due to permissions.")
            except Exception as e:
                logger.error(f"An error occurred: {e}\nGroup ID: {chat_id}")

    def setup_flask_routes(self):
        """Set up Flask routes for web ping."""
        @self.flask_app.route('/')
        def index():
            return redirect(f"https://telegram.me/AboutRazi", code=302)

    def run_flask(self):
        """Run Flask server in a separate thread."""
        port = int(os.environ.get('PORT', 8080))
        self.flask_app.run(host="0.0.0.0", port=port)

    async def start(self):
        """Start the bot and related services."""
        # Load groups data
        await self.load_groups_data()
        
        # Start Flask in a separate thread
        flask_thread = threading.Thread(target=self.run_flask, daemon=True)
        flask_thread.start()
        
        # Start the Pyrogram bot
        await self.bot.start()
        logger.info("Bot started successfully.")
        
        # Keep the bot running
        await self.bot.idle()

def main():
    bot = AutoDeleteBot()
    asyncio.run(bot.start())

if __name__ == "__main__":
    main()
