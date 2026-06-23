import asyncio
import logging
import random
import string
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pymongo import MongoClient
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Message,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG - EDIT THESE BEFORE RUN ----------------
BOT_TOKEN = "8482889883:AAGGLA6eEmHhSnnGaA3_aAsvkKi3j7GN0TI"
MONGO_URI = "mongodb+srv://banning972_db_user:htbNKSewT8lPHObI@cluster0.u24qotb.mongodb.net/?retryWrites=true&w=majority"
PRIVATE_CHANNEL_ID = -1003133185798
ADMIN_IDS: List[int] = [7694228822]
# Premium channel ID (yahan se expired users auto-kick honge)
PREMIUM_CHANNEL_ID = -1003608973399  # ISKO APNA PREMIUM CHANNEL ID SE REPLACE KARNA
# Force join channels (can be @username or -100ID format)
FORCE_JOIN_CHANNELS: List[str] = ["@merijaan7x","@merijaan7xbackup"]
# Main channel link for Join button
MAIN_CHANNEL_LINK = "https://t.me/merijaan7xbackup"
# -----------------------------------------------------------------

# --- MongoDB setup ---
client = MongoClient(MONGO_URI)
db = client["merijaan7xBot"]
media_collection = db["media_files"]
users_collection = db["users"]
settings_collection = db["settings"]
access_collection = db["access_tokens"]
deleted_users_collection = db["deleted_users"]

# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------- SAFE REPLY FUNCTION ----------------
async def safe_reply(update: Update, text: str, **kwargs):
    """Safely reply to a message, handling None messages"""
    try:
        if update.message:
            return await update.message.reply_text(text, **kwargs)
        elif update.effective_message:
            return await update.effective_message.reply_text(text, **kwargs)
        elif update.callback_query and update.callback_query.message:
            return await update.callback_query.message.reply_text(text, **kwargs)
        else:
            logger.error(f"Cannot reply: No message object found. Text: {text}")
            return None
    except Exception as e:
        logger.error(f"Error in safe_reply: {e}")
        return None

# ---------------- HELPERS ----------------
def gen_id(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def save_data(media_id: str, files: list, custom_photo: Optional[str] = None):
    """Save media data with optional custom photo"""
    media_collection.update_one(
        {"media_id": media_id}, 
        {"$set": {"files": files, "custom_photo": custom_photo}}, 
        upsert=True
    )


def get_data(media_id: str) -> Optional[dict]:
    """Get media data including custom photo"""
    doc = media_collection.find_one({"media_id": media_id})
    return doc if doc else None


def ensure_user_record(user_id: int, username: Optional[str] = None):
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "username": username, "active": True}},
        upsert=True,
    )


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def set_premium(user_id: int, value: bool):
    """Set permanent premium status"""
    users_collection.update_one(
        {"user_id": user_id}, 
        {"$set": {"premium": bool(value), "premium_type": "permanent" if value else None}},
        upsert=True
    )


def is_premium(user_id: int) -> bool:
    """Check if user has premium (permanent or temporary)"""
    u = users_collection.find_one({"user_id": user_id})
    if u and u.get("premium"):
        return True
    
    # Check temporary access
    access_doc = access_collection.find_one({"user_id": user_id, "active": True})
    if access_doc:
        expiry_date = access_doc.get("expiry_date")
        if expiry_date and expiry_date > datetime.now():
            return True
    
    return False


def ban_user(user_id: int):
    users_collection.update_one({"user_id": user_id}, {"$set": {"banned": True}}, upsert=True)


def unban_user(user_id: int):
    users_collection.update_one({"user_id": user_id}, {"$set": {"banned": False}}, upsert=True)


def is_banned(user_id: int) -> bool:
    u = users_collection.find_one({"user_id": user_id})
    return bool(u and u.get("banned", False))

# ---------------- NEW HELPER FUNCTIONS ----------------
def get_force_join_channels() -> List[str]:
    """Get current force join channels from database"""
    doc = settings_collection.find_one({"key": "force_join_channels"})
    if doc and "channels" in doc:
        return doc["channels"]
    return FORCE_JOIN_CHANNELS.copy()

def save_force_join_channels(channels: List[str]):
    """Save force join channels to database"""
    settings_collection.update_one(
        {"key": "force_join_channels"},
        {"$set": {"channels": channels}},
        upsert=True
    )

def add_private_force_join(channel_id: str):
    """Add private channel to force join list"""
    channels = get_force_join_channels()
    if channel_id not in channels:
        channels.append(channel_id)
        save_force_join_channels(channels)
    return channels

def remove_private_force_join(channel_id: str):
    """Remove private channel from force join list"""
    channels = get_force_join_channels()
    if channel_id in channels:
        channels.remove(channel_id)
        save_force_join_channels(channels)
    return channels

def add_public_force_join(channel_username: str):
    """Add public channel to force join list"""
    if not channel_username.startswith("@"):
        channel_username = "@" + channel_username
    return add_private_force_join(channel_username)

def remove_public_force_join(channel_username: str):
    """Remove public channel from force join list"""
    if not channel_username.startswith("@"):
        channel_username = "@" + channel_username
    return remove_private_force_join(channel_username)

def grant_access(user_id: int, days: int):
    """Grant temporary access to user"""
    expiry_date = datetime.now() + timedelta(days=days)
    access_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "expiry_date": expiry_date,
            "granted_date": datetime.now(),
            "days": days,
            "active": True,
            "notification_sent": False,
            "warning_sent": False,
            "kicked": False
        }},
        upsert=True
    )
    # Also set as premium for access period
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"premium": True, "premium_type": "temporary"}},
        upsert=True
    )

def revoke_access(user_id: int):
    """Revoke user's temporary access"""
    access_collection.update_one(
        {"user_id": user_id},
        {"$set": {"active": False}},
        upsert=True
    )
    # Remove premium status if not permanent
    user_doc = users_collection.find_one({"user_id": user_id})
    if user_doc and user_doc.get("premium_type") != "permanent":
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"premium": False, "premium_type": None}}
        )

def get_access_expiry(user_id: int) -> Optional[datetime]:
    """Get user's access expiry date"""
    doc = access_collection.find_one({"user_id": user_id, "active": True})
    return doc.get("expiry_date") if doc else None

def get_expiring_access_users(hours_before: int = 72) -> List[Dict]:
    """Get users whose access is expiring in next X hours"""
    cutoff_time = datetime.now() + timedelta(hours=hours_before)
    return list(access_collection.find({
        "expiry_date": {"$lte": cutoff_time, "$gte": datetime.now()},
        "active": True,
        "warning_sent": False
    }))

def get_expired_access_users() -> List[Dict]:
    """Get users whose access has expired"""
    return list(access_collection.find({
        "expiry_date": {"$lt": datetime.now()},
        "active": True,
        "kicked": False
    }))

def mark_warning_sent(user_id: int):
    """Mark warning as sent for user"""
    access_collection.update_one(
        {"user_id": user_id},
        {"$set": {"warning_sent": True}}
    )

def mark_kicked(user_id: int):
    """Mark user as kicked from premium channel"""
    access_collection.update_one(
        {"user_id": user_id},
        {"$set": {"kicked": True}}
    )

def get_channel_invite_link(channel_id: str) -> Optional[str]:
    """Get invite link for private channel from database"""
    doc = settings_collection.find_one({"key": "private_channels"})
    if doc and channel_id in doc:
        return doc[channel_id]
    return None

def save_channel_invite_link(channel_id: str, invite_link: str):
    """Save invite link for private channel"""
    settings_collection.update_one(
        {"key": "private_channels"},
        {"$set": {channel_id: invite_link}},
        upsert=True
    )

def add_deleted_user(user_id: int, username: Optional[str] = None):
    """Add user to deleted users collection"""
    deleted_users_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "username": username,
            "deleted_at": datetime.now(),
            "deleted_count": 1
        }},
        upsert=True
    )

def get_deleted_users_count() -> int:
    """Get count of deleted users"""
    return deleted_users_collection.count_documents({})

