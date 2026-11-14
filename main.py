
import os
import json
import base64
import re
import requests
import feedparser

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GH_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]

HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json"
}

# Haber kaynakları
SOURCES = {
    "Marca": "https://e00-marca.uecdn.es/rss/futbol/mercado-fichajes.xml",
    "CaughtOffside": "https://www.caughtoffside.com/feed/",
    "BBC Sport": "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "Sky Sports": "https://www.skysports.com/rss/11095",
    "Football Italia": "https://www.football-italia.net/feed/",
    "Get Football News Germany": "https://www.getfootballnewsgermany.com/feed/"
}

# Transfer haberlerini ayıklamak için kelimeler
TRANSFER_WORDS = re.compile(
    r"\b("
    r"transfer|transfers|signing|signs|signed|"
    r"loan|bid|medical|deal|contract|"
    r"agrees|agreement|joins|completes|"
    r"departure|leaves|interest|target|"
    r"renewal|fichaje|fichajes|traspaso|"
    r"cesion|firma|wechsel|leihe|"
    r"verpflichtet|unterschreibt|angebot|"
    r"transfermarkt|imza|kiralik|kiralık|"
    r"anlasti|anlaştı|teklif|sozlesme|"
    r"sözleşme|ayrildi|ayrıldı|"
    r"transferi|transferde"
    r")\b",
    re.IGNORECASE
)

def load_seen():
    url = f"https://api.github.com/repos/{REPO}/contents/seen.json"
    r = requests.get(url, headers=HEADERS, timeout=20)

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
        "message": "Update football news history",
        "content": content
    }

    if sha:
        data["sha"] = sha

    r = requests.put(url, headers=HEADERS, json=data, timeout=20)
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

    except Exception as e:
        print(f"Çeviri hatası: {e}")
        return text


def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    r = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True
        },
        timeout=20
    )

    r.raise_for_status()


def get_news(source_name, rss_url):
    try:
        response = requests.get(
            rss_url,
            headers={"User-Agent": "Mozilla/5.0 FootballNewsBot/1.0"},
            timeout=25
        )
        response.raise_for_status()

        feed = feedparser.parse(response.content)

        print(f"{source_name}: {len(feed.entries)} haber bulundu")

        news = []

        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()

            if not title or not link:
                continue

            if not TRANSFER_WORDS.search(title):
                continue

            news.append({
                "source": source_name,
                "title": title,
                "link": link
            })

        return news

    except Exception as e:
        print(f"{source_name} kaynak hatası: {e}")
        return []


# BOT BAŞLIYOR

seen, sha = load_seen()
new_seen = list(seen)

all_news = []

for source_name, rss_url in SOURCES.items():
    all_news.extend(get_news(source_name, rss_url))

print(f"Toplam transfer haberi: {len(all_news)}")

sent_count = 0

for item in all_news:

    link = item["link"]

    if link in new_seen:
        continue

    original_title = item["title"]
    turkish_title = translate(original_title)

    message = (
        "⚽ TRANSFER HABERİ\n\n"
        f"📰 {turkish_title}\n\n"
        f"📌 Kaynak: {item['source']}\n"
        f"🔗 {link}"
    )

    try:
        send_message(message)

        new_seen.append(link)
        sent_count += 1

        print(f"Gönderildi: {item['source']} - {turkish_title}")

    except Exception as e:
        print(f"Gönderim hatası: {e}")

    if sent_count >= 10:
        break

new_seen = new_seen[-1000:]

if new_seen != seen:
    save_seen(new_seen, sha)

print(f"BOT TAMAMLANDI. Gönderilen haber: {sent_count}")
