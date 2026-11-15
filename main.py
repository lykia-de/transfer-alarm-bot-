import os
import re
import json
import time
import hashlib
import unicodedata
from html import escape
from urllib.parse import urlsplit, urlunsplit

import requests
import feedparser
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# RATEBROS TRANSFER BOT
# GitHub Actions secrets required:
# TELEGRAM_BOT_TOKEN
# TELEGRAM_CHAT_ID
#
# Optional:
# GITHUB_TOKEN (automatically available as GITHUB_TOKEN in Actions)
# GITHUB_REPOSITORY (automatically available in Actions)
# SEEN_FILE (default: seen.json)
# MAX_AGE_HOURS (default: 72)
# ============================================================

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

# These are known player names and useful aliases. Add names here if needed.
PLAYER_ALIASES = [
    "Milot Rashica", "Rafa Silva", "Ciro Immobile", "Gedson Fernandes",
    "Orkun Kökçü", "Hakan Çalhanoğlu", "Victor Osimhen", "Mauro Icardi",
    "Barış Alper Yılmaz", "Kerem Aktürkoğlu", "Yunus Akgün",
    "Fenerbahçe", "Beşiktaş", "Galatasaray", "Trabzonspor",
    "Dodi Lukebakio", "Frank Zambo Anguissa", "Zambo Anguissa",
    "Oumar Solet", "Joe Willock", "Leandro Trossard", "Richarlison",
    "Yegor Yarmolyuk", "Aleksey Batrakov", "Kislyak", "El Khannous",
    "Oulai", "Ermedin Demirović", "Batagov", "Doumbia", "Désiré Doué",
    "Danilo", "Marco Asensio", "Rodri", "Michy Batshuayi",
    "Ahmetcan Kaplan", "Mohamed Bayo", "Ederson", "Talisca",
    "Cristiano Ronaldo", "Lionel Messi", "Kylian Mbappé",
    "Erling Haaland", "Jude Bellingham", "Vinícius Júnior",
    "Bukayo Saka", "Martin Ødegaard", "Declan Rice",
    "Mohamed Salah", "Virgil van Dijk", "Alexander Isak",
    "Bruno Fernandes", "Marcus Rashford", "Cole Palmer",
    "Harry Kane", "Jamal Musiala", "Florian Wirtz",
    "Leroy Sané", "Joshua Kimmich", "Victor Boniface",
    "Rafael Leão", "Lautaro Martínez", "Nicolò Barella",
    "Khvicha Kvaratskhelia", "Ousmane Dembélé", "Achraf Hakimi",
    "Randal Kolo Muani", "João Neves", "William Saliba",
    "Gabriel Martinelli", "Kai Havertz", "Son Heung-min",
    "James Maddison", "Rodrygo", "Federico Valverde",
    "Aurélien Tchouaméni", "Endrick", "Arda Güler",
]

TRANSFER_TERMS = [
    "transfer", "transfers", "transferi", "transferde", "transferine",
    "transfer olacak", "transfer oluyor", "transfer gündeminde",
    "anlaşma", "anlasti", "anlaştı", "anlaşmaya vardı", "anlasmaya vardi",
    "imza", "imzaladı", "imzaladi", "sözleşme", "sozlesme",
    "kiralık", "kiralik", "kiraladı", "kiraladi", "kiralanacak",
    "teklif", "bonservis", "serbest kalacak", "serbest oyuncu",
    "fichaje", "fichajes", "trasferimento", "mercato",
    "wechsel", "transfers news", "transfer news", "signing",
    "signs", "signed", "deal", "agreed", "bid", "loan",
    "joins", "joined", "departure", "leaves", "leaving",
    "wants to sign", "set to join", "move to",
]

INCOMING_TERMS = [
    "kadrosuna kat", "transfer etmek istiyor", "transfer edecek",
    "transfer ediyor", "teklif yaptı", "teklif yapti", "teklif sundu",
    "anlaşma sağladı", "anlasma sagladi", "imza atacak",
    "imza attı", "imza atti", "geliyor", "gelecek",
    "joins", "joined", "signs", "signed", "set to join",
    "agreed to join", "move to", "deal agreed", "loan move",
    "fichó", "ficho", "llega", "wechselt zu",
]

