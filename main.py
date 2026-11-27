
import os
import logging
import math
import requests

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

# =====================================
# FAVOUR GOAL PREDICTOR
# =====================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("API_NINJAS_KEY")

API_URL = "https://api.api-ninjas.com/v1/soccermatches"
NIGERIA_TZ = ZoneInfo("Africa/Lagos")

LEAGUES = [
    "epl",
    "laliga",
    "bundesliga",
    "seriea",
    "ligue1",
    "ucl",
    "uel"
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

session = requests.Session()
session.headers.update({"X-Api-Key": API_KEY or ""})

# =====================================
# API CONNECTION
# =====================================

def api_get(params):
    if not API_KEY:
        raise ValueError("API_NINJAS_KEY is missing.")

    response = session.get(
        API_URL,
        params=params,
        timeout=25
    )

    if response.status_code == 401:
        raise ValueError("Invalid API Ninjas key.")

    if response.status_code == 403:
        raise ValueError("API access denied. Check your API plan.")

    if response.status_code == 429:
        raise ValueError("API request limit reached. Try again later.")

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        raise ValueError("Unexpected football API response.")

    return data


def team_name(team):
    return team.get("name", "Unknown team")


def match_time(match):
    value = match.get("start_time")

    if not value:
        return "Time unavailable"

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        return dt.astimezone(NIGERIA_TZ).strftime(
            "%A, %d %B %Y - %I:%M %p WAT"
        )

    except Exception:
        return "Time unavailable"


def venue_name(match):
    venue = match.get("venue") or {}

    if not isinstance(venue, dict):
        return "Venue not provided"

    parts = [
        venue.get("name"),
        venue.get("city"),
        venue.get("country")
    ]

    result = ", ".join(str(x) for x in parts if x)

    return result or "Venue not provided"


def get_team_id(match, side):
    team = match.get(side) or {}
    return team.get("team_id")


# =====================================
# UPCOMING MATCHES
# =====================================

def get_upcoming_matches(days=7):
    found = {}

    today = datetime.now(timezone.utc).date()

    for league in LEAGUES:
        for offset in range(days + 1):

            match_date = today + timedelta(days=offset)

            try:
                matches = api_get({
                    "league": league,
                    "date": match_date.isoformat()
                })

                for match in matches:
                    if match.get("status") != "scheduled":
                        continue

                    game_id = match.get("game_id")

                    if game_id:
                        found[game_id] = match

            except Exception as error:
                logging.warning(
                    "Upcoming %s %s: %s",
                    league,
                    match_date,
                    error
                )

    result = list(found.values())

    result.sort(
        key=lambda x: x.get("start_time", "")
    )

    return result


# =====================================
# LIVE MATCH LIST
# =====================================

def get_live_matches():
    found = {}

    for league in LEAGUES:
        try:
            matches = api_get({"league": league})

            for match in matches:
                if match.get("status") == "in_progress":
                    game_id = match.get("game_id")

                    if game_id:
                        found[game_id] = match

        except Exception as error:
            logging.warning(
                "Live %s: %s",
                league,
                error
            )

    return list(found.values())


# =====================================
# RECENT TEAM RESULTS
# =====================================

def get_recent_results(team_id):
    matches = api_get({"team": team_id})

    finished = []

    for match in matches:
        if match.get("status") != "final":
            continue

        if match.get("home_score") is None:
            continue

        if match.get("away_score") is None:
            continue

        finished.append(match)

    finished.sort(
        key=lambda x: x.get("start_time", ""),
        reverse=True
    )

    return finished[:10]


def team_goal_averages(matches, team_id):
    scored = []
    conceded = []

    for match in matches:
        home_id = get_team_id(match, "home_team")

        if home_id == team_id:
            scored.append(match["home_score"])
            conceded.append(match["away_score"])
        else:
            scored.append(match["away_score"])
            conceded.append(match["home_score"])

    if not scored:
        raise ValueError("No recent team results.")

    return (
        sum(scored) / len(scored),
        sum(conceded) / len(conceded)
    )


# =====================================
# POISSON GOAL MODEL
# =====================================

def poisson(mean, goals):
    return (
        math.exp(-mean)
        * mean ** goals
        / math.factorial(goals)
    )


def calculate_markets(home_mean, away_mean):
    home_win = 0
    draw = 0
    away_win = 0

    over = {
        0.5: 0,
        1.5: 0,
        2.5: 0,
        3.5: 0,
        4.5: 0
    }

    btts_yes = 0

    for home_goals in range(10):
        for away_goals in range(10):

            probability = (
                poisson(home_mean, home_goals)
                * poisson(away_mean, away_goals)
            )

            if home_goals > away_goals:
                home_win += probability
            elif home_goals == away_goals:
                draw += probability
            else:
                away_win += probability

            total_goals = home_goals + away_goals

            for line in over:
                if total_goals > line:
                    over[line] += probability

            if home_goals > 0 and away_goals > 0:
                btts_yes += probability

    markets = {
        "Home Win": home_win,
        "Draw": draw,
        "Away Win": away_win,
        "1X": home_win + draw,
        "X2": draw + away_win,
        "12": home_win + away_win,
        "BTTS Yes": btts_yes,
        "BTTS No": 1 - btts_yes
    }

    for line, probability in over.items():
        markets[f"Over {line}"] = probability
        markets[f"Under {line}"] = 1 - probability

    return markets


# =====================================
# MATCH ANALYSIS
# =====================================


def analyse_match(match):
    home = match.get("home_team") or {}
    away = match.get("away_team") or {}

    home_id = home.get("team_id")
    away_id = away.get("team_id")

    if not home_id or not away_id:
        return "NO SAFE PREDICTION: Missing team information."

    home_games = [
        game for game in get_recent_results(home_id)
        if get_team_id(game, "home_team") == home_id
    ]

    away_games = [
        game for game in get_recent_results(away_id)
        if get_team_id(game, "away_team") == away_id
    ]

    if len(home_games) < 3 or len(away_games) < 3:
        return "NO SAFE PREDICTION: Insufficient recent results."


    home_scored, home_conceded = team_goal_averages(
        home_games, home_id
    )

    away_scored, away_conceded = team_goal_averages(
        away_games, away_id
    )

    home_mean = max(
        0.15,
        (home_scored + away_conceded) / 2
    )

    away_mean = max(
        0.15,
        (away_scored + home_conceded) / 2
    )

    markets = calculate_markets(
        home_mean,
        away_mean
    )

    outcomes = {
        "Home Win": markets["Home Win"],
        "Draw": markets["Draw"],
        "Away Win": markets["Away Win"]
    }

    ranked = sorted(
        outcomes.items(),
        key=lambda item: item[1],
        reverse=True
    )

    best_name, best_probability = ranked[0]

    margin = best_probability - ranked[1][1]

    lines = [
        "⚽ FAVOUR GOAL PREDICTOR",
        "",
        f"{team_name(home)} vs {team_name(away)}",
        "",
        "📅 " + match_time(match),
        "🏟️ " + venue_name(match),
        f"🏆 Competition: {match.get('league', 'Unknown').upper()}",
        "",
        "📊 MATCH OUTCOME",
        f"Home Win: {markets['Home Win']:.1%}",
        f"Draw: {markets['Draw']:.1%}",
        f"Away Win: {markets['Away Win']:.1%}",
        "",
        "🔀 DOUBLE CHANCE",
        f"1X: {markets['1X']:.1%}",
        f"X2: {markets['X2']:.1%}",
        f"12: {markets['12']:.1%}",
        "",
        "⚽ OVER / UNDER GOALS"
    ]

    for line in [0.5, 1.5, 2.5, 3.5, 4.5]:
        lines.append(
            f"Over {line}: {markets[f'Over {line}']:.1%}"
        )
        lines.append(
            f"Under {line}: {markets[f'Under {line}']:.1%}"
        )

    lines.extend([
        "",
        "🥅 BOTH TEAMS TO SCORE",
        f"BTTS Yes: {markets['BTTS Yes']:.1%}",
        f"BTTS No: {markets['BTTS No']:.1%}",
        "",
        "📌 PREDICTION FILTER"
    ])

    if best_probability >= 0.60 and margin >= 0.12:
        lines.append(
            f"Statistical lean: {best_name}"
        )
    else:
        lines.append("🚫 NO SAFE PREDICTION")

    lines.extend([
        "",
        "Model: Recent-results Poisson estimate.",
        "Not a guarantee or a verified betting edge."
    ])

    return "\n".join(lines)


# =====================================
# TELEGRAM COMMANDS
# =====================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ Welcome to Favour Goal Predictor!\n\n"
        "Your football analysis assistant.\n\n"
        "/live - Live match listings\n"
        "/upcoming - Upcoming fixtures\n"
        "/predict - Match predictions\n"
        "/help - Commands\n\n"
        "Predictions are estimates, not guarantees."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ FAVOUR GOAL PREDICTOR\n\n"
        "/live - Matches in progress\n"
        "/upcoming - Fixtures, dates, times and venues\n"
        "/predict - Analyse upcoming matches\n"
        "/start - Start the bot\n\n"
        "All kickoff times are displayed in Nigeria time (WAT)."
    )


