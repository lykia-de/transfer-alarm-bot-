
import os
import re
import json
import html
import time
import base64
import unicodedata
from urllib.parse import quote

import requests
import feedparser
from bs4 import BeautifulSoup


# =========================
# RATEBROS AYARLARI
# =========================

PLAYER_FILE = "players.json"
MAX_NEWS_PER_RUN = 10
MAX_SEEN_LINKS = 3000

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")
GITHUB_REF_NAME = os.getenv("GITHUB_REF_NAME", "main")

SEEN_FILE = "seen.json"

RSS_SOURCES = {
    "Marca": "https://e00-marca.uecdn.es/rss/futbol/mercado-fichajes.xml",
    "CaughtOffside": "https://www.caughtoffside.com/feed/",
    "Sky Sports": "https://www.skysports.com/rss/11095",
    "Football Italia": "https://www.football-italia.net/feed/",
    "Get Football News Germany": "https://www.getfootballnewsgermany.com/feed/",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 RATEBROS Football News Bot"
}

CLUBS = [
    "Real Madrid", "Barcelona", "Atletico Madrid",
    "Arsenal", "Manchester City", "Manchester United",
    "Liverpool", "Chelsea", "Tottenham", "Newcastle",
    "Bayern Munich", "Borussia Dortmund", "Bayer Leverkusen",
    "RB Leipzig", "Paris Saint-Germain", "PSG",
    "Inter Milan", "Inter", "AC Milan", "Juventus",
    "Napoli", "Roma", "Beşiktaş", "Besiktas",
    "Galatasaray", "Fenerbahçe", "Fenerbahce",
    "Trabzonspor", "Ajax", "Benfica", "Porto",
    "Sporting CP", "Al Nassr", "Al Hilal",
    "Al Ittihad", "Al Ahli", "Getafe", "Udinese",
    "Wolfsburg", "Southampton",
]

TRANSFER_WORDS = [
    # İngilizce
    "transfer", "transfers", "sign", "signing", "signed",
    "signs", "join", "joins", "joined", "move", "moves",
    "moving", "deal", "agreement", "agreed", "bid",
    "offer", "interest", "interested", "target",
    "negotiations", "loan", "permanent", "exit",
    "departure", "release clause", "contract offer",
    "contract talks", "set to join", "close to signing",

    # İspanyolca
    "fichaje", "fichajes", "ficha", "fichar",
    "acuerdo", "oferta", "interes", "interés",
    "negociaciones", "traspaso", "cesion", "cesión",
    "llegada", "salida", "firmar", "renovacion",
    "renovación", "mercado",

    # Almanca
    "wechsel", "wechseln", "verpflichtung",
    "verpflichtet", "leihe", "ausleihe",
    "angebot", "interesse", "verhandlungen",
    "unterschreibt", "verlängert", "transferiert",

    # İtalyanca
    "accordo", "prestito", "ingaggio",
    "trattativa", "trattative", "firma",
    "firmare", "interesse", "offerta",
    "cessione", "rinnovo", "acquisto",

    # Fransızca
    "transfert", "accord", "accordo",
    "prêt", "offre", "intérêt", "rejoint",
]

BAD_TITLE_WORDS = [
    "highlights", "match report", "player ratings",
    "predicted lineup", "starting lineup",
    "injury update", "injury news",
    "reaction", "analysis", "watch",
    "wonderkid record", "goal of the season",
]

MANAGER_WORDS = [
    "manager", "head coach", "coach",
    "managerial", "managerial role",
    "sacked", "appointed as manager",
]


# =========================
# METİN İŞLEME
# =========================

def normalize(text):
    text = str(text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        c for c in text
        if not unicodedata.combining(c)
    )
    text = text.replace("ß", "ss")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_phrase(text, phrase):
    text = normalize(text)
    phrase = normalize(phrase)

    if not phrase:
        return False

    return bool(
        re.search(
            r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])",
            text
        )
    )


