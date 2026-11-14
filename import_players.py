
import csv
import gzip
import io
import json
from datetime import datetime, timezone

import requests

SOURCE_URL = (
    "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/"
    "data/players.csv.gz"
)

OUTPUT_FILE = "players.json"


def main():
    print("RATEBROS: Oyuncu verileri indiriliyor...")

    response = requests.get(SOURCE_URL, timeout=180)
    response.raise_for_status()

    content = response.content

    # CSV dosyası gzip formatındaysa aç.
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)

    text_file = io.TextIOWrapper(
        io.BytesIO(content),
        encoding="utf-8-sig",
        newline=""
    )

    reader = csv.DictReader(text_file)
    players = []
    seen_ids = set()

    for row in reader:
        name = (row.get("name") or "").strip()
        player_id = (row.get("player_id") or "").strip()

        if not name or not player_id or player_id in seen_ids:
            continue

        seen_ids.add(player_id)

        players.append({
            "id": player_id,
            "name": name,
            "club": (row.get("current_club_name") or "").strip(),
            "country": (
                row.get("country_of_citizenship") or ""
            ).strip(),
            "position": (row.get("position") or "").strip(),
            "sub_position": (
                row.get("sub_position") or ""
            ).strip()
        })

    database = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "dcaribou/transfermarkt-datasets",
        "source_data_cutoff": "2026-07-06",
        "player_count": len(players),
        "players": players
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(database, file, ensure_ascii=False, indent=2)

    print(f"Tamamlandı! {len(players)} oyuncu kaydedildi.")


if __name__ == "__main__":
    main()
