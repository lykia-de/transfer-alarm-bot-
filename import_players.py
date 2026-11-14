
import csv
import gzip
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = (
    "https://raw.githubusercontent.com/"
    "salimt/football-datasets/main/datalake/transfermarkt/"
)

URLS = {
    "players": BASE_URL + "player_profiles/player_profiles.csv",
    "values": BASE_URL + "player_market_value/player_market_value.csv",
}

OUTPUT_PLAYERS = Path("players.json")
OUTPUT_VALUES = Path("player_market_values.jsonl.gz")
OUTPUT_TRANSFERS = Path("player_transfers.jsonl.gz")

HEADERS = {"User-Agent": "RATEBROS-football-bot/1.0"}


def download_csv(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=180,
    )
    response.raise_for_status()

    text = response.content.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())

    if not reader.fieldnames:
        raise RuntimeError(f"CSV başlıkları bulunamadı: {url}")

    return reader


def get(row, *names):
    normalized = {
        str(key).strip().lower().replace(" ", "_"): value
        for key, value in row.items()
        if key is not None
    }

    for name in names:
        value = normalized.get(name.lower().replace(" ", "_"))
        if value is not None and str(value).strip():
            return str(value).strip()

    return ""


def parse_height(value):
    if not value:
        return None

    match = re.search(r"(\d+[,.]?\d*)", value)

    if not match:
        return None

    try:
        number = float(match.group(1).replace(",", "."))

        if number < 3:
            number *= 100

        return round(number)
    except ValueError:
        return None


def parse_date(value):
    if not value:
        return None

    value = value.strip()

    formats = [
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return value


def parse_number(value):
    if not value:
        return None

    try:
        return int(float(value.replace(",", ".")))
    except (ValueError, AttributeError):
        return None


def write_json_atomic(path, data):
    temp_path = path.with_suffix(path.suffix + ".tmp")

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False)

    os.replace(temp_path, path)


def import_players():
    print("Oyuncu profilleri indiriliyor...")

    reader = download_csv(URLS["players"])
    players = []
    player_by_id = {}

    for row in reader:
        player_id = get(row, "player_id")
        name = get(row, "player_name")

        if not player_id or not name:
            continue

        home_name = get(row, "name_in_home_country")

        aliases = []
        if home_name and home_name.lower() != name.lower():
            aliases.append(home_name)

        player = {
            "player_id": player_id,
            "name": name,
            "player_name": name,
            "aliases": aliases,
            "club": get(row, "current_club_name"),
            "age": None,
            "date_of_birth": parse_date(
                get(row, "date_of_birth")
            ),
            "height": parse_height(get(row, "height")),
            "country": get(row, "citizenship"),
            "position": get(
                row,
                "player_main_position",
                "main_position",
                "position",
            ),
            "sub_position": get(
                row,
                "player_sub_position",
                "sub_position",
            ),
            "foot": get(row, "foot"),
            "joined": parse_date(get(row, "joined")),
            "contract_expires": parse_date(
                get(row, "contract_expires")
            ),
            "image": get(row, "player_image_url"),
            "url": (
                "https://www.transfermarkt.com/"
                + get(row, "player_slug")
                + "/profil/spieler/"
                + player_id
            ),
            "current_market_value": None,
            "highest_market_value": None,
        }

        players.append(player)
        player_by_id[player_id] = player

    if len(players) < 1000:
        raise RuntimeError(
            f"Profil verisi beklenenden az: {len(players)}"
        )

    print(f"Bulunan oyuncu profili: {len(players):,}")

    return players, player_by_id


def import_market_values(player_by_id):
    print("Piyasa değerleri indiriliyor...")

    reader = download_csv(URLS["values"])
    count = 0

    temp_path = OUTPUT_VALUES.with_suffix(
        OUTPUT_VALUES.suffix + ".tmp"
    )

    latest = {}

    with gzip.open(
        temp_path,
        "wt",
        encoding="utf-8",
    ) as output:

        for row in reader:
            player_id = get(row, "player_id")
            date = parse_date(get(row, "date_unix"))
            value = parse_number(get(row, "value"))

            if not player_id or not date or value is None:
                continue

            record = {
                "player_id": player_id,
                "date": date,
                "value": value,
            }

            output.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )

            count += 1

            previous = latest.get(player_id)

            if previous is None or date >= previous["date"]:
                latest[player_id] = record

    if count < 1000:
        os.remove(temp_path)
        raise RuntimeError(
            f"Piyasa değeri verisi beklenenden az: {count}"
        )

    os.replace(temp_path, OUTPUT_VALUES)

    for player_id, record in latest.items():
        player = player_by_id.get(player_id)

        if player:
            player["current_market_value"] = record["value"]

    print(f"Piyasa değeri kaydı: {count:,}")


def create_empty_transfers_file():
    print("Transfer geçmişi şimdilik devre dışı.")

    temp_path = OUTPUT_TRANSFERS.with_suffix(
        OUTPUT_TRANSFERS.suffix + ".tmp"
    )

    with gzip.open(temp_path, "wt", encoding="utf-8"):
        pass

    os.replace(temp_path, OUTPUT_TRANSFERS)


def main():
    players, player_by_id = import_players()

    import_market_values(player_by_id)

    print("Oyuncu dosyası kaydediliyor...")
    write_json_atomic(OUTPUT_PLAYERS, players)

    create_empty_transfers_file()

    print("--------------------------------")
    print("RATEBROS veritabanı hazır!")
    print(f"Oyuncular: {len(players):,}")
    print("Piyasa değerleri güncellendi.")
    print("Transfer geçmişi şimdilik boş.")
    print("--------------------------------")


if __name__ == "__main__":
    main()
