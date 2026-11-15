
import os
import re
import json
import time
import base64
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import escape
from urllib.parse import urlsplit, urlunsplit

import requests
import feedparser

# ==========================================
# RATEBROS AYARLARI
# ==========================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")

MAX_NEWS = 10
MAX_SEEN = 3000
MAX_WORKERS = 12
HEADERS = {"User-Agent": "Mozilla/5.0 RATEBROS"}

RSS_SOURCES = {
    "Marca": "https://e00-marca.uecdn.es/rss/futbol/mercado-fichajes.xml",
    "CaughtOffside": "https://www.caughtoffside.com/feed/",
    "Sky Sports": "https://www.skysports.com/rss/11095",
    "Football Italia": "https://www.football-italia.net/feed/",
    "Get Football News Germany": "https://www.getfootballnewsgermany.com/feed/",
    "A Spor": "https://www.aspor.com.tr/rss/news.xml",
    "A Spor Futbol": "https://www.aspor.com.tr/rss/futbol.xml",
    "A Spor Süper Lig": "https://www.aspor.com.tr/rss/spor-toto-super-lig.xml",
    "A Spor Beşiktaş": "https://www.aspor.com.tr/rss/besiktas.xml",
    "A Spor Fenerbahçe": "https://www.aspor.com.tr/rss/fenerbahce.xml",
    "A Spor Galatasaray": "https://www.aspor.com.tr/rss/galatasaray.xml",
    "A Spor Trabzonspor": "https://www.aspor.com.tr/rss/trabzonspor.xml",
    "OrtaPas": "https://ortapas.com/rss",
    "OrtaPas Transfer": "https://ortapas.com/rss/transfer",
    "OrtaPas Süper Lig": "https://ortapas.com/rss/super-lig",
    "OrtaPas Beşiktaş": "https://ortapas.com/rss/besiktas",
    "OrtaPas Galatasaray": "https://ortapas.com/rss/galatasaray",
    "OrtaPas Fenerbahçe": "https://ortapas.com/rss/fenerbahce",
    "OrtaPas Trabzonspor": "https://ortapas.com/rss/trabzonspor",
}

TRANSFER_WORDS = [
    "transfer", "signing", "signed for", "signs for",
    "sign for", "set to sign", "set to join", "joins",
    "joined", "loan move", "on loan", "loan deal",
    "contract offer", "new contract", "contract extension",
    "bid for", "offers for", "offer for", "deal with",
    "transfer deal", "move to", "agreed terms",
    "personal terms", "medical", "interest in",
    "wants to sign", "target", "fichaje", "fichajes",
    "ficha por", "fichar por", "oferta por",
    "mercado de fichajes", "wechsel zu", "verpflichtet",
    "trasferimento", "accordo", "offerta per",
    "transfert", "accord de transfert",
    "anlaşma sağladı", "anlaşmaya vardı", "imza attı",
    "sözleşme imzaladı", "kiralık olarak", "kiraladı",
    "kiralıyor", "bonservisini aldı", "kadrosuna kattı",
    "takımdan ayrılıyor", "ayrılacak", "ayrılığı gündemde",
    "resmî teklif", "resmi teklif", "teklif yaptı",
    "teklif geldi", "görüşmelere başladı",
    "transfer listesinde", "talip oldu",
]

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
    "Rodri", "Endrick", "Felix Nmecha", "Victor Boniface",
    "Jonathan David", "Mason Greenwood", "Randal Kolo Muani",
    "Khvicha Kvaratskhelia", "Alexander Sorloth",
    "Benjamin Sesko", "Xavi Simons", "Jeremie Frimpong",
    "Ousmane Dembele", "Bernardo Silva", "Ilkay Gundogan",
    "Thomas Muller", "Nicolo Barella", "Marcus Thuram",
    "Dusan Vlahovic", "Paulo Dybala", "Sandro Tonali",
    "Ruben Dias", "William Saliba", "Gabriel Jesus",
    "Gabriel Martinelli", "Kai Havertz", "Son Heung Min",
    "Virgil van Dijk", "Trent Alexander Arnold",
    "Darwin Nunez", "Luis Diaz", "Alexis Mac Allister",
    "Dominik Szoboszlai", "Martin Zubimendi", "Mikel Merino",
    "Nicolas Jackson", "Christopher Nkunku", "Jadon Sancho",
    "Joao Palhinha", "Matthijs de Ligt", "Manuel Neuer",
    "Leroy Sane", "Serge Gnabry", "Kingsley Coman",
    "Milan Skriniar", "Ederson", "Alisson Becker",
    "Ciro Immobile", "Rafa Silva", "Gedson Fernandes",
    "Milot Rashica", "Semih Kilicsoy", "Victor Nelsson",
    "Davinson Sanchez", "Lucas Torreira", "Dries Mertens",
    "Fernando Muslera", "Gabriel Sara", "Fred",
    "Edin Dzeko", "Dusan Tadic", "Sebastian Szymanski",
    "Alexander Djiku", "Jayden Oosterwolde",
    "Youssef En Nesyri", "Filip Kostic", "Sofyan Amrabat",
    "Talisca", "Rachid Ghezzal", "Ugurcan Cakir",
    "Enis Destan", "Abdulkadir Omur", "Okay Yokuslu",
    "Salih Ozcan", "Yunus Akgun", "Kerem Akturkoglu",
    "Altay Bayindir", "Merih Demiral", "Caglar Soyuncu",
    "Zeki Celik",
]

