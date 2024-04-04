import os
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from flask import Flask, redirect
from threading import Thread
from motor.motor_asyncio import AsyncIOMotorClient


API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
BOT_USERNAME = os.environ.get("BOT_USERNAME") # Without @

#database
client = AsyncIOMotorClient(DATABASE_URL)
db = client['databas']
groups = db['group_id']


bot = Client(
    "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN)


@bot.on_message(filters.command("start") & filters.private)
async def start(_, message):
    button = [[
        InlineKeyboardButton("➕ Add me in your Group", url=f"http://t.me/{BOT_USERNAME}?startgroup=none&admin=delete_messages"),
        ],[
        InlineKeyboardButton("📌 Updates channel", url=f"https://t.me/botsync"),
    ]]
    await message.reply_text(
        f"<b>Hello {message.from_user.mention},\nI am a AutoDelete Bot, I can delete your groups messages automatically after a certain period of time.\nUsage:</b> <code>/set_time <delete_time_in_seconds></code>",
        reply_markup=InlineKeyboardMarkup(button),
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True
    )
    
@bot.on_message(filters.command("set_time"))
async def set_delete_time(_, message):

    # Check if the message is from a private chat
    if message.chat.type in [enums.ChatType.PRIVATE]:
        await message.reply("This command can only be used in groups.")
        return
    
    # Extract group_id and delete_time from the message
    if len(message.text.split()) == 1:
        await message.reply_text("<b>Please provide the delete time in seconds. Usage:</b> <code>/set_time <delete_time_in_seconds></code>")
        return

    delete_time = message.text.split()[1]
    if not delete_time.isdigit():
        await message.reply_text("<b>Delete time must be an integer.</b>")
        return
    
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Check if the user is the group owner or an admin
    administrators = []
    async for m in bot.get_chat_members(chat_id, filter=enums.ChatMembersFilter.ADMINISTRATORS):
        administrators.append(m.user.id)

    if user_id not in administrators:
        await message.reply("<b>Only group admins can enable or disable auto approve.</b>")
        return
    
    # Save to the database
    await groups.update_one(
        {"group_id": chat_id},
        {"$set": {"delete_time": delete_time}},
        upsert=True
    )
    try:
        await message.reply_text(f"<b>Set delete_time to {delete_time} seconds for this group.</b>")
    except Exception as e:
        await message.reply_text(f"Erorr: {e}")    
        
@bot.on_message(filters.group)
async def delete_message(_, message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Check if the user is the group owner or an admin
    administrators = []
    async for m in bot.get_chat_members(chat_id, filter=enums.ChatMembersFilter.ADMINISTRATORS):
        administrators.append(m.user.id)

    if user_id not in administrators:
        return

    # Check if the group has a delete time set
    group = await groups.find_one({"group_id": chat_id})
    if not group:
        return

    delete_time = group["delete_time"]

    try:
        # Delete the message
        await message.delete(delete_time)
    except Exception as e:
        print(f"An error occurred: {e}/nGroup ID: {chat_id}")    


# Flask configuration
app = Flask(__name__)

@app.route('/')
def index():
    return redirect(f"https://telegram.me/{BOT_USERNAME}", code=302)

def run():
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))

if __name__ == "__main__":
    t = Thread(target=run)
    t.start()
    bot.run()    