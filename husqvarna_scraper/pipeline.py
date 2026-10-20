"""Turn portal answers into the three output layouts.

The layouts were reverse-engineered from the operator's own archives, so the shapes here
are copied, not designed:

  canonical   parts/<id>.json  + plots/<PLOT>.json    (plot lists part_file)
  by_plot     <PLOT>/<id>.json + <PLOT>/_category.json (plot lists available)
  category    same as by_plot, minus product.json, plus related_products.json
              and a _part_list.json carrying `category` + `missing_part_ids`

Everything below is derived from two responses: the product query (IPL diagrams carry the
part list, positions and coordinates) and the batched part queries (specifications and
replacement history).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

NBSP = "\u00a0"
NB_HYPHEN = "\u2011"


def plot_slug(name: str) -> str:
    """'CHASSIS / FRAME' -> 'CHASSIS_FRAME' (the folder names in the archives)."""
    return re.sub(r"[^A-Z0-9]+", "_", (name or "").upper()).strip("_")


def format_article_number(number: str) -> str:
    """'968424101' -> '968 42 41‑01' (nbsp + non-breaking hyphen, as the portal renders it)."""
    digits = re.sub(r"\D", "", number or "")
    if len(digits) != 9:
        return number or ""
    return f"{digits[:3]}{NBSP}{digits[3:5]}{NBSP}{digits[5:7]}{NB_HYPHEN}{digits[7:]}"


def build_plots(article: dict[str, Any]) -> list[dict[str, Any]]:
    """IPL diagrams -> plot records with their parts (positions, quantities, coords)."""
    plots: list[dict[str, Any]] = []
    for ipl in article.get("ipls") or []:
        parts = []
        for item in ipl.get("articles") or []:
            parts.append({
                "article_number": item.get("id"),
                "position": item.get("number"),
                "quantity": item.get("quantity"),
                "name": item.get("name"),
                "article_description": item.get("articleDescription"),
                "comment": item.get("comment"),
                "replaced_ids": item.get("replacedIds"),
                "coordinates": item.get("coordinates") or [],
                "source_url": item.get("url"),
            })
        plots.append({
            "main_product_article": article.get("id"),
            "plot_id": ipl.get("id"),
            "plot_name": ipl.get("name"),
            "plot_image": ipl.get("image"),
            "parts": parts,
        })
    return plots


def collect_part_ids(article: dict[str, Any]) -> list[str]:
    """IPL parts first, then spareParts entries that no diagram mentions.

    Measured on the operator's archives: 151 from the diagrams + 4 from spareParts = 155,
    exactly the `part_ids` list they shipped.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for ipl in article.get("ipls") or []:
        for item in ipl.get("articles") or []:
            pid = item.get("id")
            if pid and pid not in seen:
                seen.add(pid)
                ids.append(pid)
    for part in article.get("spareParts") or []:
        pid = part.get("id")
        if pid and pid not in seen:
            seen.add(pid)
            ids.append(pid)
    # The archives list part_ids in ascending article order, not in diagram order.
    return sorted(ids)


