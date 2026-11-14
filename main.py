
import os
import re
import json
import base64
import html
import unicodedata
import requests
import feedparser

from datetime import datetime, timezone
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
PLAYER_FILE = "players.json"

MAX_NEWS_PER_RUN = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 Chrome/120 Safari/537.36"
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
    "Barcelona": ["Barcelona", "FC Barcelona"],
    "Atletico Madrid": ["Atletico Madrid", "Atlético Madrid"],
    "Arsenal": ["Arsenal"],
    "Manchester City": ["Manchester City", "Man City"],
    "Manchester United": ["Manchester United", "Man United", "Man Utd"],
    "Liverpool": ["Liverpool"],
    "Chelsea": ["Chelsea"],
    "Tottenham": ["Tottenham", "Spurs"],
    "Newcastle": ["Newcastle United"],
    "Bayern Munich": ["Bayern Munich", "Bayern"],
    "Borussia Dortmund": ["Borussia Dortmund", "Dortmund"],
    "Bayer Leverkusen": ["Bayer Leverkusen", "Leverkusen"],
    "RB Leipzig": ["RB Leipzig"],
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
    "transfer", "signing", "signed for", "signs for",
    "deal", "bid", "offer", "loan", "departure",
    "exit", "target", "interest", "interested",
    "talks", "negotiations", "agreement",
    "release clause", "move to", "join", "joining",
    "set to leave", "wants to leave", "could leave",
    "will leave", "loan deal", "buy option",
    "option to buy", "purchase option", "recall",
    "renewal", "extends contract", "contract extension",
    "wechsel", "verpflichten", "leihe", "vertrag",
    "accordo", "prestito", "ingaggio",
    "fichar", "cesión", "traspaso", "salida",
    "salir", "oferta", "enero", "mercato",
    "mercado", "fichajes"
]

