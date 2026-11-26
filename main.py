

import os
import logging
import math
import requests

from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ---------------- CONFIGURATION ----------------

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

API_URL = "https://v3.football.api-sports.io"
NIGERIA_TZ = ZoneInfo("Africa/Lagos")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ---------------- API CONNECTION ----------------

def api_get(endpoint, params=None):
    if not FOOTBALL_API_KEY:
        raise ValueError("Football API key is missing.")

    headers = {
        "x-apisports-key": FOOTBALL_API_KEY
    }

    response = requests.get(
        f"{API_URL}/{endpoint}",
        headers=headers,
        params=params or {},
        timeout=25
    )

    response.raise_for_status()
    data = response.json()

    if data.get("errors"):
        raise RuntimeError(str(data["errors"]))

    return data.get("response", [])


# ---------------- MATCH DATE ----------------

def match_time(date_string):
    dt = datetime.fromisoformat(
        date_string.replace("Z", "+00:00")
    ).astimezone(NIGERIA_TZ)

    return dt.strftime("%A, %d %B %Y"), dt.strftime("%I:%M %p")


# ---------------- LIVE MATCHES ----------------

async def live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Checking live matches...")

    try:
        matches = api_get(
            "fixtures",
            {"live": "all", "timezone": "Africa/Lagos"}
        )

        if not matches:
            await update.message.reply_text(
                "No live matches found right now."
            )
            return

        lines = ["⚽ LIVE MATCHES\n"]

        for match in matches[:15]:
            teams = match["teams"]
            goals = match["goals"]
            status = match["fixture"]["status"]

            lines.append(
                f"{teams['home']['name']} "
                f"{goals['home']} - {goals['away']} "
                f"{teams['away']['name']}\n"
                f"Minute: {status.get('elapsed') or 'N/A'}\n"
                f"League: {match['league']['name']}\n"
            )

        await update.message.reply_text("\n".join(lines))

    except Exception:
        logging.exception("Live fixtures error")
        await update.message.reply_text(
            "Could not retrieve live matches. "
            "Please check your API account."
        )


# ---------------- UPCOMING MATCHES ----------------

async def upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Checking upcoming fixtures...")

    try:
        matches = api_get(
            "fixtures",
            {
                "next": 10,
                "timezone": "Africa/Lagos"
            }
        )

        if not matches:
            await update.message.reply_text(
                "No upcoming fixtures were returned."
            )
            return

        lines = ["📅 UPCOMING FOOTBALL MATCHES\n"]

        for match in matches:
            fixture = match["fixture"]
            date, time = match_time(fixture["date"])

            lines.append(
                f"⚽ {match['teams']['home']['name']} "
                f"vs {match['teams']['away']['name']}\n"
                f"📅 {date}\n"
                f"⏰ {time} WAT\n"
                f"🏆 {match['league']['name']}\n"
            )

        await update.message.reply_text("\n".join(lines))

    except Exception:
        logging.exception("Upcoming fixtures error")
        await update.message.reply_text(
            "Could not retrieve upcoming fixtures. "
            "Please check your API account."
        )


# ---------------- TEAM FORM ----------------

def team_form(team_id):
    matches = api_get(
        "fixtures",
        {
            "team": team_id,
            "last": 5,
            "timezone": "Africa/Lagos"
        }
    )

    played = []

    for match in matches:
        if match["fixture"]["status"]["short"] != "FT":
            continue

        home_id = match["teams"]["home"]["id"]
        goals = match["goals"]

        if goals["home"] is None or goals["away"] is None:
            continue

        if home_id == team_id:
            scored = goals["home"]
            conceded = goals["away"]
        else:
            scored = goals["away"]
            conceded = goals["home"]

        played.append((scored, conceded))

    if len(played) < 3:
        return None

    return {
        "scored": sum(x[0] for x in played) / len(played),
        "conceded": sum(x[1] for x in played) / len(played),
        "played": len(played)
    }


# ---------------- POISSON MODEL ----------------

def poisson(mean, goals):
    return (math.exp(-mean) * mean ** goals) / math.factorial(goals)


