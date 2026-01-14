import os
import time
import asyncio
import requests
import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from telegram import Bot

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# ======================
# LOAD ENV
# ======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

VNEXPRESS_RSS = os.getenv("VNEXPRESS_RSS", "https://vnexpress.net/rss/tin-moi-nhat.rss")
TUOITRE_RSS = os.getenv("TUOITRE_RSS", "https://tuoitre.vn/rss/tin-moi-nhat.rss")
CAFEF_HOME = os.getenv("CAFEF_HOME", "https://cafef.vn/")
TOP_N = int(os.getenv("TOP_N", "5"))

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit("❌ Missing BOT_TOKEN or CHAT_ID")


# ======================
# BUILD NEWS CONTENT
# ======================
def get_rss_news(rss_url, source_name):
    feed = feedparser.parse(rss_url)
    items = []
    for entry in feed.entries[:TOP_N]:
        items.append(f"• <a href='{entry.link}'>{entry.title}</a>")
    if not items:
        return ""
    return f"🔸 <b>{source_name}</b>\n" + "\n".join(items)


def get_cafef_news():
    try:
        res = requests.get(CAFEF_HOME, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        links = soup.select("h3 a")[:TOP_N]
        items = []
        for a in links:
            title = a.get_text(strip=True)
            link = a.get("href")
            if link and link.startswith("/"):
                link = "https://cafef.vn" + link
            if title and link:
                items.append(f"• <a href='{link}'>{title}</a>")
        if not items:
            return ""
        return "🔸 <b>CafeF</b>\n" + "\n".join(items)
    except Exception as e:
        print("❌ CafeF error:", e)
        return ""


def build_daily_message():
    parts = []

    vnexpress = get_rss_news(VNEXPRESS_RSS, "VnExpress")
    if vnexpress:
        parts.append(vnexpress)

    tuoitre = get_rss_news(TUOITRE_RSS, "Tuổi Trẻ")
    if tuoitre:
        parts.append(tuoitre)

    cafef = get_cafef_news()
    if cafef:
        parts.append(cafef)

    if not parts:
        return "Hôm nay chưa có tin mới."

    return "\n\n".join(parts)


# ======================
# SEND MESSAGE (ASYNC)
# ======================
async def send_daily_news():
     text = build_daily_message()

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()

    ok = r.json().get("ok", False)
    if ok:
        print("✅ Daily news sent successfully")
    else:
        print("❌ Telegram API returned:", r.text)

# ======================
# APSCHEDULER
# ======================
def start_scheduler():
    tz = pytz.timezone("Asia/Bangkok")
    scheduler = BackgroundScheduler(timezone=tz)

    # 🔥 TEST MODE (CHẠY MỖI PHÚT) – DÙNG ĐỂ KIỂM TRA
    # scheduler.add_job(
    #     lambda: asyncio.run(send_daily_news()),
    #     trigger=CronTrigger(minute="*/1"),
    #     id="test_every_minute",
    #     replace_existing=True,
    # )

    # ✅ CHÍNH THỨC – 09:00 SÁNG GIỜ VIỆT NAM
   scheduler.add_job(
    send_daily_news,
    trigger=CronTrigger(minute="*/1"),
    id="test_every_minute",
    replace_existing=True,
    )
    print("🧪 TEST MODE: send every minute")
    )

    scheduler.start()
    print("✅ APScheduler started (09:00 Asia/Bangkok)")


# ======================
# MAIN
# ======================
def main():
    start_scheduler()
    print("✅ Bot service running (scheduler mode, no polling)")

    # Giữ process sống cho Render Free
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
