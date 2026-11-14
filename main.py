
import os
import re
import json
import time
import base64
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import escape

import requests
import feedparser

# ==============================
# RATEBROS AYARLARI
# ==============================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")

MAX_NEWS = 10
MAX_SEEN = 2000

HEADERS = {"User-Agent": "Mozilla/5.0 RATEBROS"}

RSS_SOURCES = {
    "Marca": "https://e00-marca.uecdn.es/rss/futbol/mercado-fichajes.xml",
    "CaughtOffside": "https://www.caughtoffside.com/feed/",
    "Sky Sports": "https://www.skysports.com/rss/11095",
    "Football Italia": "https://www.football-italia.net/feed/",
    "Get Football News Germany": "https://www.getfootballnewsgermany.com/feed/",
}

# Tek başına "agreed" gibi kelimeler transfer anlamına gelmez.
TRANSFER_WORDS = [
    "transfer", "transfermarkt", "transfer window",
    "signing", "signed for", "signs for",
    "sign for", "set to sign", "set to join",
    "joins", "joined", "loan move", "on loan",
    "contract offer", "new contract", "contract extension",
    "bid for", "offers for", "offer for",
    "deal with", "transfer deal", "move to",
    "fichaje", "fichajes", "ficha por", "fichar por",
    "acuerdo de fichaje", "oferta por", "cesion",
    "mercado de fichajes", "salida del club",
    "wechsel zu", "verpflichtet", "leihe zu",
    "transferiert", "trasferimento", "accordo",
    "offerta per", "transfert", "accord de transfert",
    "signe avec", "arrivee au club",
]

# Alternatif oyuncu isimleri
PLAYER_ALIASES = [
    "Joao Felix", "Joao Cancelo", "Joao Neves",
    "Harry Kane", "Dani Carvajal", "Dani Parejo",
    "David Alaba", "Erling Haaland", "Kylian Mbappe",
    "Vinicius Junior", "Rodrygo Goes", "Mohamed Salah",
    "Kevin De Bruyne", "Bruno Fernandes",
    "Cristiano Ronaldo", "Lionel Messi", "Lamine Yamal",
    "Robert Lewandowski", "Raphinha", "Pedri", "Gavi",
    "Frenkie de Jong", "Nico Williams", "Victor Osimhen",
    "Lautaro Martinez", "Rafael Leao", "Florian Wirtz",
    "Jamal Musiala", "Joshua Kimmich", "Alphonso Davies",
    "Federico Valverde", "Martin Odegaard", "Bukayo Saka",
    "Declan Rice", "Cole Palmer", "Enzo Fernandez",
    "Alexander Isak", "Viktor Gyokeres", "Marcus Rashford",
    "Mauro Icardi", "Baris Alper Yilmaz", "Orkun Kokcu",
    "Kenan Yildiz", "Hakan Calhanoglu", "Arda Guler",
    "Ferdi Kadioglu", "Enes Unal", "Antony", "Neymar",
    "Rodri", "Endrick", "Felix Nmecha",
]

# ==============================
# METİN İŞLEME
# ==============================

def normalize(value):
    value = str(value or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        c for c in value
        if not unicodedata.combining(c)
    )
    value = value.replace("ı", "i")
    return re.findall(r"[a-z0-9]+", value)


def extract_names(data):
    names = set()

    fields = (
        "name", "player_name", "full_name",
        "player", "playerName", "fullName"
    )

    def walk(obj):
        if isinstance(obj, dict):
            for field in fields:
                value = obj.get(field)

                if isinstance(value, str):
                    value = value.strip()

                    if len(value.split()) >= 2 and len(value) >= 5:
                        names.add(value)

            for value in obj.values():
                if isinstance(value, (dict, list)):
                    walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return names


# ==============================
# OYUNCU İNDEKSİ
# ==============================

