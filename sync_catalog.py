#!/usr/bin/env python3
"""
Sincronizador de LIBRERÍA ESPECIAL TESORO.

Flujo:
1) Lee el sitemap de productos de Vidalibros.
2) Obtiene el JSON público de cada producto Shopify.
3) Conserva título, precio actual, precio anterior, disponibilidad, SKU/ISBN,
   imagen, tipo y etiquetas.
4) Aplica el margen configurado en config.json.
5) Genera products.json para la tienda.

Nota: antes de publicar el catálogo completo, confirma que tienes autorización
para reutilizar imágenes, descripciones y demás contenidos de terceros.
"""
import json, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
import xml.etree.ElementTree as ET

ROOT=Path(__file__).parent
CFG=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
BASE=CFG["source"].rstrip("/")
MARGIN=CFG["margin_percent"]/100
ROUND_TO=CFG.get("round_to",100)

HEADERS={"User-Agent":"LibreriaEspecialTesoro/1.0 catalog-sync"}

def money_round(v):
    return int(round((v*(1+MARGIN))/ROUND_TO)*ROUND_TO)

def get(url):
    r=requests.get(url,headers=HEADERS,timeout=30)
    r.raise_for_status()
    return r

def sitemap_urls():
    urls=[]
    # Shopify normally exposes sitemap_products_1.xml; there may be more than one.
    for n in range(1,30):
        u=f"{BASE}/sitemap_products_{n}.xml"
        try:
            txt=get(u).text
        except Exception:
            if n==1:
                continue
            break
        try:
            root=ET.fromstring(txt)
            for loc in root.iter():
                if loc.tag.lower().endswith("loc") and "/products/" in (loc.text or ""):
                    urls.append(loc.text.strip())
        except ET.ParseError:
            break
    # fallback to sitemap index
    if not urls:
        idx=get(f"{BASE}/sitemap.xml").text
        root=ET.fromstring(idx)
        children=[x.text.strip() for x in root.iter()
                  if x.tag.lower().endswith("loc") and "sitemap_products_" in (x.text or "")]
        for u in children:
            try:
                root2=ET.fromstring(get(u).text)
                urls += [x.text.strip() for x in root2.iter()
                         if x.tag.lower().endswith("loc") and "/products/" in (x.text or "")]
            except Exception:
                pass
    return sorted(set(urls))

def product_json(product_url):
    handle=product_url.rstrip("/").split("/products/",1)[-1]
    return get(f"{BASE}/products/{handle}.js").json()

def main():
    urls=sitemap_urls()
    print(f"Productos encontrados en sitemap: {len(urls)}")
    out=[]
    for i,u in enumerate(urls,1):
        try:
            p=product_json(u)
            price=int(p.get("price") or 0)
            old=p.get("compare_at_price")
            item={
                "id":p.get("id"),
                "name":p.get("title","").strip(),
                "cost":price,
                "price":money_round(price) if price else 0,
                "old":int(old) if old else None,
                "available":bool(p.get("available")),
                "sku":(p.get("variants") or [{}])[0].get("sku"),
                "isbn":(p.get("variants") or [{}])[0].get("barcode"),
                "cat":p.get("type") or "Libros",
                "tags":p.get("tags") or [],
                "description":p.get("description","") if CFG.get("include_description") else "",
                "image":p.get("featured_image") or ((p.get("images") or [None])[0]),
                "url":u
            }
            out.append(item)
            if i%50==0: print(f"Procesados: {i}/{len(urls)}")
            time.sleep(0.05)
        except Exception as e:
            print("ERROR",u,e)
    (ROOT/"products.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Guardados: {len(out)} productos en products.json")

if __name__=="__main__":
    main()