def get_total_deletions() -> int:
    """Get total number of deletions"""
    pipeline = [
        {"$group": {"_id": None, "total_deletions": {"$sum": "$deleted_count"}}}
    ]
    result = list(deleted_users_collection.aggregate(pipeline))
    return result[0]["total_deletions"] if result else 0

async def check_expiring_access(context: ContextTypes.DEFAULT_TYPE):
    """Background task to check for expiring access and send notifications"""
    # Check for users whose access is expiring in next 3 days
    expiring_users = get_expiring_access_users(72)  # 72 hours = 3 days
    
    for user in expiring_users:
        user_id = user["user_id"]
        expiry_date = user["expiry_date"]
        hours_left = int((expiry_date - datetime.now()).total_seconds() / 3600)
        days_left = hours_left // 24
        
        # Send warning to user
        try:
            await context.bot.send_message(
                user_id,
                f"⚠️ **ACCESS EXPIRY WARNING** ⚠️\n\n"
                f"Your premium access will expire in {days_left} day(s).\n"
                f"Expiry Date: {expiry_date.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"If your access is not renewed by admin before expiry:\n"
                f"1. You will lose upload permissions\n"
                f"2. You will be removed from premium channel\n\n"
                f"Contact admin immediately to renew your access!"
            )
        except Exception as e:
            logger.error(f"Failed to send expiry warning to {user_id}: {e}")
        
        # Send notification to all admins
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"📋 **Access Expiry Alert**\n"
                    f"User ID: {user_id}\n"
                    f"Expires in: {days_left} day(s)\n"
                    f"Date: {expiry_date.strftime('%Y-%m-%d %H:%M')}\n"
                    f"Use /renew {user_id} <days> to extend access"
                )
            except Exception as e:
                logger.error(f"Failed to send admin notification: {e}")
        
        # Mark warning as sent
        mark_warning_sent(user_id)

async def check_expired_access(context: ContextTypes.DEFAULT_TYPE):
    """Background task to check for expired access and kick users"""
    expired_users = get_expired_access_users()
    
    for user in expired_users:
        user_id = user["user_id"]
        
        try:
            # Kick user from premium channel
            await context.bot.ban_chat_member(
                chat_id=PREMIUM_CHANNEL_ID,
                user_id=user_id
            )
            
            # Unban after a minute (to remove from channel)
            await asyncio.sleep(60)
            await context.bot.unban_chat_member(
                chat_id=PREMIUM_CHANNEL_ID,
                user_id=user_id
            )
            
            # Revoke access in database
            revoke_access(user_id)
            
            # Notify user
            await context.bot.send_message(
                user_id,
                "🚫 **ACCESS EXPIRED** 🚫\n\n"
                "Your premium access has expired and you have been removed from the premium channel.\n"
                "You can no longer upload files.\n\n"
                "Contact admin to renew your access."
            )
            
            # Notify admins
            for admin_id in ADMIN_IDS:
                await context.bot.send_message(
                    admin_id,
                    f"✅ Auto-kick completed\n"
                    f"User: {user_id}\n"
                    f"Removed from premium channel\n"
                    f"Access revoked automatically"
                )
            
            # Mark as kicked
            mark_kicked(user_id)
            
        except Exception as e:
            logger.error(f"Failed to kick user {user_id} from premium channel: {e}")
            
            # Still revoke access even if kick fails
            revoke_access(user_id)
            mark_kicked(user_id)

# ---------------- AUTO DELETE HELPER ----------------
async def schedule_delete_message(bot, chat_id: int, message_id: int, delay: int = 600):
    """Schedule deletion of a message (bot's own message) after `delay` seconds."""
    async def _delete():
        try:
            await asyncio.sleep(delay)
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            logger.debug(f"schedule_delete_message: could not delete message {message_id} in {chat_id}: {e}")

    asyncio.create_task(_delete())

# ---------------- UPDATED FORCE JOIN FUNCTION ----------------
async def check_force_join_for_user(bot, user_id: int) -> (bool, List[str]):
    """Return (ok, missing_list). Channels can be @username or -100ID format."""
    missing = []
    force_join_channels = get_force_join_channels()
    
    for ch in force_join_channels:
        try:
            # Check if it's a private channel (starts with -100)
            if ch.startswith("-100"):
                # Directly use channel ID for private channels
                member = await bot.get_chat_member(int(ch), user_id)
                if member.status in ("left", "kicked"):
                    missing.append(ch)
            else:
                # Public channel (@username format)
                channel_username = ch if ch.startswith("@") else f"@{ch}"
                member = await bot.get_chat_member(channel_username, user_id)
                if member.status in ("left", "kicked"):
                    missing.append(ch)
        except Exception as e:
            logger.error(f"Error checking membership for {ch}: {e}")
            missing.append(ch)
    
    return (len(missing) == 0, missing)


