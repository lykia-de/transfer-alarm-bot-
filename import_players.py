
import csv
import gzip
import io
import json
import re
from datetime import datetime, date, timezone

import requests

BASE_URL = (
    "https://raw.githubusercontent.com/salimt/"
    "football-datasets/main/datalake/transfermarkt/"
)

URLS = {
    "players": BASE_URL + "player_profiles/player_profiles.csv",
    "values": BASE_URL + "player_market_value/player_market_value.csv",
    "transfers": (
        "https://raw.githubusercontent.com/salimt/"
        "football-datasets/main/datalake/transfermarkt/raw/"
        "player_transfer_histories/player_transfer_histories"
    ),
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "RATEBROS/1.0"})


def download_csv(url):
    print("İndiriliyor:", url)

    response = SESSION.get(url, timeout=300)
    response.raise_for_status()

    content = response.content

    if content.startswith(b"\x1f\x8b"):
        content = gzip.decompress(content)

    beginning = content[:500].decode("utf-8", errors="replace")

    if beginning.startswith("version https://git-lfs.github.com/spec/v1"):
        raise RuntimeError("Git LFS işaretçisi döndü: " + url)

    if beginning.lstrip().lower().startswith(
        ("<!doctype html", "<html")
    ):
        raise RuntimeError("CSV yerine HTML döndü: " + url)

    text = io.TextIOWrapper(
        io.BytesIO(content),
        encoding="utf-8-sig",
        newline=""
    )

    reader = csv.DictReader(text)

    if not reader.fieldnames:
        raise RuntimeError("CSV başlıkları bulunamadı: " + url)

    print("CSV sütunları:", reader.fieldnames)

    return list(reader)


def clean_row(row):
    return {
        str(k).strip().lower().replace(" ", "_"): (v or "").strip()
        for k, v in row.items()
        if k is not None
    }


def get(row, *names):
    row = clean_row(row)

    for name in names:
        value = row.get(name.lower().replace(" ", "_"), "")
        if value:
            return value

    return ""


def parse_date(value):
    if not value:
        return None

    value = str(value).strip()

    formats = (
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
    )

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    return None


def calculate_age(birthday):
    dob = parse_date(birthday)

    if not dob:
        return None

    today = date.today()

    return today.year - dob.year - (
        (today.month, today.day) < (dob.month, dob.day)
    )


def parse_height(value):
    if not value:
        return None

    value = value.lower().replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", value)

    if not match:
        return None

    number = float(match.group())

    if number < 3:
        number *= 100

    return int(round(number))


def parse_money(value):
    if value is None:
        return None

    value = str(value).strip()

    if not value or value in ("-", "N/A", "None"):
        return None

    digits = re.sub(r"[^\d]", "", value)

    return int(digits) if digits else None


def date_sort_key(value):
    parsed = parse_date(value)

    if parsed:
        return parsed.toordinal()

    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def write_jsonl_gz(filename, records):
    count = 0

    with gzip.open(filename, "wt", encoding="utf-8") as file:
        for record in records:
            file.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )
            count += 1

    return count


def main():
    print("===================================")
    print("       RATEBROS DATABASE")
    print("===================================")

    # Önce bütün kaynakları indir ve kontrol et.
    profile_rows = download_csv(URLS["players"])
    value_rows = download_csv(URLS["values"])
    transfer_rows = download_csv(URLS["transfers"])

    print("Profil satırı:", len(profile_rows))
    print("Değer satırı:", len(value_rows))
    print("Transfer satırı:", len(transfer_rows))

    if len(profile_rows) < 1000:
        raise RuntimeError("Oyuncu profil verisi eksik.")

    if len(transfer_rows) < 100:
        raise RuntimeError(
            "Transfer verisi eksik veya yanlış dosya indirildi."
        )

    # Piyasa değerleri
    latest_values = {}
    highest_values = {}
    latest_dates = {}

    def market_history():
        for raw in value_rows:
            row = clean_row(raw)

            player_id = get(row, "player_id")
            value_date = get(row, "date_unix", "date")
            value = parse_money(get(row, "value", "market_value"))

            if not player_id or value is None:
                continue

            old_date = latest_dates.get(player_id)

            if (
                old_date is None
                or date_sort_key(value_date) >= date_sort_key(old_date)
            ):
                latest_dates[player_id] = value_date
                latest_values[player_id] = value

            highest_values[player_id] = max(
                value,
                highest_values.get(player_id, value)
            )

            yield {
                "player_id": player_id,
                "date": value_date,
                "value_eur": value
            }

    values_count = write_jsonl_gz(
        "player_market_values.jsonl.gz",
        market_history()
    )

    print("Piyasa değeri geçmişi:", values_count)

    # Oyuncu profilleri
    players = []
    seen_ids = set()

    for raw in profile_rows:
        row = clean_row(raw)

        player_id = get(row, "player_id")
        name = get(row, "player_name", "name")

        if not player_id or not name or player_id in seen_ids:
            continue

        seen_ids.add(player_id)

        birthday = get(row, "date_of_birth")

        players.append({
            "id": player_id,
            "name": name,
            "age": calculate_age(birthday),
            "date_of_birth": birthday,
            "height_cm": parse_height(get(row, "height")),
            "country": get(
                row,
                "citizenship",
                "citizenship_country"
            ),
            "position": get(
                row,
                "position",
                "main_position",
                "player_main_position"
            ),
            "sub_position": get(row, "player_sub_position"),
            "foot": get(row, "foot"),
            "club": get(
                row,
                "current_club",
                "current_club_name"
            ),
            "club_id": get(row, "current_club_id"),
            "joined": get(row, "joined"),
            "contract_expires": get(row, "contract_expires"),
            "market_value_eur": latest_values.get(player_id),
            "market_value_date": latest_dates.get(player_id),
            "highest_market_value_eur": highest_values.get(player_id),
            "image_url": get(row, "player_image_url"),
            "transfermarkt_url": get(row, "player_url", "url")
        })

    database = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "salimt/football-datasets",
        "source_type": "Transfermarkt dataset",
        "player_count": len(players),
        "players": players
    }

    with open("players.json", "w", encoding="utf-8") as file:
        json.dump(
            database,
            file,
            ensure_ascii=False,
            separators=(",", ":")
        )

    print("Oyuncu profilleri:", len(players))

    # Transfer geçmişi
    def transfer_history():
        for raw in transfer_rows:
            row = clean_row(raw)

            player_id = get(row, "player_id")

            if not player_id:
                continue

            yield {
                "transfer_id": get(row, "transfer_id"),
                "player_id": player_id,
                "date": get(row, "date"),
                "season": get(row, "season"),
                "from_club": get(
                    row,
                    "from_team_name",
                    "from_club_name"
                ),
                "to_club": get(
                    row,
                    "to_team_name",
                    "to_club_name"
                ),
                "transfer_fee": get(row, "transfer_fee"),
                "value_at_transfer_eur": parse_money(
                    get(row, "value_at_transfer")
                )
            }

    transfers_count = write_jsonl_gz(
        "player_transfers.jsonl.gz",
        transfer_history()
    )

    print("Transfer geçmişi:", transfers_count)

    print("===================================")
    print("RATEBROS VERİTABANI TAMAMLANDI!")
    print("===================================")


if __name__ == "__main__":
    main()
