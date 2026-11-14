
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
# RSS KAYNAKLARI
# ==========================================

SOURCES = {
    "Marca": "https://e00-marca.uecdn.es/rss/futbol/mercado-fichajes.xml",
    "CaughtOffside": "https://www.caughtoffside.com/feed/",
    "Sky Sports": "https://www.skysports.com/rss/11095",
    "Football Italia": "https://www.football-italia.net/feed/",
    "Get Football News Germany": "https://www.getfootballnewsgermany.com/feed/"
}

# ==========================================
# FİLTRELER
# ==========================================

BAD_WORDS = re.compile(
    r"transfer window guide|transfer roundup|transfer round-up|"
    r"weekly transfer|transfer tracker|"
    r"fixtures|live scores|match report|"
    r"predicted lineup|team news|"
    r"quiz|crossword|podcast",
    re.IGNORECASE
)

TRANSFER_SIGNAL = re.compile(
    r"\b(?:"
    r"transfers?|transferred|"
    r"fichajes?|fichaje|traspasos?|"
    r"mercato|wechsel|leihe|"
    r"signing|signed|signs|"
    r"joins|joined|"
    r"loan|bid|offer|"
    r"contract|negotiations|"
    r"talks|interested|interest|"
    r"transfer target|"
    r"linked with|"
    r"agrees|agreement|"
    r"deal agreed|"
    r"set to join|"
    r"move for|"
    r"imza|kiralık|kiralik|"
    r"anlaştı|anlasti|"
    r"teklif|sözleşme|sozlesme|"
    r"görüşme|gorusme|"
    r"ilgileniyor|"
    r"imzaladı|imzaladi|"
    r"resmen transfer"
    r")\b",
    re.IGNORECASE
)

STRONG_SUMMARY_SIGNAL = re.compile(
    r"\b(?:"
    r"transfer|fichaje|traspaso|mercato|wechsel|"
    r"transfer talks|transfer target|"
    r"loan move|loan deal|"
    r"bid for|offer for|"
    r"contract extension|"
    r"personal terms|"
    r"medical ahead of|"
    r"deal agreed|"
    r"negotiations with|"
    r"imza|kiralık|kiralik|"
    r"transferi|teklif|"
    r"görüşmeler|gorusmeler|"
    r"anlaşma|anlasma"
    r")\b",
    re.IGNORECASE
)

OFFICIAL_WORDS = re.compile(
    r"\b(?:"
    r"official|confirmed|announced|"
    r"completes the signing|"
    r"has signed for|"
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
    r"reportedly|reports|rumour|rumor|"
    r"could join|may join|"
    r"interested in|linked with|"
    r"considering|talks|negotiations|"
    r"bid for|offer for|"
    r"set to|close to|"
    r"iddia|iddialara göre|iddialara gore|"
    r"gündeminde|gundeminde|"
    r"ilgileniyor|teklif yaptı|teklif yapti|"
    r"görüşüyor|gorusuyor|"
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
# METİN TEMİZLEME
# ==========================================

def clean_html(html):
    soup = BeautifulSoup(html or "", "html.parser")
    return re.sub(
        r"\s+",
        " ",
        soup.get_text(" ", strip=True)
    ).strip()


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

    if not description:
        description = entry.get("description", "")

    description = clean_html(description)

    if not description:
        return "Kaynakta ayrıntılı haber özeti bulunmuyor."

    sentences = re.split(r"(?<=[.!?])\s+", description)

    summary = " ".join(sentences[:3])

    return summary[:600]


# ==========================================
# HABER SINIFLANDIRMA
# ==========================================

def classify(title, summary):
    if BAD_WORDS.search(title):
        return None

    # Başlıkta transfer işareti varsa kabul et.
    if TRANSFER_SIGNAL.search(title):
        text = title + " " + summary

        if OFFICIAL_WORDS.search(text):
            return "✅ RESMÎ TRANSFER"

        if RUMOUR_WORDS.search(text):
            return "🟠 TRANSFER SÖYLENTİSİ"

        return "⚽ TRANSFER GELİŞMESİ"

    # Başlıkta bulunmuyorsa özette daha güçlü işaret ara.
    if STRONG_SUMMARY_SIGNAL.search(summary):
        text = title + " " + summary

        if OFFICIAL_WORDS.search(text):
            return "✅ RESMÎ TRANSFER"

        if RUMOUR_WORDS.search(text):
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

        print(f"{source_name}: RSS toplam haber: {len(feed.entries)}")

        for entry in feed.entries:
            title = clean_html(entry.get("title", ""))
            link = entry.get("link", "").strip()

            if not title or not link:
                continue

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

        print(
            f"{source_name}: "
            f"{len(articles)} transfer haberi bulundu."
        )

    except Exception as error:
        print(f"{source_name} RSS HATASI: {error}")

    return articles


# ==========================================
# ANA PROGRAM
# ==========================================

def main():
    print("================================")
    print("RATEBROS TRANSFER BOTU BAŞLADI")
    print("================================")

    seen, sha = load_seen()
    seen_set = set(seen)

    new_articles = []

    for source_name, rss_url in SOURCES.items():
        print(f"\n{source_name} kontrol ediliyor...")

        articles = get_news(source_name, rss_url)

        for article in articles:
            if article["link"] not in seen_set:
                new_articles.append(article)

    # Tekrarlanan haberleri temizle.
    unique_articles = []
    added_links = set()

    for article in new_articles:
        if article["link"] not in added_links:
            unique_articles.append(article)
            added_links.add(article["link"])

    print("\nToplam yeni haber:", len(unique_articles))

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

    seen = seen[-3000:]

    save_seen(seen, sha)

    print("\n================================")
    print("İŞLEM TAMAMLANDI")
    print("Gönderilen haber:", sent_count)
    print("================================")


if __name__ == "__main__":
    main()
