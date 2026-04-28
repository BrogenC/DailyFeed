import sqlite3
import os
import requests
import smtplib
from datetime import datetime
import random
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo


import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf

pd.set_option("display.max_columns", None)
pd.set_option("display.max_rows", None)

tickers = ["GC=F", "NVDA", "ORCL"]
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "PUT_YOUR_NEWS_API_KEY_HERE")
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "PUT_YOUR_EMAIL_HERE")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "PUT_YOUR_APP_PASSWORD_HERE")
DAILY_FEED_ICON_URL = os.getenv("DAILY_FEED_ICON_URL", "")
SEND_EMAIL = os.getenv("SEND_EMAIL", "false").lower() == "true"
SHOW_GRAPHS = os.getenv("SHOW_GRAPHS", "false").lower() == "true"
REPORTS_DIR = Path("report_assets")
SUBSCRIBERS_FILE = Path("subscribers.txt")

if not DAILY_FEED_ICON_URL:
    DAILY_FEED_ICON_URL = "https://raw.githubusercontent.com/BrogenC/DailyFeed/main/DailyFeedIcon.png"


def download_prices(ticker, period, interval):
    df = yf.download(ticker, period=period, interval=interval)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
    df["Ticker"] = ticker
    return df


def apply_daily_feed_theme():
    plt.rcParams.update({
        "figure.facecolor": "#3b3937",
        "axes.facecolor": "#3b3937",
        "text.color": "#ffffff",
        "axes.labelcolor": "#ffffff",
        "xtick.color": "#bbbbbb",
        "ytick.color": "#bbbbbb",
        "grid.color": "#555555",
        "grid.linestyle": "--",
        "grid.alpha": 0.3,
        "axes.edgecolor": "#555555",
        "axes.titleweight": "bold",
        "axes.titlesize": 14,
        "lines.linewidth": 2.5,
        "font.family": "sans-serif",
    })


