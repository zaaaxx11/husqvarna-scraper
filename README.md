# husqvarna-scraper

Automates what used to be a manual job: walk the Husqvarna B2B catalogue, open every
product, pull its IPL diagrams and every spare part, and write the result in the same
folder/file shape as the existing archives.

No browser, no login, no Places-style API key. The portal itself serves the data through one
GraphQL endpoint, and the catalogue tree is embedded in `/us/products/`.

## The catalogue

`https://portal.husqvarnagroup.com/us/products/` ships its navigation tree as a single JSON
prop. Measured 2026-10-20:

```
1 group  (Construction)
└── 8 categories
    ├── Diamond tools                9 product types, 20 leaf links
    ├── Concrete placement           4 product types, 10 leaf links
    ├── Dust and Slurry management   1 product type,   6 leaf links
    ├── Sawing, cutting and drilling 6 product types, 19 leaf links
    ├── Compaction                   1 product type,   5 leaf links
    ├── Surface preparation          6 product types,  4 leaf links
    ├── Remote demolition            1 product type,   3 leaf links
    └── Other                        4 product types,  6 leaf links
                                     32 product types, 73 leaf links
```

Those 73 leaf pages currently render **579 distinct products** carrying **1,931 distinct
article numbers** (2,461 if related-product carousels are counted, which the scraper does not) (one product can have many articles: variants, voltages, bar lengths).

> `totalCount` on a leaf page is the count of its *parent* type, not of that leaf — 132
> repeats on every diamond-blade leaf while the leaf itself renders 11–130 products. The
> rendered list is the source of truth, which is why this tool enumerates pages and not
> `totalCount`.

## Output

Three layouts, copied from the archives — not invented:

```
canonical                      by_plot                        category (parts-only)
article/<article>/             article/<article>/             article/<article>/
├── product.json               ├── <PLOT>/                     ├── _part_list.json   (+category, +missing_part_ids)
├── _part_list.json            │   ├── _category.json          ├── _errors.json
├── _errors.json               │   └── <part>.json             ├── related_products.json
├── parts/<part>.json          └── ...                         └── <PLOT>/
└── plots/<PLOT>.json                                             ├── _category.json
                                                                  └── <part>.json
```

`--layout canonical|by_plot|both` selects the first two; the `category` command always uses
the parts-only layout (the archives have no `product.json` in that mode).

Per article the run costs **1 + ceil(parts/20)** requests (1 product query + batched part
queries). A 155-part machine is 9 requests.

## Usage (one command)

```bash
./husq                     # usage
./husq install             # once: venv + dependencies
./husq one 968424101       # one article, full output
./husq cat "Diamond tools" # one category
./husq all                 # the whole catalogue
./husq cmp ref.zip out/    # diff an output tree against an archive
```

Template:

```
./husq <command> [args]

  install                 create .venv + install (run once)
  one <article> [<more>]  scrape specific article numbers
  cat "<category>"        scrape one category
  all                     scrape the entire catalogue
  cmp <ref> <out>         compare output against a .zip reference
  where                   show paths and defaults

env (optional): OUT=dir LAYOUT=both CONC=12 WORKERS=16 RPS=50
```

Real examples:

```bash
./husq install
OUT=~/husq-data ./husq all                       # full run, resumable
CONC=16 WORKERS=32 ./husq all                    # faster, ~210 MB RSS
./husq cat "Remote demolition"                   # 29 products, 233 articles
./husq one 968424101 529663903                   # two articles
./husq cmp ~/archive/article_968424101_canonical.zip ./out
./husq cmp ~/archive/other.zip ./out             # parts-only reference
```

`./husq one` writes both layouts; `./husq all` and `./husq cat` write the full product
output (with `product.json`). Add `--parts-only` to either for the category layout.

A finished article is recorded in `<out>/_state.json`; every command runs with `--resume`,
so re-running continues instead of starting over. Per-part failures land in `_errors.json`
and are also listed as `missing_part_ids` — never silently dropped.

## Run it on a server

```bash
sudo install -d /srv/husqvarna
sudo git clone https://github.com/<you>/husqvarna-scraper /srv/husqvarna/app
cd /srv/husqvarna/app && python3 -m venv .venv && .venv/bin/pip install -e .
```

`deploy/husqvarna-scraper.service` + `deploy/husqvarna-scraper.timer` run a nightly
`all --resume`; `deploy/run.sh` is the same thing without systemd.

## Speed, measured

Three changes mattered, in this order:

1. **One part fetch per product, not per article.** Variants share ~57% of their parts
   (measured: 3,404 part rows across 6 articles of one demolition robot, 1,456 unique).
2. **Batch 100 instead of 20.** 20 aliases cost 131 ms/part, 100 aliases cost 54 ms/part.
   200+ aliases degrade again (missing parts, 25 s per request).
3. **Parallelism.** 32 concurrent batches answer in the same wall time as one.

Same 6-article demolition robot, same machine:

| setting | requests | wall time | peak RSS |
|---|---|---|---|
| batch 20, sequential, rps 2 | 185 | 274 s | 45 MB |
| batch 100, workers 16, 1 product | 31 | 62 s | 55 MB |
| batch 100, workers 32, 1 product | 22 | **19.8 s** | 60 MB |
| workers 32, 8 products parallel | 161 | 65 s | 180 MB |
| workers 32, 16 products parallel | 274 | 78.6 s | 212 MB |

Throughput: 12.2 products/minute at `--concurrency 16`, 7.4 at 8. Those numbers are the
*worst* products in the catalogue (410–660 parts each); the average article carries ~136.

End-to-end check (2026-10-20): the **entire catalogue** — 1,931 articles, 164,781 part
rows, 384,134 files — finished in **6 min 56 s**, with 3,268 requests, 420 MB downloaded,
4.28 GB written and zero failed articles. Peak RSS at `--concurrency 12` stays around
200 MB.

Budget ~13 MB of RSS per concurrent product above a ~45 MB base (`--concurrency 8` ≈ 180 MB,
`--concurrency 16` ≈ 212 MB). Raise `--rps` only until the endpoint returns 429; the client
backs off and retries.

## Fields that are not portal fields

`product.json` contains keys the portal does not publish — `variant_specs`,
`numberOfVariants`, `standardEquipment`, `mainVideo`. The archives carry them, so they are
reconstructed: variants from the hero response, `standardEquipment`/`mainVideo` as empty
defaults. They are never filled with invented values.

## Honest limits

* `totalCount` is unusable (parent count) — only rendered products are captured.
* Leaf pages render a subset of their parent type; overlapping leaves are merged by product
  GUID, so the product count above is already de-duplicated.
* Part availability is whatever the portal answers. A part that returns nothing is recorded
  as `available: false` and `"not returned"`, which is exactly what the old archives did
  (39 of 3,712 files in the reference archive).
* Rate limit: the public endpoint tolerates ~2 req/s comfortably; higher rates start
  returning 429 and the client backs off.

## Tests

```bash
.venv/bin/python -m pytest tests -q
```

10 tests, no network: taxonomy parsing, GUID/article pairing, part-id ordering, reference
provenance, and both output layouts.