# Bilinen kulüpler. Bu listeyi players.json verisi tamamlayabilir.
KNOWN_CLUBS = {
    "milot rashica": "Besiktas",
}

# ==========================================
# METİN İŞLEME
# ==========================================

def normalize(value):
    value = str(value or "").lower().replace("ı", "i")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        c for c in value if not unicodedata.combining(c)
    )
    return re.findall(r"[a-z0-9]+", value)


def normalized_text(value):
    return " ".join(normalize(value))


def extract_player_data(data):
    """Oyuncu isimlerini ve varsa kulüp bilgisini JSON içinden bulur."""
    names = set()
    clubs = {}

    name_fields = (
        "name", "player_name", "full_name",
        "player", "playerName", "fullName"
    )
    club_fields = (
        "team", "club", "current_team", "current_club",
        "team_name", "club_name", "currentTeam",
        "currentClub", "teamName", "clubName"
    )

    def walk(obj):
        if isinstance(obj, dict):
            player_name = None

            for field in name_fields:
                value = obj.get(field)
                if isinstance(value, str) and len(value.split()) >= 2:
                    player_name = value.strip()
                    names.add(player_name)
                    break

            if player_name:
                for field in club_fields:
                    value = obj.get(field)
                    if isinstance(value, str) and value.strip():
                        clubs[normalized_text(player_name)] = value.strip()
                        break

            for value in obj.values():
                if isinstance(value, (dict, list)):
                    walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return names, clubs


