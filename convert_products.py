import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.dom import minidom

from bs4 import BeautifulSoup, Tag

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

REPORT_FILE = Path(
    os.getenv(
        "PRODUCTS_REPORT_FILE",
        "docs/products-report.json"
    )
)

LIMIT = int(os.getenv("PRODUCTS_LIMIT", "0"))

CONDITION_WORDS = (
    "уцін",
    "уцен",
    "вітрин",
    "витрин",
    "пошкоджен",
    "поврежден",
    "б/в",
    "б\\у",
    "refurb"
)

TITLE_BLOCKED_WORDS = (
    "акція",
    "знижка",
    "розпродаж",
    "уцінка",
    "copy",
    "original"
)

DESCRIPTION_BLOCKED_SECTIONS = (
    "комплектац",
    "гаранті",
    "гарант",
    "доставк",
    "оплат"
)

DESCRIPTION_BLOCKED_PARAGRAPHS = (
    "доставка доступна",
    "безкоштовна доставка",
    "купити у babyup",
    "замовити у babyup"
)

IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".svg"
)

VIDEO_EXTENSIONS = (
    ".mp4",
    ".mov",
    ".avi",
    ".webm"
)


def normalize_space(value):
    if value is None:
        return None

    value = re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F]",
        "",
        str(value)
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return value if value else None


def node_text(node, name):
    child = node.find(name)

    if child is None or child.text is None:
        return None

    return normalize_space(child.text)


def fetch_bytes(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=60
    ) as response:
        return response.read()


def fetch_text(url):
    data = fetch_bytes(url)

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(
            "utf-8",
            errors="replace"
        )


def build_categories(root):
    categories = {}

    for category in root.findall(
        "./shop/categories/category"
    ):
        category_id = normalize_space(
            category.get("id")
        )

        category_name = normalize_space(
            category.text
        )

        if category_id and category_name:
            categories[category_id] = category_name

    return categories


def get_source_params(node):
    result = []

    for param in node.findall("param"):
        name = normalize_space(
            param.get("name")
        )

        value = normalize_space(
            param.text
        )

        if name and value:
            result.append(
                (
                    name,
                    value
                )
            )

    return result


def get_source_pictures(node):
    result = []

    for picture in node.findall("picture"):
        value = normalize_space(
            picture.text
        )

        if not value:
            continue

        path = urlparse(
            value
        ).path.lower()

        if not path.endswith(
            IMAGE_EXTENSIONS
        ):
            continue

        if value not in result:
            result.append(value)

    return result


def clean_barcode(value):
    if not value:
        return None

    digits = re.sub(
        r"\D",
        "",
        str(value)
    )

    if 8 <= len(digits) <= 14:
        return digits

    return None


def get_source_barcode(params):
    accepted = {
        "ean",
        "ean13",
        "ean-13",
        "barcode",
        "штрихкод",
        "штрих-код",
        "gtin",
        "gtin13",
        "gtin-13"
    }

    for name, value in params:
        if name.lower() in accepted:
            barcode = clean_barcode(
                value
            )

            if barcode:
                return barcode

    return None


def parse_jsonld(soup):
    result = []

    for script in soup.find_all(
        "script",
        attrs={
            "type": re.compile(
                r"application/ld\+json",
                re.I
            )
        }
    ):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        result.append(data)

    return result


def walk_json(value):
    if isinstance(value, dict):
        yield value

        for item in value.values():
            yield from walk_json(item)

    elif isinstance(value, list):
        for item in value:
            yield from walk_json(item)


def jsonld_product_data(jsonld):
    result = {}

    for root in jsonld:
        for item in walk_json(root):
            item_type = item.get("@type")

            if isinstance(
                item_type,
                list
            ):
                types = {
                    str(x).lower()
                    for x in item_type
                }
            else:
                types = {
                    str(item_type).lower()
                }

            if "product" not in types:
                continue

            for key in (
                "sku",
                "mpn",
                "gtin",
                "gtin8",
                "gtin12",
                "gtin13",
                "gtin14"
            ):
                if key in item and item[key]:
                    result[key] = normalize_space(
                        item[key]
                    )

            brand = item.get("brand")

            if isinstance(
                brand,
                dict
            ):
                brand = brand.get("name")

            if brand:
                result["brand"] = normalize_space(
                    brand
                )

    return result


