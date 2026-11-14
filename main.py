
import os
import re
import json
import time
import base64
import hashlib
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import feedparser
from html import escape


# =========================================================
# RATEBROS - TRANSFER HABER BOTU
# =========================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")

PLAYERS_FILE = "players.json"
SEEN_FILE = "seen.json"

MAX_NEWS_PER_RUN = 10
MAX_SEEN_NEWS = 2000

HEADERS = {
    "User-Agent": "Mozilla/5.0 RATEBROS Transfer Bot"
}

RSS_SOURCES = {
    "Marca": "https://e00-marca.uecdn.es/rss/futbol/mercado-fichajes.xml",
    "CaughtOffside": "https://www.caughtoffside.com/feed/",
    "Sky Sports": "https://www.skysports.com/rss/11095",
    "Football Italia": "https://www.football-italia.net/feed/",
    "Get Football News Germany": "https://www.getfootballnewsgermany.com/feed/",
}

TRANSFER_WORDS = [
    "transfer", "transfers", "transfermarkt", "sign", "signing",
    "signed", "signs", "deal", "agreement", "agreed", "bid",
    "offer", "loan", "move", "join", "joined", "leaves",
    "leaving", "exit", "departure", "contract", "rejects",
    "rejected", "keen to", "interested", "interest",
    "fichaje", "fichajes", "ficha", "fichar", "firmar",
    "acuerdo", "oferta", "cesion", "salida", "llegada",
    "mercado", "quiere", "interes", "vuelta",
    "wechsel", "transferiert", "verpflichtet", "leihe",
    "angebot", "vertrag", "verlässt", "interesse",
    "trasferimento", "accordo", "firma", "offerta",
    "cessione", "partenza", "arrivo",
    "transfert", "accord", "signe", "offre",
    "pret", "départ", "arrivée",
    "ya es del", "principio de acuerdo",
    "close to", "set to join", "set to sign",
]

# Bazı önemli oyuncular için alternatif yazımlar.
# Veritabanında bulunmasalar bile bu isimler kontrol edilir.
PLAYER_ALIASES = [
    "Joao Felix",
    "Joao Cancelo",
    "Joao Neves",
    "Jude Bellingham",
    "Harry Kane",
    "Dani Carvajal",
    "Dani Parejo",
    "David Alaba",
    "Erling Haaland",
    "Kylian Mbappe",
    "Kylian Mbappé",
    "Vinicius Junior",
    "Vinicius Jr",
    "Rodrygo Goes",
    "Mohamed Salah",
    "Kevin De Bruyne",
    "Bruno Fernandes",
    "Cristiano Ronaldo",
    "Lionel Messi",
    "Lamine Yamal",
    "Robert Lewandowski",
    "Raphinha",
    "Pedri",
    "Gavi",
    "Frenkie de Jong",
    "Nico Williams",
    "Victor Osimhen",
    "Lautaro Martinez",
    "Rafael Leao",
    "Rafael Leão",
    "Victor Boniface",
    "Florian Wirtz",
    "Jamal Musiala",
    "Joshua Kimmich",
    "Alphonso Davies",
    "Federico Valverde",
    "Martin Odegaard",
    "Bukayo Saka",
    "Declan Rice",
    "Cole Palmer",
    "Enzo Fernandez",
    "Alexander Isak",
    "Viktor Gyokeres",
    "Mason Mount",
    "Marcus Rashford",
    "Antony",
    "Mauro Icardi",
    "Victor Nelsson",
    "Baris Alper Yilmaz",
    "Barış Alper Yılmaz",
    "Orkun Kokcu",
    "Orkun Kökçü",
    "Kenan Yildiz",
    "Kenan Yıldız",
    "Hakan Calhanoglu",
    "Hakan Çalhanoğlu",
    "Arda Guler",
    "Arda Güler",
    "Ferdi Kadioglu",
    "Ferdi Kadıoğlu",
    "Enes Unal",
    "Enes Ünal",
]

# =========================================================
# YARDIMCI FONKSİYONLAR
# =========================================================

def normalize(text):
    if not text:
        return ""

    text = str(text).lower()

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = text.replace("ı", "i")
    text = re.sub(r"[^a-z0-9]+", " ", text)

    return " ".join(text.split())


