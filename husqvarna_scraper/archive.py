"""Archive an output tree into a single .zip.

The catalogue is ~384k small JSON files on a 4.3 GB tree, so the two costs that matter are
per-file overhead and compressibility — both are handled by streaming straight into one
deflate stream instead of building a list.

`zip_tree` returns measured numbers (files, bytes in, bytes out, seconds) so a run can say
what it actually saved rather than guessing a ratio.
"""

from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path
from typing import Callable

CHUNK = 1 << 20


def zip_tree(
    src: Path,
    dest: Path,
    *,
    level: int = 6,
    on_progress: Callable[[int, int], None] | None = None,
    drop_source: bool = False,
) -> dict[str, float]:
    """Write every file under `src` into `dest`; optionally delete the tree afterwards."""
    started = time.perf_counter()
    files = [p for p in src.rglob("*") if p.is_file()]
    total_in = sum(p.stat().st_size for p in files)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    written = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
        for index, path in enumerate(files, 1):
            zf.write(path, path.relative_to(src).as_posix())
            written += 1
            if on_progress and index % 25000 == 0:
                on_progress(index, len(files))
    tmp.replace(dest)
    total_out = dest.stat().st_size
    elapsed = time.perf_counter() - started
    if drop_source:
        shutil.rmtree(src)
    return {
        "files": float(written),
        "bytes_in": float(total_in),
        "bytes_out": float(total_out),
        "seconds": round(elapsed, 1),
        "ratio": round(total_in / total_out, 2) if total_out else 0.0,
    }


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def describe(stats: dict[str, float], dest: Path) -> str:
    return (
        f"archived {int(stats['files']):,} files -> {dest} "
        f"({human(stats['bytes_in'])} -> {human(stats['bytes_out'])}, "
        f"{stats['ratio']}x, {stats['seconds']}s)"
    )