OFFICIAL_WORDS = [
    "officially signed", "official transfer",
    "completed transfer", "completes move",
    "has signed for", "joins on loan",
    "signs a contract", "official announcement"
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

MANAGER_WORDS = [
    "manager appointed", "appoints manager",
    "new head coach", "head coach appointed",
    "manager sacked", "coach sacked",
    "manager leaves", "coach leaves",
    "named manager", "named head coach",
    "managerial appointment", "coach appointment",
    "appointing a manager", "appointing a coach",
    "technical director appointed"
]

BAD_TITLE_WORDS = [
    "match report", "starting line-up", "starting lineup",
    "predicted lineup", "predicted line-up",
    "live blog", "transfer centre live",
    "transfer center live", "highlights",
    "player ratings", "press conference",
    "post-match", "starting xi"
]


# ==========================================
# METİN İŞLEME
# ==========================================

def normalize(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(
        c for c in text if not unicodedata.combining(c)
    )
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_text(text):
    if not text:
        return ""

    soup = BeautifulSoup(str(text), "html.parser")
    text = soup.get_text(" ", strip=True)
    text = html.unescape(text)

    return re.sub(r"\s+", " ", text).strip()


def contains_phrase(text, phrase):
    text = normalize(text)
    phrase = normalize(phrase)

    if not phrase:
        return False

    return f" {phrase} " in f" {text} "


def split_sentences(text):
    return [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", text or "")
        if len(s.strip()) > 25
    ]


# ==========================================
# OYUNCU VERİTABANI
# ==========================================

def load_players():
    if not os.path.exists(PLAYER_FILE):
        raise RuntimeError("players.json bulunamadı!")

    with open(PLAYER_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    # Yeni format: doğrudan liste
    if isinstance(data, list):
        records = data

    # Eski format: {"players": [...]}
    elif isinstance(data, dict):
        records = data.get("players", [])

    else:
        records = []

    if not records:
        raise RuntimeError("Oyuncu veritabanı boş!")

    players = []

    for item in records:
        if not isinstance(item, dict):
            continue

        name = (
            item.get("name")
            or item.get("player_name")
            or item.get("full_name")
            or ""
        )

        name = str(name).strip()

        if not name:
            continue

        aliases = item.get("aliases", [])

        if isinstance(aliases, str):
            aliases = [aliases]

        names = [name]

        for alias in aliases:
            alias = str(alias).strip()

            if alias and alias not in names:
                names.append(alias)

        players.append({
            "name": name,
            "names": names,
            "club": str(
                item.get("club")
                or item.get("current_club_name")
                or ""
            ).strip(),
            "player_id": item.get("player_id"),
            "position": item.get("position", ""),
            "country": item.get("country", ""),
            "market_value": item.get("current_market_value")
        })

    if not players:
        raise RuntimeError("Oyuncular okunamadı!")

    print(f"Oyuncu veritabanı: {len(players):,} oyuncu")

    return players


# ==========================================
# OYUNCU TESPİTİ
# ==========================================

def find_title_players(title, players):
    text = normalize(title)
    matches = {}

    for player in players:
        for name in player["names"]:
            normalized_name = normalize(name)

            if len(normalized_name) < 5:
                continue

            if f" {normalized_name} " in f" {text} ":
                matches[player["name"]] = player
                break

    results = list(matches.values())

    filtered = []

    for player in results:
        player_name = normalize(player["name"])

        is_part_of_longer = any(
            player_name != normalize(other["name"])
            and f" {player_name} " in
            f" {normalize(other['name'])} "
            for other in results
        )

        if not is_part_of_longer:
            filtered.append(player)

    return filtered


# ==========================================
# KULÜP TESPİTİ
# ==========================================

def find_clubs(text):
    found = []

    for club, aliases in CLUBS.items():
        for alias in aliases:
            if contains_phrase(text, alias):
                found.append(club)
                break

    return list(dict.fromkeys(found))


# ==========================================
# HABER SAYFASI
# ==========================================

def read_article(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for element in soup.select(
            "script, style, nav, footer, header, aside, "
            "iframe, form, .advertisement, .advert, "
            ".social-share, .related-articles"
        ):
            element.decompose()

        selectors = [
            '[itemprop="articleBody"]',
            "article",
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
# TRANSFER DOĞRULAMA
# ==========================================

def has_transfer_words(text):
    return any(
        contains_phrase(text, word)
        for word in TRANSFER_WORDS
    )


def is_manager_news(text):
    return any(
        contains_phrase(text, word)
        for word in MANAGER_WORDS
    )


def validate_article(title, summary, body, players):

    if any(
        contains_phrase(title, word)
        for word in BAD_TITLE_WORDS
    ):
        return None

    if is_manager_news(title):
        return None

    title_players = find_title_players(title, players)

    if len(title_players) != 1:
        print("Reddedildi: Başlıkta tek oyuncu bulunamadı.")
        return None

    player = title_players[0]

    full_text = f"{title}. {summary}. {body}"
    sentences = split_sentences(full_text)

    player_sentences = []

    for index, sentence in enumerate(sentences):
        if any(
            contains_phrase(sentence, name)
            for name in player["names"]
        ):
            player_sentences.append(index)

    if not player_sentences:
        print("Reddedildi: Oyuncu haber gövdesinde yok.")
        return None

    relevant_indices = set()

    for index in player_sentences:
        for nearby in (index - 1, index, index + 1):
            if 0 <= nearby < len(sentences):
                relevant_indices.add(nearby)

    relevant_sentences = [
        sentences[i] for i in sorted(relevant_indices)
    ]

    evidence_text = " ".join(relevant_sentences)

    if not has_transfer_words(evidence_text):
        print("Reddedildi: Transfer ifadesi bulunamadı.")
        return None

    if is_manager_news(evidence_text):
        return None

    clubs = find_clubs(f"{title}. {evidence_text}")

    if not clubs:
        print("Reddedildi: Takip edilen kulüp bulunamadı.")
        return None

    return {
        "player": player,
        "clubs": clubs,
        "sentences": relevant_sentences,
        "evidence": evidence_text
    }


# ==========================================
# SINIFLANDIRMA
# ==========================================

def classify(evidence):
    text = normalize(evidence)

    if any(
        contains_phrase(text, word)
        for word in OFFICIAL_WORDS
    ):
        return "⚽ RESMÎ TRANSFER"

    if any(
        contains_phrase(text, word)
        for word in STRONG_WORDS
    ):
        return "🔥 GÜÇLÜ TRANSFER İDDİASI"

    if any(
        contains_phrase(text, word)
        for word in RUMOR_WORDS
    ):
        return "🟠 TRANSFER SÖYLENTİSİ"

    return "⚽ TRANSFER GELİŞMESİ"


# ==========================================
# BONSERVİS
# ==========================================

def extract_fee(evidence):
    patterns = [
        r"(?:€|£)\s?\d+(?:[.,]\d+)?\s?(?:million|m|billion|bn)",
        r"\d+(?:[.,]\d+)?\s?(?:million|m|billion|bn)\s?(?:euros|pounds)",
        r"(?:€|£)\s?\d{1,3}(?:[.,]\d{3})+"
    ]

    for pattern in patterns:
        match = re.search(
            pattern, evidence, re.IGNORECASE
        )

        if match:
            return match.group(0)

    return "Açıklanmadı"


# ==========================================
# TÜRKÇE ÇEVİRİ
# ==========================================

def translate_to_turkish(text):
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
        ).strip()

    except Exception as error:
        print("Çeviri hatası:", error)
        return text


def make_summary(sentences):
    text = " ".join(sentences[:3])
    translated = translate_to_turkish(text)

    if len(translated) > 900:
        translated = translated[:900].rsplit(" ", 1)[0] + "..."

    return translated or "Özet oluşturulamadı."


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
        url,
        headers=github_headers(),
        timeout=20
    )

    if response.status_code == 404:
        return set(), None

    response.raise_for_status()

    data = response.json()

    content = base64.b64decode(
        data["content"]
    ).decode("utf-8")

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
# TELEGRAM
# ==========================================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Telegram ayarları eksik!")

    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True
        },
        timeout=20
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram hatası: {result}"
        )


# ==========================================
# MESAJ OLUŞTURMA
# ==========================================

def make_message(article, validation):
    player = validation["player"]["name"]
    clubs = ", ".join(validation["clubs"])

    evidence = validation["evidence"]

    status = classify(evidence)
    fee = extract_fee(evidence)

    translated_title = translate_to_turkish(
        article["title"]
    )

    summary = make_summary(
        validation["sentences"]
    )

    return (
        f"{status}\n\n"
        f"👤 Oyuncu: {player}\n"
        f"🏟️ İlgili kulüp: {clubs}\n"
        f"💰 Bonservis: {fee}\n\n"
        f"📰 Kaynak: {article['source']}\n"
        f"📌 {translated_title}\n\n"
        f"📝 {summary}\n\n"
        f"🔗 Kaynak:\n{article['link']}"
    )[:4000]


# ==========================================
# ANA PROGRAM
# ==========================================

def main():
    print("================================")
    print("RATEBROS - DOĞRULAMALI HABER SİSTEMİ")
    print("================================")

    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Telegram ayarları eksik!")

    players = load_players()
    seen, seen_sha = load_seen()

    new_articles = []

    for source, feed_url in SOURCES.items():

        print(f"\n{source} kontrol ediliyor...")

        try:
            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                print("RSS okunamadı:", source)
                continue

            for entry in feed.entries:

                title = clean_text(entry.get("title", ""))
                link = entry.get("link", "")

                if not title or not link or link in seen:
                    continue

                rss_summary = clean_text(
                    entry.get("summary", "")
                )

                if not rss_summary and entry.get("content"):
                    rss_summary = clean_text(
                        entry["content"][0].get("value", "")
                    )

                print("Kontrol:", title)

                body = read_article(link)

                if not body:
                    print("Reddedildi: Haber gövdesi okunamadı.")
                    continue

                validation = validate_article(
                    title,
                    rss_summary,
                    body,
                    players
                )

                if not validation:
                    print("Haber reddedildi.")
                    continue

                new_articles.append({
                    "source": source,
                    "title": title,
                    "summary": rss_summary,
                    "body": body,
                    "link": link,
                    "validation": validation
                })

        except Exception as error:
            print(f"{source} RSS hatası: {error}")

    # Aynı link birden fazla RSS kaynağında varsa tekilleştir.
    unique_articles = {}
    for article in new_articles:
        unique_articles.setdefault(article["link"], article)

    new_articles = list(unique_articles.values())

    print(
        f"\nDoğrulamayı geçen benzersiz haber: "
        f"{len(new_articles)}"
    )

    sent = 0

    for article in new_articles[:MAX_NEWS_PER_RUN]:

        try:
            message = make_message(
                article,
                article["validation"]
            )

            send_telegram(message)

            seen.add(article["link"])
            sent += 1

            print("GÖNDERİLDİ:", article["title"])

        except Exception as error:
            print("Gönderme hatası:", error)

    save_seen(seen, seen_sha)

    print("================================")
    print("İŞLEM TAMAMLANDI")
    print("Gönderilen haber:", sent)
    print("================================")


if __name__ == "__main__":
    main()