def jsonld_breadcrumbs(jsonld):
    candidates = []

    for root in jsonld:
        for item in walk_json(root):
            item_type = item.get("@type")

            if isinstance(
                item_type,
                list
            ):
                types = {
                    str(x).lower()
                    for x in item_type
                }
            else:
                types = {
                    str(item_type).lower()
                }

            if "breadcrumblist" not in types:
                continue

            names = []

            for element in item.get(
                "itemListElement",
                []
            ):
                if not isinstance(
                    element,
                    dict
                ):
                    continue

                name = element.get("name")

                if not name:
                    nested = element.get("item")

                    if isinstance(
                        nested,
                        dict
                    ):
                        name = nested.get("name")

                name = normalize_space(
                    name
                )

                if name:
                    names.append(name)

            if names:
                candidates = names

    return candidates


def get_page_barcode(
    soup,
    raw_html,
    jsonld_data,
    source_barcode
):
    if source_barcode:
        return source_barcode

    product_data = jsonld_product_data(
        jsonld_data
    )

    for key in (
        "gtin14",
        "gtin13",
        "gtin12",
        "gtin8",
        "gtin"
    ):
        barcode = clean_barcode(
            product_data.get(key)
        )

        if barcode:
            return barcode

    page_text = soup.get_text(
        " ",
        strip=True
    )

    patterns = (
        r"(?:EAN(?:-13)?|GTIN(?:-13)?|Штрих[\s-]*код)\s*[:№]?\s*([0-9]{8,14})",
        r'"(?:ean|gtin|barcode|gtin13|gtin14)"\s*:\s*"([0-9]{8,14})"'
    )

    for pattern in patterns:
        for haystack in (
            page_text,
            raw_html
        ):
            match = re.search(
                pattern,
                haystack,
                re.I
            )

            if match:
                barcode = clean_barcode(
                    match.group(1)
                )

                if barcode:
                    return barcode

    return None


def get_vendor_code(
    soup,
    raw_html,
    jsonld_data,
    fallback
):
    product_data = jsonld_product_data(
        jsonld_data
    )

    for key in (
        "mpn",
        "sku"
    ):
        value = normalize_space(
            product_data.get(key)
        )

        if value:
            return value

    page_text = soup.get_text(
        " ",
        strip=True
    )

    patterns = (
        r"Артикул\s*[:№]?\s*([A-Za-zА-Яа-яІіЇїЄєҐґ0-9._/\-]+)",
        r"(?:SKU|MPN)\s*[:№]?\s*([A-Za-z0-9._/\-]+)"
    )

    for pattern in patterns:
        for haystack in (
            page_text,
            raw_html
        ):
            match = re.search(
                pattern,
                haystack,
                re.I
            )

            if match:
                value = normalize_space(
                    match.group(1)
                )

                if value:
                    return value

    return fallback


def get_final_category(
    soup,
    jsonld_data,
    source_category,
    title
):
    breadcrumbs = jsonld_breadcrumbs(
        jsonld_data
    )

    if not breadcrumbs:
        selectors = (
            ".breadcrumbs a",
            ".breadcrumb a",
            ".breadcrumb-item a",
            "[itemtype*='BreadcrumbList'] [itemprop='name']",
            ".breadcrumbs__item a"
        )

        for selector in selectors:
            values = [
                normalize_space(
                    item.get_text(
                        " ",
                        strip=True
                    )
                )
                for item in soup.select(
                    selector
                )
            ]

            values = [
                item
                for item in values
                if item
            ]

            if values:
                breadcrumbs = values
                break

    ignored = {
        "головна",
        "каталог"
    }

    if title:
        ignored.add(
            normalize_space(
                title
            ).lower()
        )

    filtered = []

    for item in breadcrumbs:
        normalized = normalize_space(
            item
        )

        if not normalized:
            continue

        if normalized.lower() in ignored:
            continue

        filtered.append(
            normalized
        )

    if filtered:
        return filtered[-1]

    return source_category


