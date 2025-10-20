# pip install python-telegram-bot==13.15
import json
import os
import time
from typing import Optional, List
from telegram import Update, Message, InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext

TOKEN = "886484638:AAGobE1VHxOLlhqRXIK1SV9zlMLEXZdvCyo"
SOURCE_CHANNEL = -1001276269509  # source channel ID

TARGETS = {
    -1001703093158: {  # Channel A
        "https://t.me/captainadilfakhri": "https://t.me/captkingmaker"
    },
    -1001360694193: {  # Channel B
        "https://t.me/captainadilfakhri": "https://t.me/TFDCEOBSA",
        "https://example.com/old": "https://example.com/newB"
    }
}

STATE_DIR = "message_maps"
os.makedirs(STATE_DIR, exist_ok=True)


def load_map(target_id: int) -> dict:
    path = os.path.join(STATE_DIR, f"{target_id}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): int(v) for k, v in data.items()}
        except Exception:
            return {}
    return {}


def save_map(target_id: int, mapping: dict) -> None:
    path = os.path.join(STATE_DIR, f"{target_id}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in mapping.items()}, f)
    except Exception:
        pass


message_maps = {tid: load_map(tid) for tid in TARGETS.keys()}


def replace_links(s: Optional[str], link_map: dict) -> Optional[str]:
    if not s:
        return s
    for old, new in link_map.items():
        s = s.replace(old, new)
    return s


# --- Media group buffering ---
media_groups = {}  # {media_group_id: {"messages": [], "time": timestamp}}
MEDIA_GROUP_TIMEOUT = 1.0  # seconds to wait before flushing group


def flush_due_media_groups(context: CallbackContext):
    now = time.time()
    to_flush = [mgid for mgid, data in media_groups.items() if now - data["time"] >= MEDIA_GROUP_TIMEOUT]
    for mgid in to_flush:
        data = media_groups.pop(mgid, None)
        if not data:
            continue
        msgs: List[Message] = data["messages"]
        first_msg = msgs[0]
        orig_text = first_msg.caption or ""
        for target_id, link_map in TARGETS.items():
            new_caption = replace_links(orig_text, link_map) if orig_text else None
            media = []
            for i, m in enumerate(msgs):
                if m.photo:
                    media.append(InputMediaPhoto(m.photo[-1].file_id, caption=new_caption if i == 0 else None))
                elif m.video:
                    media.append(InputMediaVideo(m.video.file_id, caption=new_caption if i == 0 else None))
                elif m.document:
                    media.append(InputMediaDocument(m.document.file_id, caption=new_caption if i == 0 else None))
                elif m.audio:
                    media.append(InputMediaAudio(m.audio.file_id, caption=new_caption if i == 0 else None))
            try:
                sent_list = context.bot.send_media_group(target_id, media)
                for sm, tm in zip(msgs, sent_list):
                    message_maps[target_id][sm.message_id] = tm.message_id
                save_map(target_id, message_maps[target_id])
            except Exception as e:
                print("Error sending media group:", e)


def handle(update: Update, context: CallbackContext):
    msg = update.effective_message
    if not msg or msg.chat_id != SOURCE_CHANNEL:
        return

    # --- Media groups ---
    if msg.media_group_id:
        mgid = msg.media_group_id
        if mgid not in media_groups:
            media_groups[mgid] = {"messages": [], "time": time.time()}
        media_groups[mgid]["messages"].append(msg)
        return

    # --- Non-media messages ---
    for target_id, link_map in TARGETS.items():
        reply_to_target_id = None
        if msg.reply_to_message:
            src_id = msg.reply_to_message.message_id
            reply_to_target_id = message_maps[target_id].get(src_id)

        sent = None
        try:
            if msg.text:
                sent = context.bot.send_message(
                    target_id,
                    replace_links(msg.text, link_map) or msg.text,
                    reply_to_message_id=reply_to_target_id
                )
            elif msg.sticker:
                sent = context.bot.send_sticker(target_id, msg.sticker.file_id, reply_to_message_id=reply_to_target_id)
            elif msg.photo:
                sent = context.bot.send_photo(
                    target_id, msg.photo[-1].file_id,
                    caption=replace_links(msg.caption, link_map) if msg.caption else None,
                    reply_to_message_id=reply_to_target_id
                )
            elif msg.video:
                sent = context.bot.send_video(
                    target_id, msg.video.file_id,
                    caption=replace_links(msg.caption, link_map) if msg.caption else None,
                    reply_to_message_id=reply_to_target_id
                )
            elif msg.document:
                sent = context.bot.send_document(
                    target_id, msg.document.file_id,
                    caption=replace_links(msg.caption, link_map) if msg.caption else None,
                    reply_to_message_id=reply_to_target_id
                )
            elif msg.audio:
                sent = context.bot.send_audio(
                    target_id, msg.audio.file_id,
                    caption=replace_links(msg.caption, link_map) if msg.caption else None,
                    reply_to_message_id=reply_to_target_id
                )
            if sent:
                message_maps[target_id][msg.message_id] = sent.message_id
                save_map(target_id, message_maps[target_id])
        except Exception as e:
            print(f"Error forwarding message {msg.message_id}: {e}")


# --- Catch-up for messages while bot was offline ---
def catchup(context: CallbackContext):
    for target_id in TARGETS.keys():
        last_mapped_ids = message_maps[target_id]
        last_id = max(last_mapped_ids.keys(), default=0)
        try:
            for msg in context.bot.get_chat(SOURCE_CHANNEL).get_history(offset_id=0, limit=100):  # fetch recent messages
                if msg.message_id > last_id:
                    fake_update = Update(update_id=0, message=msg)
                    handle(fake_update, context)
        except Exception as e:
            print("Error during catchup:", e)


def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # handle live messages
    dp.add_handler(MessageHandler(Filters.chat(SOURCE_CHANNEL), handle))

    # repeating job to flush media groups
    updater.job_queue.run_repeating(flush_due_media_groups, interval=1.0, first=1.0)
    # catch-up job at startup
    updater.job_queue.run_once(catchup, 1.0)

    print("Forwarder with media-group batching running…")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
