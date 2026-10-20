"""Offline tests: the parsers and the layout builders must not need the network."""

from __future__ import annotations

import json

from husqvarna_scraper.catalog import parse_product_page, parse_taxonomy
from husqvarna_scraper.pipeline import (
    build_plots,
    build_related,
    collect_part_ids,
    format_article_number,
    part_record,
    plot_slug,
    reference_index,
)

TAXONOMY_HTML = """<script>React.createElement(Nav, {"groups":[{"id":"g","title":"Construction","list":[
{"id":"c","title":"Diamond tools","list":[{"id":"t","title":"Diamond blades","list":[
{"id":"l1","link":{"text":"All Diamond blades","href":"/us/diamond-blades/"}},
{"id":"l2","link":{"text":"Wall saw blades","href":"/us/diamond-blades/wall-saw-blades/"}}]}]}]}]})</script>"""

PRODUCT_HTML = (
    '{"__typename":"DiamondTool","id":"{084ABAD1-0097-48DB-9FCE-1D623820DC3A}","sku":"968424101",'
    '"url":"/us/power-cutters/k3600mk-ii/","name":{"longName":"Husqvarna K 3600 MK II"},'
    '"articles":[{"__typename":"Article","id":"968424101"},'
    '{"__typename":"Article","id":"968424102"}]}'
)

ARTICLE = {
    "id": "968424101",
    "articleDescription": "K 3600 MK II",
    "isDiscontinued": False,
    "isNew": True,
    "name": {"productName": "Husqvarna K 3600 MK II", "shortName": "K 3600 MK II",
             "longName": "Husqvarna K 3600 MK II"},
    "product": {"category": {"name": "Power cutters"}},
    "ipls": [{
        "id": "HVA_PL-000011710",
        "name": "HANDLE",
        "image": {"url": "https://media/x.png", "altText": "HANDLE"},
        "articles": [{
            "id": "506349404", "number": 1, "quantity": 1, "name": "TAP",
            "articleDescription": "TAP K3600", "comment": None,
            "replacedIds": ["506349402"], "coordinates": ["810;231;821;246"],
            "url": "https://portal.husqvarnagroup.com/us/spare-parts/?part=506349404",
        }],
    }],
    "spareParts": [{"id": "501691702"}],
}


def test_plot_slug_matches_folder_names():
    assert plot_slug("CHASSIS / FRAME") == "CHASSIS_FRAME"
    assert plot_slug("LEVER") == "LEVER"
    assert plot_slug("HANDLE, COMPLETE") == "HANDLE_COMPLETE"


def test_article_number_is_formatted_like_the_portal():
    assert format_article_number("968424101") == "968\u00a042\u00a041\u201101"
    assert format_article_number("529663903") == "529\u00a066\u00a039\u201103"
    assert format_article_number("abc") == "abc"


def test_taxonomy_yields_every_leaf_tagged_with_its_parents():
    leaves = parse_taxonomy(TAXONOMY_HTML)
    assert [l.title for l in leaves] == ["All Diamond blades", "Wall saw blades"]
    assert all(l.category == "Diamond tools" and l.product_type == "Diamond blades" for l in leaves)
    assert str(leaves[0].url).endswith("/us/diamond-blades/")


def test_product_page_pairs_guid_with_its_articles():
    refs = parse_product_page(PRODUCT_HTML)
    assert len(refs) == 1
    assert refs[0].product_id == "{084ABAD1-0097-48DB-9FCE-1D623820DC3A}"
    assert refs[0].article_ids == ["968424101", "968424102"]
    assert refs[0].slug == "k3600mk-ii"


def test_part_ids_are_sorted_and_merge_ipl_with_spare_parts():
    ids = collect_part_ids(ARTICLE)
    assert ids == ["501691702", "506349404"], "spare-parts-only ids must survive, sorted"


