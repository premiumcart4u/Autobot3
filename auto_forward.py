# pip install python-telegram-bot==20.7
import json
import os
import time
import logging
from typing import Optional, List, Dict
from telegram import (
    Update, Message, InputMediaPhoto, InputMediaVideo,
    InputMediaDocument, InputMediaAudio, error
)
from telegram.ext import Application, MessageHandler, filters, CallbackContext

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONFIG ---
TOKEN = "886484638:AAGobE1VHxOLlhqRXIK1SV9zlMLEXZdvCyo"
SOURCE_CHANNEL = -1001276269509  # source channel ID

# WARNING: Make sure the bot is an admin in ALL channels with post permissions!
TARGETS = {
    -1001703093158: {
        "https://t.me/captainadilfakhri": "https://t.me/captkingmaker",
    },
    -1001360694193: {
        "https://t.me/captainadilfakhri": "https://t.me/TFDCEOBSA",
        "https://example.com/old": "https://example.com/newB"
    }
}

STATE_DIR = "message_maps"
os.makedirs(STATE_DIR, exist_ok=True)

# --- Helpers for saving message maps ---
def load_map(target_id: int) -> dict:
    path = os.path.join(STATE_DIR, f"{target_id}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Convert string keys back to integers
                return {int(k): v for k, v in data.items()}
        except Exception as e:
            logger.error(f"Error loading map for {target_id}: {e}")
            return {}
    return {}

def save_map(target_id: int, mapping: dict) -> None:
    path = os.path.join(STATE_DIR, f"{target_id}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            # Convert int keys to strings for JSON
            json.dump({str(k): v for k, v in mapping.items()}, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving map for {target_id}: {e}")

message_maps = {tid: load_map(tid) for tid in TARGETS.keys()}

def replace_links(s: Optional[str], link_map: dict) -> Optional[str]:
    if not s:
        return s
    for old, new in link_map.items():
        s = s.replace(old, new)
    return s

# --- Media group management ---
media_groups: Dict[str, Dict] = {}
MEDIA_GROUP_TIMEOUT = 2.0  # Increased timeout

async def flush_due_media_groups(context: CallbackContext):
    now = time.time()
    to_flush = [mgid for mgid, d in media_groups.items() if now - d["time"] >= MEDIA_GROUP_TIMEOUT]
    
    for mgid in to_flush:
        group = media_groups.pop(mgid, None)
        if not group:
            continue
        
        msgs: List[Message] = group["messages"]
        if not msgs:
            continue
            
        first = msgs[0]
        caption = first.caption or ""

        for target_id, link_map in TARGETS.items():
            try:
                new_caption = replace_links(caption, link_map) if caption else None
                media = []
                
                for i, m in enumerate(msgs):
                    c = new_caption if i == 0 else None
                    if m.photo:
                        media.append(InputMediaPhoto(media=m.photo[-1].file_id, caption=c))
                    elif m.video:
                        media.append(InputMediaVideo(media=m.video.file_id, caption=c))
                    elif m.document:
                        media.append(InputMediaDocument(media=m.document.file_id, caption=c))
                    elif m.audio:
                        media.append(InputMediaAudio(media=m.audio.file_id, caption=c))

                if media:
                    # Send media group
                    sent_list = await context.bot.send_media_group(target_id, media)
                    
                    # Update message maps
                    for sm, tm in zip(msgs, sent_list):
                        message_maps[target_id][sm.message_id] = tm.message_id
                    save_map(target_id, message_maps[target_id])
                    logger.info(f"✅ Sent media group with {len(media)} items to {target_id}")
                    
            except error.TelegramError as e:
                logger.error(f"Error sending media group to {target_id}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error sending media group: {e}")

async def handle(update: Update, context: CallbackContext):
    msg = update.effective_message
    
    # Debug logging
    logger.info(f"Received message ID: {msg.message_id if msg else 'None'}, Chat ID: {msg.chat_id if msg else 'None'}")
    
    if not msg:
        return
        
    # Check if message is from source channel
    if msg.chat_id != SOURCE_CHANNEL:
        logger.info(f"Ignoring message from chat {msg.chat_id} (not source channel)")
        return

    logger.info(f"Processing message {msg.message_id} from source channel")

    # Handle grouped media
    if msg.media_group_id:
        logger.info(f"Message {msg.message_id} is part of media group: {msg.media_group_id}")
        mgid = msg.media_group_id
        if mgid not in media_groups:
            media_groups[mgid] = {"messages": [], "time": time.time()}
        media_groups[mgid]["messages"].append(msg)
        media_groups[mgid]["time"] = time.time()
        
        # Schedule flush
        if "job" not in media_groups[mgid]:
            media_groups[mgid]["job"] = context.application.create_task(
                flush_after_delay(context, mgid)
            )
        return

    # Single posts (text, image, etc.)
    for target_id, link_map in TARGETS.items():
        reply_to_target = None
        if msg.reply_to_message:
            src_id = msg.reply_to_message.message_id
            reply_to_target = message_maps[target_id].get(src_id)

        sent = None
        caption = replace_links(msg.caption, link_map) if msg.caption else None
        text = replace_links(msg.text, link_map) if msg.text else None

        try:
            if msg.photo:
                logger.info(f"Sending photo to {target_id}")
                sent = await context.bot.send_photo(
                    target_id, msg.photo[-1].file_id, 
                    caption=caption, 
                    reply_to_message_id=reply_to_target
                )
            elif msg.video:
                logger.info(f"Sending video to {target_id}")
                sent = await context.bot.send_video(
                    target_id, msg.video.file_id, 
                    caption=caption, 
                    reply_to_message_id=reply_to_target
                )
            elif msg.document:
                logger.info(f"Sending document to {target_id}")
                sent = await context.bot.send_document(
                    target_id, msg.document.file_id, 
                    caption=caption, 
                    reply_to_message_id=reply_to_target
                )
            elif msg.audio:
                logger.info(f"Sending audio to {target_id}")
                sent = await context.bot.send_audio(
                    target_id, msg.audio.file_id, 
                    caption=caption, 
                    reply_to_message_id=reply_to_target
                )
            elif msg.text:
                logger.info(f"Sending text to {target_id}")
                sent = await context.bot.send_message(
                    target_id, text or msg.text, 
                    reply_to_message_id=reply_to_target
                )
            elif msg.sticker:
                logger.info(f"Sending sticker to {target_id}")
                sent = await context.bot.send_sticker(
                    target_id, msg.sticker.file_id,
                    reply_to_message_id=reply_to_target
                )
            elif msg.animation:
                logger.info(f"Sending animation/GIF to {target_id}")
                sent = await context.bot.send_animation(
                    target_id, msg.animation.file_id,
                    caption=caption,
                    reply_to_message_id=reply_to_target
                )
            else:
                logger.warning(f"Unsupported message type: {msg}")

            if sent:
                message_maps[target_id][msg.message_id] = sent.message_id
                save_map(target_id, message_maps[target_id])
                logger.info(f"✅ Successfully sent to {target_id} (message ID: {sent.message_id})")

        except error.Forbidden as e:
            logger.error(f"❌ Bot not allowed to post in {target_id}. Make sure bot is admin: {e}")
        except error.TimedOut as e:
            logger.error(f"❌ Timeout sending to {target_id}: {e}")
        except error.TelegramError as e:
            logger.error(f"❌ Telegram error sending to {target_id}: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error for {target_id}: {e}", exc_info=True)

async def flush_after_delay(context: CallbackContext, mgid: str):
    """Flush media group after timeout"""
    await asyncio.sleep(MEDIA_GROUP_TIMEOUT)
    await flush_due_media_groups(context)

async def post_init(application: Application):
    """Verify bot permissions on startup"""
    me = await application.bot.get_me()
    logger.info(f"🤖 Bot started: @{me.username}")
    
    # Check source channel
    try:
        chat = await application.bot.get_chat(SOURCE_CHANNEL)
        logger.info(f"✅ Source channel: {chat.title} (ID: {SOURCE_CHANNEL})")
    except Exception as e:
        logger.error(f"❌ Cannot access source channel: {e}")
    
    # Check target channels
    for target_id in TARGETS.keys():
        try:
            chat = await application.bot.get_chat(target_id)
            logger.info(f"✅ Target channel accessible: {chat.title} (ID: {target_id})")
        except Exception as e:
            logger.error(f"❌ Cannot access target channel {target_id}: {e}")

def main():
    # Create Application
    application = Application.builder().token(TOKEN).build()
    
    # Add handler for source channel messages
    application.add_handler(MessageHandler(filters.Chat(chat_id=SOURCE_CHANNEL), handle))
    
    # Add job to flush media groups
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(flush_due_media_groups, interval=1.0, first=1.0)
    
    # Add post-init check
    application.post_init = post_init
    
    logger.info("✅ Forwarder with captions & media running...")
    logger.info(f"📡 Monitoring channel: {SOURCE_CHANNEL}")
    logger.info(f"🎯 Forwarding to: {list(TARGETS.keys())}")
    
    # Start polling
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    import asyncio
    main()