def load_players():
    names = set(PLAYER_ALIASES)

    try:
        with open("players.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        names.update(extract_names(data))
        print(f"Oyuncu veritabanı: {len(names):,} isim")

    except Exception as error:
        print("Oyuncu veritabanı hatası:", error)

    return names


def build_indexes(names):
    full_index = {}
    surname_candidates = defaultdict(set)

    for name in names:
        tokens = normalize(name)

        if len(tokens) < 2:
            continue

        node = full_index

        for token in tokens:
            node = node.setdefault(token, {})

        node.setdefault("_names", []).append(name)

        surname_candidates[tokens[-1]].add(name)

    # Sadece tek bir oyuncuya ait soyadlarını kullan.
    unique_surnames = {
        surname: next(iter(candidates))
        for surname, candidates in surname_candidates.items()
        if len(candidates) == 1
    }

    print("Oyuncu indeksi hazır.")
    print("Benzersiz soyadı:", len(unique_surnames))

    return full_index, unique_surnames


def find_players(title, indexes):
    full_index, surname_index = indexes
    words = normalize(title)
    found = []

    # Önce tam isim eşleşmesi.
    for start in range(len(words)):
        node = full_index

        for position in range(start, len(words)):
            word = words[position]

            if word not in node:
                break

            node = node[word]

            for name in node.get("_names", []):
                if name not in found:
                    found.append(name)

    # Soyadı eşleşmesi: yalnızca benzersiz soyadları.
    # Soyadından hemen sonra başka bir büyük harfle
    # başlayan isim varsa eşleşmeyi atla.
    raw_words = re.findall(r"\b[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'-]*\b", title)

    for i, raw_word in enumerate(raw_words):
        token = normalize(raw_word)

        if len(token) != 1:
            continue

        surname = token[0]
        name = surname_index.get(surname)

        if not name:
            continue

        if i + 1 < len(raw_words):
            next_word = raw_words[i + 1]

            if next_word[:1].isupper():
                continue

        if name not in found:
            found.append(name)

    return found


# ==============================
# TRANSFER FİLTRESİ
# ==============================

def is_transfer_news(title):
    normalized = " ".join(normalize(title))

    return any(
        " ".join(normalize(term)) in normalized
        for term in TRANSFER_WORDS
    )


# ==============================
# TÜRKÇE ÇEVİRİ
# ==============================

def translate_to_turkish(text):
    if not text:
        return text

    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": "tr",
                "dt": "t",
                "q": text,
            },
            headers=HEADERS,
            timeout=8,
        )

        response.raise_for_status()
        data = response.json()

        translated = "".join(
            part[0]
            for part in data[0]
            if part and part[0]
        )

        return translated.strip() or text

    except Exception as error:
        print("Çeviri yapılamadı:", error)
        return text


# ==============================
# RSS HABERLERİ
# ==============================

def fetch_feed(source, url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=12,
        )
        response.raise_for_status()

        feed = feedparser.parse(response.content)
        articles = []

        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()

            if not title or not link:
                continue

            articles.append({
                "source": source,
                "title": title,
                "link": link,
                "id": entry.get("id") or link,
            })

        print(f"{source}: {len(articles)} haber")
        return articles

    except Exception as error:
        print(f"{source} RSS hatası:", error)
        return []


def get_all_news():
    results = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(fetch_feed, name, url)
            for name, url in RSS_SOURCES.items()
        ]

        for future in as_completed(futures):
            try:
                results.extend(future.result())
            except Exception as error:
                print("RSS sonucu hatası:", error)

    unique = {}

    for article in results:
        unique[article["id"]] = article

    print("Benzersiz haber:", len(unique))
    return list(unique.values())


# ==============================
# GÖRÜLEN HABERLER
# ==============================

def github_url():
    if not GITHUB_REPOSITORY:
        return None

    return (
        f"https://api.github.com/repos/"
        f"{GITHUB_REPOSITORY}/contents/seen.json"
    )