def contains_transfer_word(text):
    normalized = normalize(text)

    for word in TRANSFER_WORDS:
        if contains_phrase(normalized, word):
            return True

    return False


# =========================
# OYUNCU VERİTABANI
# =========================

def load_players():
    if not os.path.exists(PLAYER_FILE):
        raise RuntimeError("players.json bulunamadı!")

    with open(PLAYER_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = data.get("players", [])
    else:
        records = []

    players = []
    name_index = {}

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

        names = [name] + [
            str(alias).strip()
            for alias in aliases
            if str(alias).strip()
        ]

        player = {
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
            "market_value": item.get("current_market_value"),
        }

        players.append(player)

        for player_name in names:
            normalized = normalize(player_name)

            # Tek harfli veya çok kısa isimleri kullanma.
            if len(normalized.replace(" ", "")) < 5:
                continue

            name_index.setdefault(normalized, []).append(player)

    print(f"Oyuncu veritabanı: {len(players):,} oyuncu")
    print(f"İsim eşleşmeleri: {len(name_index):,}")

    return players, name_index


def find_title_players(text, name_index):
    normalized = normalize(text)
    found = {}

    # İsimleri uzun olandan kısa olana doğru kontrol et.
    for player_name in sorted(
        name_index.keys(),
        key=len,
        reverse=True
    ):
        if not contains_phrase(normalized, player_name):
            continue

        for player in name_index[player_name]:
            key = str(
                player.get("player_id")
                or player["name"]
            )
            found[key] = player

    return list(found.values())


# =========================
# KULÜP KONTROLÜ
# =========================

def find_clubs(text):
    found = []

    for club in CLUBS:
        if contains_phrase(text, club):
            if club not in found:
                found.append(club)

    return found


# =========================
# RSS HABERLERİ
# =========================

def get_feed_entries():
    all_entries = []
    seen_links = set()

    for source_name, url in RSS_SOURCES.items():
        print(f"\nKaynak kontrol ediliyor: {source_name}")

        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=20
            )
            response.raise_for_status()

            feed = feedparser.parse(response.content)

            for entry in feed.entries:
                link = str(
                    getattr(entry, "link", "")
                ).strip()

                if not link or link in seen_links:
                    continue

                seen_links.add(link)

                all_entries.append({
                    "source": source_name,
                    "title": str(
                        getattr(entry, "title", "")
                    ).strip(),
                    "summary": str(
                        getattr(entry, "summary", "")
                    ).strip(),
                    "link": link,
                })

            print(
                f"Bulunan haber: {len(feed.entries)}"
            )

        except Exception as e:
            print(f"Kaynak hatası: {e}")

    return all_entries


# =========================
# HABER SAYFASINI OKU
# =========================

def read_article(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )
        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        for element in soup([
            "script", "style", "nav",
            "footer", "header", "aside"
        ]):
            element.decompose()

        article = soup.find("article")

        if article:
            text = article.get_text(" ", strip=True)
        else:
            text = soup.get_text(" ", strip=True)

        return re.sub(r"\s+", " ", text)[:12000]

    except Exception as e:
        print(f"Sayfa okunamadı: {e}")
        return ""


# =========================
# HABER DOĞRULAMA
# =========================

