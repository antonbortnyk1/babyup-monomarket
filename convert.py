import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE_URL = os.getenv("SOURCE_URL", "https://babyup.ua/marketplace-integration/rozetka-feed/ff442a101279a54baa44e63e8da3cec2")
OUTPUT_FILE = Path(os.getenv("OUTPUT_FILE", "docs/mono.json"))
WAREHOUSE_ID = os.getenv("WAREHOUSE_ID", "1")
WARRANTY_TYPE = os.getenv("WARRANTY_TYPE", "no")
WARRANTY_PERIOD = int(os.getenv("WARRANTY_PERIOD", "0"))
MAX_PAY_IN_PARTS = int(os.getenv("MAX_PAY_IN_PARTS", "6"))
LIMIT = int(os.getenv("LIMIT", "0"))


def number(value, default=0):
    if value is None:
        return default

    value = str(value).strip().replace(",", ".")

    if not value:
        return default

    result = float(value)

    return int(result) if result.is_integer() else result


def text(node, name):
    child = node.find(name)

    if child is None or child.text is None:
        return None

    value = child.text.strip()

    return value if value else None


def get_days_to_dispatch():
    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    weekday = now.weekday()

    if weekday == 4:
        return 3

    if weekday == 5:
        return 2

    return 1


def load_xml():
    request = urllib.request.Request(
        SOURCE_URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def convert(xml_bytes):
    root = ET.fromstring(xml_bytes)
    offers = root.findall("./shop/offers/offer")

    if LIMIT > 0:
        offers = offers[:LIMIT]

    data = []
    days_to_dispatch = get_days_to_dispatch()

    for offer in offers:
        code = str(offer.get("id", "")).strip()

        if not code:
            continue

        availability = str(
            offer.get("available", "false")
        ).lower() == "true"

        price = number(
            text(offer, "price"),
            0
        )

        old_price_raw = text(
            offer,
            "price_old"
        )

        old_price = (
            number(old_price_raw, 0)
            if old_price_raw is not None
            else None
        )

        stock = number(
            text(offer, "stock_quantity"),
            0
        )

        if not availability:
            stock = 0

        item = {
            "code": code,
            "price": price,
            "old_price": old_price,
            "availability": availability,
            "stock": stock,
            "warehouses": [
                {
                    "id": WAREHOUSE_ID,
                    "stock": stock
                }
            ],
            "warranty_type": WARRANTY_TYPE,
            "warranty_period": WARRANTY_PERIOD,
            "max_pay_in_parts": MAX_PAY_IN_PARTS,
            "days_to_dispatch": days_to_dispatch,
            "manufacture": None
        }

        data.append(item)

    return {
        "updatedAt": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "total": len(data),
        "data": data
    }


def main():
    xml_bytes = load_xml()
    result = convert(xml_bytes)

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    OUTPUT_FILE.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    print(
        f"Generated {OUTPUT_FILE}: "
        f"{result['total']} offers, "
        f"days_to_dispatch={get_days_to_dispatch()}"
    )


if __name__ == "__main__":
    main()