def contains_phrase(text, phrase):
    text = normalize(text)
    phrase = normalize(phrase)

    if not text or not phrase:
        return False

    return bool(
        re.search(
            r"(?<![a-z0-9])" +
            re.escape(phrase) +
            r"(?![a-z0-9])",
            text
        )
    )


def extract_player_names(data):
    names = set()

    possible_fields = [
        "name",
        "player_name",
        "full_name",
        "player",
        "playerName",
        "fullName",
    ]

    def walk(item):
        if isinstance(item, dict):
            for field in possible_fields:
                value = item.get(field)

                if isinstance(value, str):
                    value = value.strip()

                    # Tek kelimelik isimleri veritabanından almıyoruz.
                    if len(value.split()) >= 2 and len(value) >= 5:
                        names.add(value)

            for value in item.values():
                if isinstance(value, (dict, list)):
                    walk(value)

        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(data)

    return names


def load_players():
    names = set(PLAYER_ALIASES)

    try:
        with open(PLAYERS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        names.update(extract_player_names(data))

        print(f"Oyuncu veritabanı isimleri: {len(names):,}")

    except FileNotFoundError:
        print("UYARI: players.json bulunamadı. Alternatif isimler kullanılacak.")

    except Exception as error:
        print(f"Oyuncu veritabanı okunamadı: {error}")

    return sorted(names, key=len, reverse=True)


def find_players(title, player_names):
    found = []

    normalized_title = normalize(title)

    for player in player_names:
        normalized_player = normalize(player)

        if not normalized_player:
            continue

        if contains_phrase(normalized_title, normalized_player):
            if player not in found:
                found.append(player)

    return found


def is_transfer_news(title):
    normalized_title = normalize(title)

    return any(
        contains_phrase(normalized_title, word)
        for word in TRANSFER_WORDS
    )


# =========================================================
# RSS HABERLERİNİ ÇEK
# =========================================================

def fetch_feed(source_name, url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        response.raise_for_status()

        feed = feedparser.parse(response.content)

        articles = []

        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()

            if not title or not link:
                continue

            article_id = entry.get("id") or link

            articles.append({
                "source": source_name,
                "title": title,
                "link": link,
                "id": article_id,
            })

        print(f"{source_name}: {len(articles)} haber")

        return articles

    except Exception as error:
        print(f"{source_name} RSS hatası: {error}")
        return []


def get_all_news():
    all_news = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(fetch_feed, name, url): name
            for name, url in RSS_SOURCES.items()
        }

        for future in as_completed(futures):
            try:
                all_news.extend(future.result())
            except Exception as error:
                print(f"RSS sonucu alınamadı: {error}")

    unique = {}
    for article in all_news:
        unique[article["id"]] = article

    news = list(unique.values())

    print(f"Toplam benzersiz RSS haberi: {len(news)}")

    return news


# =========================================================
# GITHUB ÜZERİNDE GÖRÜLEN HABERLERİ SAKLA
# =========================================================

def github_api_url():
    if not GITHUB_REPOSITORY:
        return None

    return (
        "https://api.github.com/repos/"
        + GITHUB_REPOSITORY
        + "/contents/"
        + SEEN_FILE
    )


def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_seen():
    url = github_api_url()

    if url and GITHUB_TOKEN:
        try:
            response = requests.get(
                url,
                headers=github_headers(),
                timeout=15
            )

            if response.status_code == 200:
                content = response.json()["content"]
                decoded = base64.b64decode(content).decode("utf-8")
                data = json.loads(decoded)

                print(f"Önceden görülen haber: {len(data)}")
                return set(data)

            if response.status_code != 404:
                print("GitHub seen.json okunamadı:", response.status_code)

        except Exception as error:
            print("GitHub seen.json hatası:", error)

    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        print(f"Yerel görülen haber: {len(data)}")
        return set(data)

    except Exception:
        return set()


def save_seen(seen):
    seen_list = list(seen)[-MAX_SEEN_NEWS:]

    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as file:
            json.dump(seen_list, file, ensure_ascii=False, indent=2)
    except Exception as error:
        print("Yerel seen.json kaydedilemedi:", error)

    url = github_api_url()

    if not url or not GITHUB_TOKEN:
        print("GitHub token/repository bulunamadı; yerel kayıt kullanıldı.")
        return

    try:
        # Mevcut dosyanın SHA değerini al.
        response = requests.get(
            url,
            headers=github_headers(),
            timeout=15
        )

        sha = None

        if response.status_code == 200:
            sha = response.json().get("sha")
        elif response.status_code != 404:
            print("GitHub SHA alınamadı:", response.status_code)
            return

        content = json.dumps(
            seen_list,
            ensure_ascii=False,
            indent=2
        )

        encoded = base64.b64encode(
            content.encode("utf-8")
        ).decode("utf-8")

        payload = {
            "message": "Update seen transfer news",
            "content": encoded,
        }

        if sha:
            payload["sha"] = sha

        result = requests.put(
            url,
            headers=github_headers(),
            json=payload,
            timeout=20
        )

        if result.status_code in (200, 201):
            print("seen.json GitHub'a kaydedildi.")
        else:
            print(
                "GitHub kayıt hatası:",
                result.status_code,
                result.text[:300]
            )

    except Exception as error:
        print("GitHub kayıt hatası:", error)


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(article, players):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram token veya chat ID eksik!")
        return False

    player_text = ", ".join(players)

    message = (
        "🚨 <b>RATEBROS TRANSFER ALARMI</b>\n\n"
        f"⚽ <b>Oyuncu:</b> {escape(player_text)}\n"
        f"📰 <b>Haber:</b> {escape(article['title'])}\n"
        f"🌍 <b>Kaynak:</b> {escape(article['source'])}\n\n"
        f'🔗 <a href="{escape(article["link"], quote=True)}">'
        "Haberi Oku</a>"
    )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20
        )

        if response.status_code == 200:
            print("Telegram'a gönderildi:", article["title"])
            return True

        print("Telegram hatası:", response.text[:300])
        return False

    except Exception as error:
        print("Telegram bağlantı hatası:", error)
        return False


