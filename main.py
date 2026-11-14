
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    )
}

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
    "transfer", "signing", "signs for", "signed for",
    "deal", "bid", "offer", "loan", "contract",
    "departure", "exit", "target", "interest",
    "interested", "talks", "negotiations",
    "agreement", "release clause", "fichajes",
    "mercato", "transfermarkt", "transfer window",
    "move to", "join", "joining", "set to leave",
    "wants to leave", "could leave", "will leave",
    "loan deal", "buy option", "option to buy",
    "purchase option", "return to", "recall",
    "renewal", "extends contract", "contract extension",
    "wechsel", "verpflichten", "leihe",
    "accordo", "prestito", "ingaggio",
    "fichar", "cesión", "traspaso"
]

BAD_TITLE_WORDS = [
    "match report", "starting line-up", "starting lineup",
    "predicted lineup", "predicted line-up",
    "live blog", "transfer centre live", "transfer center live",
    "highlights", "player ratings", "watch:",
    "video:", "reaction:", "post-match",
    "press conference", "interview:"
]

OFFICIAL_WORDS = [
    "officially signed", "official:", "here we go",
    "completed transfer", "completes move",
    "has signed for", "joins on loan",
    "announced", "unveiled", "signs a contract"
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
    "reportedly", "according to reports",
    "being monitored", "interest from"
]


# ==========================================
# GITHUB KAYIT SİSTEMİ
# ==========================================

def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }


def load_seen():
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        raise RuntimeError("GitHub kayıt ayarları bulunamadı.")

    url = (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}"
        f"/contents/{SEEN_FILE}?ref={quote(GITHUB_BRANCH)}"
    )

    response = requests.get(
        url, headers=github_headers(), timeout=20
    )

    if response.status_code == 404:
        return set(), None

    response.raise_for_status()

    data = response.json()
    content = base64.b64decode(data["content"]).decode("utf-8")

    return set(json.loads(content)), data["sha"]


def save_seen(seen, sha):
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
        "message": "RATEBROS haber kayıtlarını güncelle",
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
# METİN TEMİZLEME
# ==========================================

def clean_text(text):
    if not text:
        return ""

    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ==========================================
# HABER SAYFASINI OKUMA
# ==========================================

def read_article(url):
    """
    Haber sayfasındaki ana makale metnini çıkarmaya çalışır.
    Bazı siteler bot erişimini veya tam metni engelleyebilir.
    """

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for element in soup.select(
            "script, style, nav, footer, header, "
            "aside, iframe, form, .advertisement, "
            ".advert, .social-share, .related-articles"
        ):
            element.decompose()

        selectors = [
            "article",
            '[itemprop="articleBody"]',
            ".article-body",
            ".article-content",
            ".entry-content",
            ".post-content",
            ".story-body",
            ".content-body",
            "main"
        ]

        for selector in selectors:
            container = soup.select_one(selector)

            if not container:
                continue

            paragraphs = [
                clean_text(p.get_text(" ", strip=True))
                for p in container.find_all("p")
            ]

            paragraphs = [
                p for p in paragraphs if len(p) > 45
            ]

            text = " ".join(paragraphs)

            if len(text) > 250:
                return text[:9000]

        paragraphs = [
            clean_text(p.get_text(" ", strip=True))
            for p in soup.find_all("p")
        ]

        paragraphs = [
            p for p in paragraphs if len(p) > 45
        ]

        return " ".join(paragraphs)[:9000]

    except Exception as error:
        print("Haber sayfası okunamadı:", error)
        return ""


# ==========================================
# KULÜP TESPİTİ
# ==========================================

def find_clubs(text):
    found = []

    for club, aliases in CLUBS.items():
        for alias in aliases:
            pattern = (
                r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
            )

            if re.search(pattern, text, re.IGNORECASE):
                found.append(club)
                break

    return found


# ==========================================
# HABER FİLTRESİ
# ==========================================

