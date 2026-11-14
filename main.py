
import os
import json
import base64
import re
import time
import requests
import feedparser
from bs4 import BeautifulSoup

# ==========================================
# AYARLAR
# ==========================================

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GH_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]

API_URL = f"https://api.github.com/repos/{REPO}/contents/seen.json"

HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json"
}

# ==========================================
# HABER KAYNAKLARI
# ==========================================

SOURCES = {
    "Marca": "https://e00-marca.uecdn.es/rss/futbol/mercado-fichajes.xml",
    "CaughtOffside": "https://www.caughtoffside.com/feed/",
    "Sky Sports": "https://www.skysports.com/rss/11095",
    "Football Italia": "https://www.football-italia.net/feed/",
    "Get Football News Germany": "https://www.getfootballnewsgermany.com/feed/"
}

# ==========================================
# TRANSFER FİLTRELERİ
# ==========================================

BAD_WORDS = re.compile(
    r"transfer window guide|transfer roundup|transfer round-up|"
    r"all the latest transfers|transfer gossip column|"
    r"weekly transfer|transfer tracker|"
    r"fixtures|live scores|match report|"
    r"predicted lineup|team news|"
    r"quiz|highlights|watch live|"
    r"transfer rehberi|transfer değerlendirmesi|"
    r"transfer dosyası|haftanın transfer",
    re.IGNORECASE
)

TRANSFER_WORDS = re.compile(
    r"\b(?:"
    r"transfer|transfers|transferred|"
    r"transfer target|transfer talks|"
    r"transfer fee|transfer bid|"
    r"signing|signed for|signs for|"
    r"loan deal|loan move|"
    r"loan signing|"
    r"bid for|offer for|"
    r"deal agreed|agreement reached|"
    r"agreed terms|personal terms|"
    r"contract extension|new contract|"
    r"contract talks|"
    r"set to join|close to joining|"
    r"move for|"
    r"interested in signing|"
    r"negotiations with|"
    r"medical ahead of|"
    r"fichaje|traspaso|"
    r"wechsel|leihe|"
    r"kiralık|kiralik|"
    r"imza|transferi|"
    r"teklif|sözleşme|sozlesme|"
    r"anlaştı|anlasti|"
    r"görüşmeler|gorusmeler|"
    r"imzaladı|imzaladi|"
    r"resmen transfer|"
    r"transfer görüşmesi|transfer gorusmesi"
    r")\b",
    re.IGNORECASE
)

OFFICIAL_WORDS = re.compile(
    r"\b(?:"
    r"official|confirmed|announced|"
    r"completes the signing|"
    r"has signed for|"
    r"joins officially|"
    r"deal completed|"
    r"resmen açıklandı|resmen aciklandi|"
    r"resmen transfer oldu|"
    r"imzaladı|imzaladi|"
    r"transferi tamamlandı|transferi tamamlandi|"
    r"kulübü açıkladı|kulubu acikladi"
    r")\b",
    re.IGNORECASE
)

RUMOUR_WORDS = re.compile(
    r"\b(?:"
    r"reportedly|reports|report|"
    r"rumour|rumor|"
    r"could join|may join|"
    r"interested in|"
    r"linked with|"
    r"transfer target|"
    r"considering|"
    r"talks|negotiations|"
    r"bid for|offer for|"
    r"set to|close to|"
    r"iddia|iddialara göre|iddialara gore|"
    r"gündeminde|gundeminde|"
    r"ilgileniyor|"
    r"teklif yaptı|teklif yapti|"
    r"görüşüyor|goruşuyor|gorusuyor|"
    r"anlaşma yakın|anlasma yakin"
    r")\b",
    re.IGNORECASE
)

# ==========================================
# GÖRÜLMÜŞ HABERLER
# ==========================================

def load_seen():
    response = requests.get(API_URL, headers=HEADERS, timeout=20)

    if response.status_code == 404:
        return [], None

    response.raise_for_status()

    data = response.json()
    content = base64.b64decode(data["content"]).decode("utf-8")

    return json.loads(content), data["sha"]


def save_seen(seen, sha):
    content = json.dumps(
        seen,
        ensure_ascii=False,
        indent=2
    )

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("utf-8")

    payload = {
        "message": "Transfer haberleri kaydedildi",
        "content": encoded
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        API_URL,
        headers=HEADERS,
        json=payload,
        timeout=20
    )

    response.raise_for_status()


# ==========================================
# METİN TEMİZLEME VE ÇEVİRİ
# ==========================================

