# Librería Especial Tesoro — V3

## Qué hace
- Catálogo web responsive.
- Carrito con cantidades.
- Pedido completo por WhatsApp: 300 552 9485.
- `config.json` controla el margen (25% inicial).
- `sync_catalog.py` intenta obtener los productos públicos de Vidalibros mediante sus endpoints públicos de Shopify.
- GitHub Actions puede ejecutar la sincronización diariamente.

## Publicación gratuita recomendada
1. Crear un repositorio privado o público en GitHub.
2. Subir estos archivos.
3. Activar GitHub Actions.
4. Publicar el sitio con Cloudflare Pages conectado al repositorio.
5. Cada sincronización actualizará `products.json`.

## Importante
La sincronización técnica no significa que exista autorización para reutilizar imágenes, textos o marcas de Vidalibros. Antes de usar el catálogo completo comercialmente, confirma los permisos correspondientes. Se recomienda empezar con datos/productos autorizados.

## Margen
En `config.json`:
`"margin_percent": 25`

El precio de venta se calcula como:
precio Vidalibros x (1 + margen)
y se redondea al valor indicado en `round_to`.
Sitio web de Librería Especial Tesoro.