def analyse(home, away):
    home_form = team_form(home["id"])
    away_form = team_form(away["id"])

    if not home_form or not away_form:
        return None

    # Estimated goals using recent scoring and conceding form
    home_xg = (
        home_form["scored"] + away_form["conceded"]
    ) / 2

    away_xg = (
        away_form["scored"] + home_form["conceded"]
    ) / 2

    home_xg = max(0.15, min(home_xg, 4.5))
    away_xg = max(0.15, min(away_xg, 4.5))

    home_win = 0
    draw = 0
    away_win = 0
    over_15 = 0
    over_25 = 0
    btts = 0

    for h in range(7):
        for a in range(7):
            probability = poisson(home_xg, h) * poisson(away_xg, a)

            if h > a:
                home_win += probability
            elif h == a:
                draw += probability
            else:
                away_win += probability

            if h + a >= 2:
                over_15 += probability

            if h + a >= 3:
                over_25 += probability

            if h > 0 and a > 0:
                btts += probability

    total = home_win + draw + away_win

    if total <= 0:
        return None

    results = {
        "Home Win": home_win / total,
        "Draw": draw / total,
        "Away Win": away_win / total
    }

    return {
        "results": results,
        "over15": over_15,
        "over25": over_25,
        "btts": btts,
        "home_xg": home_xg,
        "away_xg": away_xg,
        "sample": min(home_form["played"], away_form["played"])
    }


# ---------------- PREDICTION COMMAND ----------------

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 Analysing upcoming matches. Please wait..."
    )

    try:
        matches = api_get(
            "fixtures",
            {
                "next": 5,
                "timezone": "Africa/Lagos"
            }
        )

        if not matches:
            await update.message.reply_text(
                "No upcoming matches available for analysis."
            )
            return

        lines = ["⚽ FAVOUR GOAL PREDICTOR\n"]

        for match in matches:
            home = match["teams"]["home"]
            away = match["teams"]["away"]

            try:
                result = analyse(home, away)

                date, time = match_time(match["fixture"]["date"])

                lines.append(
                    f"⚽ {home['name']} vs {away['name']}\n"
                    f"📅 {date} | {time} WAT\n"
                )

                if not result:
                    lines.append(
                        "⚠️ NO SAFE PREDICTION\n"
                        "Insufficient recent team data.\n"
                    )
                    continue

                outcomes = result["results"]
                ranked = sorted(
                    outcomes.items(),
                    key=lambda item: item[1],
                    reverse=True
                )

                best_name, best_probability = ranked[0]
                second_probability = ranked[1][1]

                for name, probability in ranked:
                    lines.append(
                        f"{name}: {probability * 100:.1f}%"
                    )

                lines.append(
                    f"Over 1.5 goals: {result['over15'] * 100:.1f}%"
                )
                lines.append(
                    f"Over 2.5 goals: {result['over25'] * 100:.1f}%"
                )
                lines.append(
                    f"BTTS: {result['btts'] * 100:.1f}%"
                )

                lines.append(
                    f"Estimated goals: {result['home_xg']:.2f} - "
                    f"{result['away_xg']:.2f}"
                )

                # Strict selection rule, not a guarantee
                if (
                    best_probability >= 0.60
                    and best_probability - second_probability >= 0.12
                    and result["sample"] >= 3
                ):
                    lines.append(
                        f"⭐ Strongest estimated outcome: {best_name}"
                    )
                else:
                    lines.append(
                        "⚠️ NO SAFE PREDICTION"
                    )

                lines.append(
                    f"Based on {result['sample']} recent matches per team."
                )
                lines.append("")

            except Exception:
                logging.exception(
                    "Analysis failed for %s vs %s",
                    home["name"],
                    away["name"]
                )
                lines.append(
                    f"{home['name']} vs {away['name']}\n"
                    "Analysis unavailable for this match.\n"
                )

        await update.message.reply_text("\n".join(lines))

    except Exception:
        logging.exception("Prediction engine error")
        await update.message.reply_text(
            "Prediction engine cannot retrieve match data. "
            "Please check your API account."
        )


# ---------------- START AND HELP ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ Welcome to Favour Goal Predictor!\n\n"
        "I analyse football statistics and estimate match outcomes.\n\n"
        "Commands:\n"
        "/live - Live matches\n"
        "/upcoming - Upcoming fixtures\n"
        "/predict - Statistical predictions\n"
        "/help - Help\n\n"
        "All match times are shown in Nigeria time (WAT).\n"
        "Predictions are estimates, not guaranteed results."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


# ---------------- RUN BOT ----------------

def main():
    if not BOT_TOKEN:
        raise ValueError("Telegram bot token is missing.")

    if not FOOTBALL_API_KEY:
        raise ValueError("Football API key is missing.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("live", live))
    app.add_handler(CommandHandler("upcoming", upcoming))
    app.add_handler(CommandHandler("predict", predict))

    logging.info("Favour Goal Predictor is running.")

    app.run_polling()


if __name__ == "__main__":
    main()

    