async def live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔴 Checking football matches..."
    )

    try:
        matches = get_live_matches()

        if not matches:
            await update.message.reply_text(
                "No matches currently reported as in progress."
            )
            return

        for match in matches[:10]:
            home = team_name(match.get("home_team") or {})
            away = team_name(match.get("away_team") or {})

            home_score = match.get("home_score")
            away_score = match.get("away_score")

            if home_score is None or away_score is None:
                score = "Live score unavailable on your API plan"
            else:
                score = f"{home_score} - {away_score}"

            await update.message.reply_text(
                f"🔴 {home} vs {away}\n"
                f"Score: {score}\n"
                f"Status: {match.get('status')}\n"
                f"🏟️ {venue_name(match)}\n"
                f"🕒 {match_time(match)}"
            )

    except Exception as error:
        logging.exception("Live command failed")
        await update.message.reply_text(
            f"Live service error: {error}"
        )


async def upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📅 Finding upcoming fixtures..."
    )

    try:
        matches = get_upcoming_matches()

        if not matches:
            await update.message.reply_text(
                "No upcoming fixtures were returned."
            )
            return

        for match in matches[:15]:
            home = team_name(match.get("home_team") or {})
            away = team_name(match.get("away_team") or {})

            await update.message.reply_text(
                f"⚽ {home} vs {away}\n"
                f"🏆 {match.get('league', 'Unknown').upper()}\n"
                f"📅 {match_time(match)}\n"
                f"🏟️ {venue_name(match)}"
            )

    except Exception as error:
        logging.exception("Upcoming command failed")
        await update.message.reply_text(
            f"Upcoming fixtures error: {error}"
        )


async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧠 Analysing upcoming matches...\n"
        "This may take a little time."
    )

    try:
        matches = get_upcoming_matches()

        if not matches:
            await update.message.reply_text(
                "No upcoming fixtures found."
            )
            return

        count = 0

        for match in matches[:5]:
            try:
                report = analyse_match(match)

                await update.message.reply_text(report)

                count += 1

            except Exception as error:
                logging.warning(
                    "Could not analyse match: %s",
                    error
                )

        if count == 0:
            await update.message.reply_text(
                "No predictions could be calculated. "
                "The API may not have enough completed results."
            )

    except Exception as error:
        logging.exception("Prediction command failed")
        await update.message.reply_text(
            f"Prediction service error: {error}"
        )


# =====================================
# START BOT
# =====================================

def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing.")

    if not API_KEY:
        raise ValueError("API_NINJAS_KEY is missing.")

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