async def check_force_join(update_obj: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update_obj.effective_user
    ok, missing = await check_force_join_for_user(context.bot, user.id)
    if not ok:
        buttons = []
        for ch in missing:
            if ch.startswith("-100"):
                # Private channel - get invite link
                invite_link = get_channel_invite_link(ch)
                if invite_link:
                    buttons.append([InlineKeyboardButton(f"Join Private Channel", url=invite_link)])
                else:
                    buttons.append([InlineKeyboardButton(f"Private Channel - Contact Admin", callback_data=f"no_invite:{ch}")])
            else:
                # Public channel
                channel_username = ch if ch.startswith("@") else f"@{ch}"
                buttons.append([InlineKeyboardButton(f"Join {channel_username}", url=f"https://t.me/{channel_username.lstrip('@')}")])
        
        # Add the "I Joined" button
        buttons.append([InlineKeyboardButton("✅ I Joined", callback_data=f"confirm_join:")])
        
        try:
            if update_obj.effective_message:
                await update_obj.effective_message.reply_html(
                    "🚫 Please join all required channels to use this bot. After joining click ✅ I Joined",
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
            else:
                await context.bot.send_message(update_obj.effective_chat.id,
                                               "🚫 Please join all required channels to use this bot. After joining click ✅ I Joined",
                                               reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            # last-resort: ignore send failure
            logger.debug("Could not send force-join message to user.")
        return False
    return True


# ---------------- UPDATED START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user_record(user.id, user.username)

    if is_banned(user.id):
        await safe_reply(update, "🚫 You are banned from using this bot.")
        return

    # If arrived with /start <media_id>, keep for later (on join confirm)
    media_id = context.args[0] if context.args else None

    ok, missing = await check_force_join_for_user(context.bot, user.id)
    if not ok:
        # Show join buttons + "I Joined" with context of media_id encoded in callback
        buttons = []
        for ch in missing:
            if ch.startswith("-100"):
                # Private channel - get invite link
                invite_link = get_channel_invite_link(ch)
                if invite_link:
                    buttons.append([InlineKeyboardButton(f"Join Private Channel", url=invite_link)])
                else:
                    buttons.append([InlineKeyboardButton(f"Private Channel - Contact Admin", callback_data=f"no_invite:{ch}")])
            else:
                # Public channel
                channel_username = ch if ch.startswith("@") else f"@{ch}"
                buttons.append([InlineKeyboardButton(f"Join {channel_username}", url=f"https://t.me/{channel_username.lstrip('@')}")])
        
        cb = f"confirm_join:{media_id or ''}"
        buttons.append([InlineKeyboardButton("✅ I Joined", callback_data=cb)])
        
        try:
            if update.message or (update.callback_query and update.callback_query.message):
                await safe_reply(update,
                    "🚫 Please join all required channels and then click below:",
                    reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            try:
                await context.bot.send_message(update.effective_chat.id, 
                    "🚫 Please join all required channels and then click below:",
                    reply_markup=InlineKeyboardMarkup(buttons))
            except Exception:
                logger.debug("Failed to send join prompt.")
        return

    # If user is fine with join and has media_id -> send media
    if media_id:
        await _send_media_for_media_id(update, context, media_id)
        
        # After sending media, show upload option ONLY FOR ADMIN
        if is_admin(user.id):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Upload Your Files", callback_data="upload")]])
            await safe_reply(update,
                "Want to upload your own files?",
                reply_markup=kb
            )
        return

    # normal start: show welcome & upload button (only for admin)
    if is_admin(user.id):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Start Uploading", callback_data="upload")]])
        await safe_reply(update,
            "<b>Welcome to Media Upload Bot!</b>\nSend media and get shareable links.\n(Admins & Premium users only.)",
            reply_markup=kb,
            parse_mode='HTML'
        )
    else:
        await safe_reply(update,
            "<b>Welcome to Media Download Bot!</b>\nUse the shared links to download media.",
            parse_mode='HTML'
        )


# helper to send stored media and warning
async def _send_media_for_media_id(update_or_chat_prov, context: ContextTypes.DEFAULT_TYPE, media_id: str):
    # update_or_chat_prov expected to be Update (with .message or .callback_query.message)
    target_msg = None
    if isinstance(update_or_chat_prov, Update):
        target_msg = update_or_chat_prov.message or (update_or_chat_prov.callback_query.message if update_or_chat_prov.callback_query else None)
    if not target_msg:
        logger.debug("No message object available to reply when sending media.")
        return

    data = get_data(media_id)
    if not data or "files" not in data:
        try:
            await target_msg.reply_text("❌ Media expired or not found.")
        except Exception:
            logger.debug("Failed to reply: media not found.")
        return

    files = data["files"]
    custom_photo = data.get("custom_photo")
    
    sent_messages = []
    
    # First send custom photo if available
    if custom_photo:
        try:
            photo_msg = await target_msg.reply_photo(custom_photo)
            sent_messages.append(photo_msg)
        except Exception as e:
            logger.error(f"Failed to send custom photo: {e}")
    
    # Then send all media files
    for f in files:
        try:
            t = f["type"]
            sent_msg: Optional[Message] = None
            if t == "photo":
                sent_msg = await target_msg.reply_photo(f["file_id"], caption=f.get("caption", ""))
            elif t == "video":
                sent_msg = await target_msg.reply_video(f["file_id"], caption=f.get("caption", ""))
            elif t == "document":
                sent_msg = await target_msg.reply_document(f["file_id"], caption=f.get("caption", ""))
            elif t == "animation":
                sent_msg = await target_msg.reply_animation(f["file_id"], caption=f.get("caption", ""))
            elif t == "video_note":
                # video_note cannot be sent with reply_* directly by Message in many libs; use bot.send_video_note
                sent_msg = await context.bot.send_video_note(target_msg.chat.id, f["file_id"])
            if sent_msg:
                sent_messages.append(sent_msg)
        except Exception as e:
            logger.error(f"Send failed for media_id {media_id}: {e}")

    # send final warning + join main channel button
    join_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Our Channel", url=MAIN_CHANNEL_LINK)]])
    warning_text = (
        "⚠️ Dᴜᴇ ᴛᴏ Cᴏᴘʏʀɪɢʜᴛ ɪssᴜᴇs...\n"
        "Yᴏᴜʀ ғɪʟᴇs ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ᴡɪᴛʜɪɴ 10 Mɪɴᴜᴛᴇs.\n"
        "Sᴏ ᴘʟᴇᴀsᴇ ғᴏʀᴡᴀʀᴅ ᴛʜᴇᴍ ᴛᴏ ᴀɴʏ ᴏᴛʜᴇʀ ᴘʟᴀᴄᴇ ғᴏʀ ғᴜᴛᴜʀᴇ ᴀᴠᴀɪʟᴀʙɪʟɪᴛʏ."
    )
    try:
        warning_msg = await target_msg.reply_text(warning_text, reply_markup=join_btn)
    except Exception:
        warning_msg = None

    # Track this as a deletion for stats
    user = update_or_chat_prov.effective_user if isinstance(update_or_chat_prov, Update) else None
    if user:
        add_deleted_user(user.id, user.username)

    # schedule deletions for all sent messages and the warning
    for msg in sent_messages:
        try:
            await schedule_delete_message(context.bot, msg.chat.id, msg.message_id, delay=600)
        except Exception as e:
            logger.info(f"Failed schedule delete for {getattr(msg,'message_id',None)}: {e}")

    if warning_msg:
        await schedule_delete_message(context.bot, warning_msg.chat.id, warning_msg.message_id, delay=600)


# ---------------- UPLOAD ----------------
async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_obj = update.message or (update.callback_query.message if update.callback_query else None)
    if not msg_obj:
        return
    user = update.effective_user

    if is_banned(user.id):
        await msg_obj.reply_text("🚫 You are banned from using this bot.")
        return

    ok, _ = await check_force_join_for_user(context.bot, user.id)
    if not ok:
        await start(update, context)
        return

    if not (is_admin(user.id) or is_premium(user.id)):
        await msg_obj.reply_text("⚠️ You are not an admin or premium user. You can't upload files.")
        return

    context.user_data["upload_files"] = []
    context.user_data["media_id"] = gen_id()
    context.user_data["custom_photo"] = None  # Store custom photo
    await msg_obj.reply_text("Send files now. Press ✅ when done.", reply_markup=ReplyKeyboardMarkup([["✅"]], resize_keyboard=True))


# ---------------- UPDATED MEDIA HANDLER ----------------
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    user = update.effective_user
    ensure_user_record(user.id, user.username)

    # If this user is currently composing a broadcast (admin), handle separately
    if context.user_data.get("awaiting_broadcast"):
        return await _capture_broadcast_content(update, context)

    # If admin wants to set custom photo
    if context.user_data.get("awaiting_custom_photo"):
        if msg.photo:
            # Store the photo file_id
            context.user_data["custom_photo"] = msg.photo[-1].file_id
            context.user_data.pop("awaiting_custom_photo", None)
            await msg.reply_text("✅ Custom photo set! Now send your media files and press ✅ when done.")
        else:
            await msg.reply_text("❌ Please send a photo for custom thumbnail.")
        return

    if is_banned(user.id):
        await msg.reply_text("🚫 You are banned from using this bot.")
        return

    ok, _ = await check_force_join_for_user(context.bot, user.id)
    if not ok:
        # ask them to join
        await start(update, context)
        return

    # If user is not admin or premium, don't allow upload
    if not (is_admin(user.id) or is_premium(user.id)):
        await msg.reply_text("⚠️ You are not an admin or premium user. You can't upload files.")
        return

    # collect media
    f = None
    caption = msg.caption or ""
    if msg.forward_from or msg.forward_from_chat:
        caption = caption or (msg.forward_from_chat.title if msg.forward_from_chat else "")

    if msg.photo:
        f = {"type": "photo", "file_id": msg.photo[-1].file_id, "caption": caption}
    elif msg.video:
        f = {"type": "video", "file_id": msg.video.file_id, "caption": caption}
    elif getattr(msg, "video_note", None):
        f = {"type": "video_note", "file_id": msg.video_note.file_id, "caption": caption}
    elif msg.document:
        f = {"type": "document", "file_id": msg.document.file_id, "caption": caption}
    elif msg.animation:
        f = {"type": "animation", "file_id": msg.animation.file_id, "caption": caption}
    elif msg.text:
        f = None

    if f:
        context.user_data.setdefault("upload_files", []).append(f)
        await msg.reply_text("✅ Saved. Send more or press ✅ to finish.")


# ---------------- BROADCAST FLOW (ADMIN) ----------------
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    # If admin used /broadcast <text> directly, capture immediately
    args = context.args
    if args:
        text = " ".join(args)
        context.user_data["broadcast_pending"] = {"type": "text", "text": text}
        await _send_broadcast_preview(update, context)
        return

    # Ask admin to send the message or reply to a media
    context.user_data["awaiting_broadcast"] = True
    await safe_reply(update, "Send the message to broadcast (or reply to a photo/video/document with /broadcast).")


async def _capture_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    if not is_admin(user.id):
        context.user_data.pop("awaiting_broadcast", None)
        await safe_reply(update, "Only admins can broadcast.")
        return

    # detect type
    if msg.photo:
        payload = {"type": "photo", "file_id": msg.photo[-1].file_id, "caption": msg.caption or ""}
    elif msg.video:
        payload = {"type": "video", "file_id": msg.video.file_id, "caption": msg.caption or ""}
    elif getattr(msg, "video_note", None):
        payload = {"type": "video_note", "file_id": msg.video_note.file_id, "caption": msg.caption or ""}
    elif msg.document:
        payload = {"type": "document", "file_id": msg.document.file_id, "caption": msg.caption or ""}
    elif msg.animation:
        payload = {"type": "animation", "file_id": msg.animation.file_id, "caption": msg.caption or ""}
    elif msg.text:
        payload = {"type": "text", "text": msg.text}
    else:
        await safe_reply(update, "Unsupported content. Send text, photo, video, document, animation or round video.")
        return

    context.user_data.pop("awaiting_broadcast", None)
    context.user_data["broadcast_pending"] = payload
    await _send_broadcast_preview(update, context)


async def _send_broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = context.user_data.get("broadcast_pending")
    if not payload:
        await safe_reply(update, "No broadcast content found.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"bc_confirm:{update.effective_user.id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"bc_cancel:{update.effective_user.id}")]
    ])

    try:
        if payload["type"] == "text":
            preview = await safe_reply(update, f"📢 Broadcast Preview:\n\n{payload['text']}", reply_markup=keyboard)
        elif payload["type"] == "photo":
            if update.message:
                preview = await update.message.reply_photo(payload["file_id"], caption=payload.get("caption", ""), reply_markup=keyboard)
            else:
                preview = await safe_reply(update, "📢 Broadcast Preview: (Photo)", reply_markup=keyboard)
        elif payload["type"] == "video":
            if update.message:
                preview = await update.message.reply_video(payload["file_id"], caption=payload.get("caption", ""), reply_markup=keyboard)
            else:
                preview = await safe_reply(update, "📢 Broadcast Preview: (Video)", reply_markup=keyboard)
        elif payload["type"] == "video_note":
            preview = await safe_reply(update, "📢 Broadcast Preview: (round video)\n\n(You'll send a video_note to users)", reply_markup=keyboard)
        elif payload["type"] == "document":
            if update.message:
                preview = await update.message.reply_document(payload["file_id"], caption=payload.get("caption", ""), reply_markup=keyboard)
            else:
                preview = await safe_reply(update, "📢 Broadcast Preview: (Document)", reply_markup=keyboard)
        elif payload["type"] == "animation":
            if update.message:
                preview = await update.message.reply_animation(payload["file_id"], caption=payload.get("caption", ""), reply_markup=keyboard)
            else:
                preview = await safe_reply(update, "📢 Broadcast Preview: (Animation)", reply_markup=keyboard)
        else:
            await safe_reply(update, "Unsupported broadcast type.")
            return
    except Exception as e:
        logger.error(f"Preview send failed: {e}")
        await safe_reply(update, "Failed to send preview.")
        return

    # store preview message id & chat so we can edit it during broadcast
    if preview:
        context.user_data["broadcast_preview_message"] = {"chat_id": preview.chat.id, "message_id": preview.message_id}

# ---------------- ADMIN PANEL ----------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel with buttons"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can access this panel.")
        return
    
    keyboard = InlineKeyboardMarkup([
        # Row 1: User Management
        [
            InlineKeyboardButton("👤 Grant Premium", callback_data="admin_grant_perm"),
            InlineKeyboardButton("⏰ Grant Temp Access", callback_data="admin_grant_temp")
        ],
        # Row 2: Access Management
        [
            InlineKeyboardButton("❌ Remove Premium", callback_data="admin_remove_perm"),
            InlineKeyboardButton("🗑️ Remove Temp Access", callback_data="admin_remove_temp")
        ],
        # Row 3: User Controls
        [
            InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
            InlineKeyboardButton("✅ Unban User", callback_data="admin_unban")
        ],
        # Row 4: Channel Management
        [
            InlineKeyboardButton("📢 Add Channel", callback_data="admin_add_channel"),
            InlineKeyboardButton("🗑️ Remove Channel", callback_data="admin_remove_channel")
        ],
        # Row 5: Lists & Stats
        [
            InlineKeyboardButton("📋 List Channels", callback_data="admin_list_channels"),
            InlineKeyboardButton("📊 List Access", callback_data="admin_list_access")
        ],
        # Row 6: Broadcast & Stats
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton("📈 Stats", callback_data="admin_stats")
        ],
        # Row 7: Media & Renew
        [
            InlineKeyboardButton("🗑️ Delete Media", callback_data="admin_delete_media"),
            InlineKeyboardButton("🔄 Renew Access", callback_data="admin_renew_access")
        ],
        # Row 8: New Custom Photo Feature
        [
            InlineKeyboardButton("🖼️ Set Custom Photo", callback_data="admin_set_photo")
        ]
    ])
    
    await safe_reply(update,
        "🛠️ **Admin Control Panel**\n\nSelect an option below:",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

# ---------------- ADMIN CALLBACK HANDLERS ----------------
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin panel callbacks"""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this panel.")
        return
    
    if data == "admin_grant_perm":
        context.user_data["awaiting_action"] = "grant_perm"
        await safe_reply(update,
            "👤 **Grant Permanent Premium**\n\n"
            "Send user ID to grant permanent premium access:\n"
            "Example: `123456789`",
            parse_mode='Markdown'
        )
    
    elif data == "admin_grant_temp":
        context.user_data["awaiting_action"] = "grant_temp"
        await safe_reply(update,
            "⏰ **Grant Temporary Access**\n\n"
            "Send user ID and days (space separated):\n"
            "Example: `123456789 30`",
            parse_mode='Markdown'
        )
    
    elif data == "admin_remove_perm":
        context.user_data["awaiting_action"] = "remove_perm"
        await safe_reply(update,
            "❌ **Remove Permanent Premium**\n\n"
            "Send user ID to remove permanent premium:\n"
            "Example: `123456789`",
            parse_mode='Markdown'
        )
    
    elif data == "admin_remove_temp":
        context.user_data["awaiting_action"] = "remove_temp"
        await safe_reply(update,
            "🗑️ **Remove Temporary Access**\n\n"
            "Send user ID to remove temporary access:\n"
            "Example: `123456789`",
            parse_mode='Markdown'
        )
    
    elif data == "admin_ban":
        context.user_data["awaiting_action"] = "ban"
        await safe_reply(update,
            "🚫 **Ban User**\n\n"
            "Send user ID to ban:\n"
            "Example: `123456789`",
            parse_mode='Markdown'
        )
    
    elif data == "admin_unban":
        context.user_data["awaiting_action"] = "unban"
        await safe_reply(update,
            "✅ **Unban User**\n\n"
            "Send user ID to unban:\n"
            "Example: `123456789`",
            parse_mode='Markdown'
        )
    
    elif data == "admin_add_channel":
        # Show channel type options
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔒 Private Channel", callback_data="admin_add_private")],
            [InlineKeyboardButton("🌐 Public Channel", callback_data="admin_add_public")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
        try:
            await query.message.edit_text(
                "📢 **Add Channel**\n\nSelect channel type:",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        except:
            await safe_reply(update, "📢 **Add Channel**\n\nSelect channel type:", reply_markup=keyboard, parse_mode='Markdown')
    
    elif data == "admin_add_private":
        context.user_data["awaiting_action"] = "add_private"
        await safe_reply(update,
            "🔒 **Add Private Channel**\n\n"
            "Send channel ID and invite link (space separated):\n"
            "Example: `-1001234567890 https://t.me/+abc123`",
            parse_mode='Markdown'
        )
    
    elif data == "admin_add_public":
        context.user_data["awaiting_action"] = "add_public"
        await safe_reply(update,
            "🌐 **Add Public Channel**\n\n"
            "Send channel username:\n"
            "Example: `@channelname`",
            parse_mode='Markdown'
        )
    
    elif data == "admin_remove_channel":
        context.user_data["awaiting_action"] = "remove_channel"
        await safe_reply(update,
            "🗑️ **Remove Channel**\n\n"
            "Send channel ID or username to remove:\n"
            "Examples:\n"
            "`-1001234567890` (private)\n"
            "`@channelname` (public)",
            parse_mode='Markdown'
        )
    
    elif data == "admin_list_channels":
        await cmd_listforcejoin(update, context)
        await admin_panel(update, context)
    
    elif data == "admin_list_access":
        await cmd_listaccess(update, context)
        await admin_panel(update, context)
    
    elif data == "admin_broadcast":
        await broadcast_command(update, context)
    
    elif data == "admin_stats":
        await show_stats(update, context)  # FIXED: Changed from cmd_stats to show_stats
    
    elif data == "admin_delete_media":
        context.user_data["awaiting_action"] = "delete_media"
        await safe_reply(update,
            "🗑️ **Delete Media**\n\n"
            "Send media ID to delete:\n"
            "Example: `AbC123De`",
            parse_mode='Markdown'
        )
    
    elif data == "admin_renew_access":
        context.user_data["awaiting_action"] = "renew_access"
        await safe_reply(update,
            "🔄 **Renew Access**\n\n"
            "Send user ID and days to renew (space separated):\n"
            "Example: `123456789 30`",
            parse_mode='Markdown'
        )
    
    elif data == "admin_set_photo":
        context.user_data["awaiting_custom_photo"] = True
        await safe_reply(update,
            "🖼️ **Set Custom Photo**\n\n"
            "Send a photo that will be shown before all media when users click on links.\n"
            "This photo will be used for all future uploads until changed.",
            parse_mode='Markdown'
        )
    
    elif data == "admin_back":
        await admin_panel(update, context)

# ---------------- ADMIN MESSAGE HANDLER ----------------
async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin action responses"""
    user = update.effective_user
    if not user or not is_admin(user.id):
        return
    
    msg = update.message
    if not msg or not msg.text:
        return
    
    action = context.user_data.get("awaiting_action")
    
    if not action:
        return
    
    text = msg.text.strip()
    
    try:
        if action == "grant_perm":
            user_id = int(text)
            set_premium(user_id, True)
            await safe_reply(update, f"✅ Permanent premium granted to user {user_id}")
            
        elif action == "grant_temp":
            parts = text.split()
            if len(parts) != 2:
                await safe_reply(update, "❌ Format: user_id days\nExample: 123456789 30")
                return
            user_id = int(parts[0])
            days = int(parts[1])
            grant_access(user_id, days)
            expiry_date = datetime.now() + timedelta(days=days)
            await safe_reply(update,
                f"✅ Temporary access granted!\n"
                f"User: {user_id}\n"
                f"Days: {days}\n"
                f"Expires: {expiry_date.strftime('%Y-%m-%d')}"
            )
            
        elif action == "remove_perm":
            user_id = int(text)
            set_premium(user_id, False)
            await safe_reply(update, f"❌ Permanent premium removed from user {user_id}")
            
        elif action == "remove_temp":
            user_id = int(text)
            revoke_access(user_id)
            await safe_reply(update, f"🗑️ Temporary access removed from user {user_id}")
            
        elif action == "ban":
            user_id = int(text)
            ban_user(user_id)
            await safe_reply(update, f"🚫 User {user_id} banned")
            
        elif action == "unban":
            user_id = int(text)
            unban_user(user_id)
            await safe_reply(update, f"✅ User {user_id} unbanned")
            
        elif action == "add_private":
            parts = text.split()
            if len(parts) != 2:
                await safe_reply(update, "❌ Format: channel_id invite_link\nExample: -1001234567890 https://t.me/+abc123")
                return
            channel_id = parts[0]
            invite_link = parts[1]
            
            if not channel_id.startswith("-100"):
                await safe_reply(update, "❌ Channel ID must start with -100")
                return
            
            save_channel_invite_link(channel_id, invite_link)
            updated_channels = add_private_force_join(channel_id)
            await safe_reply(update,
                f"✅ Private channel added!\n"
                f"ID: {channel_id}\n"
                f"Link: {invite_link}\n"
                f"Total: {len(updated_channels)} channels"
            )
            
        elif action == "add_public":
            channel_username = text if text.startswith("@") else f"@{text}"
            updated_channels = add_public_force_join(channel_username)
            await safe_reply(update,
                f"✅ Public channel added!\n"
                f"Channel: {channel_username}\n"
                f"Total: {len(updated_channels)} channels"
            )
            
        elif action == "remove_channel":
            channel = text
            if channel.startswith("-100"):
                updated_channels = remove_private_force_join(channel)
            else:
                if not channel.startswith("@"):
                    channel = "@" + channel
                updated_channels = remove_public_force_join(channel)
            await safe_reply(update,
                f"✅ Channel removed!\n"
                f"Channel: {channel}\n"
                f"Total: {len(updated_channels)} channels"
            )
            
        elif action == "delete_media":
            media_id = text
            result = media_collection.delete_one({"media_id": media_id})
            if result.deleted_count:
                await safe_reply(update, f"✅ Media {media_id} deleted")
            else:
                await safe_reply(update, f"❌ Media {media_id} not found")
                
        elif action == "renew_access":
            parts = text.split()
            if len(parts) != 2:
                await safe_reply(update, "❌ Format: user_id days\nExample: 123456789 30")
                return
            user_id = int(parts[0])
            days = int(parts[1])
            
            # Get current expiry
            current_doc = access_collection.find_one({"user_id": user_id, "active": True})
            if current_doc:
                current_expiry = current_doc.get("expiry_date", datetime.now())
                new_expiry = current_expiry + timedelta(days=days)
                action_text = "renewed"
            else:
                new_expiry = datetime.now() + timedelta(days=days)
                action_text = "granted"
            
            # Update access
            access_collection.update_one(
                {"user_id": user_id},
                {"$set": {
                    "expiry_date": new_expiry,
                    "active": True,
                    "warning_sent": False,
                    "kicked": False
                }},
                upsert=True
            )
            
            await safe_reply(update,
                f"✅ Access {action_text}!\n"
                f"User: {user_id}\n"
                f"Added days: {days}\n"
                f"New expiry: {new_expiry.strftime('%Y-%m-%d')}"
            )
    
    except ValueError:
        await safe_reply(update, "❌ Invalid input. Please check the format.")
    except Exception as e:
        logger.error(f"Admin action error: {e}")
        await safe_reply(update, f"❌ Error: {str(e)}")
    
    # Clear action and show admin panel again
    context.user_data.pop("awaiting_action", None)
    await admin_panel(update, context)

# ---------------- RENEW COMMAND ----------------
async def cmd_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Renew user's temporary access"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    if len(context.args) != 2:
        await safe_reply(update, "Usage: /renew <user_id> <days>\nExample: /renew 123456789 30")
        return
    
    try:
        user_id = int(context.args[0])
        days = int(context.args[1])
        
        # Get current expiry
        current_doc = access_collection.find_one({"user_id": user_id, "active": True})
        if current_doc:
            current_expiry = current_doc.get("expiry_date", datetime.now())
            new_expiry = current_expiry + timedelta(days=days)
            action = "renewed"
        else:
            new_expiry = datetime.now() + timedelta(days=days)
            action = "granted"
        
        # Update access
        access_collection.update_one(
            {"user_id": user_id},
            {"$set": {
                "expiry_date": new_expiry,
                "active": True,
                "warning_sent": False,
                "kicked": False,
                "granted_date": datetime.now(),
                "days": days
            }},
            upsert=True
        )
        
        # Ensure premium status
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"premium": True, "premium_type": "temporary"}},
            upsert=True
        )
        
        await safe_reply(update,
            f"✅ Access {action}!\n"
            f"User: {user_id}\n"
            f"Days: {days}\n"
            f"Expiry: {new_expiry.strftime('%Y-%m-%d %H:%M')}"
        )
        
        # Notify user
        try:
            await context.bot.send_message(
                user_id,
                f"🔄 **Access Renewed!**\n\n"
                f"Your premium access has been renewed for {days} more days.\n"
                f"New expiry: {new_expiry.strftime('%Y-%m-%d')}\n\n"
                f"Thank you for using our service!"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")
            
    except ValueError:
        await safe_reply(update, "❌ Invalid input. Please provide valid user ID and days.")

# ---------------- MISSING FUNCTIONS ADDED ----------------
async def cmd_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Grant temporary access to user"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    if len(context.args) < 2:
        await safe_reply(update, "Usage: /access <user_id> <days>\nExample: /access 123456789 30")
        return
    
    try:
        user_id = int(context.args[0])
        days = int(context.args[1])
        
        if days <= 0:
            await safe_reply(update, "Days must be greater than 0.")
            return
        
        grant_access(user_id, days)
        expiry_date = datetime.now() + timedelta(days=days)
        
        await safe_reply(update,
            f"✅ Access granted successfully!\n"
            f"User ID: {user_id}\n"
            f"Days: {days}\n"
            f"Expiry Date: {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"User will receive notification 3 days before expiry."
        )
        
        # Notify user
        try:
            await context.bot.send_message(
                user_id,
                f"🎉 Premium Access Granted!\n"
                f"Your premium access has been activated for {days} days.\n"
                f"Expiry Date: {expiry_date.strftime('%Y-%m-%d')}\n\n"
                f"You can now upload media and use all premium features."
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")
            
    except ValueError:
        await safe_reply(update, "Invalid input. Please provide valid user ID and days.")

async def cmd_removeaccess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove user's temporary access"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    if not context.args:
        await safe_reply(update, "Usage: /removeaccess <user_id>\nExample: /removeaccess 123456789")
        return
    
    try:
        user_id = int(context.args[0])
        revoke_access(user_id)
        
        await safe_reply(update,
            f"✅ Access revoked successfully!\n"
            f"User ID: {user_id}\n"
            f"Premium features have been disabled for this user."
        )
        
        # Notify user
        try:
            await context.bot.send_message(
                user_id,
                f"⚠️ Premium Access Revoked\n"
                f"Your premium access has been revoked.\n"
                f"You can no longer upload media.\n\n"
                f"Contact admin for more information."
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")
            
    except ValueError:
        await safe_reply(update, "Invalid user ID. Please provide a valid numeric user ID.")

async def cmd_listforcejoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all force join channels"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    channels = get_force_join_channels()
    if not channels:
        await safe_reply(update, "No force join channels configured.")
        return
    
    message = "📋 Force Join Channels List:\n\n"
    for i, channel in enumerate(channels, 1):
        if channel.startswith("-100"):
            invite_link = get_channel_invite_link(channel)
            if invite_link:
                message += f"{i}. {channel} [✅ Invite Link]\n"
            else:
                message += f"{i}. {channel} [❌ No Invite Link]\n"
        else:
            message += f"{i}. {channel}\n"
    
    message += f"\nTotal: {len(channels)} channels\n"
    message += "✅ = Has invite link\n❌ = No invite link (users can't join)"
    await safe_reply(update, message)

async def cmd_listaccess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all users with temporary access"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    active_users = list(access_collection.find({"active": True}))
    if not active_users:
        await safe_reply(update, "No users with active temporary access.")
        return
    
    message = "📋 Users with Temporary Access:\n\n"
    for user in active_users:
        expiry_date = user.get("expiry_date")
        days_left = (expiry_date - datetime.now()).days if expiry_date else "N/A"
        granted_date = user.get("granted_date", "N/A")
        if isinstance(granted_date, datetime):
            granted_date = granted_date.strftime("%Y-%m-%d")
        
        message += f"👤 User ID: {user['user_id']}\n"
        message += f"   Days: {user.get('days', 'N/A')}\n"
        message += f"   Granted: {granted_date}\n"
        message += f"   Expires: {expiry_date.strftime('%Y-%m-%d') if expiry_date else 'N/A'}\n"
        message += f"   Days Left: {days_left}\n"
        message += f"   {'⚠️ Expiring Soon' if days_left <= 3 and days_left > 0 else ''}\n"
        message += "   ───────────────\n"
    
    message += f"\nTotal: {len(active_users)} active users"
    await safe_reply(update, message)

# ---------------- FIXED STATS FUNCTION ----------------
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot stats with deleted users info"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    total = users_collection.count_documents({})
    active = users_collection.count_documents({"active": True})
    banned = users_collection.count_documents({"banned": True})
    premium = users_collection.count_documents({"premium": True})
    temp_access = access_collection.count_documents({"active": True})
    force_join_count = len(get_force_join_channels())
    deleted_users_count = get_deleted_users_count()
    total_deletions = get_total_deletions()
    media_count = media_collection.count_documents({})
    
    # Get custom photo status
    custom_photo_status = "❌ Not Set"
    if context.user_data.get("custom_photo"):
        custom_photo_status = "✅ Set"
    
    await safe_reply(update,
        f"📊 **Bot Statistics**\n\n"
        f"👥 **Users:**\n"
        f"• Total Users: {total}\n"
        f"• Active Users: {active}\n"
        f"• Banned Users: {banned}\n"
        f"• Premium Users: {premium}\n"
        f"• Temp Access Users: {temp_access}\n"
        f"• Deleted Users: {deleted_users_count}\n\n"
        f"📈 **Activity:**\n"
        f"• Total Downloads: {total_deletions}\n"
        f"• Total Media Files: {media_count}\n\n"
        f"📢 **Channels:**\n"
        f"• Force Join Channels: {force_join_count}\n\n"
        f"🔄 **Custom Features:**\n"
        f"• Custom Photo: {custom_photo_status}"
    )

# ---------------- FIXED: cmd_stats function ----------------
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /stats"""
    await show_stats(update, context)

async def cmd_addprivatefj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add private channel with invite link to force join list"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    if len(context.args) < 2:
        await safe_reply(update,
            "Usage: /addprivatefj <channel_id> <invite_link>\n"
            "Example: /addprivatefj -1001234567890 https://t.me/+abc123def456\n\n"
            "Note: Channel ID must start with -100"
        )
        return
    
    channel_id = context.args[0]
    invite_link = context.args[1]
    
    # Validate channel ID format
    if not channel_id.startswith("-100"):
        await safe_reply(update,
            "❌ Invalid private channel ID format.\n"
            "Private channel ID must start with -100 (e.g., -1001234567890)"
        )
        return
    
    try:
        # Save invite link
        save_channel_invite_link(channel_id, invite_link)
        
        # Add to force join list
        updated_channels = add_private_force_join(channel_id)
        
        await safe_reply(update,
            f"✅ Private channel added successfully!\n"
            f"Channel ID: {channel_id}\n"
            f"Invite Link: {invite_link}\n"
            f"Total force join channels: {len(updated_channels)}"
        )
    except Exception as e:
        logger.error(f"Error adding private channel: {e}")
        await safe_reply(update, f"❌ Error: {str(e)}")

async def cmd_addpvtforcejoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add private channel to force join list (without invite link)"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    if not context.args:
        await safe_reply(update, "Usage: /addpvtforcejoin <channel_id>\nExample: /addpvtforcejoin -1001234567890")
        return
    
    channel_id = context.args[0]
    
    # Validate channel ID format
    if not channel_id.startswith("-100"):
        await safe_reply(update,
            "❌ Invalid private channel ID format.\n"
            "Private channel ID must start with -100 (e.g., -1001234567890)"
        )
        return
    
    updated_channels = add_private_force_join(channel_id)
    
    await safe_reply(update,
        f"✅ Private channel added to force join list.\n"
        f"Channel ID: {channel_id}\n"
        f"Total channels: {len(updated_channels)}\n"
        f"Note: Add invite link using /addprivatefj {channel_id} <invite_link>"
    )

async def cmd_removepvtforcejoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove private channel from force join list"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    if not context.args:
        await safe_reply(update, "Usage: /removepvtforcejoin <channel_id>\nExample: /removepvtforcejoin -1001234567890")
        return
    
    channel_id = context.args[0]
    updated_channels = remove_private_force_join(channel_id)
    
    await safe_reply(update,
        f"✅ Private channel removed from force join list.\n"
        f"Channel ID: {channel_id}\n"
        f"Total channels: {len(updated_channels)}"
    )

async def cmd_addpubfj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add public channel to force join list"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    if not context.args:
        await safe_reply(update, "Usage: /addpubfj <channel_username>\nExample: /addpubfj @schoolxResources")
        return
    
    channel_username = context.args[0]
    if not channel_username.startswith("@"):
        channel_username = "@" + channel_username
    updated_channels = add_public_force_join(channel_username)
    
    await safe_reply(update,
        f"✅ Public channel added to force join list.\n"
        f"Channel: {channel_username}\n"
        f"Total channels: {len(updated_channels)}"
    )

async def cmd_removepubfj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove public channel from force join list"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    if not context.args:
        await safe_reply(update, "Usage: /removepubfj <channel_username>\nExample: /removepubfj @schoolxResources")
        return
    
    channel_username = context.args[0]
    if not channel_username.startswith("@"):
        channel_username = "@" + channel_username
    updated_channels = remove_public_force_join(channel_username)
    
    await safe_reply(update,
        f"✅ Public channel removed from force join list.\n"
        f"Channel: {channel_username}\n"
        f"Total channels: {len(updated_channels)}"
    )

async def cmd_setinvite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set invite link for existing private channel"""
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can use this command.")
        return
    
    if len(context.args) < 2:
        await safe_reply(update,
            "Usage: /setinvite <channel_id> <invite_link>\n"
            "Example: /setinvite -1001234567890 https://t.me/+abc123def456"
        )
        return
    
    channel_id = context.args[0]
    invite_link = context.args[1]
    
    if not channel_id.startswith("-100"):
        await safe_reply(update, "❌ Channel ID must start with -100")
        return
    
    # Check if channel exists in force join list
    channels = get_force_join_channels()
    if channel_id not in channels:
        await safe_reply(update,
            f"❌ Channel {channel_id} not in force join list.\n"
            f"Add it first using /addpvtforcejoin {channel_id}"
        )
        return
    
    save_channel_invite_link(channel_id, invite_link)
    await safe_reply(update,
        f"✅ Invite link set for channel {channel_id}\n"
        f"Link: {invite_link}"
    )

# ---------------- UPDATED CALLBACK QUERY ROUTER ----------------
async def callback_query_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    # Handle no invite link for private channel
    if data.startswith("no_invite:"):
        channel_id = data.split(":", 1)[1]
        await safe_reply(update,
            f"❌ No invite link available for private channel: {channel_id}\n"
            f"Please contact the admin to get an invite link."
        )
        return

    # Admin panel callbacks
    if data.startswith("admin_"):
        await admin_callback_handler(update, context)
        return

    # confirm join flow
    if data.startswith("confirm_join:"):
        media_id = data.split(":", 1)[1] if ":" in data else ""
        user = update.effective_user
        ok, missing = await check_force_join_for_user(context.bot, user.id)
        if ok:
            # remove join prompt (if possible)
            try:
                await query.message.delete()
            except Exception:
                pass
            if media_id:
                # send the requested media
                await _send_media_for_media_id(update, context, media_id)
                return
            else:
                # Only show upload option for admin
                if is_admin(user.id):
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Start Uploading", callback_data="upload")]])
                    try:
                        await safe_reply(update,
                            "<b>Welcome! You joined successfully.</b>\nYou can now use the bot features.",
                            reply_markup=kb,
                            parse_mode='HTML'
                        )
                    except Exception:
                        try:
                            await context.bot.send_message(update.effective_chat.id, "Welcome! You joined successfully.", reply_markup=kb)
                        except Exception:
                            pass
                else:
                    try:
                        await safe_reply(update,
                            "<b>Welcome! You joined successfully.</b>\nUse the shared links to download media.",
                            parse_mode='HTML'
                        )
                    except Exception:
                        pass
                return
        else:
            buttons = []
            for ch in missing:
                if ch.startswith("-100"):
                    invite_link = get_channel_invite_link(ch)
                    if invite_link:
                        buttons.append([InlineKeyboardButton(f"Join Private Channel", url=invite_link)])
                    else:
                        buttons.append([InlineKeyboardButton(f"Private Channel - Contact Admin", callback_data=f"no_invite:{ch}")])
                else:
                    channel_username = ch if ch.startswith("@") else f"@{ch}"
                    buttons.append([InlineKeyboardButton(f"Join {channel_username}", url=f"https://t.me/{channel_username.lstrip('@')}")])
            
            buttons.append([InlineKeyboardButton("✅ I Joined", callback_data=f"confirm_join:{media_id or ''}")])
            try:
                await query.message.edit_text("It looks like you still haven't joined all required channels. Please join and then click 'I Joined'.",
                                              reply_markup=InlineKeyboardMarkup(buttons))
            except Exception:
                await safe_reply(update,
                    "It looks like you still haven't joined all required channels. Please join and then click 'I Joined'.",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            return

    # upload button pressed
    if data == "upload":
        # call upload flow using update (it will detect callback_query.message)
        await upload(update, context)
        return

    # broadcast confirm/cancel
    if data.startswith("bc_confirm:") or data.startswith("bc_cancel:"):
        admin_id = int(data.split(":", 1)[1])
        if update.effective_user.id != admin_id:
            await safe_reply(update, "Only the admin who started this broadcast can confirm/cancel it.")
            return

        if data.startswith("bc_cancel:"):
            context.user_data.pop("broadcast_pending", None)
            context.user_data.pop("broadcast_preview_message", None)
            try:
                await query.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await safe_reply(update, "❌ Broadcast cancelled.")
            return

        # start broadcasting
        payload = context.user_data.get("broadcast_pending")
        preview_msg_info = context.user_data.get("broadcast_preview_message")
        if not payload or not preview_msg_info:
            await safe_reply(update, "No broadcast found or preview lost.")
            return

        try:
            await context.bot.edit_message_reply_markup(preview_msg_info["chat_id"], preview_msg_info["message_id"], reply_markup=None)
        except Exception:
            pass

        progress_text = "📡 Broadcasting...\nSent: 0 / 0\n(working...)"
        try:
            progress_msg = await context.bot.send_message(preview_msg_info["chat_id"], progress_text)
        except Exception:
            progress_msg = None

        asyncio.create_task(_run_broadcast_task(context.bot, payload, progress_msg))
        context.user_data.pop("broadcast_pending", None)
        context.user_data.pop("broadcast_preview_message", None)
        await safe_reply(update, "✅ Broadcast started. Progress will be updated shortly.")
        return


async def _run_broadcast_task(bot, payload: Dict[str, Any], progress_msg: Optional[Message]):
    users = [u["user_id"] for u in users_collection.find({"banned": {"$ne": True}})]
    total = len(users)
    sent = 0
    failed = 0

    def _progress_text(done, total, s, f):
        return f"📡 Broadcasting...\nSent: {done} / {total}\nSuccess: {s} | Failed: {f}"

    async def _update_progress(done, total, s, f):
        txt = _progress_text(done, total, s, f)
        if progress_msg:
            try:
                await bot.edit_message_text(txt, progress_msg.chat.id, progress_msg.message_id)
            except Exception:
                pass

    for idx, uid in enumerate(users, start=1):
        try:
            if payload["type"] == "text":
                await bot.send_message(uid, payload["text"])
            elif payload["type"] == "photo":
                await bot.send_photo(uid, payload["file_id"], caption=payload.get("caption", ""))
            elif payload["type"] == "video":
                await bot.send_video(uid, payload["file_id"], caption=payload.get("caption", ""))
            elif payload["type"] == "video_note":
                await bot.send_video_note(uid, payload["file_id"])
            elif payload["type"] == "document":
                await bot.send_document(uid, payload["file_id"], caption=payload.get("caption", ""))
            elif payload["type"] == "animation":
                await bot.send_animation(uid, payload["file_id"], caption=payload.get("caption", ""))
            else:
                await bot.send_message(uid, "Message from admin")
            sent += 1
        except Exception as e:
            failed += 1
            logger.debug(f"Broadcast send failed to {uid}: {e}")

        if idx % 5 == 0 or idx == total:
            await _update_progress(idx, total, sent, failed)

        await asyncio.sleep(0.05)

    final = f"✅ Broadcast completed.\nTotal: {total}\nSuccess: {sent} | Failed: {failed}"
    if progress_msg:
        try:
            await bot.edit_message_text(final, progress_msg.chat.id, progress_msg.message_id)
        except Exception:
            pass


# ---------------- ORIGINAL ADMIN COMMANDS (for backward compatibility) ----------------
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await admin_panel(update, context)

async def make_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await safe_reply(update, "Usage: /premium <id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await safe_reply(update, "Invalid user id.")
        return
    set_premium(uid, True)
    await safe_reply(update, f"✅ Permanent premium granted for {uid}")

async def remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await safe_reply(update, "Usage: /unpremium <id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await safe_reply(update, "Invalid user id.")
        return
    set_premium(uid, False)
    await safe_reply(update, f"❌ Permanent premium removed for {uid}")

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await safe_reply(update, "Usage: /ban <id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await safe_reply(update, "Invalid user id.")
        return
    ban_user(uid)
    await safe_reply(update, f"🚫 User {uid} banned successfully.")

async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await safe_reply(update, "Usage: /unban <id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await safe_reply(update, "Invalid user id.")
        return
    unban_user(uid)
    await safe_reply(update, f"✅ User {uid} unbanned successfully.")

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await safe_reply(update, "🚫 Only admins can delete media.")
        return
    if not context.args:
        await safe_reply(update, "Usage: /del <media_id>")
        return
    media_id = context.args[0]
    result = media_collection.delete_one({"media_id": media_id})
    if result.deleted_count:
        await safe_reply(update, f"✅ Media {media_id} deleted permanently.")
    else:
        await safe_reply(update, f"❌ Media {media_id} not found.")

# ---------------- TEXT HANDLER FOR ✅ BUTTON ----------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages including ✅ button"""
    msg = update.message
    if not msg:
        return
    user = update.effective_user
    ensure_user_record(user.id, user.username)

    # If this user is currently composing a broadcast (admin), handle separately
    if context.user_data.get("awaiting_broadcast"):
        return await _capture_broadcast_content(update, context)

    # If admin is responding to admin panel action
    if is_admin(user.id) and context.user_data.get("awaiting_action"):
        return await admin_message_handler(update, context)

    # If admin wants to set custom photo
    if is_admin(user.id) and context.user_data.get("awaiting_custom_photo"):
        return await handle_media(update, context)

    if is_banned(user.id):
        await msg.reply_text("🚫 You are banned from using this bot.")
        return

    ok, _ = await check_force_join_for_user(context.bot, user.id)
    if not ok:
        # ask them to join
        await start(update, context)
        return

    # finish upload on ✅
    if msg.text and msg.text.strip() == "✅":
        files = context.user_data.get("upload_files", [])
        if not files:
            await msg.reply_text("❌ No media.", reply_markup=ReplyKeyboardRemove())
            
            # Still show upload option
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Upload Again", callback_data="upload")]])
            await msg.reply_text("Want to upload files?", reply_markup=kb)
            return
        
        media_id = context.user_data.get("media_id")
        if not media_id:
            await msg.reply_text("❌ Session expired. Start upload again.")
            context.user_data.pop("upload_files", None)
            
            # Show upload option
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Start Uploading", callback_data="upload")]])
            await msg.reply_text("Want to upload files?", reply_markup=kb)
            return
        
        custom_photo = context.user_data.get("custom_photo")
        save_data(media_id, files, custom_photo)
        share_link = f"https://t.me/{(await context.bot.get_me()).username}?start={media_id}"
        
        # Send success message with upload again option
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Share Link", url=share_link)],
            [InlineKeyboardButton("📤 Upload More", callback_data="upload")]
        ])
        
        await msg.reply_text(
            f"✅ Uploaded Successfully!\n\n"
            f"🔗 **Download Link:**\n`{share_link}`\n\n"
            f"⚠️ **Note:** Files will be deleted in 10 minutes. Forward them to Saved Messages for future access.\n\n"
            f"Want to upload more files?",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )

        # Forward to private channel with details
        try:
            uname = f"@{user.username}" if user.username else "NoUsername"
            p_text = f"📦 New Upload Received\n👤 User: {uname} ({user.id})\n🔗 Link: {share_link}"
            await context.bot.send_message(PRIVATE_CHANNEL_ID, p_text)
            
            # Send custom photo if available
            if custom_photo:
                await context.bot.send_photo(PRIVATE_CHANNEL_ID, custom_photo, caption="📸 Custom Photo for this upload")
                
            for f in files:
                t = f["type"]
                if t == "photo":
                    await context.bot.send_photo(PRIVATE_CHANNEL_ID, f["file_id"], caption=f.get("caption", ""))
                elif t == "video":
                    await context.bot.send_video(PRIVATE_CHANNEL_ID, f["file_id"], caption=f.get("caption", ""))
                elif t == "document":
                    await context.bot.send_document(PRIVATE_CHANNEL_ID, f["file_id"])
                elif t == "animation":
                    await context.bot.send_animation(PRIVATE_CHANNEL_ID, f["file_id"])
                elif t == "video_note":
                    await context.bot.send_video_note(PRIVATE_CHANNEL_ID, f["file_id"])
        except Exception as e:
            logger.error(f"Forward to private channel failed: {e}")

        context.user_data.clear()
        return
    
    # For other text messages (not ✅), show help or start message
    else:
        await start(update, context)

# ---------------- FALLBACKS & ERROR HANDLER ----------------
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_reply(update, "Unknown command or action.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Unhandled error: {context.error}", exc_info=True)
    
    try:
        # Try to send error message
        if isinstance(update, Update):
            if update.effective_message:
                await update.effective_message.reply_text("⚠️ An unexpected error occurred. Please try again later.")
            elif update.message:
                await update.message.reply_text("⚠️ An unexpected error occurred. Please try again later.")
            elif update.callback_query and update.callback_query.message:
                await update.callback_query.message.reply_text("⚠️ An unexpected error occurred. Please try again later.")
    except Exception as e:
        logger.error(f"Failed to send error message: {e}")

# ---------------- BACKGROUND TASK SETUP ----------------
async def setup_background_tasks(app):
    """Setup background tasks for the bot"""
    # Create job queue for checking expiring access (every 6 hours)
    app.job_queue.run_repeating(
        check_expiring_access,
        interval=21600,  # Check every 6 hours
        first=10
    )
    
    # Create job queue for checking expired access (every 12 hours)
    app.job_queue.run_repeating(
        check_expired_access,
        interval=43200,  # Check every 12 hours
        first=30
    )
    
    logger.info("Background tasks setup complete")

# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Setup background tasks
    app.post_init = setup_background_tasks

    # Core handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(callback_query_router))
    
    # Media handler - should be before admin message handler
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.ANIMATION | filters.VIDEO_NOTE,
        handle_media
    ))
    
    # Text handler for ✅ button and admin responses
    app.add_handler(MessageHandler(
        filters.TEXT & (~filters.COMMAND),
        handle_text
    ))

    # Admin commands (for backward compatibility)
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("cmd", cmd_list))
    app.add_handler(CommandHandler("premium", make_premium))
    app.add_handler(CommandHandler("unpremium", remove_premium))
    app.add_handler(CommandHandler("stats", cmd_stats))  # FIXED: This will call cmd_stats which calls show_stats
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("unban", cmd_unban))
    app.add_handler(CommandHandler("del", cmd_delete))
    app.add_handler(CommandHandler("renew", cmd_renew))
    
    # Old admin commands (still supported but use admin panel instead)
    app.add_handler(CommandHandler("addprivatefj", cmd_addprivatefj))
    app.add_handler(CommandHandler("addpvtforcejoin", cmd_addpvtforcejoin))
    app.add_handler(CommandHandler("removepvtforcejoin", cmd_removepvtforcejoin))
    app.add_handler(CommandHandler("addpubfj", cmd_addpubfj))
    app.add_handler(CommandHandler("removepubfj", cmd_removepubfj))
    app.add_handler(CommandHandler("setinvite", cmd_setinvite))
    app.add_handler(CommandHandler("access", cmd_access))
    app.add_handler(CommandHandler("removeaccess", cmd_removeaccess))
    app.add_handler(CommandHandler("listforcejoin", cmd_listforcejoin))
    app.add_handler(CommandHandler("listaccess", cmd_listaccess))

    # Broadcast preview confirm handler, unknown fallback
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Error handler
    app.add_error_handler(error_handler)

    logger.info("🚀 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    # Don't forget to update PREMIUM_CHANNEL_ID in config section
    if PREMIUM_CHANNEL_ID == -1001234567890:
        logger.warning("⚠️ Please update PREMIUM_CHANNEL_ID in config section!")
    
    main()