def load_players():
    names = set(PLAYER_ALIASES)
    clubs = dict(KNOWN_CLUBS)

    try:
        with open("players.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        database_names, database_clubs = extract_player_data(data)
        names.update(database_names)
        clubs.update(database_clubs)

        print("Oyuncu veritabanı:", len(names), "isim")
        print("Kulüp kaydı:", len(clubs), "oyuncu")

    except Exception as error:
        print("Oyuncu veritabanı hatası:", error)

    return names, clubs


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

    unique_surnames = {
        surname: next(iter(candidates))
        for surname, candidates in surname_candidates.items()
        if len(candidates) == 1
    }

    return full_index, unique_surnames


def find_players(title, indexes):
    full_index, surname_index = indexes
    words = normalize(title)
    found = []

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

    # Tek başına soyadı eşleşmesi yanlış sonuç üretebilir.
    # Bu nedenle soyadı eşleşmesini yalnızca başlıkta tam ad yoksa kullan.
    if not found:
        raw_words = re.findall(r"\b[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'-]*\b", title)

        for raw_word in raw_words:
            token = normalize(raw_word)
            if len(token) != 1:
                continue

            name = surname_index.get(token[0])
            if name and name not in found:
                found.append(name)

    return found


# ==========================================
# TRANSFER HABERİ SINIFLANDIRMA
# ==========================================

REPLACEMENT_PATTERNS = [
    r"\b(.+?) yerine\b",
    r"\b(.+?)'nin yerine\b",
    r"\b(.+?) yerine gelecek\b",
    r"\b(.+?) yerine geliyor\b",
    r"\binstead of\b",
    r"\breplace(?:s|d|ment)?\b",
    r"\breplacement for\b",
    r"\bremplace\b",
    r"\bal posto di\b",
]

INCOMING_PATTERNS = [
    r"\btransfer ediyor\b",
    r"\btransfer etmek istiyor\b",
    r"\bkadrosuna kat",
    r"\btransfer listesine aldı\b",
    r"\bteklif yaptı\b",
    r"\bteklif sundu\b",
    r"\banlaşma sağladı\b",
    r"\bimza at",
    r"\bgeliyor\b",
    r"\bgelecek\b",
    r"\bjoin(?:s|ed)?\b",
    r"\bsign(?:s|ed)?\b",
    r"\bset to join\b",
    r"\bmove to\b",
    r"\bfichar\b",
    r"\bwechselt zu\b",
]

OUTGOING_PATTERNS = [
    r"\btakımdan ayrıl",
    r"\bkulüpten ayrıl",
    r"\bsatış listesinde\b",
    r"\bsatmak istiyor\b",
    r"\bgönderilecek\b",
    r"\bgönderiyor\b",
    r"\byolcu\b",
    r"\bveda ediyor\b",
    r"\bveda edecek\b",
    r"\bleave(?:s|ing)?\b",
    r"\bdepart(?:s|ure)?\b",
    r"\bexit\b",
    r"\bsold\b",
    r"\bsale\b",
    r"\bloaned out\b",
    r"\bloan move\b",
    r"\bwechseln\b",
]

def has_pattern(text, patterns):
    return any(re.search(pattern, text) for pattern in patterns)


def is_transfer_news(title):
    text = normalized_text(title)
    return any(normalized_text(term) in text for term in TRANSFER_WORDS)


def classify_article(title, player):
    """
    Dönen değer:
    incoming, outgoing veya reject.
    Başlık yeterli bilgi vermiyorsa haber gönderilmez.
    """
    text = normalized_text(title)
    player_text = normalized_text(player)

    # Oyuncu başka birinin yerine gelecek hedef değilse,
    # bu başlık oyuncunun transferini anlatmıyor olabilir.
    for pattern in REPLACEMENT_PATTERNS:
        match = re.search(pattern, text)

        if match:
            phrase = normalized_text(match.group(0))
            if player_text in phrase or any(
                token in phrase.split()
                for token in player_text.split()
            ):
                return "reject"

            # "Rashica yerine X gelecek" türü başlıkta Rashica
            # başlığın transfer hedefi değildir.
            before = text[:match.start()]
            after = text[match.end():]

            if player_text in before or player_text in after:
                return "reject"

    if has_pattern(text, OUTGOING_PATTERNS):
        return "outgoing"

    if has_pattern(text, INCOMING_PATTERNS):
        return "incoming"

    return "reject"


# ==========================================
# HABER TEKRARI VE KÜMELEME
# ==========================================

STOP_WORDS = {
    "the", "a", "an", "and", "or", "to", "for", "of",
    "in", "on", "at", "is", "are", "was", "with",
    "de", "la", "el", "del", "en", "por", "y",
    "ve", "ile", "icin", "bir", "bu", "son",
    "transfer", "transfers", "fichaje", "fichajes",
    "haber", "iddia", "iddiasi", "gundem",
}


def title_tokens(title):
    return {
        word for word in normalize(title)
        if len(word) > 2 and word not in STOP_WORDS
    }


def similarity(a, b):
    first = title_tokens(a)
    second = title_tokens(b)

    if not first or not second:
        return 0

    return len(first & second) / len(first | second)


def canonical_link(link):
    try:
        parts = urlsplit(link)
        return urlunsplit((
            parts.scheme, parts.netloc.lower(),
            parts.path.rstrip("/"), "", ""
        ))
    except Exception:
        return link


def article_key(article):
    return canonical_link(article["link"]) or article["id"]


def cluster_articles(articles):
    clusters = []

    for article in articles:
        players = set(article["players"])
        placed = False

        for cluster in clusters:
            if not players.intersection(cluster["players"]):
                continue

            best_similarity = max(
                similarity(article["title"], item["title"])
                for item in cluster["articles"]
            )

            if best_similarity >= 0.35:
                cluster["articles"].append(article)
                cluster["players"].update(players)
                placed = True
                break

        if not placed:
            clusters.append({
                "articles": [article],
                "players": set(players),
            })

    return clusters


# ==========================================
# TÜRKÇE ÇEVİRİ
# ==========================================

def translate_to_turkish(text):
    if not text:
        return text

    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx", "sl": "auto",
                "tl": "tr", "dt": "t", "q": text,
            },
            headers=HEADERS,
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()

        translated = "".join(
            part[0] for part in data[0] if part and part[0]
        )
        return translated.strip() or text

    except Exception as error:
        print("Çeviri yapılamadı:", error)
        return text


# ==========================================
# RSS HABERLERİ
# ==========================================

def fetch_feed(source, url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=12)
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

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
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
        key = article_key(article)
        if key not in unique:
            unique[key] = article

    print("Benzersiz haber:", len(unique))
    return list(unique.values())


