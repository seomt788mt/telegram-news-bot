import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import sqlite3
from datetime import time
from typing import List, Dict

import requests
import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Bangkok")
SEND_TIME = os.getenv("SEND_TIME", "09:00")
TOP_N = int(os.getenv("TOP_N", "5"))

VNEXPRESS_RSS = os.getenv("VNEXPRESS_RSS")
TUOITRE_RSS = os.getenv("TUOITRE_RSS")
CAFEF_HOME = os.getenv("CAFEF_HOME", "https://cafef.vn/")

DB_PATH = "sent_items.sqlite3"


def db_init():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sent (
            id TEXT PRIMARY KEY,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def db_is_sent(item_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sent WHERE id=?", (item_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def db_mark_sent(item_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO sent(id) VALUES(?)", (item_id,))
    conn.commit()
    conn.close()


def parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def escape_html(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace("\"", "&quot;"))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def fetch_rss(rss_url: str, source_name: str, top_n: int) -> List[Dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari",
        "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        r = requests.get(rss_url, headers=headers, timeout=20)
        r.raise_for_status()
        feed = feedparser.parse(r.content)  # parse từ bytes
    except Exception as e:
        print(f"[RSS ERROR] {source_name}: {e}")
        return []

    items = []
    for e in feed.entries[: top_n * 3]:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        item_id = f"{source_name}:{link}"
        items.append({"id": item_id, "source": source_name, "title": title, "link": link})
        if len(items) >= top_n:
            break
    return items



def fetch_cafef_home(top_n: int) -> List[Dict]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; TelegramNewsBot/1.0)"}
    r = requests.get(CAFEF_HOME, headers=headers, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    links = []
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        text = a.get_text(" ", strip=True)

        if not href or not text:
            continue

        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://cafef.vn" + href

        # CafeF thường có bài dạng .chn
        if "cafef.vn" in href and href.endswith(".chn"):
            if len(text) < 20:
                continue
            item_id = f"cafef:{href}"
            links.append({"id": item_id, "source": "CafeF", "title": text, "link": href})

    seen = set()
    uniq = []
    for it in links:
        if it["link"] in seen:
            continue
        seen.add(it["link"])
        uniq.append(it)
        if len(uniq) >= top_n:
            break

    return uniq


def collect_news(top_n: int) -> Dict[str, List[Dict]]:
    items_by_source = {
        "VnExpress": fetch_rss(VNEXPRESS_RSS, "vnexpress", top_n),
        "Tuổi Trẻ": fetch_rss(TUOITRE_RSS, "tuoitre", top_n),
        "CafeF": fetch_cafef_home(top_n),
    }

    # lọc item đã gửi
    for src in list(items_by_source.keys()):
        filtered = []
        for it in items_by_source[src]:
            if not db_is_sent(it["id"]):
                filtered.append(it)
        items_by_source[src] = filtered[:top_n]

    return items_by_source


def format_message(items_by_source: Dict[str, List[Dict]]) -> str:
    lines = ["📰 <b>Tin mới nhất (09:00)</b>", ""]
    for source, items in items_by_source.items():
        lines.append(f"🔸 <b>{escape_html(source)}</b>")
        if not items:
            lines.append("Không có tin mới hoặc đã gửi trước đó.")
        else:
            for i, it in enumerate(items, 1):
                title = escape_html(it["title"])
                link = it["link"]
                lines.append(f"{i}. <a href=\"{link}\">{title}</a>")
        lines.append("")
    lines.append("— Bot gửi tin tự động mỗi ngày ✅")
    return "\n".join(lines)


async def send_daily_news(context: ContextTypes.DEFAULT_TYPE) -> None:
    items_by_source = collect_news(TOP_N)
    msg = format_message(items_by_source)

    await context.bot.send_message(
        chat_id=CHAT_ID,
        text=msg,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    for items in items_by_source.values():
        for it in items:
            db_mark_sent(it["id"])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("✅ Bot đã sẵn sàng. Gõ /send để test gửi ngay.")


async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items_by_source = collect_news(TOP_N)
    msg = format_message(items_by_source)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    for items in items_by_source.values():
        for it in items:
            db_mark_sent(it["id"])


def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise SystemExit("Thiếu BOT_TOKEN hoặc CHAT_ID trong file .env")

    db_init()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("send", cmd_send))

    t = parse_hhmm(SEND_TIME)
    app.job_queue.run_daily(
        send_daily_news,
        time=t,
        name="daily_news",
        chat_id=CHAT_ID,
    )

    print(f"✅ Running... daily at {SEND_TIME} ({TIMEZONE}) to chat_id={CHAT_ID}")
threading.Thread(target=start_health_server, daemon=True).start()
    app.run_polling()


if __name__ == "__main__":
    main()