def clean_html(html):
    soup = BeautifulSoup(html or "", "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def translate(text):
    if not text:
        return ""

    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": "tr",
                "dt": "t",
                "q": text[:4500]
            },
            timeout=20
        )

        response.raise_for_status()
        data = response.json()

        return "".join(
            part[0] for part in data[0] if part[0]
        )

    except Exception as error:
        print("Çeviri hatası:", error)
        return text


# ==========================================
# HABER ÖZETİ
# ==========================================

def make_summary(entry):
    description = entry.get("summary", "")

    if not description and entry.get("content"):
        description = entry["content"][0].get("value", "")

    description = clean_html(description)

    if len(description) < 40:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", description)

    summary = " ".join(sentences[:3])

    return summary[:600]


# ==========================================
# HABER SINIFLANDIRMA
# ==========================================

def classify(title, summary):
    title = title.strip()
    summary = summary.strip()

    if BAD_WORDS.search(title):
        return None

    # Öncelikle başlıkta transfer işareti arıyoruz.
    if TRANSFER_WORDS.search(title):
        text = title + " " + summary

        if OFFICIAL_WORDS.search(text):
            return "✅ RESMÎ TRANSFER"

        if RUMOUR_WORDS.search(text):
            return "🟠 TRANSFER SÖYLENTİSİ"

        return "⚽ TRANSFER GELİŞMESİ"

    # Başlıkta yoksa özette daha güçlü transfer ifadeleri arıyoruz.
    if TRANSFER_WORDS.search(summary):
        if OFFICIAL_WORDS.search(summary):
            return "✅ RESMÎ TRANSFER"

        if RUMOUR_WORDS.search(summary):
            return "🟠 TRANSFER SÖYLENTİSİ"

        return "⚽ TRANSFER GELİŞMESİ"

    return None


# ==========================================
# TELEGRAM
# ==========================================

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True
        },
        timeout=20
    )

    response.raise_for_status()


# ==========================================
# RSS HABERLERİNİ AL
# ==========================================

def get_news(source_name, rss_url):
    articles = []

    try:
        response = requests.get(
            rss_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=25
        )

        response.raise_for_status()

        feed = feedparser.parse(response.content)

        for entry in feed.entries:
            title = clean_html(entry.get("title", ""))
            link = entry.get("link", "").strip()

            if not title or not link:
                continue

            # Video ve yayın sayfalarını ele.
            lowered_link = link.lower()

            if any(word in lowered_link for word in [
                "/iplayer/",
                "/video/",
                "/watch/",
                "/live/",
                "/podcast/"
            ]):
                continue

            summary = make_summary(entry)

            if not summary:
                continue

            category = classify(title, summary)

            if not category:
                continue

            articles.append({
                "source": source_name,
                "title": title,
                "summary": summary,
                "link": link,
                "category": category
            })

    except Exception as error:
        print(f"{source_name} RSS hatası: {error}")

    return articles


# ==========================================
# ANA PROGRAM
# ==========================================

def main():
    print("Transfer botu başladı.")

    seen, sha = load_seen()
    seen_set = set(seen)

    new_articles = []

    for source_name, rss_url in SOURCES.items():
        print(f"{source_name} kontrol ediliyor...")

        articles = get_news(source_name, rss_url)

        for article in articles:
            if article["link"] in seen_set:
                continue

            new_articles.append(article)

    # Aynı linki farklı kaynaklardan gelirse bir kez gönder.
    unique_articles = []
    added_links = set()

    for article in new_articles:
        if article["link"] not in added_links:
            unique_articles.append(article)
            added_links.add(article["link"])

    sent_count = 0

    for article in unique_articles[:10]:
        title_tr = translate(article["title"])
        summary_tr = translate(article["summary"])

        message = (
            f"{article['category']}\n\n"
            f"📰 {title_tr}\n\n"
            f"📝 ÖZET:\n{summary_tr}\n\n"
            f"📌 Kaynak: {article['source']}\n"
            f"🔗 {article['link']}"
        )

        try:
            send_message(message)

            seen.append(article["link"])
            seen_set.add(article["link"])

            sent_count += 1
            print("Gönderildi:", article["title"])

            time.sleep(1)

        except Exception as error:
            print("Telegram gönderim hatası:", error)

    # Liste çok büyümesin.
    seen = seen[-3000:]

    save_seen(seen, sha)

    print(f"İşlem tamamlandı. Gönderilen haber: {sent_count}")


if __name__ == "__main__":
    main()