# ==========================================
# GÖRÜLEN HABERLER - GITHUB
# ==========================================

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
                url, headers=github_headers(), timeout=12
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
            url, headers=github_headers(), timeout=12
        )

        sha = None

        if response.status_code == 200:
            sha = response.json().get("sha")
        elif response.status_code != 404:
            print("GitHub okuma hatası:", response.status_code)
            return

        content = json.dumps(data, ensure_ascii=False, indent=2)

        payload = {
            "message": "Update RATEBROS seen news",
            "content": base64.b64encode(
                content.encode("utf-8")
            ).decode("utf-8"),
        }

        if sha:
            payload["sha"] = sha

        result = requests.put(
            url, headers=github_headers(),
            json=payload, timeout=15
        )

        if result.status_code in (200, 201):
            print("seen.json kaydedildi.")
        else:
            print("GitHub kayıt hatası:", result.status_code)

    except Exception as error:
        print("GitHub kayıt hatası:", error)


# ==========================================
# TELEGRAM MESAJI
# ==========================================

def send_telegram(cluster):
    articles = cluster["articles"]

    source_order = [
        "Sky Sports", "Marca", "A Spor",
        "A Spor Futbol", "A Spor Süper Lig",
        "Football Italia", "Get Football News Germany",
        "OrtaPas", "OrtaPas Transfer", "CaughtOffside",
    ]

    best_article = min(
        articles,
        key=lambda article: (
            source_order.index(article["source"])
            if article["source"] in source_order
            else len(source_order)
        )
    )

    player = cluster["players"][0]
    translated_title = translate_to_turkish(best_article["title"])

    direction = best_article["direction"]

    if direction == "incoming":
        direction_text = "Gelen transfer"
    else:
        direction_text = "Ayrılık / giden transfer"

    message = (
        "🚨 <b>RATEBROS TRANSFER</b>\n\n"
        f"⚽ <b>Oyuncu:</b> {escape(player)}\n"
        f"🔄 <b>Durum:</b> {direction_text}\n"
        f"📰 <b>Haber:</b> {escape(translated_title)}\n"
        f"🌍 <b>Kaynak:</b> {escape(best_article['source'])}\n\n"
        f'🔗 <a href="{escape(best_article["link"], quote=True)}">Haberi Oku</a>'
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


# ==========================================
# ANA PROGRAM
# ==========================================

def main():
    started = time.time()

    print("================================")
    print("RATEBROS BAŞLIYOR")
    print("================================")

    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram ayarları eksik!")
        return

    players, player_clubs = load_players()
    indexes = build_indexes(players)

    print("\nRSS kontrol ediliyor...")
    articles = get_all_news()
    seen = load_seen()

    candidates = []

    print("\nHABERLER KONTROL EDİLİYOR")

    for article in articles:
        key = article_key(article)

        if key in seen or article["id"] in seen:
            continue

        if not is_transfer_news(article["title"]):
            continue

        matched = find_players(article["title"], indexes)

        if not matched:
            print("Oyuncu eşleşmedi:", article["title"])
            continue

        # Başlıkta birden fazla oyuncu varsa belirsiz olabilir.
        # Şimdilik yalnızca tek oyunculu haberleri gönder.
        if len(matched) != 1:
            print("Birden fazla oyuncu bulundu, atlandı:", article["title"])
            continue

        player = matched[0]
        direction = classify_article(article["title"], player)

        if direction == "reject":
            print("Belirsiz / oyuncu hedef değil, atlandı:", article["title"])
            continue

        club = player_clubs.get(normalized_text(player))

        article["players"] = matched
        article["direction"] = direction
        article["player_club"] = club
        article["seen_key"] = key

        print("TRANSFER ADAYI:", article["title"])
        print("Oyuncu:", player, "| Kulüp:", club, "| Tür:", direction)

        candidates.append(article)

    clusters = cluster_articles(candidates)

    print("Transfer adayı:", len(candidates))
    print("Haber kümeleri:", len(clusters))

    sent = 0

    for cluster in clusters[:MAX_NEWS]:
        # Küme içindeki ilk oyuncunun yönünü kullan.
        directions = {
            article["direction"] for article in cluster["articles"]
        }

        # Aynı oyuncu için çelişkili haberleri göndermiyoruz.
        if len(directions) != 1:
            print("Çelişkili haber kümesi atlandı.")
            continue

        cluster["players"] = sorted(cluster["players"])

        if send_telegram(cluster):
            for article in cluster["articles"]:
                seen.add(article["seen_key"])
                seen.add(article["id"])
            sent += 1

        time.sleep(1)

    save_seen(seen)

    print("\n================================")
    print("RATEBROS TAMAMLANDI")
    print("RSS haberleri:", len(articles))
    print("Transfer adayları:", len(candidates))
    print("Gönderilen:", sent)
    print("Süre:", round(time.time() - started, 1), "saniye")
    print("================================")


if __name__ == "__main__":
    main()
