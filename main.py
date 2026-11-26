
import os
import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

API_URL = "https://v3.football.api-sports.io/fixtures"
NIGERIA_TZ = ZoneInfo("Africa/Lagos")

def get_fixtures(params):
    response = requests.get(
        API_URL,
        headers={"x-apisports-key": FOOTBALL_API_KEY},
        params=params,
        timeout=25
    )
    response.raise_for_status()
    data = response.json()

    if data.get("errors"):
        raise ValueError(str(data["errors"]))

    return data.get("response", [])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ Welcome to Favour Football AI!\n\n"
        "Commands:\n"
        "/live - Live football matches\n"
        "/upcoming - Upcoming fixtures and kickoff times\n"
        "/help - Help menu\n\n"
        "All fixture times are shown in Nigeria time (WAT)."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ Favour Football AI Commands\n\n"
        "/start - Start bot\n"
        "/live - Live matches\n"
        "/upcoming - Upcoming matches\n"
        "/help - Help"
    )

async def live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        matches = get_fixtures({"live": "all"})

        if not matches:
            await update.message.reply_text(
                "No live matches found right now."
            )
            return

        for match in matches[:15]:
            home = match["teams"]["home"]["name"]
            away = match["teams"]["away"]["name"]
            goals_home = match["goals"]["home"]
            goals_away = match["goals"]["away"]
            minute = match["fixture"]["status"]["elapsed"]
            league = match["league"]["name"]

            await update.message.reply_text(
                f"⚽ {home} {goals_home} - {goals_away} {away}\n"
                f"🏆 {league}\n"
                f"⏱️ Minute: {minute}\n"
            )

    except Exception:
        logging.exception("Live fixtures error")
        await update.message.reply_text(
            "Could not retrieve live matches. Please try again."
        )

async def upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        matches = get_fixtures({
            "next": 10,
            "timezone": "Africa/Lagos"
        })

        if not matches:
            await update.message.reply_text(
                "No upcoming fixtures were returned by the API."
            )
            return

        await update.message.reply_text(
            "📅 UPCOMING FOOTBALL MATCHES\n"
            "🇳🇬 All kickoff times are Nigeria time (WAT)."
        )

        for match in matches:
            fixture = match["fixture"]
            home = match["teams"]["home"]["name"]
            away = match["teams"]["away"]["name"]
            league = match["league"]["name"]

            kickoff = datetime.fromisoformat(
                fixture["date"].replace("Z", "+00:00")
            ).astimezone(NIGERIA_TZ)

            day = kickoff.strftime("%A")
            date = kickoff.strftime("%d %B %Y")
            time = kickoff.strftime("%I:%M %p")

            message = (
                f"⚽ {home} vs {away}\n"
                f"🏆 {league}\n"
                f"📅 Day: {day}\n"
                f"🗓️ Date: {date}\n"
                f"⏰ Kickoff: {time} WAT"
            )

            await update.message.reply_text(message)

    except Exception:
        logging.exception("Upcoming fixtures error")
        await update.message.reply_text(
            "Could not retrieve upcoming fixtures. "
            "Please check your API account and try again."
        )

def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    if not FOOTBALL_API_KEY:
        raise RuntimeError("FOOTBALL_API_KEY is missing")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("live", live))
    app.add_handler(CommandHandler("upcoming", upcoming))

    app.run_polling()

if __name__ == "__main__":
    main()

