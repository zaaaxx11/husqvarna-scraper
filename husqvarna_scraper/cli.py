"""Command line entry point.

    husqvarna-scraper article 968424101 --out out --layout both
    husqvarna-scraper category https://portal.husqvarnagroup.com/us/diamond-blades/ --name diamond-blades
    husqvarna-scraper all --out out --resume

A run is resumable: every finished article is recorded in `_state.json`, and `--resume`
skips it. Failures are per-part (`_errors.json`) and per-article (state `failed`), never a
silently short file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from .catalog import CATALOG_URL, ProductRef, enumerate_products
from .client import HusqClient
from .pipeline import (
    build_plots,
    build_product,
    collect_part_ids,
    part_record,
    write_article,
    write_category_article,
)
from .queries import SITE

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
CATALOG_URL = "https://portal.husqvarnagroup.com/us/products/"


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Runner:
    def __init__(self, out: Path, *, layout: str, resume: bool, concurrency: int, rps: float,
                 batch_size: int, site: str, limit: int = 0) -> None:
        self.out = out
        self.layout = layout
        self.resume = resume
        self.concurrency = concurrency
        self.client = HusqClient(site=site, rps=rps, batch_size=batch_size)
        self.state_path = out / "_state.json"
        self.limit = limit
        self.state: dict[str, Any] = self._load_state()
        self.done: set[str] = set(self.state.get("done", []))
        self.failed: dict[str, str] = dict(self.state.get("failed", {}))

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text())
            except json.JSONDecodeError:
                pass
        return {"done": [], "failed": {}}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = {"done": sorted(self.done), "failed": self.failed,
                      "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self.state_path.write_text(json.dumps(self.state, indent=1))

    async def close(self) -> None:
        await self.client.aclose()

    # ------------------------------------------------------------------ one article
    async def scrape_article(
        self,
        article_id: str,
        *,
        product_id: str | None = None,
        category: str | None = None,
        mode: str = "article",
    ) -> None:
        if self.resume and article_id in self.done:
            return
        sections = await self.client.product_sections(article_id)
        hero = None
        if product_id:
            try:
                hero = await self.client.product_hero(product_id)
            except Exception as exc:  # noqa: BLE001
                _log(f"  hero failed for {product_id}: {type(exc).__name__}")
        plots = build_plots(sections)
        part_ids = collect_part_ids(sections)
        rows = await self.client.parts(part_ids)
        errors = {pid: "not returned" for pid, val in rows.items() if val is None}
        parts = {pid: val for pid, val in rows.items() if val is not None}

        if mode == "category":
            write_category_article(self.out, sections, category=category or "other",
                                   plots=plots, parts=parts, errors=errors)
        else:
            product = build_product(sections, hero)
            write_article(self.out, sections, product=product, plots=plots,
                          parts=parts, errors=errors, layout=self.layout)
        self.done.add(article_id)
        self.failed.pop(article_id, None)
        self._save_state()
        _log(f"  ok {article_id}: {len(part_ids)} parts, {len(errors)} missing")

    # ------------------------------------------------------------------ batches
    async def run_refs(self, refs: list[ProductRef], *, category: str | None, mode: str,
                       limit: int = 0) -> None:
        if limit:
            refs = refs[:limit]
        sem = asyncio.Semaphore(self.concurrency)

        async def one(ref: ProductRef) -> None:
            async with sem:
                for aid in ref.article_ids:
                    try:
                        await self.scrape_article(
                            aid, product_id=ref.product_id,
                            category=category, mode=mode)
                    except Exception as exc:  # noqa: BLE001
                        self.failed[aid] = f"{type(exc).__name__}: {exc}"
                        self._save_state()
                        _log(f"  FAIL {aid}: {type(exc).__name__}: {exc}")

        await asyncio.gather(*(one(r) for r in refs))

    async def run_category(self, only: str | None, *, name: str) -> None:
        async with httpx.AsyncClient(timeout=45, headers={"User-Agent": USER_AGENT}) as http:
            _log(f"reading taxonomy from {CATALOG_URL}")
            refs = await enumerate_products(
                http, only_category=only,
                on_leaf=lambda leaf, n, err: _log(
                    f"  {leaf.category[:22]:22s} | {leaf.product_type[:26]:26s} | "
                    f"{leaf.title[:30]:30s} -> {n if not err else 'ERR ' + err}"))
        articles = sum(len(r.article_ids) for r in refs)
        _log(f"{name}: {len(refs)} products, {articles} articles")
        await self.run_refs(refs, category=name, mode="category", limit=self.limit)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("husqvarna-scraper",
                                description="Scrape Husqvarna portal products, IPLs and parts.")
    sub = p.add_subparsers(dest="command", required=True)

    for name in ("article", "category", "all"):
        sp = sub.add_parser(name)
        sp.add_argument("target", nargs="*", help="article ids, or a category URL")
        sp.add_argument("--out", default="out")
        sp.add_argument("--layout", choices=("canonical", "by_plot", "both"), default="both")
        sp.add_argument("--resume", action="store_true")
        sp.add_argument("--concurrency", type=int, default=2)
        sp.add_argument("--rps", type=float, default=2.0)
        sp.add_argument("--batch-size", type=int, default=20)
        sp.add_argument("--site", default=SITE)
        sp.add_argument("--limit", type=int, default=0,
                        help="stop after N products (0 = no cap)")
        sp.add_argument("--name", default=None,
                        help="category to run, e.g. \"Diamond tools\" (case-insensitive substring)")
    return p


async def main_async(args: argparse.Namespace) -> int:
    out = Path(args.out)
    runner = Runner(out, layout=args.layout, resume=args.resume,
                    concurrency=args.concurrency, rps=args.rps,
                    batch_size=args.batch_size, site=args.site, limit=args.limit)
    try:
        if args.command == "article":
            if not args.target:
                print("give at least one article id", file=sys.stderr)
                return 2
            for aid in args.target:
                await runner.scrape_article(aid, mode="article")
        elif args.command == "category":
            only = args.name or (" ".join(args.target) if args.target else None)
            await runner.run_category(only, name=only or "all")
        else:
            await runner.run_category(args.name, name=args.name or "all")
    finally:
        stats = runner.client.stats
        _log(f"requests={stats['requests']} bytes={stats['bytes']} retries={stats['retries']}")
        await runner.close()
    return 0


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
