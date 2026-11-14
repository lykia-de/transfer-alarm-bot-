
import os
import re
import json
import base64
import html
import requests
import feedparser

from bs4 import BeautifulSoup
from urllib.parse import quote


# ==========================================
# AYARLAR
# ==========================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")
GITHUB_BRANCH = os.getenv("GITHUB_REF_NAME", "main")

SEEN_FILE = "seen.json"
MAX_NEWS_PER_RUN = 10

SOURCES = {
    "Marca": "https://e00-marca.uecdn.es/rss/futbol/mercado-fichajes.xml",
    "CaughtOffside": "https://www.caughtoffside.com/feed/",
    "Sky Sports": "https://www.skysports.com/rss/11095",
    "Football Italia": "https://www.football-italia.net/feed/",
    "Get Football News Germany": "https://www.getfootballnewsgermany.com/feed/"
}

CLUBS = {
    "Real Madrid": ["Real Madrid", "Real Madrid CF"],
    "Barcelona": ["Barcelona", "FC Barcelona", "Barca"],
    "Atletico Madrid": ["Atletico Madrid", "Atlético Madrid"],
    "Arsenal": ["Arsenal"],
    "Manchester City": ["Manchester City", "Man City"],
    "Manchester United": ["Manchester United", "Man United", "Man Utd"],
    "Liverpool": ["Liverpool"],
    "Chelsea": ["Chelsea"],
    "Tottenham": ["Tottenham", "Spurs"],
    "Newcastle": ["Newcastle United", "Newcastle"],
    "Bayern Munich": ["Bayern Munich", "Bayern"],
    "Borussia Dortmund": ["Borussia Dortmund", "Dortmund"],
    "Bayer Leverkusen": ["Bayer Leverkusen", "Leverkusen"],
    "RB Leipzig": ["RB Leipzig", "Leipzig"],
    "PSG": ["Paris Saint-Germain", "Paris Saint Germain", "PSG"],
    "Inter": ["Inter Milan", "Inter"],
    "AC Milan": ["AC Milan", "Milan"],
    "Juventus": ["Juventus", "Juve"],
    "Napoli": ["Napoli"],
    "Roma": ["AS Roma", "Roma"],
    "Beşiktaş": ["Besiktas", "Beşiktaş"],
    "Galatasaray": ["Galatasaray"],
    "Fenerbahçe": ["Fenerbahce", "Fenerbahçe"],
    "Trabzonspor": ["Trabzonspor"],
    "Ajax": ["Ajax"],
    "Benfica": ["Benfica"],
    "Porto": ["FC Porto", "Porto"],
    "Sporting": ["Sporting CP", "Sporting Lisbon"],
    "Al Nassr": ["Al Nassr"],
    "Al Hilal": ["Al Hilal"],
    "Al Ittihad": ["Al Ittihad"],
    "Al Ahli": ["Al Ahli"]
}

TRANSFER_WORDS = [
    "transfer", "signing", "sign", "signs", "signed",
    "deal", "bid", "offer", "move", "join", "joining",
    "loan", "contract", "exit", "departure", "target",
    "interest", "interested", "talks", "negotiations",
    "agreement", "release clause", "fichajes",
    "mercato", "transfers"
]

BAD_WORDS = [
    "transfer centre live",
    "transfer center live",
    "transfer live blog",
    "live transfer blog",
    "match report",
    "starting line-up",
    "starting lineup",
    "fixtures",
    "predicted lineup",
    "predicted line-up"
]

OFFICIAL_WORDS = [
    "officially signed", "official: ", "here we go",
    "completed transfer", "completes move",
    "signs for", "has signed for", "joins on",
    "announced", "unveiled"
]

STRONG_WORDS = [
    "agreement reached", "deal agreed",
    "medical booked", "medical scheduled",
    "personal terms agreed", "final stages",
    "close to signing", "set to sign",
    "advanced talks", "bid accepted"
]

RUMOR_WORDS = [
    "could join", "interested in", "wants to sign",
    "linked with", "targeting", "considering",
    "eyeing", "open to", "ready to offer",
    "reportedly", "according to reports"
]


# ==========================================
# GITHUB: DAHA ÖNCE GÖNDERİLEN HABERLER
# ==========================================

def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }


def load_seen():
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print("UYARI: GitHub kayıt ayarları bulunamadı.")
        return set(), None

    url = (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}"
        f"/contents/{SEEN_FILE}?ref={quote(GITHUB_BRANCH)}"
    )

    try:
        response = requests.get(
            url, headers=github_headers(), timeout=20
        )

        if response.status_code == 404:
            return set(), None

        response.raise_for_status()
        data = response.json()

        content = base64.b64decode(data["content"]).decode("utf-8")
        links = json.loads(content)

        return set(links), data["sha"]

    except Exception as error:
        print("seen.json okunamadı:", error)
        raise