def download_intraday_prices(ticker, period="1d", interval="15m"):
    df = yf.download(ticker, period=period, interval=interval, prepost=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    datetime_column = "Datetime" if "Datetime" in df.columns else "Date"
    df = df[[datetime_column, "Open", "High", "Low", "Close", "Volume"]]
    df = df.rename(columns={datetime_column: "Timestamp"})
    df["Ticker"] = ticker
    return df


def filter_past_week(df):
    eastern = ZoneInfo("America/New_York")
    timestamps = pd.to_datetime(df["Timestamp"])
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(eastern)
    else:
        timestamps = timestamps.dt.tz_convert(eastern)

    filtered_df = df.copy()
    filtered_df["Timestamp"] = timestamps
    return filtered_df.sort_values("Timestamp")


def filter_today_market_hours(df):
    eastern = ZoneInfo("America/New_York")
    now_eastern = datetime.now(eastern)
    market_open = pd.Timestamp(
        year=now_eastern.year,
        month=now_eastern.month,
        day=now_eastern.day,
        hour=9,
        minute=30,
        tz=eastern,
    )
    current_time = pd.Timestamp(now_eastern)

    timestamps = pd.to_datetime(df["Timestamp"])
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(eastern)
    else:
        timestamps = timestamps.dt.tz_convert(eastern)

    filtered_df = df.copy()
    filtered_df["Timestamp"] = timestamps
    filtered_df = filtered_df[
        (filtered_df["Timestamp"] >= market_open)
        & (filtered_df["Timestamp"] <= current_time)
    ]
    return filtered_df


def initialize_tables(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_title TEXT NOT NULL,
            article_title TEXT NOT NULL,
            article_source TEXT,
            article_url TEXT,
            published_at TEXT,
            fetched_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS email_subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()


conn = sqlite3.connect("stocks.db")
initialize_tables(conn)

for i, ticker in enumerate(tickers):
    write_mode = "replace" if i == 0 else "append"

    daily_df = download_prices(ticker, period="ytd", interval="1d")
    weekly_df = download_prices(ticker, period="5d", interval="1d")
    weekly_15m_df = download_intraday_prices(ticker, period="5d", interval="15m")
    intraday_df = download_intraday_prices(ticker, period="1d", interval="15m")
    intraday_df = filter_today_market_hours(intraday_df)

    daily_df.to_sql("stock_prices_daily", conn, if_exists=write_mode, index=False)
    weekly_df.to_sql("stock_prices_weekly", conn, if_exists=write_mode, index=False)
    weekly_15m_df.to_sql("stock_prices_weekly_15m", conn, if_exists=write_mode, index=False)
    intraday_df.to_sql("stock_prices_intraday_15m", conn, if_exists=write_mode, index=False)

daily_query = """
SELECT Date, Ticker, Open, High, Low, Close, Volume
FROM stock_prices_daily
WHERE Volume > 1000000
ORDER BY Ticker, Date
"""

weekly_query = """
SELECT Date, Ticker, Open, High, Low, Close, Volume
FROM stock_prices_weekly
ORDER BY Ticker, Date
"""

intraday_query = """
SELECT Timestamp, Ticker, Open, High, Low, Close, Volume
FROM stock_prices_intraday_15m
ORDER BY Ticker, Timestamp
"""

daily_result = pd.read_sql_query(daily_query, conn)
weekly_result = pd.read_sql_query(weekly_query, conn)
intraday_result = pd.read_sql_query(intraday_query, conn)

print("Daily data:")
print(daily_result.head())

print("\nPast-week daily data:")
print(weekly_result.head())

print("\nIntraday 15-minute data:")
print(intraday_result.head())


def build_graphs(ticker_symbol):
    daily_plot_df = pd.read_sql_query(
        """
        SELECT Date, Close
        FROM stock_prices_daily
        WHERE Ticker = ?
        ORDER BY Date
        """,
        conn,
        params=(ticker_symbol,),
        parse_dates=["Date"],
    )

    weekly_plot_df = pd.read_sql_query(
        """
        SELECT Date, Close
        FROM stock_prices_weekly
        WHERE Ticker = ?
        ORDER BY Date
        """,
        conn,
        params=(ticker_symbol,),
        parse_dates=["Date"],
    )

    intraday_plot_df = pd.read_sql_query(
        """
        SELECT Timestamp, Close
        FROM stock_prices_intraday_15m
        WHERE Ticker = ?
        ORDER BY Timestamp
        """,
        conn,
        params=(ticker_symbol,),
        parse_dates=["Timestamp"],
    )

    plt.figure(figsize=(10, 5))
    plt.plot(daily_plot_df["Date"], daily_plot_df["Close"], label=f"{ticker_symbol} Daily Close")
    plt.title(f"{ticker_symbol} Daily Closing Price (YTD)")
    plt.xlabel("Date")
    plt.ylabel("Close")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.legend()
    plt.show()

    plt.figure(figsize=(10, 5))
    plt.plot(
        weekly_plot_df["Date"],
        weekly_plot_df["Close"],
        color="orange",
        marker="o",
        label=f"{ticker_symbol} Daily Close (Past Week)",
    )
    plt.title(f"{ticker_symbol} Daily Closing Price Over the Past Week")
    plt.xlabel("Date")
    plt.ylabel("Close")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.legend()
    plt.show()

    plt.figure(figsize=(10, 5))
    plt.plot(
        intraday_plot_df["Timestamp"],
        intraday_plot_df["Close"],
        color="green",
        label=f"{ticker_symbol} 15-Minute Price",
    )
    plt.title(f"{ticker_symbol} Current-Day Price Every 15 Minutes")
    plt.xlabel("Time")
    plt.ylabel("Price")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.legend()
    plt.show()

def fetch_news(category=None, sources=None, query=None, country="us", page_size=5):
    api_key = NEWS_API_KEY
    if not api_key or api_key == "PUT_YOUR_NEWS_API_KEY_HERE":
        raise ValueError("NEWS_API_KEY is not set.")

    url = "https://newsapi.org/v2/top-headlines"
    params = {
        "apiKey": api_key,
        "pageSize": page_size,
    }

    if sources:
        params["sources"] = sources
    else:
        params["country"] = country
        if category:
            params["category"] = category
        if query:
            params["q"] = query

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "ok":
        raise ValueError(data.get("message", "News API request failed."))

    return data["articles"]


def print_articles(section_title, articles):
    print(f"\n{section_title}")
    print("-" * len(section_title))
    for article in articles:
        print(f"- {article['title']}")


def fetch_daily_news_sections():
    return {
        "Top News": fetch_news(),
        "Tech News": fetch_news(sources="techcrunch"),
        "Sports News": fetch_news(category="sports"),
    }


def store_news_sections(connection, news_sections):
    fetched_at = datetime.now(ZoneInfo("America/New_York")).isoformat()
    connection.execute("DELETE FROM news_articles")

    for section_title, articles in news_sections.items():
        for article in articles:
            source_name = None
            if article.get("source"):
                source_name = article["source"].get("name")

            connection.execute(
                """
                INSERT INTO news_articles (
                    section_title,
                    article_title,
                    article_source,
                    article_url,
                    published_at,
                    fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    section_title,
                    article.get("title"),
                    source_name,
                    article.get("url"),
                    article.get("publishedAt"),
                    fetched_at,
                ),
            )

    connection.commit()



#Subscribers

def add_subscriber(connection, email):
    connection.execute(
        """
        INSERT OR IGNORE INTO email_subscribers (email, created_at)
        VALUES (?, ?)
        """,
        (email, datetime.now(ZoneInfo("America/New_York")).isoformat()),
    )
    connection.commit()




def drop_subscriber(connection, email):
    connection.execute(
        """
        DELETE FROM email_subscribers
        WHERE email = ?
        """,
        (email,),
    )
    connection.commit()


def sync_subscribers_from_file(connection, subscribers_file=SUBSCRIBERS_FILE):
    connection.execute("DELETE FROM email_subscribers")

    if not subscribers_file.exists():
        connection.commit()
        return

    with subscribers_file.open("r", encoding="utf-8") as file_handle:
        for line in file_handle:
            email = line.strip()
            if not email or email.startswith("#"):
                continue

            connection.execute(
                """
                INSERT OR IGNORE INTO email_subscribers (email, created_at)
                VALUES (?, ?)
                """,
                (email, datetime.now(ZoneInfo("America/New_York")).isoformat()),
            )

    connection.commit()


def get_active_subscribers(connection):
    cursor = connection.execute(
        """
        SELECT email
        FROM email_subscribers
        WHERE is_active = 1
        ORDER BY email
        """
    )
    return [row[0] for row in cursor.fetchall()]


sync_subscribers_from_file(conn)






def get_stored_news(connection):
    return pd.read_sql_query(
        """
        SELECT section_title, article_title, article_source, article_url, published_at, fetched_at
        FROM news_articles
        ORDER BY section_title, published_at DESC, id
        """,
        connection,
    )


def score_article(article):
    score = 0
    published_at = article.get("publishedAt")
    if published_at:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        age_hours = (datetime.now(ZoneInfo("UTC")) - published).total_seconds() / 3600
        if age_hours < 2:
            score += 5
        elif age_hours < 6:
            score += 3
        elif age_hours < 12:
            score += 1

    title = article.get("title", "")
    if len(title) < 80:
        score += 1
    if article.get("description"):
        score += 1

    keywords = ["ai", "war", "election", "market", "economy", "fed", "stocks"]
    for word in keywords:
        if word in title.lower():
            score += 2

    trusted_sources = ["Reuters", "BBC News", "The New York Times", "Associated Press"]
    source_name = article.get("source", {}).get("name", "")
    if source_name in trusted_sources:
        score += 2

    return score


def pick_top_story(articles):
    seen_titles = set()
    unique_articles = []
    for article in articles:
        title = article.get("title", "").strip()
        key = title[:50].lower()
        if title and key not in seen_titles:
            seen_titles.add(key)
            unique_articles.append(article)

    if not unique_articles:
        return None, []

    top_story = max(unique_articles, key=score_article)
    remaining_articles = [article for article in unique_articles if article != top_story]
    return top_story, remaining_articles


def get_ticker_display_name(ticker_symbol):
    names = {
        "NVDA": "NVIDIA",
        "GC=F": "Gold Futures",
    }
    return names.get(ticker_symbol, ticker_symbol)


def generate_chart_image(connection, ticker_symbol, output_path):
    chart_df = pd.read_sql_query(
        """
        SELECT Timestamp, Close
        FROM stock_prices_weekly_15m
        WHERE Ticker = ?
        ORDER BY Timestamp
        """,
        connection,
        params=(ticker_symbol,),
        parse_dates=["Timestamp"],
    )

    if chart_df.empty:
        return None

    apply_daily_feed_theme()
    fig, ax = plt.subplots(figsize=(8, 4))
    fig.patch.set_alpha(0)
    ax.patch.set_alpha(0)

    min_close = chart_df["Close"].min()
    max_close = chart_df["Close"].max()
    price_range = max_close - min_close
    padding = max(price_range * 0.15, max_close * 0.005)
    lower_bound = min_close - padding
    upper_bound = max_close + padding

    ax.plot(chart_df["Timestamp"], chart_df["Close"], color="#ff7d26")
    ax.fill_between(
        chart_df["Timestamp"],
        chart_df["Close"],
        lower_bound,
        color="#ff7d26",
        alpha=0.15,
    )
    ax.set_title(f"{get_ticker_display_name(ticker_symbol)} Price Over the Past Week")
    ax.set_xlabel("Time")
    ax.set_ylabel("Close")
    ax.set_ylim(lower_bound, upper_bound)
    ax.grid(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight", transparent=True)
    plt.close()
    return output_path


def prepare_email_chart_images(connection):
    REPORTS_DIR.mkdir(exist_ok=True)
    chart_specs = {
        "chart_nvda": ("NVDA", REPORTS_DIR / "nvda_ytd.png"),
        "chart_gold": ("GC=F", REPORTS_DIR / "gold_ytd.png"),
    }

    generated = {}
    for content_id, (ticker_symbol, output_path) in chart_specs.items():
        image_path = generate_chart_image(connection, ticker_symbol, output_path)
        if image_path:
            generated[content_id] = image_path

    return generated


def build_news_email_body(connection):
    stored_news_df = get_stored_news(connection)
    if stored_news_df.empty:
        return "No news articles were stored for today."

    lines = ["Today's news summary", ""]
    current_section = None

    for row in stored_news_df.itertuples(index=False):
        if row.section_title != current_section:
            current_section = row.section_title
            lines.append(current_section)
            lines.append("-" * len(current_section))

        source_text = f" ({row.article_source})" if row.article_source else ""
        lines.append(f"- {row.article_title}{source_text}")
        if row.article_url:
            lines.append(f"  {row.article_url}")

    return "\n".join(lines)


def build_html_email(connection, chart_cids):
    stored_news_df = get_stored_news(connection)
    generated_at = datetime.now(ZoneInfo("America/New_York")).strftime("%B %d, %Y %I:%M %p ET")


    dailyHeader = [
        "What matters today.",
        "Your fresh daily feed is served.",
        "Get informed in 5 minutes.",
        "Everything you need, nothing you don’t.",
        "Goes down quicker than your third coffee.",
        "If knowledge is power, be a tyrant.",
        "Compiling your daily reality.",
        "The internet wants you to know this.",
        "It's the news, but readable.",
        "Your boss wants you informed.",
        "Short enough for your attention span.",
        "No cat memes included.",
        "The internet (mostly) behaved today.",
        "How many times did you hit snooze today?",
        "I see you out there procrastinating.",
        "You again?",
        "Be smarter than everyone else.",
        "At least act like you learn something.",
        "Sit down and read.",
        "Since you forgot everything from yesterday.",
        "I'm in charge now."

    ]

    dailyFooter = [
        "You’re all caught up.",
        "We're already preparing your next feed.",
        "That’s your Daily Feed.",
        "See you tomorrow.",
        "That's enough info for one day.",
        "You're now dangerously informed.",
        "Now you know about your Matrix.",
        "Now slightly more informed.",
        "That wasn't so bad.",
        "Now get back to work.",
        "Good job, you actually read the news.",
        "I told you. We don't source cat memes.",
        "Let's see if anything happens tomorrow.",
        "Don't sleep in again.",
        "More work awaits.",
        "Come back, or else.",
        "That's all the knowledge you can handle for now.",
        "Don't get any ideas.",
        "You may go now.",
        "Try and remember today, ok?",
        "You're welcome"

    ]

    index = random.randrange(len(dailyHeader))

    selected_header = dailyHeader[index]
    selected_footer = dailyFooter[index]

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    news_sections_html = []
    if stored_news_df.empty:
        news_sections_html.append(
            """
            <div class="section-card">
              <h2>News</h2>
              <div class="story-card">No news articles were stored for this run.</div>
            </div>
            """
        )
    else:
        for section_title, section_df in stored_news_df.groupby("section_title", sort=False):
            stories_html = []
            for row in section_df.itertuples(index=False):
                source_html = f"<div class='story-source'>{row.article_source or 'Unknown source'}</div>"
                link_html = ""
                if row.article_url:
                    link_html = f"<a class='story-link' href='{row.article_url}'>Read more</a>"
                stories_html.append(
                    f"""
                    <div class="story-card">
                      <div class="story-title">{row.article_title}</div>
                      {source_html}
                      {link_html}
                    </div>
                    """
                )
            news_sections_html.append(
                f"""
                <div class="section-card">
                  <h2>{section_title}</h2>
                  {''.join(stories_html)}
                </div>
                """
            )

    chart_blocks = []
    if "chart_nvda" in chart_cids:
        chart_blocks.append(
            """
            <div class="chart-card">
              <h3>NVIDIA</h3>
              <img src="cid:chart_nvda" alt="NVIDIA stock chart" />
            </div>
            """
        )
    if "chart_gold" in chart_cids:
        chart_blocks.append(
            """
            <div class="chart-card">
              <h3>Gold Futures</h3>
              <img src="cid:chart_gold" alt="Gold futures chart" />
            </div>
            """
        )

    return f"""
    <html>
      <head>
        <style>
          body {{
            margin: 0;
            padding: 0;
            background-color: #302f2d;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          }}

          .container {{
            max-width: 880px;
            margin: 0 auto;
            padding: 20px;
          }}

          /* HERO */
          .hero {{
            background: linear-gradient(135deg, #ff5a00, #ff7d26);
            border-radius: 18px;
            padding: 20px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.5);
          }}

          /* HEADER ROW WITH ICON */
          .hero-top {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 6px;
          }}

          .icon {{
            width: 42px;
            height: 42px;
            border-radius: 10px;
            object-fit: cover;
            box-shadow: 0 8px 20px rgba(0,0,0,0.3);
          }}

          .title {{
            font-size: 26px;
            font-weight: 700;
            margin: 0;
          }}

          .date {{
            font-size: 13px;
            opacity: 0.85;
            margin-top: 4px;
          }}

          /* HEADER BAR */
          .header-bar {{
            margin-top: 14px;
            padding: 10px 12px;
            background: #3b3937;
            border: 1px solid rgba(255,125,38,0.15);
            border-radius: 10px;
            font-size: 14px;
            color: #ff9a4d;
          }}

          /* CHART GRID */
          .chart-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px;
            margin: 20px 0;
          }}

          .chart-card {{
            background: #3b3937;
            border-radius: 14px;
            padding: 16px;
            border: 1px solid rgba(255,125,38,0.15);
          }}

          .chart-card h3 {{
            margin-top: 0;
            color: #ff7d26;
          }}

          .chart-card img {{
            width: 100%;
            border-radius: 10px;
          }}

          /* SECTION CARDS */
          .section-card {{
            background: #3b3937;
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 16px;
            border: 1px solid rgba(255,125,38,0.15);
          }}

          .section-title {{
            font-size: 18px;
            font-weight: 600;
            color: #ff7d26;
            margin-bottom: 10px;
          }}

          .story-card {{
            padding: 10px 0;
            border-top: 1px solid rgba(255,255,255,0.08);
          }}

          .story-card:first-child {{
            border-top: none;
          }}

          .story-title {{
            font-size: 16px;
            font-weight: 600;
            color: #ff9a4d;
          }}

          .story-source {{
            font-size: 13px;
            opacity: 0.6;
            margin-bottom: 4px;
          }}

          .story-link {{
            color: #ff7d26;
            text-decoration: none;
            font-weight: 500;
          }}

          /* FOOTER */
          .footer {{
            margin-top: 25px;
            background: linear-gradient(90deg, #ff5a00, #ff7d26);
            padding: 16px 14px;
            text-align: center;
            font-size: 15px;
            font-weight: 600;
            color: #ffffff;
            border-radius: 10px;
            box-shadow: 0 10px 30px rgba(255,90,0,0.25);
          }}

        </style>
      </head>

      <body>
        <div class="container">

          <!-- HERO -->
          <div class="hero">

            <div class="hero-top">
              <!-- <img class="icon" src="DailyFeedIcon.png" alt="Daily Feed Icon"> -->
              <h1 class="title">Daily Feed</h1>
            </div>

            <div class="date">Generated {generated_at}</div>

            <div class="header-bar">
              {selected_header}
            </div>

          </div>

          <!-- CHARTS -->
          <div class="chart-grid">
            {''.join(chart_blocks)}
          </div>

          <!-- NEWS -->
          <div class="section-card">
            <div class="section-title">📰 Top News</div>
            {news_sections_html[2] if len(news_sections_html) > 0 else ""}
          </div>

          <div class="section-card">
            <div class="section-title">💻 Tech</div>
            {news_sections_html[1] if len(news_sections_html) > 1 else ""}
          </div>

          <div class="section-card">
            <div class="section-title">🏀 Sports</div>
            {news_sections_html[0] if len(news_sections_html) > 2 else ""}
          </div>

          <!-- FOOTER -->
          <div class="footer">
            {selected_footer}
          </div>

        </div>
      </body>
    </html>
    """


def build_html_email_v2(connection, chart_cids):
    stored_news_df = get_stored_news(connection)
    daily_header = [
        "What matters today.",
        "Your fresh daily feed is served.",
        "Get informed in 5 minutes.",
        "Everything you need, nothing you don't.",
        "Goes down quicker than your third coffee.",
        "If knowledge is power, be a tyrant.",
        "Compiling your daily reality.",
        "The internet wants you to know this.",
        "It's the news, but readable.",
        "Your boss wants you informed.",
        "Short enough for your attention span.",
        "No cat memes included.",
        "The internet (mostly) behaved today.",
        "How many times did you hit snooze today?",
        "I see you out there procrastinating.",
        "You again?",
        "Be smarter than everyone else.",
        "At least act like you learn something.",
        "Sit down and read.",
        "Since you forgot everything from yesterday.",
        "I'm in charge now."
    ]
    daily_footer = [
        "You're all caught up.",
        "We're already preparing your next feed.",
        "That's your Daily Feed.",
        "See you tomorrow.",
        "That's enough info for one day.",
        "You're now dangerously informed.",
        "Now you know about your Matrix.",
        "Now slightly more informed.",
        "That wasn't so bad.",
        "Now get back to work.",
        "Good job, you actually read the news.",
        "I told you. We don't source cat memes.",
        "Let's see if anything happens tomorrow.",
        "Don't sleep in again.",
        "More work awaits.",
        "Come back, or else.",
        "That's all the knowledge you can handle for now.",
        "Don't get any ideas.",
        "You may go now.",
        "Try and remember today, ok?",
        "You're welcome"
    ]

    index = random.randrange(len(daily_header))
    selected_header = daily_header[index]
    selected_footer = daily_footer[index]
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    icon_html = ""
    if DAILY_FEED_ICON_URL:
        icon_html = f'<img class="icon" src="{DAILY_FEED_ICON_URL}" alt="Daily Feed Icon" />'

    sections_map = {"Top News": "", "Tech News": "", "Sports News": ""}
    featured_story_html = ""

    if stored_news_df.empty:
        sections_map["Top News"] = '<div class="story-card">No news articles were stored for this run.</div>'
    else:
        top_news_df = stored_news_df[stored_news_df["section_title"] == "Top News"]
        top_articles = [
            {
                "title": row.article_title,
                "description": row.article_source or "Unknown source",
                "url": row.article_url,
                "publishedAt": row.published_at,
                "source": {"name": row.article_source or ""},
            }
            for row in top_news_df.itertuples(index=False)
        ]
        featured_story, remaining_top_articles = pick_top_story(top_articles)

        if featured_story:
            featured_link = ""
            if featured_story.get("url"):
                featured_link = f"<a class='featured-link' href='{featured_story['url']}'>Read more</a>"
            featured_source = featured_story.get("source", {}).get("name", "Top headlines")
            featured_story_html = f"""
            <div class="featured-story-card">
              <div class="featured-label">Top Story</div>
              <div class="featured-title">{featured_story['title']}</div>
              <div class="featured-summary">{featured_story.get('description') or "Featured from today's top headlines."}</div>
              <div class="featured-meta-bar">
                <div class="featured-meta-source">{featured_source}</div>
                {featured_link}
              </div>
            </div>
            """

        for section_title in ["Top News", "Tech News", "Sports News"]:
            section_df = stored_news_df[stored_news_df["section_title"] == section_title]
            if section_title == "Top News" and featured_story:
                rows_to_render = remaining_top_articles
            else:
                rows_to_render = [
                    {
                        "title": row.article_title,
                        "source": row.article_source or "Unknown source",
                        "url": row.article_url,
                    }
                    for row in section_df.itertuples(index=False)
                ]

            stories_html = []
            for row in rows_to_render:
                link_html = ""
                if row.get("url"):
                    link_html = f"<a class='story-link' href='{row['url']}'>Read more</a>"
                stories_html.append(
                    f"""
                    <div class="story-card">
                      <div class="story-title">{row['title']}</div>
                      <div class="story-source">{row['source']}</div>
                      {link_html}
                    </div>
                    """
                )
            sections_map[section_title] = "".join(stories_html) or '<div class="story-card">No stories available.</div>'

    chart_blocks = []
    if "chart_nvda" in chart_cids:
        chart_blocks.append(
            """
            <div class="chart-card">
              <h3>NVIDIA</h3>
              <img src="cid:chart_nvda" alt="NVIDIA stock chart" />
            </div>
            """
        )
    if "chart_gold" in chart_cids:
        chart_blocks.append(
            """
            <div class="chart-card">
              <h3>Gold Futures</h3>
              <img src="cid:chart_gold" alt="Gold futures chart" />
            </div>
            """
        )

    return f"""
    <html>
      <head>
        <style>
          body {{
            margin: 0;
            padding: 0;
            background-color: #302f2d;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          }}
          .container {{
            max-width: 880px;
            margin: 0 auto;
            padding: 20px;
          }}
          .hero {{
            background: linear-gradient(135deg, #ff5a00, #ff7d26);
            border-radius: 18px;
            padding: 20px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.5);
          }}
          .hero-top {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 6px;
          }}
          .icon {{
            width: 42px;
            height: 42px;
            border-radius: 10px;
            object-fit: cover;
            box-shadow: 0 8px 20px rgba(0,0,0,0.3);
          }}
          .title {{
            font-size: 26px;
            font-weight: 700;
            margin: 0;
          }}
          .date {{
            font-size: 13px;
            opacity: 0.85;
            margin-top: 4px;
          }}
          .header-bar {{
            margin-top: 14px;
            padding: 10px 12px;
            background: #3b3937;
            border: 1px solid rgba(255,125,38,0.15);
            border-radius: 10px;
            font-size: 14px;
            color: #ff9a4d;
          }}
          .chart-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px;
            margin: 20px 0;
          }}
          .chart-card {{
            background: #3b3937;
            border-radius: 14px;
            padding: 16px;
            border: 1px solid rgba(255,125,38,0.15);
          }}
          .chart-card h3 {{
            margin-top: 0;
            color: #ff7d26;
          }}
          .chart-card img {{
            width: 100%;
            border-radius: 10px;
          }}
          .featured-story-card {{
            background: linear-gradient(135deg, rgba(255,90,0,0.38), rgba(255,125,38,0.18));
            border: 1px solid rgba(255,125,38,0.28);
            border-radius: 16px;
            padding: 18px;
            margin: 18px 0 20px 0;
          }}
          .featured-label {{
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 12px;
            color: #ffb27a;
            margin-bottom: 8px;
            font-weight: 700;
          }}
          .featured-title {{
            font-size: 24px;
            font-weight: 700;
            color: #fff4ec;
            margin-bottom: 10px;
            line-height: 1.3;
          }}
          .featured-summary {{
            color: #ffe1cf;
            font-size: 15px;
            line-height: 1.5;
            margin-bottom: 10px;
          }}
          .featured-link {{
            color: #ffffff;
            text-decoration: none;
            font-weight: 600;
          }}
          .featured-meta-bar {{
            margin-top: 14px;
            background: #3b3937;
            border: 1px solid rgba(255,125,38,0.15);
            border-radius: 12px;
            padding: 12px 14px;
          }}
          .featured-meta-source {{
            color: #d7d7d7;
            font-size: 13px;
            margin-bottom: 6px;
          }}
          .section-card {{
            background: #3b3937;
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 16px;
            border: 1px solid rgba(255,125,38,0.15);
          }}
          .section-title {{
            font-size: 18px;
            font-weight: 600;
            color: #ff7d26;
            margin-bottom: 10px;
          }}
          .story-card {{
            padding: 10px 0;
            border-top: 1px solid rgba(255,255,255,0.08);
          }}
          .story-card:first-child {{
            border-top: none;
          }}
          .story-title {{
            font-size: 16px;
            font-weight: 600;
            color: #ff9a4d;
          }}
          .story-source {{
            font-size: 13px;
            opacity: 0.6;
            margin-bottom: 4px;
          }}
          .story-link {{
            color: #ff7d26;
            text-decoration: none;
            font-weight: 500;
          }}
          .end-divider {{
            height: 2px;
            background: linear-gradient(90deg, transparent, #ff7d26, transparent);
            margin: 30px 0 15px 0;
            opacity: 0.7;
          }}
          .footer-full {{
            width: 100%;
            max-width: 100%;
            box-sizing: border-box;
            background: linear-gradient(90deg, #ff5a00, #ff7d26);
            padding: 18px;
            text-align: center;
            font-size: 16px;
            font-weight: 700;
            color: #ffffff;
            margin-top: 30px;
            overflow: hidden;
          }}
        </style>
      </head>
      <body>
        <div class="container">
          <div class="hero">
            <div class="hero-top">
              {icon_html}
              <h1 class="title">Daily Feed</h1>
            </div>
            <div class="date">Generated {generated_at}</div>
            <div class="header-bar">{selected_header}</div>
          </div>
          <div class="chart-grid">
            {''.join(chart_blocks)}
          </div>
          {featured_story_html}
          <div class="section-card">
            <div class="section-title">Top News</div>
            {sections_map["Top News"]}
          </div>
          <div class="section-card">
            <div class="section-title">Tech</div>
            {sections_map["Tech News"]}
          </div>
          <div class="section-card">
            <div class="section-title">Sports</div>
            {sections_map["Sports News"]}
          </div>
        </div>
        <div class="end-divider"></div>
        <div class="footer-full">{selected_footer}</div>
      </body>
    </html>
    """


def send_email_to_subscribers(connection, subject, text_body, html_body, chart_paths):
    sender = EMAIL_SENDER
    app_password = EMAIL_APP_PASSWORD
    recipients = get_active_subscribers(connection)

    if (
        not sender
        or not app_password
        or sender == "PUT_YOUR_EMAIL_HERE"
        or app_password == "PUT_YOUR_APP_PASSWORD_HERE"
    ):
        raise ValueError("EMAIL_SENDER or EMAIL_APP_PASSWORD is not set.")

    if not recipients:
        print("No active subscribers found.")
        return

    last_error = None
    smtp_modes = [
        ("ssl", "smtp.gmail.com", 465),
        ("starttls", "smtp.gmail.com", 587),
    ]

    for mode, host, port in smtp_modes:
        try:
            if mode == "ssl":
                server = smtplib.SMTP_SSL(host, port, timeout=20)
            else:
                server = smtplib.SMTP(host, port, timeout=20)

            with server:
                if mode == "starttls":
                    server.starttls()

                server.login(sender, app_password)

                for email_address in recipients:
                    msg = EmailMessage()
                    msg.set_content(text_body)
                    msg.add_alternative(html_body, subtype="html")
                    html_part = msg.get_payload()[-1]

                    for content_id, image_path in chart_paths.items():
                        with open(image_path, "rb") as image_file:
                            html_part.add_related(
                                image_file.read(),
                                maintype="image",
                                subtype="png",
                                cid=f"<{content_id}>",
                            )

                    msg["Subject"] = subject
                    msg["From"] = sender
                    msg["To"] = email_address
                    server.send_message(msg)
                    print(f"Sent to: {email_address}")

                return
        except Exception as error:
            last_error = error

    raise RuntimeError(f"Failed to send email via Gmail SMTP: {last_error}")



if SHOW_GRAPHS:
    build_graphs("NVDA")
    build_graphs("GC=F")



try:
    news_sections = fetch_daily_news_sections()
    store_news_sections(conn, news_sections)
    for section_title, articles in news_sections.items():
        print_articles(section_title, articles)
except Exception as error:
    print("News API error:", error)

print("\nStored news rows:")
print(get_stored_news(conn).head())


# Subscribers here.
add_subscriber(conn, "brogenc777@gmail.com")


print("\nActive subscribers:")
print(get_active_subscribers(conn))

# Uncomment this when EMAIL_SENDER and EMAIL_APP_PASSWORD are set in PyCharm.
text_email_body = build_news_email_body(conn)
chart_images = prepare_email_chart_images(conn)
html_email_body = build_html_email_v2(conn, chart_images)
if SEND_EMAIL:
    send_email_to_subscribers(conn, "Daily Feed", text_email_body, html_email_body, chart_images)
else:
    print("SEND_EMAIL is false; skipping email send.")


conn.close()
