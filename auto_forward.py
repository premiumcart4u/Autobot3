# pip install python-telegram-bot==13.15
import json
import os
import time
from typing import Optional, List
from telegram import (
    Update, Message, InputMediaPhoto, InputMediaVideo,
    InputMediaDocument, InputMediaAudio
)
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext

# --- CONFIG ---
TOKEN = "886484638:AAGobE1VHxOLlhqRXIK1SV9zlMLEXZdvCyo"
SOURCE_CHANNEL = -1001276269509  # source channel ID

TARGETS = {
    -1001703093158: {"https://t.me/captainadilfakhri": "https://t.me/captkingmaker"},
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
                return {int(k): int(v) for k, v in data.items()}
        except Exception:
            return {}
    return {}


def save_map(target_id: int, mapping: dict) -> None:
    path = os.path.join(STATE_DIR, f"{target_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in mapping.items()}, f)


message_maps = {tid: load_map(tid) for tid in TARGETS.keys()}


def replace_links(s: Optional[str], link_map: dict) -> Optional[str]:
    if not s:
        return s
    for old, new in link_map.items():
        s = s.replace(old, new)
    return s


# --- Media group management ---
media_groups = {}
MEDIA_GROUP_TIMEOUT = 1.0


def flush_due_media_groups(context: CallbackContext):
    now = time.time()
    to_flush = [mgid for mgid, d in media_groups.items() if now - d["time"] >= MEDIA_GROUP_TIMEOUT]
    for mgid in to_flush:
        group = media_groups.pop(mgid, None)
        if not group:
            continue
        msgs: List[Message] = group["messages"]
        first = msgs[0]
        caption = first.caption or ""

        for target_id, link_map in TARGETS.items():
            new_caption = replace_links(caption, link_map) if caption else None
            media = []
            for i, m in enumerate(msgs):
                c = new_caption if i == 0 else None
                if m.photo:
                    media.append(InputMediaPhoto(m.photo[-1].file_id, caption=c))
                elif m.video:
                    media.append(InputMediaVideo(m.video.file_id, caption=c))
                elif m.document:
                    media.append(InputMediaDocument(m.document.file_id, caption=c))
                elif m.audio:
                    media.append(InputMediaAudio(m.audio.file_id, caption=c))

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

    # handle grouped media
    if msg.media_group_id:
        mgid = msg.media_group_id
        media_groups.setdefault(mgid, {"messages": [], "time": time.time()})
        media_groups[mgid]["messages"].append(msg)
        media_groups[mgid]["time"] = time.time()
        return

    # single posts (text, image, etc.)
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
                sent = context.bot.send_photo(
                    target_id, msg.photo[-1].file_id, caption=caption, reply_to_message_id=reply_to_target
                )
            elif msg.video:
                sent = context.bot.send_video(
                    target_id, msg.video.file_id, caption=caption, reply_to_message_id=reply_to_target
                )
            elif msg.document:
                sent = context.bot.send_document(
                    target_id, msg.document.file_id, caption=caption, reply_to_message_id=reply_to_target
                )
            elif msg.audio:
                sent = context.bot.send_audio(
                    target_id, msg.audio.file_id, caption=caption, reply_to_message_id=reply_to_target
                )
            elif msg.text:
                sent = context.bot.send_message(
                    target_id, text or msg.text, reply_to_message_id=reply_to_target
                )

            if sent:
                message_maps[target_id][msg.message_id] = sent.message_id
                save_map(target_id, message_maps[target_id])

        except Exception as e:
            print(f"Error forwarding message {msg.message_id}: {e}")


def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(MessageHandler(Filters.chat(SOURCE_CHANNEL), handle))
    updater.job_queue.run_repeating(flush_due_media_groups, interval=1.0, first=1.0)

    print("✅ Forwarder with captions & media running…")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
