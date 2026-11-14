
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
    "🇬🇧 Premier League": "Premier League football transfer news",
    "🇪🇸 La Liga": "La Liga football transfer news",
    "🇩🇪 Bundesliga": "Bundesliga football transfer news",
    "🇮🇹 Serie A": "Serie A football transfer news",
    "🇫🇷 Ligue 1": "Ligue 1 football transfer news",
    "🇹🇷 Süper Lig": "Süper Lig transfer haberleri"
}

def load_seen():
    url = f"https://api.github.com/repos/{REPO}/contents/seen.json"
    r = requests.get(url, headers=HEADERS)

    if r.status_code == 200:
        data = r.json()
        content = base64.b64decode(data["content"]).decode()
        return json.loads(content), data["sha"]

    if r.status_code == 404:
        return [], None

    r.raise_for_status()

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
total_count = 0

for league, query in LEAGUES.items():

    league_count = 0

    rss_url = (
        "https://news.google.com/rss/search?q="
        + quote(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )

    feed = feedparser.parse(rss_url)

    print(f"{league}: {len(feed.entries)} haber bulundu")

    for entry in reversed(feed.entries):

        link = entry.get("link", "")

        if not link or link in new_seen:
            continue

        original_title = entry.get(
            "title", "Yeni transfer haberi"
        )

        title = translate(original_title)

        message = (
            f"⚽ TRANSFER HABERİ\n"
            f"{league}\n\n"
            f"📰 {title}\n\n"
            f"🔗 {link}"
        )

        try:
            send_message(message)

            new_seen.append(link)
            league_count += 1
            total_count += 1

            print(f"Gönderildi: {league} - {title}")

        except Exception as e:
            print(f"Gönderilemedi: {e}")

        if league_count >= 5:
            break

new_seen = new_seen[-1000:]

if new_seen != seen:
    save_seen(new_seen, sha)

print(f"Tamamlandı. Toplam yeni haber: {total_count}")
