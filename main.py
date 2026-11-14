
import os
import json
import base64
import re
import requests
import feedparser
from bs4 import BeautifulSoup

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GH_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]

HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json"
}

SOURCES = {
    "Marca": "https://e00-marca.uecdn.es/rss/futbol/mercado-fichajes.xml",
    "CaughtOffside": "https://www.caughtoffside.com/feed/",
    "BBC Sport": "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "Sky Sports": "https://www.skysports.com/rss/11095",
    "Football Italia": "https://www.football-italia.net/feed/",
    "Get Football News Germany": "https://www.getfootballnewsgermany.com/feed/"
}

# Genel ve toplu içerikleri ele
BAD_WORDS = re.compile(
    r"transfer window guide|transfer roundup|transfer round-up|"
    r"all the latest transfers|transfer gossip column|"
    r"weekly transfer|transfer tracker|"
    r"fixtures|live scores|match report|"
    r"predicted lineup|team news|"
    r"haftanın transfer|transfer dosyası|"
    r"transfer rehberi|transfer değerlendirmesi|"
    r"transfer gündemi|son dakika programı",
    re.IGNORECASE
)

# Somut transfer gelişmesi veya söylenti işaretleri
TRANSFER_WORDS = re.compile(
    r"transfer|signing|signed|signs|"
    r"loan|bid|offer|medical|deal|contract|"
    r"agrees|agreement|joins|departure|leaves|"
    r"interest|interested|target|negotiations|"
    r"talks|linked with|move for|"
    r"wants to sign|set to join|"
    r"fichaje|traspaso|cesion|"
    r"wechsel|leihe|verpflichtet|"
    r"imza|kiralik|kiralık|anlaştı|anlasti|"
    r"teklif|sözleşme|sozlesme|"
    r"ayrıldı|ayrildi|transferi|"
    r"görüşme|gorusme|ilgileniyor|"
    r"resmen|imzaladı|imzaladi",
    re.IGNORECASE
)

OFFICIAL_WORDS = re.compile(
    r"official|confirmed|announced|"
    r"completes the signing|has signed|"
    r"joins officially|"
    r"resmen açıklandı|resmen aciklandi|"
    r"resmen transfer oldu|"
    r"imzaladı|imzaladi|"
    r"transferi tamamlandı|transferi tamamlandi|"
    r"kulübü açıkladı|kulubu acikladi",
    re.IGNORECASE
)

RUMOUR_WORDS = re.compile(
    r"report|reports|reportedly|rumour|rumor|"
    r"could join|may join|interested|"
    r"linked with|target|considering|"
    r"talks|negotiations|bid|offer|"
    r"set to|close to|"
    r"iddia|iddialara göre|iddialara gore|"
    r"gündeminde|gundeminde|ilgileniyor|"
    r"teklif yaptı|teklif yapti|"
    r"görüşüyor|goruşuyor|gorusuyor|"
    r"anlaşma yakın|anlasma yakin",
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
        "message": "Update transfer news history",
        "content": content
    }

    if sha:
        data["sha"] = sha

    r = requests.put(url, headers=HEADERS, json=data, timeout=20)
    r.raise_for_status()


def clean_html(html):
    soup = BeautifulSoup(html, "html.parser")
    return " ".join(soup.get_text(" ").split())


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

        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()

        return "".join(part[0] for part in r.json()[0])

    except Exception as e:
        print(f"Çeviri hatası: {e}")
        return text


def make_summary(entry):
    description = entry.get("summary", "")

    if not description and entry.get("content"):
        description = entry["content"][0].get("value", "")

    description = clean_html(description)

    if len(description) < 60:
        return None

    sentences = re.split(r'(?<=[.!?])\s+', description)
    summary = " ".join(sentences[:3]).strip()

    if len(summary) > 600:
        summary = summary[:597].rsplit(" ", 1)[0] + "..."

    return summary


def classify(title, summary):
    text = title + " " + summary

    if BAD_WORDS.search(text):
        return None

    if not TRANSFER_WORDS.search(text):
        return None

    if OFFICIAL_WORDS.search(text):
        return "✅ RESMÎ TRANSFER"

    if RUMOUR_WORDS.search(text):
        return "🟠 TRANSFER SÖYLENTİSİ"

    return "⚽ TRANSFER GELİŞMESİ"


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

            summary = make_summary(entry)

            if not summary:
                continue

            category = classify(title, summary)

            if not category:
                continue

            news.append({
                "source": source_name,
                "title": title,
                "summary": summary,
                "link": link,
                "category": category
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

print(f"Filtrelenmiş transfer haberi: {len(all_news)}")

sent_count = 0

for item in all_news:

    link = item["link"]

    if link in new_seen:
        continue

    turkish_title = translate(item["title"])
    turkish_summary = translate(item["summary"])

    message = (
        f"{item['category']}\n\n"
        f"📰 {turkish_title}\n\n"
        f"📝 ÖZET:\n{turkish_summary}\n\n"
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