def test_reference_index_carries_ipl_provenance():
    refs = reference_index(build_plots(ARTICLE))
    row = refs["506349404"][0]
    assert row["source_type"] == "ipl"
    assert row["ipl_id"] == "HVA_PL-000011710"
    assert row["position"] == 1
    assert row["replaced_ids"] == ["506349402"]
    assert row["coordinates"] == ["810;231;821;246"]


def test_part_record_writes_the_archive_shape():
    refs = reference_index(build_plots(ARTICLE))
    part = {
        "id": "506349404", "name": "TAP", "articleDescription": "TAP K3600",
        "articleNumberFormatted": "506\u00a034\u00a094\u201104",
        "brand": "Husqvarna", "description": None,
        "mainImage": {"url": "https://media/x.png", "altText": "TAP", "imageProvider": "APRIMO"},
        "specifications": {"articleDescription": "TAP K3600", "netWeight": "0.1 kg"},
        "replacementHistory": [], "alsoUsedIn": [
            {"__typename": "Machine", "id": "{X}", "url": "/us/x/",
             "name": {"longName": "Husqvarna K 3600 MK II", "shortName": "K 3600 MK II",
                      "productName": "Husqvarna K 3600 MK II"}}],
        "url": "https://portal.husqvarnagroup.com/us/spare-parts/?part=506349404",
    }
    rec = part_record(part, refs=refs["506349404"], available=True,
                      product_article="968424101", product_name="K 3600 MK II")
    assert set(rec) == {"information", "Specification", "replacement_history",
                        "also_used_in", "source", "raw_part", "available"}
    assert rec["information"]["article_number"] == "506349404"
    assert rec["information"]["subtitle"] == "TAP K3600"
    assert rec["information"]["main_image"] == {"url": "https://media/x.png", "altText": "TAP"}
    assert rec["source"]["main_product_name"] == "K 3600 MK II"
    assert rec["also_used_in"][0]["name"]["shortName"] == "K 3600 MK II"
    assert rec["raw_part"]["price"] is None


def test_spare_parts_only_part_records_a_spare_parts_reference():
    rec = part_record(None, refs=[], available=False,
                      spare_meta={"name": "COMBINATION WRENCH", "articleDescription": None,
                                  "url": "https://portal.husqvarnagroup.com/us/spare-parts/?part=501691702"})
    assert rec["source"]["references"][0]["source_type"] == "spareParts"
    assert rec["available"] is False


def test_related_products_flatten_accessories_and_tools():
    payload = build_related({
        "id": "968424101",
        "relatedAccessories": {"totalCount": 1, "result": [{
            "id": "597123401", "numberFormatted": "597 12 34\u201101",
            "name": {"shortName": "WS 440 HF"}, "articleDescription": "WS 440 HF",
            "mainImage": {"url": "https://media/y.png", "altText": "WS 440 HF"}}]},
        "relatedTools": [],
    })
    assert payload["total_count"] == 1
    assert payload["related_products"][0]["source_type"] == "relatedAccessories"
    assert payload["related_products"][0]["name"] == "WS 440 HF"


def test_layout_writer_emits_plot_folders_only(tmp_path):
    from husqvarna_scraper.pipeline import build_product, write_article

    product = build_product(ARTICLE, None)
    write_article(tmp_path, ARTICLE, product=product, plots=build_plots(ARTICLE),
                  parts={"506349404": {"id": "506349404", "name": "TAP"}},
                  errors={"501691702": "not returned"})
    root = tmp_path / "article" / "968424101"
    assert (root / "product.json").exists()
    assert json.loads((root / "_part_list.json").read_text())["part_ids"] == ["501691702", "506349404"]
    assert (root / "HANDLE" / "506349404.json").exists()
    assert not (root / "parts").exists(), "canonical layout is gone"
    assert not (root / "plots").exists(), "canonical layout is gone"
    plot = json.loads((root / "HANDLE" / "_category.json").read_text())
    assert plot["parts"][0]["available"] is True