def add_characteristic(
    target,
    seen,
    name,
    value
):
    name = normalize_space(name)
    value = normalize_space(value)

    if not name or not value:
        return

    if len(name) > 100:
        return

    if len(value) > 500:
        return

    normalized_name = name.lower()

    if normalized_name in {
        "бренд",
        "артикул",
        "ean",
        "ean13",
        "штрихкод",
        "штрих-код",
        "gtin",
        "ціна",
        "цена",
        "наявність",
        "наличие"
    }:
        return

    key = (
        normalized_name,
        value.lower()
    )

    if key in seen:
        return

    seen.add(key)

    target.append(
        (
            name,
            value
        )
    )


def extract_page_characteristics(
    soup
):
    result = []
    seen = set()

    for row in soup.find_all("tr"):
        cells = row.find_all(
            [
                "th",
                "td"
            ],
            recursive=False
        )

        if len(cells) < 2:
            continue

        add_characteristic(
            result,
            seen,
            cells[0].get_text(
                " ",
                strip=True
            ),
            cells[1].get_text(
                " ",
                strip=True
            )
        )

    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")

        if dd is None:
            continue

        add_characteristic(
            result,
            seen,
            dt.get_text(
                " ",
                strip=True
            ),
            dd.get_text(
                " ",
                strip=True
            )
        )

    for element in soup.find_all(
        [
            "li",
            "div",
            "p"
        ]
    ):
        value = normalize_space(
            element.get_text(
                " ",
                strip=True
            )
        )

        if not value:
            continue

        if ":" not in value:
            continue

        if len(value) > 500:
            continue

        name, parameter_value = value.split(
            ":",
            1
        )

        name = normalize_space(name)
        parameter_value = normalize_space(
            parameter_value
        )

        if not name or not parameter_value:
            continue

        if len(name) > 80:
            continue

        add_characteristic(
            result,
            seen,
            name,
            parameter_value
        )

    return result


def extract_description_characteristics(
    html
):
    result = []
    seen = set()

    if not html:
        return result

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    for li in soup.find_all("li"):
        value = normalize_space(
            li.get_text(
                " ",
                strip=True
            )
        )

        if not value or ":" not in value:
            continue

        name, parameter_value = value.split(
            ":",
            1
        )

        name = normalize_space(name)
        parameter_value = normalize_space(
            parameter_value
        )

        if not name or not parameter_value:
            continue

        if len(name) > 100:
            continue

        add_characteristic(
            result,
            seen,
            name,
            parameter_value
        )

    return result


def merge_characteristics(
    page_characteristics,
    description_characteristics,
    source_params
):
    result = []
    seen = set()

    for name, value in (
        page_characteristics
        + description_characteristics
        + source_params
    ):
        add_characteristic(
            result,
            seen,
            name,
            value
        )

    return result


def parse_number(value):
    if not value:
        return None

    match = re.search(
        r"(-?\d+(?:[.,]\d+)?)",
        str(value)
    )

    if not match:
        return None

    return float(
        match.group(1).replace(
            ",",
            "."
        )
    )


def format_number(value):
    if value is None:
        return None

    if float(value).is_integer():
        return str(
            int(value)
        )

    return (
        f"{value:.3f}"
        .rstrip("0")
        .rstrip(".")
    )


def convert_weight_to_kg(value):
    number = parse_number(
        value
    )

    if number is None:
        return None

    lowered = value.lower()

    if "кг" in lowered:
        return format_number(
            number
        )

    if re.search(
        r"(^|\s)г($|\s|[.,])",
        lowered
    ):
        return format_number(
            number / 1000
        )

    return None