def validate_article(article, name_index):
    title = article["title"]
    summary = article["summary"]
    source = article["source"]

    title_normalized = normalize(title)
    summary_normalized = normalize(summary)

    combined = f"{title} {summary}"

    if any(
        contains_phrase(title_normalized, word)
        for word in BAD_TITLE_WORDS
    ):
        return None

    title_players = find_title_players(
        title,
        name_index
    )

    if not title_players:
        print("Reddedildi: Başlıkta oyuncu bulunamadı.")
        return None

    # Başlıkta oyuncu var ama transfer işareti yoksa
    # haber metnini de kontrol et.
    transfer_found = contains_transfer_word(combined)

    body = ""

    if not transfer_found or len(title_players) > 1:
        body = read_article(article["link"])

    full_text = f"{title} {summary} {body}"

    if not contains_transfer_word(full_text):
        print("Reddedildi: Transfer ifadesi bulunamadı.")
        return None

    # Teknik direktör haberlerini ele.
    title_has_manager = any(
        contains_phrase(title_normalized, word)
        for word in MANAGER_WORDS
    )

    if title_has_manager and not any(
        contains_phrase(title_normalized, word)
        for word in [
            "player", "sign", "transfer",
            "join", "fichaje", "wechsel"
        ]
    ):
        print("Reddedildi: Teknik direktör haberi.")
        return None

    clubs = find_clubs(full_text)

    if not clubs:
        print("Reddedildi: Takip edilen kulüp bulunamadı.")
        return None

    # Birden fazla oyuncu varsa metinde transfer
    # ifadesiyle bağlantısı daha güçlü olanı seç.
    selected_player = None

    if len(title_players) == 1:
        selected_player = title_players[0]
    else:
        body_normalized = normalize(body or summary)

        scored = []

        for player in title_players:
            score = 0

            for name in player["names"]:
                normalized_name = normalize(name)

                if contains_phrase(body_normalized, normalized_name):
                    score += 2

                if contains_phrase(title_normalized, normalized_name):
                    score += 1

            player_club = normalize(player.get("club", ""))

            if player_club and player_club in normalize(full_text):
                score += 1

            scored.append((score, player))

        scored.sort(
            key=lambda item: item[0],
            reverse=True
        )

        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            print("Reddedildi: Birden fazla oyuncu eşit derecede olası.")
            return None

        selected_player = scored[0][1]

    if not selected_player:
        return None

    return {
        "player": selected_player,
        "clubs": clubs,
        "body": body,
        "source": source,
    }


# =========================
# ÜCRET BULMA
# =========================

def extract_fee(text):
    patterns = [
        r"€\s?\d+(?:[.,]\d+)?\s?(?:m|million|bn|billion)?",
        r"£\s?\d+(?:[.,]\d+)?\s?(?:m|million|bn|billion)?",
        r"\$\s?\d+(?:[.,]\d+)?\s?(?:m|million|bn|billion)?",
        r"\d+(?:[.,]\d+)?\s?(?:million|m|billion|bn)\s?(?:euros|euro|pounds)?",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        if match:
            return match.group(0)

    return None


# =========================
# TÜRKÇE ÇEVİRİ
# =========================

def translate_text(text):
    if not text:
        return ""

    try:
        url = (
            "https://translate.googleapis.com/translate_a/single"
            "?client=gtx&sl=auto&tl=tr&dt=t&q="
            + quote(text[:3000])
        )

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=12
        )

        response.raise_for_status()
        data = response.json()

        translated = "".join(
            part[0]
            for part in data[0]
            if part and part[0]
        )

        return translated.strip() or text

    except Exception:
        return text


# =========================
# TELEGRAM MESAJI
# =========================

def build_message(article, verification):
    player = verification["player"]
    title = article["title"]
    summary = article["summary"]
    body = verification["body"]

    translated_title = translate_text(title)

    source_text = summary or body[:700]

    translated_summary = translate_text(
        source_text[:2500]
    )

    fee = extract_fee(
        f"{title} {summary} {body}"
    )

    player_name = html.escape(player["name"])
    safe_title = html.escape(translated_title)
    safe_summary = html.escape(translated_summary)
    safe_source = html.escape(article["source"])
    safe_link = html.escape(article["link"], quote=True)

    message = (
        "⚽ <b>RATEBROS | TRANSFER HABERİ</b>\n\n"
        f"👤 <b>Oyuncu:</b> {player_name}\n"
        f"🏟 <b>İlgili kulüp:</b> "
        f"{html.escape(', '.join(verification['clubs']))}\n\n"
        f"📰 <b>{safe_title}</b>\n\n"
        f"{safe_summary[:1800]}\n\n"
    )

    if fee:
        message += (
            f"💰 <b>Haberde geçen ücret:</b> "
            f"{html.escape(fee)}\n"
        )

    message += (
        f"\n🌐 <b>Kaynak:</b> {safe_source}\n"
        f'🔗 <a href="{safe_link}">Haberi oku</a>'
    )

    return message[:3900]


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "Telegram secret bilgileri eksik!"
        )

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=20
    )

    if not response.ok:
        print("Telegram hatası:", response.text)
        response.raise_for_status()

    return True


