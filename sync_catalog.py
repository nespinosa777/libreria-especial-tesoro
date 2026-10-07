#!/usr/bin/env python3
"""
Librería Especial Tesoro — sincronización v3

Fuente de catálogo: Vidalibros / Shopify products.json.
- Prueba: SYNC_LIMIT=10 descarga solamente 10 productos.
- Completo: SYNC_LIMIT=0 recorre páginas de hasta 250 productos.
- ISBN: intenta barcode, luego SKU y luego texto del producto.
- Portadas: Open Library por ISBN, pero solo se guarda si la imagen
  realmente responde con contenido de imagen.
- Google Books se deja fuera de la ruta principal porque devolvió 429.
- Si no hay productos, NO reemplaza products.json.
"""
import json
import os
import re
import time
from decimal import Decimal, ROUND_HALF_UP
from html import unescape
from pathlib import Path

import requests

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

BASE = CFG["source"].rstrip("/")
MARGIN = Decimal(str(CFG.get("margin_percent", 25))) / Decimal("100")
ROUND_TO = Decimal(str(CFG.get("round_to", 100)))
TEST_LIMIT = int(os.getenv("SYNC_LIMIT", "0") or "0")

HEADERS = {
    "User-Agent": "LibreriaEspecialTesoro/3.0 catalog-sync"
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
    rounded = (value / ROUND_TO).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    ) * ROUND_TO
    return int(rounded)


def html_to_text(value):
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", unescape(value)).strip()


def fetch_shopify_products():
    products = []

    if TEST_LIMIT:
        # Shopify accepts limit up to 250. Asking only for the test amount
        # makes the test genuinely small.
        data = get_json(
            f"{BASE}/products.json",
            {"limit": min(TEST_LIMIT, 250), "page": 1},
        )
        batch = data.get("products") or []
        return batch[:TEST_LIMIT]

    page = 1
    while True:
        data = get_json(
            f"{BASE}/products.json",
            {"limit": 250, "page": page},
        )
        batch = data.get("products") or []
        if not batch:
            break

        products.extend(batch)
        print(f"Productos descargados: {len(products)}")
        page += 1

        if page > 1000:
            raise RuntimeError("Se alcanzó el límite de seguridad de páginas.")

    return products


def find_isbn(product):
    variants = product.get("variants") or []

    for v in variants:
        isbn = clean_isbn(v.get("barcode"))
        if isbn:
            return isbn

    for v in variants:
        isbn = clean_isbn(v.get("sku"))
        if isbn:
            return isbn

    text = " ".join([
        str(product.get("title") or ""),
        str(product.get("body_html") or ""),
        " ".join(map(str, product.get("tags") or [])),
    ])

    matches = re.findall(
        r"(?<!\d)(97[89]\d{10}|\d{9}[\dXx])(?!\d)", text
    )
    return clean_isbn(matches[0]) if matches else None


def check_openlibrary_cover(isbn):
    """
    Open Library cover URL basada en ISBN.
    Verificamos que el servidor entregue realmente una imagen antes de
    guardarla. Así no contamos una URL inexistente como portada.
    """
    url = f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"

    try:
        r = SESSION.get(
            url,
            timeout=15,
            allow_redirects=True,
            stream=True,
        )
        content_type = (r.headers.get("content-type") or "").lower()
        ok = r.status_code == 200 and content_type.startswith("image/")
        r.close()

        if ok:
            return url, "Open Library"

    except requests.RequestException as e:
        print(f"  Open Library {isbn}: {e}")

    return None, None


def find_cover(isbn):
    if not isbn:
        return None, None

    return check_openlibrary_cover(isbn)


def main():
    print("=== Librería Especial Tesoro — sincronización v3 ===")
    print(f"Fuente: {BASE}")
    print(f"Margen: {MARGIN * 100}%")
    print(f"Límite de prueba: {TEST_LIMIT or 'catálogo completo'}")

    products = fetch_shopify_products()

    if not products:
        raise RuntimeError(
            "Vidalibros no devolvió productos. "
            "NO se modifica products.json."
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

        if isbn:
            isbn_count += 1

        image = None
        cover_source = None

        if isbn:
            image, cover_source = find_cover(isbn)
            if image:
                cover_count += 1

        compare = variant.get("compare_at_price")
        try:
            old = int(Decimal(str(compare))) if compare else None
        except Exception:
            old = None

        item = {
            "id": p.get("id"),
            "name": str(p.get("title") or "").strip(),
            "cost": cost,
            "price": sale_price(cost),
            "old": old,
            "available": any(
                bool(v.get("available")) for v in variants
            ) if variants else False,
            "sku": variant.get("sku"),
            "isbn": isbn,
            "cat": p.get("product_type") or "Libros",
            "tags": p.get("tags") or [],
            "description": (
                html_to_text(p.get("body_html"))
                if CFG.get("include_description") else ""
            ),
            "image": image,
            "cover_source": cover_source,
            "url": (
                f"{BASE}/products/{p.get('handle')}"
                if p.get("handle") else BASE
            ),
        }

        out.append(item)

        if i % 10 == 0 or i == len(products):
            print(
                f"Procesados: {i}/{len(products)} | "
                f"ISBN: {isbn_count} | Portadas reales: {cover_count}"
            )

        # Evita golpear demasiado rápido al servicio de portadas.
        if image is None and isbn:
            time.sleep(0.15)

    if not out:
        raise RuntimeError(
            "El catálogo resultó vacío. NO se modifica products.json."
        )

    target = ROOT / "products.json"
    target.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("=== RESULTADO ===")
    print(f"Productos encontrados: {len(out)}")
    print(f"ISBN encontrados: {isbn_count}")
    print(f"Portadas reales encontradas: {cover_count}")
    print(f"Guardado: {target}")


if __name__ == "__main__":
    main()