def convert_dimension_to_cm(value):
    number = parse_number(
        value
    )

    if number is None:
        return None

    lowered = value.lower()

    if "мм" in lowered:
        return format_number(
            number / 10
        )

    if "см" in lowered:
        return format_number(
            number
        )

    if re.search(
        r"(^|\s)м($|\s|[.,])",
        lowered
    ):
        return format_number(
            number * 100
        )

    return None


def get_packaging_dimensions(
    characteristics
):
    result = {
        "weight": None,
        "height": None,
        "width": None,
        "length": None
    }

    for name, value in characteristics:
        lowered = name.lower()

        is_package = (
            "упаков" in lowered
            or "брутто" in lowered
            or "пакув" in lowered
        )

        if not is_package:
            continue

        if (
            result["weight"] is None
            and (
                "ваг" in lowered
                or "вес" in lowered
            )
        ):
            result["weight"] = (
                convert_weight_to_kg(
                    value
                )
            )

        if (
            result["height"] is None
            and (
                "висот" in lowered
                or "высот" in lowered
            )
        ):
            result["height"] = (
                convert_dimension_to_cm(
                    value
                )
            )

        if (
            result["width"] is None
            and "ширин" in lowered
        ):
            result["width"] = (
                convert_dimension_to_cm(
                    value
                )
            )

        if (
            result["length"] is None
            and (
                "довжин" in lowered
                or "длин" in lowered
            )
        ):
            result["length"] = (
                convert_dimension_to_cm(
                    value
                )
            )

    return result