# =========================
# GITHUB SEEN.JSON
# =========================

def github_api_url():
    if not GITHUB_REPOSITORY:
        return None

    return (
        "https://api.github.com/repos/"
        f"{GITHUB_REPOSITORY}/contents/{SEEN_FILE}"
    )


def github_headers():
    headers = {
        "Accept": "application/vnd.github+json"
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = (
            f"Bearer {GITHUB_TOKEN}"
        )

    return headers


def load_seen():
    local_seen = []

    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                local_seen = data

        except Exception:
            pass

    api_url = github_api_url()

    if not api_url or not GITHUB_TOKEN:
        return set(local_seen)

    try:
        response = requests.get(
            api_url,
            headers=github_headers(),
            timeout=15
        )

        if response.status_code == 200:
            content = response.json()

            decoded = base64.b64decode(
                content["content"]
            ).decode("utf-8")

            data = json.loads(decoded)

            if isinstance(data, list):
                local_seen.extend(data)

    except Exception as e:
        print("GitHub seen.json okunamadı:", e)

    return set(local_seen)


def save_seen(seen):
    data = list(seen)[-MAX_SEEN_LINKS:]

    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    api_url = github_api_url()

    if not api_url or not GITHUB_TOKEN:
        return

    try:
        response = requests.get(
            api_url,
            headers=github_headers(),
            timeout=15
        )

        sha = None

        if response.status_code == 200:
            sha = response.json().get("sha")

        content = base64.b64encode(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2
            ).encode("utf-8")
        ).decode("utf-8")

        payload = {
            "message": "Update RATEBROS seen links",
            "content": content,
            "branch": GITHUB_REF_NAME,
        }

        if sha:
            payload["sha"] = sha

        result = requests.put(
            api_url,
            headers=github_headers(),
            json=payload,
            timeout=20
        )

        if not result.ok:
            print("GitHub kayıt hatası:", result.text)
        else:
            print("seen.json GitHub'a kaydedildi.")

    except Exception as e:
        print("GitHub seen.json kaydedilemedi:", e)


# =========================
# ANA PROGRAM
# =========================

def main():
    print("\n============================")
    print("      RATEBROS BAŞLIYOR")
    print("============================\n")

    players, name_index = load_players()

    seen = load_seen()

    print(f"Önceden görülen haber: {len(seen)}")

    entries = get_feed_entries()

    print(f"\nToplam benzersiz RSS haberi: {len(entries)}")

    verified = []

    for article in entries:
        link = article["link"]

        if link in seen:
            continue

        print(f"\nKontrol: {article['title']}")

        result = validate_article(
            article,
            name_index
        )

        if result:
            print(
                "DOĞRULANDI:",
                result["player"]["name"]
            )

            verified.append(
                (article, result)
            )

        time.sleep(0.2)

    print(
        f"\nDoğrulamayı geçen haber: {len(verified)}"
    )

    sent = 0

    for article, result in verified[:MAX_NEWS_PER_RUN]:
        try:
            message = build_message(
                article,
                result
            )

            send_telegram(message)

            seen.add(article["link"])
            sent += 1

            print(
                "Telegram'a gönderildi:",
                article["title"]
            )

            time.sleep(1)

        except Exception as e:
            print("Gönderim hatası:", e)

    save_seen(seen)

    print("\n============================")
    print("       RATEBROS BİTTİ")
    print("============================")
    print(f"Gönderilen haber: {sent}")


if __name__ == "__main__":
    main()
