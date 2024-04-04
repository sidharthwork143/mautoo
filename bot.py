import os
from pyrogram import Client, filters, enums
from flask import Flask, redirect
from threading import Thread
from motor.motor_asyncio import AsyncIOMotorClient


API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

#database
client = AsyncIOMotorClient(DATABASE_URL)
db = client['databas']
groups = db['group_id']


app = Client(
    "bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN)


app.on_message(filters.command("start") & filters.private)
async def start(_, message):
    await message.reply_text(
        f"Hello {message.from_user.mention},\n\nI am a AutoDelete Bot.\n\nI can delete your groups messages automatically after a certain period of time\n\n Add me as a admin in your group and give delete permisions\n\nUsage: /set_time <delete_time_in_seconds>")
    
@app.on_message(filters.command("set_time"))
async def set_delete_time(app, message):

        # Check if the message is from a private chat
    if message.chat.type in [enums.ChatType.PRIVATE]:
        await message.reply("This command can only be used in groups.")
        return
    
    # Extract group_id and delete_time from the message
    args = message.text.split()
    if len(args) != 3:
        await message.reply_text("Usage: /set_time <delete_time_in_seconds>")
        return

    delete_time = args[1]
    if not delete_time.isdigit():
        await message.reply_text("Delete time must be an integer.")
        return
    
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Check if the user is the group owner or an admin
    administrators = []
    async for m in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.ADMINISTRATORS):
        administrators.append(m.user.id)

    if user_id not in administrators:
        await message.reply("Only group admins can enable or disable auto approve.")
        return
    

    # Save to the database
    await groups.update_one(
        {"group_id": chat_id},
        {"$set": {"delete_time": delete_time}},
        upsert=True
    )
    try:
        await message.reply_text(f"Set delete time to {delete_time} seconds for this group.")
    except Exception as e:
        await message.reply_text(f"An error occurred: {e}")    

app.on_message(filters.group)
async def delete_message(_, message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Check if the user is the group owner or an admin
    administrators = []
    async for m in client.get_chat_members(chat_id, filter=enums.ChatMembersFilter.ADMINISTRATORS):
        administrators.append(m.user.id)

    if user_id not in administrators:
        return

    # Check if the group has a delete time set
    group = await groups.find_one({"group_id": chat_id})
    if not group:
        return

    delete_time = group["delete_time"]

    # Delete the message
    await message.delete(delay=delete_time)


# Flask configuration
web = Flask(__name__)

@web.route('/')
def index():
    return redirect("https://telegram.me/botsync", code=302)

def run():
    web.run(host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))

if __name__ == "__main__":
    t = Thread(target=run)
    t.start()
    app.run()    