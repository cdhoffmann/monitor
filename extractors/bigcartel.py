"""Extractor for BigCartel storefronts. Pulls product name, price, and sold-out status."""
import json
import re
import urllib.request

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# Max chars to scan inside each product's <a> block (BigCartel cards are large due to srcset)
_BLOCK_SCAN = 5000


def extract(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode('utf-8')

    # Product names + slugs come from JSON-LD — reliable regardless of theme
    names = {}
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if data.get('@type') == 'ItemList':
            for item in data.get('itemListElement', []):
                item_url = item.get('url', '')
                slug = item_url.rstrip('/').split('/')[-1]
                if slug:
                    names[slug] = item.get('name', slug)
            break

    products = {}
    for slug, name in names.items():
        # Find the product's <a> card in the HTML
        idx = html.find(f'href="/product/{slug}"')
        if idx == -1:
            continue
        block = html[idx: idx + _BLOCK_SCAN]

        sold_out = bool(re.search(r'prod-thumb-status[^>]*>[^<]*sold\s*out', block, re.I))

        price_match = re.search(r'data-currency-amount="([\d.]+)"', block)
        if price_match:
            amount = float(price_match.group(1))
            price = f'${amount:,.2f}' if amount == int(amount) else f'${amount}'
        else:
            price = 'unknown'

        products[f'/product/{slug}'] = {
            'name': name,
            'sold_out': sold_out,
            'price': price,
        }

    return products