OUTGOING_TERMS = [
    "takımdan ayrıl", "takimdan ayril", "kulüpten ayrıl",
    "kulupten ayril", "satmak istiyor", "satış listesine",
    "gönderilecek", "gonderilecek", "yolcu", "veda ediyor",
    "veda edecek", "ayrılıyor", "ayriliyor", "ayrılacak",
    "ayrilacak", "leave", "leaves", "leaving", "depart",
    "departure", "sold", "sale", "loaned out", "set to leave",
]

REPLACEMENT_TERMS = [
    "yerine", "replacement for", "instead of", "replace",
    "as a replacement",
]

HEADERS = {
    "User-Agent": "RATEBROS-TransferBot/1.0 (+https://github.com/)"
}
HTTP = requests.Session()
HTTP.headers.update(HEADERS)


def normalize(value):
    """Lowercase, remove accents and normalize punctuation/whitespace."""
    value = str(value or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("ı", "i").replace("ß", "ss")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def clean_html(value):
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def canonical_url(url):
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
        # Remove tracking parameters while keeping meaningful query-free URL.
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except Exception:
        return url.strip()


def stable_id(article):
    raw = canonical_url(article.get("url")) or (
        normalize(article.get("title", "")) + "|" + article.get("source", "")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fetch_feed(source, url):
    try:
        response = HTTP.get(url, timeout=18)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        items = []

        for entry in feed.entries[:100]:
            title = clean_html(entry.get("title", ""))
            link = entry.get("link", "")
            summary = clean_html(
                entry.get("summary", "") or entry.get("description", "")
            )
            if not title or not link:
                continue

            published = entry.get("published_parsed") or entry.get("updated_parsed")
            published_ts = None
            if published:
                try:
                    published_ts = time.mktime(published)
                except Exception:
                    pass

            items.append({
                "title": title,
                "summary": summary[:2500],
                "url": link,
                "source": source,
                "published_ts": published_ts,
            })

        print(f"[RSS] {source}: {len(items)} haber")
        return items
    except Exception as exc:
        print(f"[RSS HATA] {source}: {exc}")
        return []


def fetch_all_feeds():
    articles = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [
            pool.submit(fetch_feed, source, url)
            for source, url in RSS_SOURCES.items()
        ]
        for future in as_completed(futures):
            articles.extend(future.result())

    unique = {}
    for article in articles:
        key = canonical_url(article["url"])
        if key and key not in unique:
            unique[key] = article

    result = list(unique.values())
    print(f"[RSS] Toplam benzersiz haber: {len(result)}")
    return result


def load_player_names():
    names = set(PLAYER_ALIASES)
    path = "players.json"

    if not os.path.exists(path):
        print("[OYUNCU] players.json bulunamadı; yerleşik isim listesi kullanılacak.")
        return sorted(names)

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)

        def walk(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key.lower() in {
                        "name", "player_name", "full_name", "player",
                        "playername", "fullname"
                    } and isinstance(value, str):
                        if len(value.strip()) >= 3:
                            names.add(value.strip())
                    else:
                        walk(value)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(data)
        print(f"[OYUNCU] Kullanılabilir oyuncu adı: {len(names)}")
    except Exception as exc:
        print(f"[OYUNCU] players.json okunamadı: {exc}")

    return sorted(names)


def build_player_index(names):
    # Exact normalized names are matched as phrases.
    index = {}
    for name in names:
        key = normalize(name)
        if len(key) < 3:
            continue
        index.setdefault(key, name)
    return index


def find_players(text, player_index):
    normalized_text = " " + normalize(text) + " "
    found = []

    # Longer names first to avoid matching a short alias before a full name.
    for key, original in sorted(
        player_index.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if " " + key + " " in normalized_text:
            if original not in found:
                found.append(original)

    return found


def is_transfer_news(article):
    text = normalize(article["title"] + " " + article.get("summary", ""))
    return any(normalize(term) in text for term in TRANSFER_TERMS)


def classify_direction(title, player):
    text = normalize(title)
    player_name = normalize(player)

    # If the headline says "X yerine Y", X is not automatically the incoming player.
    if any(normalize(term) in text for term in REPLACEMENT_TERMS):
        return "Belirsiz"

    if any(normalize(term) in text for term in OUTGOING_TERMS):
        return "Ayrılık iddiası"

    if any(normalize(term) in text for term in INCOMING_TERMS):
        return "Transfer iddiası"

    return "Transfer gündemi"


def is_recent(article):
    hours = int(os.getenv("MAX_AGE_HOURS", "72"))
    timestamp = article.get("published_ts")
    if not timestamp:
        return True
    return timestamp >= time.time() - hours * 3600


def load_seen():
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    path = os.getenv("SEEN_FILE", "seen.json")

    if token and repo:
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        try:
            response = HTTP.get(
                url,
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/vnd.github+json"},
                timeout=15,
            )
            if response.status_code == 200:
                import base64
                content = base64.b64decode(response.json()["content"])
                data = json.loads(content.decode("utf-8"))
                return set(data.get("seen", [])), response.json().get("sha")
            if response.status_code == 404:
                return set(), None
            print(f"[GITHUB] seen.json okunamadı: {response.status_code}")
        except Exception as exc:
            print(f"[GITHUB] seen.json okuma hatası: {exc}")

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return set(data.get("seen", [])), None
    except Exception:
        return set(), None


def save_seen(seen, sha=None):
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    path = os.getenv("SEEN_FILE", "seen.json")
    payload = {"seen": sorted(seen)[-5000:]}

    if token and repo:
        import base64
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        content = base64.b64encode(
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("ascii")

        body = {
            "message": "Update RATEBROS seen news",
            "content": content,
        }
        if sha:
            body["sha"] = sha

        try:
            response = HTTP.put(
                url,
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/vnd.github+json"},
                json=body,
                timeout=20,
            )
            if response.status_code not in (200, 201):
                print(f"[GITHUB] seen.json kaydedilemedi: "
                      f"{response.status_code} {response.text[:300]}")
            else:
                print("[GITHUB] seen.json kaydedildi.")
            return
        except Exception as exc:
            print(f"[GITHUB] seen.json yazma hatası: {exc}")

    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def send_telegram(article, player, direction):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[TELEGRAM HATA] TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik.")
        return False

    title = escape(article["title"])
    player_text = escape(player)
    source = escape(article["source"])
    url = escape(article["url"], quote=True)
    direction_text = escape(direction)

    message = (
        "🚨 <b>RATEBROS TRANSFER</b>\n\n"
        f"⚽ <b>Oyuncu:</b> {player_text}\n"
        f"📰 <b>Haber:</b> {title}\n"
        f"📌 <b>Durum:</b> {direction_text}\n"
        f"🌍 <b>Kaynak:</b> {source}\n"
        f'🔗 <a href="{url}">Haberi Oku</a>'
    )

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = HTTP.post(
            endpoint,
            data={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if response.ok and response.json().get("ok"):
            print(f"[TELEGRAM] Gönderildi: {player} | {article['title']}")
            return True

        print(f"[TELEGRAM HATA] {response.status_code}: {response.text[:300]}")
        return False
    except Exception as exc:
        print(f"[TELEGRAM HATA] {exc}")
        return False


def main():
    print("=" * 55)
    print("RATEBROS BAŞLIYOR")
    print("=" * 55)

    player_names = load_player_names()
    player_index = build_player_index(player_names)
    seen, seen_sha = load_seen()

    print(f"[SEEN] Daha önce görülen haber: {len(seen)}")

    articles = fetch_all_feeds()
    candidates = []

    for article in articles:
        if not is_recent(article):
            continue

        article_id = stable_id(article)
        if article_id in seen:
            continue

        if not is_transfer_news(article):
            continue

        search_text = article["title"] + " " + article.get("summary", "")
        players = find_players(search_text, player_index)

        if not players:
            print(f"[EŞLEŞME YOK] {article['title']}")
            continue

        # A single article may mention several players. Keep each match,
        # but avoid sending the same article multiple times.
        # Prefer the longest full name if aliases overlap.
        player = sorted(players, key=lambda name: len(normalize(name)), reverse=True)[0]
        direction = classify_direction(article["title"], player)

        if direction == "Belirsiz":
            print(f"[BAĞLAM BELİRSİZ] {article['title']}")
            seen.add(article_id)
            continue

        candidates.append((article, player, direction, article_id))

    print(f"[ADAY] Transfer haberi: {len(candidates)}")

    # Avoid flooding: max 15 posts per run.
    sent = 0
    for article, player, direction, article_id in candidates[:15]:
        if send_telegram(article, player, direction):
            seen.add(article_id)
            sent += 1
        time.sleep(0.35)

    # Mark old/unusable candidates seen only when they were successfully sent
    # or deliberately rejected as ambiguous above.
    save_seen(seen, seen_sha)

    print("-" * 55)
    print(f"Tamamlandı | Gönderilen: {sent} | Yeni aday: {len(candidates)}")
    print("=" * 55)


if __name__ == "__main__":
    main()