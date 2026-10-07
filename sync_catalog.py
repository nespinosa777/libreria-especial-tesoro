#!/usr/bin/env python3
"""
Sincronizador de LIBRERÍA ESPECIAL TESORO.

Obtiene el catálogo público de Vidalibros (Shopify), aplica el margen
configurado y busca una portada por ISBN.

Protecciones:
- Si no se obtiene ningún producto, NO reemplaza products.json.
- SYNC_LIMIT permite probar con pocos productos.
- Las portadas se validan por ISBN cuando la fuente lo permite.
"""
import json
import os
import re
import time
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from html import unescape

import requests

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

BASE = CFG["source"].rstrip("/")
MARGIN = Decimal(str(CFG.get("margin_percent", 25))) / Decimal("100")
ROUND_TO = Decimal(str(CFG.get("round_to", 100)))
TEST_LIMIT = int(os.getenv("SYNC_LIMIT", "0") or "0")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LibreriaEspecialTesoro/2.0; catalog-sync)"
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def get_json(url, params=None, timeout=30):
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def clean_isbn(value):
    if not value:
        return None
    s = re.sub(r"[^0-9Xx]", "", str(value))
    if len(s) in (10, 13):
        return s.upper()
    return None


def sale_price(cost):
    if not cost:
        return 0
    value = Decimal(str(cost)) * (Decimal("1") + MARGIN)
    rounded = (value / ROUND_TO).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * ROUND_TO
    return int(rounded)


def html_to_text(value):
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", str(value))
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def fetch_shopify_products():
    """Try Shopify's public products.json in pages of up to 250."""
    products = []
    page = 1

    while True:
        data = get_json(f"{BASE}/products.json", {"limit": 250, "page": page})
        batch = data.get("products") or []
        if not batch:
            break

        products.extend(batch)
        print(f"Productos descargados: {len(products)}")

        if TEST_LIMIT and len(products) >= TEST_LIMIT:
            return products[:TEST_LIMIT]

        # Public products.json pagination returns an empty page when finished.
        page += 1
        if page > 1000:
            raise RuntimeError("Demasiadas páginas; se detuvo por seguridad.")

    return products


def find_isbn(product):
    variants = product.get("variants") or []
    # Prefer barcode because Shopify stores ISBNs there on many book catalogs.
    for v in variants:
        isbn = clean_isbn(v.get("barcode"))
        if isbn:
            return isbn
    for v in variants:
        isbn = clean_isbn(v.get("sku"))
        if isbn:
            return isbn

    # Fallback: search ISBN-like strings in product text.
    text = " ".join([
        str(product.get("title") or ""),
        str(product.get("body_html") or ""),
        " ".join(map(str, product.get("tags") or [])),
    ])
    matches = re.findall(r"(?<!\d)(97[89]\d{10}|\d{9}[\dXx])(?!\d)", text)
    return clean_isbn(matches[0]) if matches else None


def google_books_cover(isbn):
    """Return a cover only when Google Books reports the exact ISBN."""
    try:
        data = get_json(
            "https://www.googleapis.com/books/v1/volumes",
            {"q": f"isbn:{isbn}", "maxResults": 5},
            timeout=20,
        )
        for item in data.get("items") or []:
            info = item.get("volumeInfo") or {}
            ids = info.get("industryIdentifiers") or []
            exact = any(clean_isbn(x.get("identifier")) == isbn for x in ids)
            links = info.get("imageLinks") or {}
            cover = links.get("thumbnail") or links.get("smallThumbnail")
            if exact and cover:
                return cover.replace("http://", "https://")
    except Exception as e:
        print(f"  Google Books: {e}")
    return None


def openlibrary_cover(isbn):
    # Open Library's ISBN cover endpoint is deterministic.
    return f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"


def find_cover(isbn):
    if not isbn:
        return None, None

    cover = google_books_cover(isbn)
    if cover:
        return cover, "Google Books"

    # Keep Open Library as a fallback URL. The browser will request the image
    # only when the product is displayed.
    return openlibrary_cover(isbn), "Open Library"


def main():
    print("=== Librería Especial Tesoro — sincronización v2 ===")
    print(f"Fuente: {BASE}")
    print(f"Margen: {MARGIN * 100}%")
    print(f"Límite de prueba: {TEST_LIMIT or 'sin límite'}")

    products = fetch_shopify_products()

    if not products:
        raise RuntimeError(
            "Vidalibros no devolvió productos. Se conserva products.json existente."
        )

    out = []
    isbn_count = 0
    cover_count = 0

    for i, p in enumerate(products, 1):
        variants = p.get("variants") or []
        variant = variants[0] if variants else {}

        raw_price = variant.get("price")
        try:
            cost = int(Decimal(str(raw_price or "0")))
        except Exception:
            cost = 0

        isbn = find_isbn(p)
        image = None
        cover_source = None

        if isbn:
            isbn_count += 1
            image, cover_source = find_cover(isbn)
            if image:
                cover_count += 1

        item = {
            "id": p.get("id"),
            "name": str(p.get("title") or "").strip(),
            "cost": cost,
            "price": sale_price(cost),
            "old": int(Decimal(str(variant.get("compare_at_price") or "0"))) if variant.get("compare_at_price") else None,
            "available": any(bool(v.get("available")) for v in variants) if variants else False,
            "sku": variant.get("sku"),
            "isbn": isbn,
            "cat": p.get("product_type") or "Libros",
            "tags": p.get("tags") or [],
            "description": html_to_text(p.get("body_html")) if CFG.get("include_description") else "",
            "image": image,
            "cover_source": cover_source,
            "source_image": p.get("images", [{}])[0].get("src") if p.get("images") else None,
            "url": f"{BASE}/products/{p.get('handle')}" if p.get("handle") else BASE,
        }
        out.append(item)

        if i % 25 == 0:
            print(f"Procesados: {i}/{len(products)} | ISBN: {isbn_count} | Portadas: {cover_count}")
        time.sleep(0.05)

    if not out:
        raise RuntimeError("El catálogo resultó vacío. No se modifica products.json.")

    target = ROOT / "products.json"
    target.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("=== RESULTADO ===")
    print(f"Productos encontrados: {len(out)}")
    print(f"ISBN encontrados: {isbn_count}")
    print(f"Portadas encontradas: {cover_count}")
    print(f"Guardado: {target}")


if __name__ == "__main__":
    main()