def save_seen(seen, sha):
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print("UYARI: seen.json kaydedilemedi.")
        return

    url = (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}"
        f"/contents/{SEEN_FILE}"
    )

    content = json.dumps(
        list(seen)[-3000:],
        ensure_ascii=False,
        indent=2
    )

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("utf-8")

    payload = {
        "message": "Transfer haberleri kaydını güncelle",
        "content": encoded,
        "branch": GITHUB_BRANCH
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        url,
        headers=github_headers(),
        json=payload,
        timeout=20
    )

    response.raise_for_status()
    print("seen.json güncellendi.")


# ==========================================
# METİN TEMİZLEME VE ÇEVİRİ
# ==========================================

def clean_text(text):
    if not text:
        return ""

    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def translate_to_turkish(text):
    if not text:
        return ""

    try:
        url = "https://translate.googleapis.com/translate_a/single"

        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": "tr",
            "dt": "t",
            "q": text[:4500]
        }

        response = requests.get(
            url, params=params, timeout=15
        )
        response.raise_for_status()

        data = response.json()
        translated = "".join(
            part[0] for part in data[0] if part[0]
        )

        return translated.strip() or text

    except Exception as error:
        print("Çeviri yapılamadı:", error)
        return text


# ==========================================
# HABER ÖZETİ
# ==========================================

def get_summary(entry):
    summary = entry.get("summary", "")

    if not summary and entry.get("description"):
        summary = entry.get("description", "")

    if not summary and entry.get("content"):
        summary = entry["content"][0].get("value", "")

    summary = clean_text(summary)

    if len(summary) > 700:
        summary = summary[:700].rsplit(" ", 1)[0] + "..."

    return summary


# ==========================================
# KULÜP TESPİTİ
# ==========================================

def find_clubs(text):
    found = []

    for club, aliases in CLUBS.items():
        for alias in aliases:
            pattern = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"

            if re.search(pattern, text, re.IGNORECASE):
                found.append(club)
                break

    return found


# ==========================================
# OYUNCU ADI TESPİTİ
# ==========================================

NAME_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "from",
    "with", "after", "before", "as", "is", "are", "has",
    "have", "will", "could", "would", "should", "his",
    "her", "their", "this", "that", "new", "deal",
    "transfer", "window", "latest", "report", "reports",
    "football", "premier", "league", "summer", "january",
    "official", "exclusive", "breaking", "revealed",
    "interest", "interested", "target", "targets",
    "wants", "want", "eyes", "eye", "move", "bid",
    "offer", "talks", "agreement", "club", "manager",
    "coach", "boss", "star", "striker", "forward",
    "midfielder", "defender", "goalkeeper"
}


def remove_club_names(text):
    result = text

    for aliases in CLUBS.values():
        for alias in aliases:
            result = re.sub(
                re.escape(alias),
                " ",
                result,
                flags=re.IGNORECASE
            )

    return result


def extract_player(title, summary):
    """
    Başlık ve özetteki muhtemel iki veya üç kelimelik
    oyuncu isimlerini bulur. Emin değilse isim üretmez.
    """

    title_text = remove_club_names(title)
    summary_text = remove_club_names(summary)

    def candidates(text):
        pattern = (
            r"\b[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'’-]+"
            r"(?:\s+[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'’-]+){1,2}\b"
        )

        matches = re.findall(pattern, text)

        results = []

        for match in matches:
            words = match.split()

            if any(
                word.lower() in NAME_STOPWORDS
                for word in words
            ):
                continue

            if len(match) < 5:
                continue

            if match not in results:
                results.append(match)

        return results

    title_candidates = candidates(title_text)

    if len(title_candidates) == 1:
        return title_candidates[0]

    if len(title_candidates) > 1:
        return "Belirlenemedi"

    summary_candidates = candidates(summary_text)

    if len(summary_candidates) == 1:
        return summary_candidates[0]

    return "Belirlenemedi"


# ==========================================
# TRANSFER HABERİ FİLTRESİ
# ==========================================

def is_transfer_news(title, summary, link):
    combined = f"{title} {summary} {link}".lower()

    if any(word in combined for word in BAD_WORDS):
        return False

    return any(
        word in combined
        for word in TRANSFER_WORDS
    )