# =========================================================
# ANA PROGRAM
# =========================================================

def main():
    print("=" * 50)
    print("RATEBROS BAŞLIYOR")
    print("=" * 50)

    if not BOT_TOKEN or not CHAT_ID:
        print("HATA: TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik!")
        return

    start_time = time.time()

    player_names = load_players()

    print(f"Kontrol edilen oyuncu ismi: {len(player_names):,}")

    # İsim eşleştirme testi
    test_names = [
        "Joao Felix",
        "Harry Kane",
        "Dani Carvajal",
        "Dani Parejo",
        "Erling Haaland",
        "David Alaba",
    ]

    print("\nOYUNCU EŞLEŞTİRME TESTİ")

    for test_name in test_names:
        result = find_players(test_name, player_names)
        print(f"TEST {test_name}: {result[:3]}")

    print("\nRSS kaynakları kontrol ediliyor...")

    news = get_all_news()

    seen = load_seen()

    print("\nHABERLER FİLTRELENİYOR")

    approved = []

    for article in news:
        title = article["title"]
        article_id = article["id"]

        if article_id in seen:
            continue

        matched_players = find_players(title, player_names)

        if not matched_players:
            print(f"ELENDİ - Oyuncu bulunamadı: {title}")
            continue

        if not is_transfer_news(title):
            print(f"ELENDİ - Transfer haberi değil: {title}")
            continue

        print(f"ONAYLANDI: {title}")
        print(f"Bulunan oyuncular: {matched_players}")

        approved.append((article, matched_players))

    print(f"\nDoğrulamayı geçen haber: {len(approved)}")

    sent_count = 0

    for article, players in approved[:MAX_NEWS_PER_RUN]:
        success = send_telegram(article, players)

        if success:
            seen.add(article["id"])
            sent_count += 1

        time.sleep(1)

    save_seen(seen)

    elapsed = round(time.time() - start_time, 1)

    print("\n" + "=" * 50)
    print("RATEBROS BİTTİ")
    print(f"Gönderilen haber: {sent_count}")
    print(f"Toplam süre: {elapsed} saniye")
    print("=" * 50)


if __name__ == "__main__":
    main()
