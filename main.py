
import os
import json
import base64
import requests
import feedparser
from urllib.parse import quote

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GH_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]

HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json"
}

LEAGUES = {
    "Premier League": "Premier League football transfer news",
    "La Liga": "La Liga football transfer news",
    "Bundesliga": "Bundesliga football transfer news",
    "Serie A": "Serie A football transfer news",
    "Ligue 1": "Ligue 1 football transfer news",
    "Süper Lig": "Süper Lig transfer haberleri"
}

def load_seen():
    url = f"https://api.github.com/repos/{REPO}/contents/seen.json"
    r = requests.get(url, headers=HEADERS)

    if r.status_code == 200:
        data = r.json()
        content = base64.b64decode(data["content"]).decode()
        return json.loads(content), data["sha"]

    return [], None

def save_seen(seen, sha):
    url = f"https://api.github.com/repos/{REPO}/contents/seen.json"
    content = base64.b64encode(
        json.dumps(seen, ensure_ascii=False).encode()
    ).decode()

    data = {
        "message": "Update transfer news history",
        "content": content
    }

    if sha:
        data["sha"] = sha

    r = requests.put(url, headers=HEADERS, json=data)
    r.raise_for_status()

def translate(text):
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": "tr",
            "dt": "t",
            "q": text
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return "".join(part[0] for part in r.json()[0])
    except Exception:
        return text

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": text},
        timeout=20
    )
    r.raise_for_status()

seen, sha = load_seen()
new_seen = list(seen)
count = 0

for league, query in LEAGUES.items():
    rss_url = (
        "https://news.google.com/rss/search?q="
        + quote(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )

    feed = feedparser.parse(rss_url)

    for entry in reversed(feed.entries):
        link = entry.get("link", "")

        if not link or link in seen:
            continue

        title = translate(entry.get("title", "Yeni transfer haberi"))

        message = (
            f"⚽ {league}\n\n"
            f"📰 {title}\n\n"
            f"🔗 {link}"
        )

        try:
            send_message(message)
            new_seen.append(link)
            count += 1
        except Exception as e:
            print("Mesaj gönderilemedi:", e)

        if count >= 20:
            break

    if count >= 20:
        break

new_seen = new_seen[-1000:]

if new_seen != seen:
    save_seen(new_seen, sha)

print(f"Tamamlandı. Gönderilen yeni haber: {count}")