def is_transfer_news(title, summary, article):
    title_lower = title.lower()
    combined = f"{title} {summary} {article}".lower()

    # Maç ve röportaj türü başlıkları ele
    if any(word in title_lower for word in BAD_TITLE_WORDS):
        return False

    # Takip edilen kulüplerden en az biri geçmeli
    clubs = find_clubs(combined)

    if not clubs:
        return False

    # Transferle ilgili açık bir ifade bulunmalı
    if not any(word in combined for word in TRANSFER_WORDS):
        return False

    return True


# ==========================================
# HABER SINIFLANDIRMA
# ==========================================

def classify(title, summary, article):
    text = f"{title} {summary} {article}".lower()

    if any(word in text for word in OFFICIAL_WORDS):
        return "✅ RESMÎ TRANSFER"

    if any(word in text for word in STRONG_WORDS):
        return "🔥 GÜÇLÜ TRANSFER İDDİASI"

    if any(word in text for word in RUMOR_WORDS):
        return "🟠 TRANSFER SÖYLENTİSİ"

    return "⚽ TRANSFER GELİŞMESİ"


# ==========================================
# OYUNCU ADI TESPİTİ
# ==========================================

NAME_STOPWORDS = {
    "the", "and", "for", "from", "with", "after",
    "before", "could", "would", "should", "their",
    "this", "that", "new", "deal", "transfer",
    "window", "latest", "report", "football",
    "league", "summer", "january", "official",
    "exclusive", "breaking", "interest", "target",
    "wants", "move", "offer", "talks", "agreement",
    "club", "manager", "coach", "star", "striker",
    "forward", "midfielder", "defender", "goalkeeper"
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
    text = remove_club_names(title)

    pattern = (
        r"\b[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'’-]+"
        r"(?:\s+[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'’-]+){1,2}\b"
    )

    candidates = re.findall(pattern, text)

    candidates = [
        name for name in candidates
        if not any(
            word.lower() in NAME_STOPWORDS
            for word in name.split()
        )
    ]

    if len(candidates) == 1:
        return candidates[0]

    return "Haberde belirtilmedi"


# ==========================================
# BONSERVİS
# ==========================================

def extract_fee(text):
    patterns = [
        r"(?:€|£)\s?\d+(?:[.,]\d+)?\s?(?:million|m|billion|bn)",
        r"\d+(?:[.,]\d+)?\s?(?:million|m|billion|bn)\s?(?:euros|pounds)",
        r"(?:€|£)\s?\d{1,3}(?:[.,]\d{3})+"
    ]

    for pattern in patterns:
        match = re.search(
            pattern, text, re.IGNORECASE
        )

        if match:
            return match.group(0)

    return "Açıklanmadı"


# ==========================================
# KISA HABER ÖZETİ
# ==========================================

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
            url, params=params, timeout=20
        )

        response.raise_for_status()

        data = response.json()

        result = "".join(
            part[0] for part in data[0] if part[0]
        )

        return result.strip()

    except Exception as error:
        print("Çeviri hatası:", error)
        return text


def make_short_summary(article_text, rss_summary):
    """
    Makaleden transferle ilgili cümleleri seçer.
    Sonra seçilen metni Türkçeye çevirir.
    """

    source_text = article_text or rss_summary

    if not source_text:
        return "Haberin ayrıntılı metnine ulaşılamadı."

    sentences = re.split(
        r"(?<=[.!?])\s+",
        source_text
    )

    keywords = [
        "transfer", "loan", "sign", "deal",
        "contract", "return", "leave", "club",
        "player", "manager", "coach", "training",
        "performance", "option", "buy",
        "interest", "talks", "agreement",
        "prestito", "accordo", "mercato",
        "wechsel", "leihe", "vertrag",
        "fichar", "cesión", "traspaso"
    ]

    selected = []

    for sentence in sentences:
        sentence = sentence.strip()

        if len(sentence) < 45:
            continue

        lower = sentence.lower()

        score = sum(
            1 for word in keywords if word in lower
        )

        if score > 0:
            selected.append((score, sentence))

    if selected:
        selected.sort(
            key=lambda item: item[0],
            reverse=True
        )

        chosen = [
            sentence for score, sentence in selected[:3]
        ]

        # Kaynaktaki sıralamayı koru
        chosen.sort(
            key=lambda sentence: source_text.find(sentence)
        )

        text = " ".join(chosen)
    else:
        text = " ".join(sentences[:2])

    text = text[:3500]

    translated = translate_to_turkish(text)

    if len(translated) > 900:
        translated = translated[:900].rsplit(" ", 1)[0] + "..."

    return translated or "Özet oluşturulamadı."


# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message):
    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
    )

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
        raise RuntimeError(
            "Telegram mesajı gönderilemedi."
        )


# ==========================================
# MESAJ OLUŞTURMA
# ==========================================

def make_message(article):
    title = article["title"]
    summary = article["summary"]
    body = article["body"]

    clubs = find_clubs(
        f"{title} {summary} {body}"
    )

    player = extract_player(title, summary)
    status = classify(title, summary, body)

    fee = extract_fee(
        f"{title} {summary} {body}"
    )

    short_summary = make_short_summary(
        body, summary
    )

    translated_title = translate_to_turkish(title)

    club_text = ", ".join(clubs)

    message = (
        f"{status}\n\n"
        f"👤 Oyuncu: {player}\n"
        f"🏟️ Kulüp: {club_text}\n"
        f"💰 Bonservis: {fee}\n\n"
        f"📰 {article['source']}\n"
        f"📌 {translated_title}\n\n"
        f"📝 {short_summary}\n\n"
        f"🔗 Kaynak:\n{article['link']}"
    )

    return message[:4000]


# ==========================================
# ANA PROGRAM
# ==========================================

def main():
    print("================================")
    print("RATEBROS HABER ANALİZ SİSTEMİ")
    print("================================")

    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Telegram ayarları eksik!"
        )

    seen, seen_sha = load_seen()

    new_articles = []

    for source, feed_url in SOURCES.items():
        print(f"\n{source} kontrol ediliyor...")

        try:
            feed = feedparser.parse(feed_url)

            print(
                f"RSS haber sayısı: {len(feed.entries)}"
            )

            matched = 0

            for entry in feed.entries:
                title = clean_text(
                    entry.get("title", "")
                )

                link = entry.get("link", "")

                if not title or not link:
                    continue

                if link in seen:
                    continue

                rss_summary = clean_text(
                    entry.get("summary", "")
                )

                if not rss_summary and entry.get("content"):
                    rss_summary = clean_text(
                        entry["content"][0].get("value", "")
                    )

                print("Haber okunuyor:", title)

                body = read_article(link)

                # Sayfa okunamazsa RSS özeti kullanılır
                if not body:
                    body = rss_summary

                if not is_transfer_news(
                    title, rss_summary, body
                ):
                    print("Filtrelendi:", title)
                    continue

                matched += 1

                new_articles.append({
                    "source": source,
                    "title": title,
                    "summary": rss_summary,
                    "body": body,
                    "link": link
                })

            print(
                f"{source}: {matched} uygun haber."
            )

        except Exception as error:
            print(
                f"{source} RSS hatası: {error}"
            )

    priority = {
        "RESMÎ TRANSFER": 0,
        "GÜÇLÜ TRANSFER İDDİASI": 1,
        "TRANSFER SÖYLENTİSİ": 2,
        "TRANSFER GELİŞMESİ": 3
    }

    def article_priority(article):
        status = classify(
            article["title"],
            article["summary"],
            article["body"]
        )

        for key, value in priority.items():
            if key in status:
                return value

        return 4

    new_articles.sort(key=article_priority)

    print(
        f"\nToplam yeni uygun haber: {len(new_articles)}"
    )

    sent = 0

    for article in new_articles[:MAX_NEWS_PER_RUN]:
        try:
            message = make_message(article)

            send_telegram(message)

            seen.add(article["link"])
            sent += 1

            print(
                "GÖNDERİLDİ:",
                article["title"]
            )

        except Exception as error:
            print(
                "Haber gönderme hatası:",
                error
            )

    save_seen(seen, seen_sha)

    print("================================")
    print("İŞLEM TAMAMLANDI")
    print(f"Gönderilen haber: {sent}")
    print("================================")


if __name__ == "__main__":
    main()
