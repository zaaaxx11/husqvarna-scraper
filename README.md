# husqvarna-scraper

Automates what used to be a manual job: walk the Husqvarna B2B catalogue, open every
product, pull its IPL diagrams and every spare part, and write the result in the folder
shape of the existing archives.

No browser, no login, no API key. The portal serves everything through one GraphQL endpoint,
and the catalogue tree is embedded in `/us/products/`.

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

Those 73 leaf pages render **579 distinct products** carrying **1,931 distinct articles**
(one product has many articles: variants, voltages, bar lengths).

> `totalCount` on a leaf page is the count of its *parent* type, not of that leaf — 132
> repeats on every diamond-blade leaf while the leaf itself renders 11–130 products. The
> rendered list is the source of truth, which is why this tool enumerates pages and not
> `totalCount`.

## Output

One layout: every part sits in the folder of the diagram it belongs to.

```
article/<article>/
├── product.json            product-level data (name, price, intro, variants)
├── _part_list.json         every part id, in ascending article order
├── _errors.json            parts the portal did not return
├── <PLOT>/_category.json   the diagram plus its parts (position, quantity, available)
└── <PLOT>/<part>.json      one file per part
```

`--parts-only` (or the `category` command) drops `product.json` and adds
`related_products.json` + `missing_part_ids`, matching the category archives.

A part that only appears in the spare-parts list — never on a diagram — has no folder to sit
in, so it is listed in `_part_list.json` and `_errors.json` but gets no file. The reference
archives behave the same way (5 of 155 parts in their own `968424101` export).

Per article the run costs **1 + ceil(parts/100)** requests: one product query plus batched
part queries. A 155-part machine is 3 requests.

## Usage (one command)

```bash
./husq                     # usage
./husq install             # once: venv + dependencies
./husq one 968424101       # one article
./husq cat "Diamond tools" # one category
./husq all                 # the whole catalogue
./husq zip out/            # archive (and delete) an output tree
./husq cmp ref.zip out.zip # diff against an archive
```

Template:

```
./husq <command> [args]

  install                 create .venv + install (run once)
  one <article> [<more>]  scrape specific article numbers
  cat "<category>"        scrape one category
  all                     scrape the entire catalogue
  zip [dir] [file.zip]    archive an output tree (then delete the tree)
  cmp <ref> <out>         compare output against a .zip (either side may be a zip)
  where                   show paths and defaults

env (optional): OUT=dir CONC=12 WORKERS=16 RPS=50 KEEP_RAW=1
```

Real examples:

```bash
./husq install
OUT=~/husq-data ./husq all                 # full run
KEEP_RAW=1 ./husq all                      # keep the tree (resumable)
CONC=16 WORKERS=32 ./husq all              # faster, ~210 MB RSS
./husq cat "Remote demolition"
./husq one 968424101 529663903
./husq cmp ~/archive/other.zip ./out.zip   # parts-only reference
```

Every run is resumable through `<out>/_state.json` — but the default auto-zip **deletes the
tree**, so resuming only works with `KEEP_RAW=1`. Per-part failures land in `_errors.json`
and are also listed as `missing_part_ids` — never silently dropped.

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

End-to-end, the whole catalogue — 1,931 articles, 164,781 part rows — finished in
**6 min 56 s**, with 3,268 requests, 420 MB downloaded, 4 retries and **zero failed
articles** at `--concurrency 12`. Peak RSS stays around 200 MB.

Budget ~13 MB of RSS per concurrent product above a ~45 MB base (`--concurrency 8` ≈ 180 MB,
`--concurrency 16` ≈ 212 MB). `--rps 50` never triggered a 429 in that run; the client still
backs off and retries if one appears.

## Disk

The catalogue is hundreds of thousands of small JSON files, and deflate eats them: **4.9×
to 5.2×** smaller with no loss. `./husq` therefore archives to `<out>.zip` when a run
finishes and removes the raw tree, unless `KEEP_RAW=1`.

| measured sample | files | tree | zip | time |
|---|---|---|---|---|
| one article (`968424101`, 155 parts) | 173 | 1.6 MB | 338 KB | <1 s |
| one category (`Remote demolition`, 74 articles) | 15,252 | 140 MB | 28.7 MB | 4.5 s |
| full catalogue (two-layout build, before the layout change) | 384,134 | 4.0 GB | 783 MiB | 4 min |

`./husq zip <dir> [dest.zip]` archives an existing tree, and `./husq cmp` accepts a zip on
either side — so a compressed output can still be diffed.

## Run it on a server

```bash
sudo install -d /srv/husqvarna
sudo git clone https://github.com/<you>/husqvarna-scraper /srv/husqvarna/app
cd /srv/husqvarna/app && python3 -m venv .venv && .venv/bin/pip install -e .
```

`deploy/husqvarna-scraper.service` + `deploy/husqvarna-scraper.timer` run a nightly
`all --resume`; `deploy/run.sh` is the same thing without systemd.

## Fields that are not portal fields

`product.json` contains keys the portal does not publish — `variant_specs`,
`numberOfVariants`, `standardEquipment`, `mainVideo`. The archives carry them, so they are
reconstructed: variants from the hero response, `standardEquipment`/`mainVideo` as empty
defaults. They are never filled with invented values.

## Honest limits

* `totalCount` is unusable (parent count) — only rendered products are captured.
* Leaf pages overlap; products are merged by GUID and articles are claimed once, so nothing
  is scraped twice. The published counts above are already de-duplicated.
* `product.json → images` carries the portal's main image only. The archives' 6-image gallery
  comes from Aprimo (`getAprimoImageURL(imageId)`), and those asset ids are not exposed by any
  product query — so the gallery cannot be reconstructed without guessing.
* Part availability is whatever the portal answers. A part that returns nothing is recorded
  as `available: false` and `"not returned"`, exactly as the old archives did.
* Parts that appear on no diagram get no file (see Output).

## Tests

```bash
.venv/bin/python -m pytest tests -q
```

10 tests, no network: taxonomy parsing, GUID/article pairing, part-id ordering, reference
provenance, and the by_plot layout.