# ==========================================
# TRANSFER DURUMU
# ==========================================

def classify(title, summary):
    text = f"{title} {summary}".lower()

    if any(word in text for word in OFFICIAL_WORDS):
        return "✅ RESMÎ TRANSFER"

    if any(word in text for word in STRONG_WORDS):
        return "🔥 GÜÇLÜ TRANSFER İDDİASI"

    if any(word in text for word in RUMOR_WORDS):
        return "🟠 TRANSFER SÖYLENTİSİ"

    return "⚽ TRANSFER GELİŞMESİ"


# ==========================================
# BONSERVİS TESPİTİ
# ==========================================

def extract_fee(text):
    patterns = [
        r"(?:€|£)\s?\d+(?:[.,]\d+)?\s?(?:million|m|billion|bn)",
        r"\d+(?:[.,]\d+)?\s?(?:million|m|billion|bn)\s?(?:euros|pounds)",
        r"(?:€|£)\s?\d{1,3}(?:[.,]\d{3})+"
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return match.group(0)

    return "Belirtilmedi"


# ==========================================
# TELEGRAM MESAJI
# ==========================================

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }

    response = requests.post(
        url, data=payload, timeout=20
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError("Telegram mesajı gönderilemedi.")

    return True


def make_message(title, summary, link, source):
    player = extract_player(title, summary)
    clubs = find_clubs(f"{title} {summary}")
    status = classify(title, summary)
    fee = extract_fee(f"{title} {summary}")

    translated_title = translate_to_turkish(title)
    translated_summary = translate_to_turkish(summary)

    if not translated_summary:
        translated_summary = "Haberin ayrıntılı özeti kaynakta bulunmuyor."

    club_text = ", ".join(clubs) if clubs else "Belirtilmedi"

    message = (
        f"{status}\n\n"
        f"👤 Oyuncu: {player}\n"
        f"🏟️ Haberde geçen kulüpler: {club_text}\n"
        f"💰 Bonservis: {fee}\n\n"
        f"📰 {source}\n"
        f"📌 {translated_title}\n\n"
        f"📝 {translated_summary}\n\n"
        f"🔗 Haberin tamamı:\n{link}"
    )

    return message


# ==========================================
# ANA PROGRAM
# ==========================================

def main():
    print("================================")
    print("RATEBROS TRANSFER BOTU BAŞLADI")
    print("OYUNCU TESPİTİ AKTİF")
    print("================================")

    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Telegram ayarları eksik!")

    seen, seen_sha = load_seen()

    new_articles = []

    for source, feed_url in SOURCES.items():
        print(f"\n{source} kontrol ediliyor...")

        try:
            feed = feedparser.parse(feed_url)

            print(
                f"{source}: RSS toplam haber: "
                f"{len(feed.entries)}"
            )

            matched = 0

            for entry in feed.entries:
                title = clean_text(entry.get("title", ""))
                link = entry.get("link", "")

                if not title or not link:
                    continue

                summary = get_summary(entry)

                if not is_transfer_news(title, summary, link):
                    continue

                matched += 1

                if link in seen:
                    continue

                new_articles.append({
                    "source": source,
                    "title": title,
                    "summary": summary,
                    "link": link
                })

            print(
                f"{source}: {matched} transfer haberi bulundu."
            )

        except Exception as error:
            print(f"{source} RSS hatası: {error}")

    # Önce önemli haberleri gönder
    priority = {
        "RESMÎ TRANSFER": 0,
        "GÜÇLÜ TRANSFER İDDİASI": 1,
        "TRANSFER SÖYLENTİSİ": 2,
        "TRANSFER GELİŞMESİ": 3
    }

    def article_priority(article):
        status = classify(
            article["title"],
            article["summary"]
        )

        for key, value in priority.items():
            if key in status:
                return value

        return 4

    new_articles.sort(key=article_priority)

    print(f"\nToplam yeni haber: {len(new_articles)}")

    sent = 0

    for article in new_articles[:MAX_NEWS_PER_RUN]:
        try:
            message = make_message(
                article["title"],
                article["summary"],
                article["link"],
                article["source"]
            )

            send_telegram(message)

            seen.add(article["link"])
            sent += 1

            print(
                f"GÖNDERİLDİ: {article['title']}"
            )

        except Exception as error:
            print(
                f"Haber gönderme hatası: {error}"
            )

    save_seen(seen, seen_sha)

    print("================================")
    print("İŞLEM TAMAMLANDI")
    print(f"Gönderilen haber: {sent}")
    print("================================")


if __name__ == "__main__":
    main()
