
import os
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ Welcome to Favour Football AI!\n\n"
        "I analyse football matches and provide prediction guidance.\n\n"
        "Use /live to check live matches.\n"
        "Use /help to see commands."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Available commands:\n"
        "/start - Start the bot\n"
        "/live - Check live matches\n"
        "/help - Show commands"
    )

async def live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not FOOTBALL_API_KEY:
        await update.message.reply_text(
            "Football API is not connected yet. Setup is in progress."
        )
        return

    try:
        response = requests.get(
            "https://v3.football.api-sports.io/fixtures",
            headers={"x-apisports-key": FOOTBALL_API_KEY},
            params={"live": "all"},
            timeout=20
        )
        response.raise_for_status()
        matches = response.json().get("response", [])

        if not matches:
            await update.message.reply_text("No live matches found right now.")
            return

        for match in matches[:10]:
            home = match["teams"]["home"]["name"]
            away = match["teams"]["away"]["name"]
            goals_home = match["goals"]["home"]
            goals_away = match["goals"]["away"]
            minute = match["fixture"]["status"]["elapsed"]

            message = (
                f"⚽ {home} {goals_home} - {goals_away} {away}\n"
                f"⏱️ Minute: {minute}\n"
                "Analysis: Live score only; prediction not guaranteed."
            )
            await update.message.reply_text(message)

    except Exception as error:
        logging.exception("Live match request failed")
        await update.message.reply_text(
            "Sorry, I couldn't retrieve live matches. Please try again later."
        )

def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("live", live))
    app.run_polling()

if __name__ == "__main__":
    main()
