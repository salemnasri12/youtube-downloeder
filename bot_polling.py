import os
import re
import asyncio
import logging
from pathlib import Path

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes,
)
import yt_dlp
import imageio_ffmpeg

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/home/salem/Downloads/YOUTUBE /downloads"))
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
URL_RE = re.compile(r"(https?://[^\s]+)")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("youtude-bot")

MAIN_KB = ReplyKeyboardMarkup(
    [["🎬 Download Video", "🎵 Download Audio"], ["❓ Help", "ℹ️ About"]],
    resize_keyboard=True,
)


def download(url: str, mode: str) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(DOWNLOAD_DIR / "%(title).80s [%(id)s].%(ext)s"),
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
    else:  # video
        opts["format"] = "bv*[height<=720]+ba/b[height<=720]/b"
        opts["merge_output_format"] = "mp4"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        ext = ".mp3" if mode == "audio" else ".mp4"
        return Path(ydl.prepare_filename(info)).with_suffix(ext)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "👋 Welcome! Send me a YouTube link, or pick an option below.",
        reply_markup=MAIN_KB,
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ How to use:\n"
        "1️⃣ Send a YouTube link\n"
        "2️⃣ Choose format: Video / HD Video / Low Video / Audio MP3\n\n"
        "Commands:\n/start - main menu\n/help - this help\n/link - how to get the link\n/about - about the bot"
    )


async def link_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔗 On YouTube: open the video → tap Share → Copy link → paste it here."
    )


async def about_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ℹ️ YouTube downloader bot powered by yt-dlp.")


async def choose_format(update: Update, ctx: ContextTypes.DEFAULT_TYPE, url: str):
    ctx.user_data["url"] = url
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Video (720p)", callback_data="dl:video")],
        [InlineKeyboardButton("📺 HD Video (1080p)", callback_data="dl:video_hd"),
         InlineKeyboardButton("📱 Low (360p)", callback_data="dl:video_low")],
        [InlineKeyboardButton("🎵 Audio MP3", callback_data="dl:audio")],
        [InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")],
    ])
    await update.message.reply_text("Choose what to download:", reply_markup=kb)


async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    mode = q.data.split(":", 1)[1]
    if mode == "cancel":
        ctx.user_data.pop("url", None)
        await q.edit_message_text("Cancelled.")
        return
    url = ctx.user_data.get("url")
    if not url:
        await q.edit_message_text("No link saved. Please send the link again.")
        return
    await q.edit_message_text("⬇️ Downloading...")
    try:
        path = await asyncio.to_thread(download, url, mode)
        if not path.exists():
            cands = sorted(DOWNLOAD_DIR.glob("*"), key=os.path.getmtime)
            path = cands[-1] if cands else path
        size_mb = path.stat().st_size / 1e6
        if size_mb > 49:
            await q.edit_message_text(f"⚠️ File too large for Telegram ({size_mb:.1f} MB).")
            return
        await q.edit_message_text("⬆️ Uploading...")
        with path.open("rb") as f:
            if mode == "audio":
                await q.message.reply_audio(f, title=path.stem)
            else:
                await q.message.reply_video(f, caption=path.stem, supports_streaming=True)
        await q.message.delete()
    except Exception as e:
        log.exception("download failed")
        await q.edit_message_text(f"❌ Error: {e}")


async def text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text == "❓ Help":
        return await help_cmd(update, ctx)
    if text == "ℹ️ About":
        return await about_cmd(update, ctx)
    if text in ("🎬 Download Video", "🎵 Download Audio"):
        ctx.user_data["pending_mode"] = "video" if "Video" in text else "audio"
        return await update.message.reply_text("🔗 Now send me the YouTube link:")
    m = URL_RE.search(text)
    if m:
        url = m.group(1)
        pending = ctx.user_data.pop("pending_mode", None)
        if pending:
            msg = await update.message.reply_text("⬇️ Downloading...")
            try:
                path = await asyncio.to_thread(download, url, pending)
                if not path.exists():
                    cands = sorted(DOWNLOAD_DIR.glob("*"), key=os.path.getmtime)
                    path = cands[-1] if cands else path
                size_mb = path.stat().st_size / 1e6
                if size_mb > 49:
                    await msg.edit_text(f"⚠️ File too large for Telegram ({size_mb:.1f} MB).")
                    return
                await msg.edit_text("⬆️ Uploading...")
                with path.open("rb") as f:
                    if pending == "audio":
                        await update.message.reply_audio(f, title=path.stem)
                    else:
                        await update.message.reply_video(f, caption=path.stem, supports_streaming=True)
                await msg.delete()
            except Exception as e:
                log.exception("download failed")
                await msg.edit_text(f"❌ Error: {e}")
            return
        return await choose_format(update, ctx, url)
    await update.message.reply_text("Please send a valid YouTube link, or use the menu.")


def main():
    app = Application.builder().token(TOKEN).read_timeout(300).write_timeout(300).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("link", link_cmd))
    app.add_handler(CommandHandler("about", about_cmd))
    app.add_handler(CallbackQueryHandler(button, pattern=r"^dl:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.run_polling()


if __name__ == "__main__":
    main()
