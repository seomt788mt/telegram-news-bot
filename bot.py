import os
import time
import asyncio
import requests
import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import html
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
def get_rss_news(rss_url: str, source_name: str) -> str:
    feed = feedparser.parse(rss_url)
    items = []

    for i, entry in enumerate(feed.entries[:TOP_N], start=1):
        title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "").strip()

        if not title or not link:
            continue

        # 🔒 Escape HTML để tránh lỗi 400
        safe_title = html.escape(title)

        items.append(
            f"{i}️⃣ <a href=\"{link}\">{safe_title}</a>"
        )

    if not items:
        return ""

    return f"📰 <b>{source_name}</b>\n\n" + "\n".join(items)

def get_cafef_news() -> str:
    try:
        res = requests.get(CAFEF_HOME, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(res.text, "html.parser")
        links = soup.select("h3 a")[:TOP_N]

        items = []
        for i, a in enumerate(links, start=1):
            title = a.get_text(strip=True)
            link = a.get("href")

            if link and link.startswith("/"):
                link = "https://cafef.vn" + link

            if not title or not link:
                continue

            safe_title = html.escape(title)

            items.append(
                f"{i}️⃣ <a href=\"{link}\">{safe_title}</a>"
            )

        if not items:
            return ""

        return "📊 <b>CafeF</b>\n\n" + "\n".join(items)

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
from datetime import datetime
import requests

def send_daily_news():
    text = build_daily_message()

    # 🔒 Chống text rỗng (bắt buộc)
    if not text or not text.strip():
        text = "Hôm nay chưa có tin mới."

    # 🗞️ Thêm tiêu đề bản tin (đẹp & chuyên nghiệp)
    today = datetime.now().strftime("%d/%m/%Y")
    text = f"🗞️ BẢN TIN SÁNG – {today}\n\n{text}"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    r = requests.post(url, json=payload, timeout=20)

    # 🔍 Log để debug nếu Telegram từ chối
    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)

    if r.status_code == 200:
        print("✅ Daily news sent successfully")



# ======================
# APSCHEDULER
# ======================
def start_scheduler():
    tz = pytz.timezone("Asia/Bangkok")
    scheduler = BackgroundScheduler(timezone=tz)

    # =========================
    # TEST MODE – GỬI MỖI PHÚT
    # =========================
    scheduler.add_job(
        send_daily_news,
        trigger=CronTrigger(minute="*/1"),
        id="test_every_minute",
        replace_existing=True,
    )

    # =========================
    # CHẠY CHÍNH THỨC 09:00
    # (COMMENT TEST MODE TRƯỚC KHI DÙNG)
    # =========================
    # scheduler.add_job(
    #     send_daily_news,
    #     trigger=CronTrigger(hour=9, minute=0),
    #     id="daily_9am",
    #     replace_existing=True,
    #     misfire_grace_time=3600,
    #     coalesce=True,
    # )

    scheduler.start()
    print("✅ APScheduler started")



# ======================
# MAIN
# ======================
def main():
    start_scheduler()
    print("✅ Bot started (scheduler mode)")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
