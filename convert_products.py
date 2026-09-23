import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

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


def clean_xml_text(value):
    if value is None:
        return None

    value = str(value)

    value = re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F]",
        "",
        value
    )

    value = value.strip()

    return value if value else None


def text(node, name):
    child = node.find(name)

    if child is None or child.text is None:
        return None

    return clean_xml_text(child.text)


def get_params(node):
    result = []

    for param in node.findall("param"):
        name = clean_xml_text(
            param.get("name")
        )

        value = clean_xml_text(
            param.text
        )

        if not name or not value:
            continue

        result.append(
            {
                "name": name,
                "value": value
            }
        )

    return result


def get_barcode(params):
    for param in params:
        if param["name"].strip().lower() == "ean":
            return param["value"]

    return None


def get_pictures(node):
    result = []

    for picture in node.findall("picture"):
        value = clean_xml_text(
            picture.text
        )

        if not value:
            continue

        if value not in result:
            result.append(value)

    return result


def load_xml():
    request = urllib.request.Request(
        SOURCE_URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=60
    ) as response:
        return response.read()


def build_categories(root):
    result = {}

    for category in root.findall(
        "./shop/categories/category"
    ):
        category_id = clean_xml_text(
            category.get("id")
        )

        category_name = clean_xml_text(
            category.text
        )

        if (
            category_id
            and category_name
        ):
            result[
                category_id
            ] = category_name

    return result


def add_text_element(
    document,
    parent,
    name,
    value
):
    value = clean_xml_text(value)

    if value is None:
        return None

    element = document.createElement(
        name
    )

    element.appendChild(
        document.createTextNode(
            value
        )
    )

    parent.appendChild(
        element
    )

    return element


def add_cdata_element(
    document,
    parent,
    name,
    value
):
    value = clean_xml_text(value)

    if value is None:
        return None

    value = value.replace(
        "]]>",
        "]]]]><![CDATA[>"
    )

    element = document.createElement(
        name
    )

    element.appendChild(
        document.createCDATASection(
            value
        )
    )

    parent.appendChild(
        element
    )

    return element


def convert(xml_bytes):
    source_root = ET.fromstring(
        xml_bytes
    )

    categories = build_categories(
        source_root
    )

    source_offers = source_root.findall(
        "./shop/offers/offer"
    )

    if LIMIT > 0:
        source_offers = source_offers[
            :LIMIT
        ]

    document = minidom.Document()

    market = document.createElement(
        "Market"
    )

    document.appendChild(
        market
    )

    offers = document.createElement(
        "offers"
    )

    market.appendChild(
        offers
    )

    total = 0
    skipped_unavailable = 0
    skipped_invalid = 0

    for source_offer in source_offers:
        code = clean_xml_text(
            source_offer.get("id")
        )

        available = (
            str(
                source_offer.get(
                    "available",
                    "false"
                )
            )
            .strip()
            .lower()
            == "true"
        )

        if not available:
            skipped_unavailable += 1
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
            categories.get(
                category_id
            )
            if category_id
            else None
        )

        brand = text(
            source_offer,
            "vendor"
        )

        product_url = text(
            source_offer,
            "url"
        )

        description = text(
            source_offer,
            "description"
        )

        params = get_params(
            source_offer
        )

        barcode = get_barcode(
            params
        )

        pictures = get_pictures(
            source_offer
        )

        if (
            not code
            or not title
            or not category
        ):
            skipped_invalid += 1
            continue

        offer = document.createElement(
            "offer"
        )

        offers.appendChild(
            offer
        )

        add_text_element(
            document,
            offer,
            "id",
            code
        )

        add_text_element(
            document,
            offer,
            "code",
            code
        )

        add_text_element(
            document,
            offer,
            "vendor_code",
            code
        )

        add_text_element(
            document,
            offer,
            "title",
            title
        )

        if barcode:
            add_text_element(
                document,
                offer,
                "barcode",
                barcode
            )

        add_text_element(
            document,
            offer,
            "category",
            category
        )

        if brand:
            add_text_element(
                document,
                offer,
                "brand",
                brand
            )

        add_text_element(
            document,
            offer,
            "availability",
            "Є в наявності"
        )

        if product_url:
            add_text_element(
                document,
                offer,
                "url",
                product_url
            )

        for picture in pictures:
            add_text_element(
                document,
                offer,
                "picture",
                picture
            )

        if description:
            add_cdata_element(
                document,
                offer,
                "description",
                description
            )

        for param in params:
            if (
                param["name"]
                .strip()
                .lower()
                == "ean"
            ):
                continue

            param_element = (
                document.createElement(
                    "param"
                )
            )

            param_element.setAttribute(
                "name",
                param["name"]
            )

            param_element.appendChild(
                document.createTextNode(
                    param["value"]
                )
            )

            offer.appendChild(
                param_element
            )

        total += 1

    xml = document.toprettyxml(
        indent="    ",
        encoding="UTF-8"
    )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    OUTPUT_FILE.write_bytes(
        xml
    )

    return (
        total,
        skipped_unavailable,
        skipped_invalid
    )


def main():
    xml_bytes = load_xml()

    (
        total,
        skipped_unavailable,
        skipped_invalid
    ) = convert(
        xml_bytes
    )

    print(
        f"Generated {OUTPUT_FILE}: "
        f"{total} products, "
        f"{skipped_unavailable} unavailable skipped, "
        f"{skipped_invalid} invalid skipped"
    )


if __name__ == "__main__":
    main()