def part_record(
    part: dict[str, Any] | None,
    *,
    refs: list[dict[str, Any]],
    available: bool,
    product_article: str | None = None,
    product_name: str | None = None,
    spare_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One part file, in the exact shape the operator's archives use.

    `source.references` is the provenance trail: an IPL row records where on the diagram the
    part sits; a part that only exists in the spare-parts list records the spare-parts entry
    instead (`source_type: "spareParts"`).
    """
    part = part or {}
    specs = part.get("specifications") or {}
    references = list(refs)
    if not references and spare_meta:
        references = [{
            "source_type": "spareParts",
            "name": spare_meta.get("name"),
            "article_description": spare_meta.get("articleDescription"),
            "source_url": spare_meta.get("url"),
            "brand": part.get("brand") or "Unbranded",
        }]
    also = [
        {
            "__typename": row.get("__typename"),
            "id": row.get("id"),
            "name": {
                "shortName": (row.get("name") or {}).get("shortName"),
                "productName": (row.get("name") or {}).get("productName"),
            },
        }
        for row in (part.get("alsoUsedIn") or [])
        if isinstance(row, dict)
    ]
    raw = dict(part)
    raw.setdefault("mainImageData", None)
    raw.setdefault("price", None)
    raw.setdefault("description", part.get("description"))
    return {
        "information": {
            "subtitle": part.get("articleDescription") or specs.get("articleDescription"),
            "article_number": part.get("id"),
            "article_number_formatted": part.get("articleNumberFormatted"),
            "article_description": part.get("description"),
            "name": part.get("name"),
            "commercial_reference": part.get("commercialReference"),
            "url": part.get("url"),
            "brand": part.get("brand"),
            "main_image": ({k: part["mainImage"].get(k) for k in ("url", "altText")}
                            if isinstance(part.get("mainImage"), dict) else part.get("mainImage")),
            "price": None,
        },
        "Specification": {"articleDescription": part.get("articleDescription"), **specs},
        "replacement_history": part.get("replacementHistory") or [],
        "also_used_in": also,
        "source": {
            "main_product_article": product_article,
            "main_product_name": product_name,
            "references": references,
        },
        "raw_part": raw,
        "available": available,
    }


def build_related(article: dict[str, Any]) -> dict[str, Any]:
    """related_products.json — the archives only ever carried accessories/tools here."""
    items: list[dict[str, Any]] = []
    for source_type in ("relatedAccessories", "relatedTools"):
        block = article.get(source_type)
        rows = block.get("result") if isinstance(block, dict) else block
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            items.append({
                "article_number": row.get("id"),
                "article_number_formatted": row.get("numberFormatted"),
                "name": (name or {}).get("shortName") if isinstance(name, dict) else name,
                "article_description": row.get("articleDescription"),
                "image": row.get("mainImage"),
                "source_type": source_type,
            })
    return {
        "main_product_article": article.get("id"),
        "total_count": len(items),
        "related_products": items,
    }


def build_product(article: dict[str, Any], hero: dict[str, Any] | None) -> dict[str, Any]:
    """product.json — portal fields plus the handful of derived keys the archives carry.

    The archives contain keys the portal does not publish (variant_specs, numberOfVariants,
    standardEquipment, mainVideo). They are reconstructed here from the hero response and
    from empty defaults, and the reconstruction is stated in the README rather than passed
    off as portal data.
    """
    hero = hero or {}
    hero_articles = hero.get("articles") or []
    hero_article = next(
        (a for a in hero_articles if str(a.get("id")) == str(article.get("id"))),
        hero_articles[0] if hero_articles else {},
    )
    name = article.get("name") or {}
    product = article.get("product") or {}
    short = name.get("shortName") or name.get("longName") or name.get("productName")
    long = name.get("longName") or name.get("productName") or short
    main_image = hero_article.get("mainImage") or hero.get("mainImage")
    price = hero_article.get("listPrice") or {}
    specs_by_id = {
        s.get("id"): s.get("name")
        for s in ((hero.get("specifications") or {}).get("topSpecificationDefinitions") or [])
    }
    variant_specs = []
    for a in hero_articles or [article]:
        values = {
            specs_by_id.get(v.get("id"), v.get("id")): v.get("formattedValue")
            for v in a.get("specificationValues") or []
        }
        variant_specs.append({
            "article_id": a.get("id"),
            "article_number": a.get("numberFormatted") or format_article_number(a.get("id", "")),
            "name": ((a.get("name") or {}) if isinstance(a.get("name"), dict) else {}).get("shortName")
                    or (a.get("name") if isinstance(a.get("name"), str) else None),
            "price": (a.get("listPrice") or {}).get("listPriceExcludingVat"),
            "specifications": values,
        })

    return {
        "id": article.get("id"),
        "number": article.get("id"),
        "numberFormatted": format_article_number(article.get("id", "")),
        "name": {
            "shortName": short,
            "longName": long,
            "productName": name.get("productName") or long,
        },
        "articleDescription": article.get("articleDescription"),
        "description": {
            "shortDescription": article.get("articleDescription"),
            "longDescription": hero_article.get("introductionText") or article.get("articleDescription"),
        },
        "introductionText": hero_article.get("introductionText"),
        "tagline": hero.get("tagline"),
        "listPrice": price,
        "images": [main_image] if main_image else [],
        "mainImageData": main_image,
        "mainVideo": {"link": None},
        "isDiscontinued": article.get("isDiscontinued"),
        "isNew": article.get("isNew"),
        "numberOfVariants": len(hero_articles) or 1,
        "variant_specs": variant_specs,
        "fitsTo": hero_article.get("fitsTo") or [],
        "included": [],
        "notIncluded": [],
        "standardEquipment": {"totalCount": 0, "result": []},
        "repairabilityIndex": hero_article.get("repairabilityIndex"),
        "iplDocuments": article.get("iplDocuments") or [],
        "ipls": article.get("ipls") or [],
        "product": {
            "category": (product.get("category") or {}).get("name") if isinstance(product.get("category"), dict) else product.get("category"),
            "id": hero.get("id"),
            "name": {"longName": long},
            "url": hero.get("url"),
        },
        "relatedAccessories": article.get("relatedAccessories") or {},
        "relatedTools": article.get("relatedTools") or [],
        "alsoUsedIn": article.get("alsoUsedIn") or [],
        "additionalFeatures": article.get("additionalFeatures") or [],
        "serviceArticleOffers": article.get("serviceArticleOffers"),
    }



def reference_index(plots: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """part_id -> the IPL rows that mention it, in the archives' reference shape."""
    index: dict[str, list[dict[str, Any]]] = {}
    for plot in plots:
        for row in plot["parts"]:
            index.setdefault(row["article_number"], []).append({
                "source_type": "ipl",
                "ipl_id": plot.get("plot_id"),
                "ipl_name": plot.get("plot_name"),
                "position": row.get("position"),
                "quantity": row.get("quantity"),
                "name": row.get("name"),
                "article_description": row.get("article_description"),
                "comment": row.get("comment"),
                "replaced_ids": row.get("replaced_ids"),
                "coordinates": row.get("coordinates"),
                "source_url": row.get("source_url"),
            })
    return index


def spare_index(article: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p.get("id"): p for p in (article.get("spareParts") or []) if isinstance(p, dict)}


def main_product_name(article: dict[str, Any], product: dict[str, Any] | None = None) -> str | None:
    raw = None
    if product:
        raw = (product.get("name") or {}).get("shortName")
    if not raw:
        name = article.get("name") or {}
        raw = name.get("shortName") or name.get("longName") or name.get("productName")
    if not raw:
        return None
    # The archives drop the brand prefix: "Husqvarna K 3600 MK II" -> "K 3600 MK II".
    clean = raw.replace("\u202f", " ").replace("\u00a0", " ")
    return re.sub(r"^Husqvarna\s+", "", clean).strip()


# --------------------------------------------------------------------- writing
def dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def write_article(
    out_dir: Path,
    article: dict[str, Any],
    *,
    product: dict[str, Any],
    plots: list[dict[str, Any]],
    parts: dict[str, dict[str, Any] | None],
    errors: dict[str, str],
    layout: str = "both",
) -> None:
    """canonical and/or by_plot for a single article."""
    root = out_dir / "article" / str(article.get("id"))
    part_ids = collect_part_ids(article)
    refs_by_part = reference_index(plots)
    spares = spare_index(article)
    pname = main_product_name(article, product if 'layout' in locals() else None)

    dump(root / "product.json", product)
    dump(root / "_errors.json", errors)
    dump(root / "_part_list.json", {
        "main_product_article": article.get("id"),
        "part_count": len(part_ids),
        "part_ids": part_ids,
        "references": refs_by_part,
    })

    if layout in ("canonical", "both"):
        for pid in part_ids:
            rec = part_record(parts.get(pid), refs=refs_by_part.get(pid, []),
                              available=parts.get(pid) is not None,
                              product_article=article.get("id"), product_name=pname,
                              spare_meta=spares.get(pid))
            rec.pop("available", None)
            dump(root / "parts" / f"{pid}.json", rec)
        for plot in plots:
            rows = []
            for row in plot["parts"]:
                item = dict(row)
                item["part_file"] = f"parts/{row['article_number']}.json"
                rows.append(item)
            dump(root / "plots" / f"{plot_slug(plot['plot_name'])}.json", {**plot, "parts": rows})

    if layout in ("by_plot", "both"):
        for plot in plots:
            folder = root / plot_slug(plot["plot_name"])
            rows = []
            for row in plot["parts"]:
                pid = row["article_number"]
                rec = part_record(parts.get(pid), refs=refs_by_part.get(pid, []),
                                  available=parts.get(pid) is not None,
                                  product_article=article.get("id"), product_name=pname,
                                  spare_meta=spares.get(pid))
                dump(folder / f"{pid}.json", rec)
                item = dict(row)
                item["available"] = parts.get(pid) is not None
                rows.append(item)
            dump(folder / "_category.json", {**plot, "parts": rows})


def write_category_article(
    out_dir: Path,
    article: dict[str, Any],
    *,
    category: str,
    plots: list[dict[str, Any]],
    parts: dict[str, dict[str, Any] | None],
    errors: dict[str, str],
) -> None:
    """Parts-only layout used by the category archives (no product.json)."""
    root = out_dir / "article" / str(article.get("id"))
    part_ids = collect_part_ids(article)
    missing = [pid for pid in part_ids if parts.get(pid) is None]
    refs_by_part = reference_index(plots)
    spares = spare_index(article)
    pname = main_product_name(article, product if 'layout' in locals() else None)

    dump(root / "_part_list.json", {
        "main_product_article": article.get("id"),
        "category": category,
        "part_count": len(part_ids),
        "part_ids": part_ids,
        "missing_part_ids": missing,
        "references": refs_by_part,
    })
    dump(root / "_errors.json", errors)
    dump(root / "related_products.json", build_related(article))

    for plot in plots:
        folder = root / plot_slug(plot["plot_name"])
        rows = []
        for row in plot["parts"]:
            pid = row["article_number"]
            rec = part_record(parts.get(pid), refs=refs_by_part.get(pid, []),
                              available=parts.get(pid) is not None,
                              product_article=article.get("id"), product_name=pname,
                              spare_meta=spares.get(pid))
            dump(folder / f"{pid}.json", rec)
            item = dict(row)
            item["available"] = parts.get(pid) is not None
            rows.append(item)
        dump(folder / "_category.json", {**plot, "parts": rows})