def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_seen():
    url = github_url()

    if url and GITHUB_TOKEN:
        try:
            response = requests.get(
                url,
                headers=github_headers(),
                timeout=12,
            )

            if response.status_code == 200:
                content = response.json()["content"]
                decoded = base64.b64decode(content).decode("utf-8")
                data = json.loads(decoded)

                print("Önceden görülen haber:", len(data))
                return set(data)

        except Exception as error:
            print("GitHub okuma hatası:", error)

    try:
        with open("seen.json", "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    data = list(seen)[-MAX_SEEN:]

    with open("seen.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    url = github_url()

    if not url or not GITHUB_TOKEN:
        return

    try:
        response = requests.get(
            url,
            headers=github_headers(),
            timeout=12,
        )

        sha = None

        if response.status_code == 200:
            sha = response.json().get("sha")
        elif response.status_code != 404:
            print("GitHub okuma hatası:", response.status_code)
            return

        content = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )

        payload = {
            "message": "Update RATEBROS seen news",
            "content": base64.b64encode(
                content.encode("utf-8")
            ).decode("utf-8"),
        }

        if sha:
            payload["sha"] = sha

        result = requests.put(
            url,
            headers=github_headers(),
            json=payload,
            timeout=15,
        )

        if result.status_code in (200, 201):
            print("seen.json kaydedildi.")
        else:
            print("GitHub kayıt hatası:", result.status_code)

    except Exception as error:
        print("GitHub kayıt hatası:", error)


# ==============================
# TELEGRAM
# ==============================

def send_telegram(article, players):
    translated_title = translate_to_turkish(article["title"])

    message = (
        "🚨 <b>RATEBROS TRANSFER ALARMI</b>\n\n"
        "🟡 <b>TRANSFER İDDİASI</b>\n\n"
        f"⚽ <b>Oyuncu:</b> {escape(', '.join(players))}\n"
        f"📰 <b>Haber:</b> {escape(translated_title)}\n"
        f"🌍 <b>Kaynak:</b> {escape(article['source'])}\n\n"
        "⚠️ <b>Transfer resmî olarak doğrulanmadı.</b>\n\n"
        f'<a href="{escape(article["link"], quote=True)}">Haberi Oku</a>'
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
            timeout=15,
        )

        if response.status_code == 200:
            print("Telegram gönderildi:", translated_title)
            return True

        print("Telegram hatası:", response.text[:250])
        return False

    except Exception as error:
        print("Telegram bağlantı hatası:", error)
        return False


# ==============================
# ANA PROGRAM
# ==============================

def main():
    started = time.time()

    print("================================")
    print("RATEBROS BAŞLIYOR")
    print("================================")

    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram ayarları eksik!")
        return

    players = load_players()
    indexes = build_indexes(players)

    print("\nEŞLEŞTİRME TESTLERİ")

    tests = [
        "Alaba ficha por Udinese tras su salida del Real Madrid",
        "Jürgen Klopp confirms Felix Nmecha has agreed to stop controversial goal celebration",
        "Principio de acuerdo Bayern-Kane",
        "Carvajal ya es del Getafe",
    ]

    for title in tests:
        print(title, "=>", find_players(title, indexes))

    print("\nRSS kontrol ediliyor...")

    articles = get_all_news()
    seen = load_seen()

    approved = []

    print("\nHABERLER KONTROL EDİLİYOR")

    for article in articles:
        if article["id"] in seen:
            continue

        if not is_transfer_news(article["title"]):
            continue

        matched = find_players(article["title"], indexes)

        if not matched:
            print("Oyuncu eşleşmedi:", article["title"])
            continue

        print("ONAYLANDI:", article["title"])
        print("Oyuncular:", matched)

        approved.append((article, matched))

    print("\nOnaylanan haber:", len(approved))

    sent = 0

    for article, matched in approved[:MAX_NEWS]:
        if send_telegram(article, matched):
            seen.add(article["id"])
            sent += 1

        time.sleep(1)

    save_seen(seen)

    print("\n================================")
    print("RATEBROS TAMAMLANDI")
    print("Gönderilen:", sent)
    print("Süre:", round(time.time() - started, 1), "saniye")
    print("================================")


if __name__ == "__main__":
    main()
