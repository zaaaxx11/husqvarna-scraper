"""Async GraphQL client for the Husqvarna portal.

One endpoint, three operations, no auth. The client owns the things that make a long run
survive: a shared rate limit, bounded retries with backoff, and batched part lookups so a
150-part machine costs 8 requests instead of 150.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from .queries import PART_QUERY, PRODUCT_QUERY, REPLACEMENT_HISTORY_FIELDS, SITE

GRAPHQL_URL = "https://portal.husqvarnagroup.com/hbd/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://portal.husqvarnagroup.com",
    "Referer": "https://portal.husqvarnagroup.com/",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
}


class GraphQLError(RuntimeError):
    """The endpoint answered 200 with an `errors` array."""


class HusqClient:
    def __init__(
        self,
        *,
        site: str = SITE,
        rps: float = 2.0,
        retries: int = 3,
        timeout: float = 45.0,
        batch_size: int = 20,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.site = site
        self.rps = max(rps, 0.1)
        self.retries = retries
        self.batch_size = max(1, batch_size)
        self._client = client or httpx.AsyncClient(timeout=timeout, headers=HEADERS)
        self._owns_client = client is None
        self._gate = asyncio.Lock()
        self._next_at = 0.0
        self.stats = {"requests": 0, "bytes": 0, "retries": 0}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "HusqClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ plumbing
    async def _throttle(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._gate:
            now = loop.time()
            wait = self._next_at - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = loop.time()
            self._next_at = now + (1.0 / self.rps)

    async def post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        payload = {"query": query, "variables": variables}
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            await self._throttle()
            try:
                resp = await self._client.post(GRAPHQL_URL, json=payload)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last = exc
            else:
                self.stats["requests"] += 1
                self.stats["bytes"] += len(resp.content)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp)
                elif resp.status_code != 200:
                    raise GraphQLError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    body = resp.json()
                    if body.get("errors"):
                        raise GraphQLError(str(body["errors"])[:300])
                    return body.get("data") or {}
            self.stats["retries"] += 1
            await asyncio.sleep(min(2 ** attempt * 0.5 + random.random() * 0.3, 8.0))
        raise GraphQLError(f"gave up after {self.retries} attempts: {last}")

    # ------------------------------------------------------------------ operations
    async def product_sections(self, article_id: str) -> dict[str, Any]:
        data = await self.post(PRODUCT_QUERY, {"siteName": self.site, "articleId": article_id})
        items = (data.get("site", {}).get("articles", {}) or {}).get("byIds") or []
        if not items or items[0] is None:
            raise GraphQLError(f"article {article_id} not returned")
        return items[0]

    async def product_hero(self, product_id: str) -> dict[str, Any] | None:
        from .queries import HERO_QUERY

        data = await self.post(HERO_QUERY, {"siteName": self.site, "productId": product_id})
        items = (data.get("site", {}).get("products", {}) or {}).get("byIds") or []
        return items[0] if items else None

    async def parts(self, part_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch part details in batches; returns {part_id: part-or-None}."""
        out: dict[str, dict[str, Any] | None] = {}
        for start in range(0, len(part_ids), self.batch_size):
            chunk = part_ids[start:start + self.batch_size]
            out.update(await self._parts_batch(chunk))
        return out  # type: ignore[return-value]

    async def _parts_batch(self, chunk: list[str]) -> dict[str, dict[str, Any] | None]:
        data = await self.post(batched_part_query(chunk), {"siteName": self.site})
        block = (data.get("site", {}) or {}).get("spareParts") or {}
        result: dict[str, dict[str, Any] | None] = {}
        for idx, pid in enumerate(chunk):
            result[pid] = block.get(f"p{idx}")
        return result


def batched_part_query(ids: list[str]) -> str:
    """One request for N parts: the captured fragment, aliased once per id.

    `getSparePart` alone does not include `replacementHistory`; the portal fetches it in a
    second call. Merging it into the same fragment was verified live (20/20 parts in one
    request, 116 KB response), which halves the request count of a full product.
    """
    _head, frag = PART_QUERY.split("fragment sparepart on SparePart", 1)
    if "replacementHistory" not in frag:
        frag = frag.replace("  __typename\n", f"  __typename\n  {REPLACEMENT_HISTORY_FIELDS}\n", 1)
    aliases = "\n".join(f'    p{i}: byId(id: "{pid}") {{ ...sparepart }}' for i, pid in enumerate(ids))
    return (
        "query batchSpareParts($siteName: String!) {\n"
        "  site(name: $siteName) {\n"
        "    spareParts {\n"
        f"{aliases}\n"
        "    }\n"
        "  }\n"
        "}\n\n"
        "fragment sparepart on SparePart" + frag
    )
