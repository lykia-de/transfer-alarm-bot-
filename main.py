import os
import requests
import feedparser

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

url = "https://news.google.com/rss/search?q=football+transfer+news&hl=en&gl=GB&ceid=GB:en"

feed = feedparser.parse(url)

for entry in feed.entries[:10]:
    title = entry.title
    link = entry.link

    message = f"⚽ TRANSFER HABERİ\n\n{title}\n\n🔗 {link}"

    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": message}
    )