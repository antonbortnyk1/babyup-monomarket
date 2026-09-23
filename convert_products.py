import os
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE_URL = os.getenv(
    "SOURCE_URL",
    "https://babyup.ua/marketplace-integration/rozetka-feed/ff442a101279a54baa44e63e8da3cec2"
)

OUTPUT_FILE = Path(
    os.getenv(
        "PRODUCTS_OUTPUT_FILE",
        "docs/products.xml"
    )
)

LIMIT = int(os.getenv("PRODUCTS_LIMIT", "0"))


def text(node, name):
    child = node.find(name)

    if child is None or child.text is None:
        return None

    value = child.text.strip()

    return value if value else None


def get_param(node, param_name):
    for param in node.findall("param"):
        name = str(param.get("name", "")).strip().lower()

        if name == param_name.lower():
            value = (param.text or "").strip()

            if value:
                return value

    return None


def load_xml():
    request = urllib.request.Request(
        SOURCE_URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def build_categories(root):
    categories = {}

    for category in root.findall("./shop/categories/category"):
        category_id = str(category.get("id", "")).strip()
        category_name = (category.text or "").strip()

        if category_id and category_name:
            categories[category_id] = category_name

    return categories


def clean_barcode(value):
    if not value:
        return None

    value = value.strip()

    if not value:
        return None

    return value


def convert(xml_bytes):
    source_root = ET.fromstring(xml_bytes)

    categories = build_categories(source_root)

    source_offers = source_root.findall(
        "./shop/offers/offer"
    )

    if LIMIT > 0:
        source_offers = source_offers[:LIMIT]

    market = ET.Element("Market")
    offers = ET.SubElement(market, "offers")

    total = 0
    skipped = 0

    for source_offer in source_offers:
        code = str(
            source_offer.get("id", "")
        ).strip()

        if not code:
            skipped += 1
            continue

        available = (
            str(
                source_offer.get(
                    "available",
                    "false"
                )
            ).lower()
            == "true"
        )

        if not available:
            continue

        title = text(
            source_offer,
            "name"
        )

        category_id = text(
            source_offer,
            "categoryId"
        )

        category = (
            categories.get(category_id)
            if category_id
            else None
        )

        brand = text(
            source_offer,
            "vendor"
        )

        barcode = clean_barcode(
            get_param(
                source_offer,
                "EAN"
            )
        )

        if not title or not category:
            skipped += 1
            continue

        offer = ET.SubElement(
            offers,
            "offer"
        )

        ET.SubElement(
            offer,
            "id"
        ).text = code

        ET.SubElement(
            offer,
            "code"
        ).text = code

        ET.SubElement(
            offer,
            "title"
        ).text = title

        if barcode:
            ET.SubElement(
                offer,
                "barcode"
            ).text = barcode

        ET.SubElement(
            offer,
            "category"
        ).text = category

        if brand:
            ET.SubElement(
                offer,
                "brand"
            ).text = brand

        ET.SubElement(
            offer,
            "availability"
        ).text = "Є в наявності"

        total += 1

    tree = ET.ElementTree(market)

    ET.indent(
        tree,
        space="    "
    )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    tree.write(
        OUTPUT_FILE,
        encoding="UTF-8",
        xml_declaration=True
    )

    return total, skipped


def main():
    xml_bytes = load_xml()

    total, skipped = convert(
        xml_bytes
    )

    print(
        f"Generated {OUTPUT_FILE}: "
        f"{total} products, "
        f"{skipped} skipped"
    )


if __name__ == "__main__":
    main()
