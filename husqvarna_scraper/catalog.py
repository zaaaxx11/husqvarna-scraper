"""Catalogue enumeration from the portal's own navigation tree.

`/us/products/` ships the whole taxonomy as one JSON prop:

    groups -> category -> product type -> leaf link ("All Diamond blades" -> /us/diamond-blades/)

Measured 2026-10-20: 1 group, 8 categories, 32 product types, 73 leaf links, 579 distinct
products and 2,461 distinct articles. The `totalCount` printed on a leaf page belongs to the
parent type (132 repeats on every diamond leaf), so the rendered product list — not
`totalCount` — is the source of truth.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import httpx

BASE = "https://portal.husqvarnagroup.com"
CATALOG_URL = f"{BASE}/us/products/"

_PRODUCT_RE = re.compile(
    r'"__typename":"(?P<kind>[A-Za-z]+)","id":"(?P<pid>\{[0-9A-Fa-f-]+\})",'
    r'"sku":"(?P<sku>[^"]*)","url":"(?P<url>/[^"]+)"'
)
_ARTICLE_RE = re.compile(r'"__typename":"Article","id":"(?P<aid>\d{9})"')


@dataclass
class ProductRef:
    product_id: str
    url: str
    article_ids: list[str] = field(default_factory=list)
    category: str | None = None
    product_type: str | None = None

    @property
    def slug(self) -> str:
        return self.url.rstrip("/").rsplit("/", 1)[-1]


@dataclass
class Leaf:
    category: str
    product_type: str
    title: str
    url: str


def _extract_json_array(text: str, key: str = '"groups":') -> list[Any]:
    start = text.index(key) + len(key)
    depth = 0
    for pos in range(start, len(text)):
        if text[pos] == "[":
            depth += 1
        elif text[pos] == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:pos + 1])
    raise ValueError("unbalanced taxonomy array")


def parse_taxonomy(html: str) -> list[Leaf]:
    """Every leaf link, tagged with the category and product type above it."""
    leaves: list[Leaf] = []
    for group in _extract_json_array(html):
        for category in group.get("list") or []:
            for product_type in category.get("list") or []:
                for leaf in product_type.get("list") or []:
                    href = (leaf.get("link") or {}).get("href")
                    if not href:
                        continue
                    leaves.append(Leaf(
                        category=category.get("title") or "",
                        product_type=product_type.get("title") or "",
                        title=(leaf.get("link") or {}).get("text") or leaf.get("title") or "",
                        url=urljoin(BASE, href),
                    ))
    return leaves


def parse_product_page(html: str, *, category: str | None = None,
                       product_type: str | None = None) -> list[ProductRef]:
    """Product/article pairs from a rendered listing page."""
    products: list[ProductRef] = []
    seen: set[str] = set()
    for match in _PRODUCT_RE.finditer(html):
        pid = match.group("pid")
        if pid in seen:
            continue
        tail = html[match.end():match.end() + 4000]
        articles = list(dict.fromkeys(_ARTICLE_RE.findall(tail)))
        if not articles:
            continue
        seen.add(pid)
        products.append(ProductRef(
            product_id=pid,
            url=urljoin(BASE, match.group("url")),
            article_ids=articles,
            category=category,
            product_type=product_type,
        ))
    return products


async def fetch_taxonomy(client: httpx.AsyncClient) -> list[Leaf]:
    resp = await client.get(CATALOG_URL)
    resp.raise_for_status()
    return parse_taxonomy(resp.text)


async def enumerate_products(
    client: httpx.AsyncClient,
    *,
    only_category: str | None = None,
    on_leaf=None,
) -> list[ProductRef]:
    """Fetch every leaf listing page and return the distinct products it renders."""
    leaves = await fetch_taxonomy(client)
    if only_category:
        wanted = only_category.strip().lower()
        leaves = [l for l in leaves if wanted in l.category.lower()]
    products: dict[str, ProductRef] = {}
    for leaf in leaves:
        try:
            resp = await client.get(leaf.url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            if on_leaf:
                on_leaf(leaf, 0, f"{type(exc).__name__}")
            continue
        found = parse_product_page(resp.text, category=leaf.category,
                                   product_type=leaf.product_type)
        for ref in found:
            existing = products.get(ref.product_id)
            if existing is None:
                products[ref.product_id] = ref
            else:
                existing.article_ids = list(dict.fromkeys(existing.article_ids + ref.article_ids))
        if on_leaf:
            on_leaf(leaf, len(found), None)
    return list(products.values())
