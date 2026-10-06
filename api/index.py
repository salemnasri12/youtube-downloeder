import os
import re
import asyncio
import logging
import tempfile
from pathlib import Path

from flask import Flask, request, jsonify
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, Bot
import yt_dlp
import imageio_ffmpeg

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
URL_RE = re.compile(r"(https?://[^\s]+)")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "ytdl"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ytdl-bot")

app = Flask(__name__)
bot = Bot(TOKEN)

MAIN_KB = ReplyKeyboardMarkup(
    [["🎬 Download Video", "🎵 Download Audio"], ["❓ Help", "ℹ️ About"]],
    resize_keyboard=True,
)

user_state = {}


def download(url: str, mode: str) -> Path:
    opts = {
        "outtmpl": str(DOWNLOAD_DIR / "%(title).60s [%(id)s].%(ext)s"),
        "ffmpeg_location": FFMPEG,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    if mode == "audio":
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        })
    elif mode == "video_low":
        opts["format"] = "bv*[height<=360]+ba/b[height<=360]/b"
        opts["merge_output_format"] = "mp4"
    elif mode == "video_hd":
        opts["format"] = "bv*[height<=1080]+ba/b[height<=1080]/b"
        opts["merge_output_format"] = "mp4"
    else:
        opts["format"] = "bv*[height<=720]+ba/b[height<=720]/b"
        opts["merge_output_format"] = "mp4"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        ext = ".mp3" if mode == "audio" else ".mp4"
        return Path(ydl.prepare_filename(info)).with_suffix(ext)


async def send(chat_id, text, **kw):
    return await bot.send_message(chat_id=chat_id, text=text, **kw)


async def handle_callback(cb):
    mode = cb.data.split(":", 1)[1]
    await cb.answer()
    chat_id = cb.message.chat_id
    if mode == "cancel":
        user_state.pop(str(chat_id), None)
        await cb.edit_message_text("Cancelled.")
        return
    url = user_state.get(str(chat_id), {}).get("url")
    if not url:
        await cb.edit_message_text("No link saved. Send it again.")
        return
    await cb.edit_message_text("⬇️ Downloading...")
    try:
        path = await asyncio.to_thread(download, url, mode)
        if not path.exists():
            cands = sorted(DOWNLOAD_DIR.glob("*"), key=os.path.getmtime)
            path = cands[-1] if cands else path
        size_mb = path.stat().st_size / 1e6
        if size_mb > 49:
            await bot.send_message(chat_id, f"⚠️ File too large ({size_mb:.1f} MB).")
            return
        with path.open("rb") as f:
            if mode == "audio":
                await bot.send_audio(chat_id, f, title=path.stem)
            else:
                await bot.send_video(chat_id, f, caption=path.stem, supports_streaming=True, write_timeout=300, read_timeout=300)
        await cb.message.delete()
    except Exception as e:
        log.exception("dl fail")
        await bot.send_message(chat_id, f"❌ Error: {e}")


async def handle_text(update: Update):
    msg = update.message
    chat_id = msg.chat_id
    text = (msg.text or "").strip()

    if text == "/start":
        user_state.pop(str(chat_id), None)
        await send(chat_id, "👋 Welcome! Send me a YouTube link, or pick an option below.", reply_markup=MAIN_KB)
    elif text in ("/help", "❓ Help"):
        await send(chat_id, "1️⃣ Send a YouTube link\n2️⃣ Choose: Video / HD / Low / Audio MP3")
    elif text == "ℹ️ About" or text == "/about":
        await send(chat_id, "ℹ️ YouTube downloader bot powered by yt-dlp.")
    elif text in ("🎬 Download Video", "🎵 Download Audio"):
        user_state[str(chat_id)] = {"pending_mode": "audio" if "Audio" in text else "video"}
        await send(chat_id, "🔗 Send me the YouTube link:")
    else:
        m = URL_RE.search(text)
        if m:
            url = m.group(1)
            st = user_state.pop(str(chat_id), {})
            pending = st.get("pending_mode")
            if pending:
                user_state[str(chat_id)] = {"url": url}
                await handle_callback_fake(chat_id, pending, msg)
            else:
                user_state[str(chat_id)] = {"url": url}
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎬 Video (720p)", callback_data="dl:video")],
                    [InlineKeyboardButton("📺 HD (1080p)", callback_data="dl:video_hd"),
                     InlineKeyboardButton("📱 Low (360p)", callback_data="dl:video_low")],
                    [InlineKeyboardButton("🎵 Audio MP3", callback_data="dl:audio")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")],
                ])
                await send(chat_id, "Choose what to download:", reply_markup=kb)
        else:
            await send(chat_id, "Please send a valid YouTube link, or use the menu.")


async def handle_callback_fake(chat_id, mode, msg):
    url = user_state.get(str(chat_id), {}).get("url")
    if not url:
        return
    status = await msg.reply_text("⬇️ Downloading...")
    try:
        path = await asyncio.to_thread(download, url, mode)
        if not path.exists():
            cands = sorted(DOWNLOAD_DIR.glob("*"), key=os.path.getmtime)
            path = cands[-1] if cands else path
        size_mb = path.stat().st_size / 1e6
        if size_mb > 49:
            await status.edit_text(f"⚠️ File too large ({size_mb:.1f} MB).")
            return
        with path.open("rb") as f:
            if mode == "audio":
                await bot.send_audio(chat_id, f, title=path.stem)
            else:
                await bot.send_video(chat_id, f, caption=path.stem, supports_streaming=True, write_timeout=300, read_timeout=300)
        await status.delete()
    except Exception as e:
        log.exception("dl fail")
        await status.edit_text(f"❌ Error: {e}")


@app.route("/api/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    if update.callback_query:
        asyncio.run(handle_callback(update.callback_query))
    elif update.message and update.message.text:
        asyncio.run(handle_text(update))
    return jsonify(ok=True)


@app.route("/api/set_webhook", methods=["GET"])
def set_webhook():
    webhook_url = request.args.get("url")
    if not webhook_url:
        return "pass ?url=https://your-app.vercel.app/api/webhook", 400
    result = asyncio.run(bot.set_webhook(webhook_url))
    return f"webhook set: {result}"


@app.route("/")
def index():
    return "YouTube downloader bot is running."
