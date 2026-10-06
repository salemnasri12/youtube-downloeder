# YouTube Downloader Telegram Bot

Telegram bot to download YouTube videos/audio, powered by yt-dlp (same engine as Seal app).

## Deploy on Vercel
1. Push this repo to GitHub and import it in Vercel.
2. Set env var `TELEGRAM_BOT_TOKEN` in Vercel project settings.
3. After deploy, visit:
   `https://<your-app>.vercel.app/api/set_webhook?url=https://<your-app>.vercel.app/api/webhook`
4. Talk to your bot on Telegram.

## Local polling (no webhook)
```
export TELEGRAM_BOT_TOKEN=...
pip install -r requirements.txt
python3 bot_polling.py
```