def sanitize_title(title):
    value = normalize_space(
        title
    )

    if not value:
        return None

    for word in TITLE_BLOCKED_WORDS:
        value = re.sub(
            rf"\b{re.escape(word)}\b",
            "",
            value,
            flags=re.I
        )

    value = value.replace(
        "«",
        ""
    ).replace(
        "»",
        ""
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    if len(value) > 100:
        value = value[:100].rstrip()

    return value


def remove_forbidden_description_sections(
    soup
):
    for heading in list(
        soup.find_all(
            re.compile(
                r"^h[1-6]$"
            )
        )
    ):
        heading_text = normalize_space(
            heading.get_text(
                " ",
                strip=True
            )
        ) or ""

        if any(
            word in heading_text.lower()
            for word in DESCRIPTION_BLOCKED_SECTIONS
        ):
            sibling = heading.next_sibling

            while sibling is not None:
                next_sibling = (
                    sibling.next_sibling
                )

                if (
                    isinstance(
                        sibling,
                        Tag
                    )
                    and re.fullmatch(
                        r"h[1-6]",
                        sibling.name or "",
                        re.I
                    )
                ):
                    break

                if isinstance(
                    sibling,
                    Tag
                ):
                    sibling.decompose()
                else:
                    sibling.extract()

                sibling = next_sibling

            heading.decompose()

    for element in list(
        soup.find_all(
            [
                "p",
                "li"
            ]
        )
    ):
        value = normalize_space(
            element.get_text(
                " ",
                strip=True
            )
        ) or ""

        lowered = value.lower()

        if any(
            word in lowered
            for word in DESCRIPTION_BLOCKED_PARAGRAPHS
        ):
            element.decompose()


def sanitize_description(
    value,
    base_url
):
    if not value:
        return None

    soup = BeautifulSoup(
        value,
        "html.parser"
    )

    for tag in soup.find_all(
        [
            "script",
            "style",
            "iframe",
            "form",
            "button"
        ]
    ):
        tag.decompose()

    remove_forbidden_description_sections(
        soup
    )

    for heading in soup.find_all(
        re.compile(
            r"^h[1-6]$"
        )
    ):
        heading.name = "h5"

    for ordered in soup.find_all("ol"):
        ordered.name = "ul"

    for image in soup.find_all("img"):
        src = normalize_space(
            image.get("src")
        )

        if not src:
            image.decompose()
            continue

        src = urljoin(
            base_url,
            src
        )

        path = urlparse(
            src
        ).path.lower()

        if not path.endswith(
            IMAGE_EXTENSIONS
        ):
            image.decompose()
            continue

        alt = normalize_space(
            image.get("alt")
        ) or ""

        image.attrs = {
            "alt": alt,
            "src": src
        }

    allowed = {
        "h5",
        "br",
        "p",
        "ul",
        "li",
        "img"
    }

    for tag in list(
        soup.find_all(True)
    ):
        if tag.name in allowed:
            if tag.name != "img":
                tag.attrs = {}

            continue

        tag.unwrap()

    for tag in list(
        soup.find_all(
            [
                "p",
                "h5",
                "li"
            ]
        )
    ):
        text_value = normalize_space(
            tag.get_text(
                " ",
                strip=True
            )
        )

        if (
            not text_value
            and not tag.find("img")
        ):
            tag.decompose()

    result = str(soup).strip()

    return result if result else None


def extract_page_videos(
    soup,
    base_url
):
    result = []

    urls = []

    for tag in soup.find_all(
        [
            "video",
            "source",
            "a"
        ]
    ):
        for attribute in (
            "src",
            "href"
        ):
            value = normalize_space(
                tag.get(attribute)
            )

            if value:
                urls.append(
                    urljoin(
                        base_url,
                        value
                    )
                )

    for value in urls:
        path = urlparse(
            value
        ).path.lower()

        if not path.endswith(
            VIDEO_EXTENSIONS
        ):
            continue

        if value not in result:
            result.append(value)

    return result[:3]


def is_condition_goods(
    title,
    category
):
    haystack = " ".join(
        value
        for value in (
            title,
            category
        )
        if value
    ).lower()

    return any(
        word in haystack
        for word in CONDITION_WORDS
    )


def add_text(
    document,
    parent,
    name,
    value
):
    value = normalize_space(
        value
    )

    if value is None:
        return

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


def add_cdata(
    document,
    parent,
    name,
    value
):
    if not value:
        return

    value = value.replace(
        "]]>",
        "]] >"
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


def add_warning(
    report,
    code,
    warning,
    fields=None,
    details=None
):
    item = {
        "code": code,
        "warning": warning
    }

    if fields:
        item["fields"] = fields

    if details:
        item["details"] = details

    report["warnings"].append(
        item
    )


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

    report = {
        "generatedAt": datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        ).replace(
            "+00:00",
            "Z"
        ),
        "source": SOURCE_URL,
        "sourceOffers": len(
            source_offers
        ),
        "exported": 0,
        "skipped": [],
        "warnings": []
    }

    for source_offer in source_offers:
        code = normalize_space(
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
            report["skipped"].append(
                {
                    "code": code,
                    "reason": "not_available"
                }
            )
            continue

        source_title = node_text(
            source_offer,
            "name"
        )

        category_id = node_text(
            source_offer,
            "categoryId"
        )

        source_category = (
            categories.get(
                category_id
            )
            if category_id
            else None
        )

        if is_condition_goods(
            source_title,
            source_category
        ):
            report["skipped"].append(
                {
                    "code": code,
                    "reason": "condition_goods"
                }
            )
            continue

        product_url = node_text(
            source_offer,
            "url"
        )

        brand = node_text(
            source_offer,
            "vendor"
        )

        description_node = (
            source_offer.find(
                "description"
            )
        )

        source_description = (
            description_node.text
            if description_node is not None
            else None
        )

        source_params = get_source_params(
            source_offer
        )

        pictures = get_source_pictures(
            source_offer
        )

        raw_html = ""

        soup = BeautifulSoup(
            "",
            "html.parser"
        )

        jsonld_data = []

        if product_url:
            try:
                raw_html = fetch_text(
                    product_url
                )

                soup = BeautifulSoup(
                    raw_html,
                    "html.parser"
                )

                jsonld_data = parse_jsonld(
                    soup
                )
            except Exception as error:
                add_warning(
                    report,
                    code,
                    "product_page_fetch_failed",
                    details=str(error)
                )

        source_barcode = get_source_barcode(
            source_params
        )

        barcode = get_page_barcode(
            soup,
            raw_html,
            jsonld_data,
            source_barcode
        )

        vendor_code = get_vendor_code(
            soup,
            raw_html,
            jsonld_data,
            code
        )

        category = get_final_category(
            soup,
            jsonld_data,
            source_category,
            source_title
        )

        page_characteristics = (
            extract_page_characteristics(
                soup
            )
            if raw_html
            else []
        )

        description_characteristics = (
            extract_description_characteristics(
                source_description
            )
        )

        characteristics = (
            merge_characteristics(
                page_characteristics,
                description_characteristics,
                source_params
            )
        )

        packaging = (
            get_packaging_dimensions(
                characteristics
            )
        )

        title = sanitize_title(
            source_title
        )

        description = (
            sanitize_description(
                source_description,
                product_url
                or "https://babyup.ua/"
            )
        )

        videos = (
            extract_page_videos(
                soup,
                product_url
            )
            if raw_html
            and product_url
            else []
        )

        missing_required = []

        for field, value in (
            (
                "code",
                code
            ),
            (
                "vendor_code",
                vendor_code
            ),
            (
                "title",
                title
            ),
            (
                "category",
                category
            ),
            (
                "brand",
                brand
            ),
            (
                "description",
                description
            )
        ):
            if not value:
                missing_required.append(
                    field
                )

        if not pictures:
            missing_required.append(
                "image_link"
            )

        if missing_required:
            report["skipped"].append(
                {
                    "code": code,
                    "reason": "missing_required_fields",
                    "fields": missing_required
                }
            )
            continue

        if not barcode:
            add_warning(
                report,
                code,
                "missing_barcode",
                fields=[
                    "barcode"
                ]
            )

        missing_packaging = [
            field
            for field, value
            in packaging.items()
            if not value
        ]

        if missing_packaging:
            add_warning(
                report,
                code,
                "missing_packaging_dimensions",
                fields=missing_packaging
            )

        if len(
            characteristics
        ) < 3:
            add_warning(
                report,
                code,
                "few_characteristics",
                details=f"{len(characteristics)} characteristics found"
            )

        offer = document.createElement(
            "offer"
        )

        offers.appendChild(
            offer
        )

        add_text(
            document,
            offer,
            "id",
            code
        )

        add_text(
            document,
            offer,
            "code",
            code
        )

        add_text(
            document,
            offer,
            "vendor_code",
            vendor_code
        )

        add_text(
            document,
            offer,
            "title",
            title
        )

        if barcode:
            add_text(
                document,
                offer,
                "barcode",
                barcode
            )

        add_text(
            document,
            offer,
            "category",
            category
        )

        add_text(
            document,
            offer,
            "brand",
            brand
        )

        add_text(
            document,
            offer,
            "availability",
            "Є в наявності"
        )

        for field in (
            "weight",
            "height",
            "width",
            "length"
        ):
            if packaging[field]:
                add_text(
                    document,
                    offer,
                    field,
                    packaging[field]
                )

        add_cdata(
            document,
            offer,
            "description",
            description
        )

        image_link = (
            document.createElement(
                "image_link"
            )
        )

        offer.appendChild(
            image_link
        )

        for picture in pictures:
            add_text(
                document,
                image_link,
                "picture",
                picture
            )

        for video in videos:
            add_text(
                document,
                offer,
                "video_link",
                video
            )

        if characteristics:
            tags = document.createElement(
                "tags"
            )

            offer.appendChild(
                tags
            )

            for name, value in characteristics:
                param = (
                    document.createElement(
                        "param"
                    )
                )

                param.setAttribute(
                    "name",
                    name
                )

                param.appendChild(
                    document.createTextNode(
                        value
                    )
                )

                tags.appendChild(
                    param
                )

        report["exported"] += 1

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

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    REPORT_FILE.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    return report


def main():
    xml_bytes = fetch_bytes(
        SOURCE_URL
    )

    report = convert(
        xml_bytes
    )

    print(
        f"Generated {OUTPUT_FILE}: "
        f"{report['exported']} products, "
        f"{len(report['skipped'])} skipped, "
        f"{len(report['warnings'])} warnings"
    )


if __name__ == "__main__":
    main()
