"""File-by-file comparison against a reference archive.

    husqvarna-scraper compare --reference article_968424101_canonical.zip --against out

Answers three questions in one pass: what is missing, what is extra, and which fields differ
(by key path, with counts and one example pair). Zips are extracted to a temp dir, so the
reference can be the archive as shipped.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

MAX_EXAMPLES = 3


def _prepare(reference: Path) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    if reference.suffix.lower() != ".zip":
        return reference, None
    tmp = tempfile.TemporaryDirectory(prefix="husq-ref-")
    with zipfile.ZipFile(reference) as zf:
        zf.extractall(tmp.name)
    # Keep the archive root: paths then read `article/<id>/...` (or `other/article/...`),
    # which is exactly the key `_key` normalises on.
    return Path(tmp.name), tmp


def _diff(ref: Any, got: Any, path: str, out: dict[str, dict[str, Any]]) -> None:
    if type(ref) is not type(got) and not (isinstance(ref, (int, float)) and isinstance(got, (int, float))):
        out.setdefault(path or "<root>", {"count": 0, "examples": []})
        out[path or "<root>"]["count"] += 1
        if len(out[path or "<root>"]["examples"]) < MAX_EXAMPLES:
            out[path or "<root>"]["examples"].append([ref, got])
        return
    if isinstance(ref, dict):
        for key in sorted(set(ref) | set(got)):
            _diff(ref.get(key), got.get(key), f"{path}.{key}" if path else key, out)
    elif isinstance(ref, list):
        if len(ref) != len(got):
            out.setdefault(f"{path}[]", {"count": 0, "examples": []})
            out[f"{path}[]"]["count"] = abs(len(ref) - len(got))
            out[f"{path}[]"]["examples"].append([f"len={len(ref)}", f"len={len(got)}"])
        for index, (a, b) in enumerate(zip(ref, got)):
            _diff(a, b, f"{path}[{index}]", out)
    elif ref != got:
        out.setdefault(path or "<root>", {"count": 0, "examples": []})
        out[path or "<root>"]["count"] += 1
        if len(out[path or "<root>"]["examples"]) < MAX_EXAMPLES:
            out[path or "<root>"]["examples"].append([ref, got])


def _key(rel: str) -> str | None:
    """Normalise `968424101/...` and `article/968424101/...` to the same key."""
    parts = rel.split("/")
    if "article" in parts:
        return "/".join(parts[parts.index("article"):])
    return None  # state files and other root noise are not part of the archive


def compare(reference: Path, against: Path, *, include_raw: bool = False) -> dict[str, Any]:
    root, tmp = _prepare(reference)
    try:
        ref_files = {
            key: p for p in root.rglob("*") if p.is_file()
            if (key := _key(p.relative_to(root).as_posix()))
        }
        got_files = {
            key: p for p in against.rglob("*") if p.is_file()
            if (key := _key(p.relative_to(against).as_posix()))
        }

        missing = sorted(set(ref_files) - set(got_files))
        extra = sorted(set(got_files) - set(ref_files))
        identical = 0
        differing: list[str] = []
        paths: dict[str, dict[str, Any]] = {}

        for rel in sorted(set(ref_files) & set(got_files)):
            if rel.endswith(".json"):
                try:
                    ref_payload = json.loads(ref_files[rel].read_text(encoding="utf-8"))
                    got_payload = json.loads(got_files[rel].read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    if ref_files[rel].read_bytes() == got_files[rel].read_bytes():
                        identical += 1
                    else:
                        differing.append(rel)
                    continue
                local: dict[str, dict[str, Any]] = {}
                _diff(ref_payload, got_payload, "", local)
                if not include_raw:
                    local = {k: v for k, v in local.items() if not k.startswith("raw_part")}
                if local:
                    differing.append(rel)
                    for path, info in local.items():
                        slot = paths.setdefault(path, {"count": 0, "files": 0, "examples": []})
                        slot["count"] += info["count"]
                        slot["files"] += 1
                        slot["examples"].extend(info["examples"][:MAX_EXAMPLES])
                else:
                    identical += 1
            else:
                if ref_files[rel].read_bytes() == got_files[rel].read_bytes():
                    identical += 1
                else:
                    differing.append(rel)

        top = sorted(paths.items(), key=lambda kv: -kv[1]["count"])[:15]
        return {
            "reference": str(reference),
            "against": str(against),
            "files_in_reference": len(ref_files),
            "files_in_target": len(got_files),
            "identical": identical,
            "differing": len(differing),
            "missing": missing,
            "extra": extra,
            "top_differing_paths": [
                {"path": p, "cells": v["count"], "files": v["files"],
                 "examples": v["examples"][:MAX_EXAMPLES]}
                for p, v in top
            ],
        }
    finally:
        if tmp is not None:
            tmp.cleanup()


def render(report: dict[str, Any]) -> str:
    lines = [
        f"reference : {report['reference']}",
        f"target    : {report['against']}",
        "",
        f"files in reference : {report['files_in_reference']}",
        f"files in target    : {report['files_in_target']}",
        f"identical          : {report['identical']}",
        f"differing          : {report['differing']}",
        f"missing            : {len(report['missing'])}",
        f"extra              : {len(report['extra'])}",
    ]
    if report["missing"]:
        lines += ["", "missing (first 10):"] + [f"  - {m}" for m in report["missing"][:10]]
    if report["extra"]:
        lines += ["", "extra (first 10):"] + [f"  + {e}" for e in report["extra"][:10]]
    if report["top_differing_paths"]:
        lines += ["", f"{'path':52s} {'cells':>6s} {'files':>6s}  example"]
        for row in report["top_differing_paths"]:
            example = ""
            if row["examples"]:
                ref_val = str(row["examples"][0][0])[:38]
                got_val = str(row["examples"][0][1])[:38]
                example = f"{ref_val!r} vs {got_val!r}"
            lines.append(f"{row['path'][:52]:52s} {row['cells']:6d} {row['files']:6d}  {example}")
    return "\n".join(lines)
