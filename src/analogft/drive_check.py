"""Manifest building and verification for data folders.

A producer writes manifest.json (file names, sizes, row counts); a consumer (e.g. a Colab run)
calls verify_manifest to confirm that the files on disk are complete before using them.
"""
from __future__ import annotations

import json
from pathlib import Path

MANIFEST = "manifest.json"


class DriveUploadIncomplete(RuntimeError):
    """The files on disk do not match manifest.json (upload probably unfinished)."""


def build_manifest(folder: Path) -> dict:
    """Describe every file under folder: size in bytes, plus row count for .jsonl/.csv."""
    files = {}
    for p in sorted(Path(folder).rglob("*")):
        if not p.is_file() or p.name == MANIFEST or p.name.startswith("."):
            continue
        entry = {"bytes": p.stat().st_size}
        if p.suffix == ".jsonl":
            entry["rows"] = sum(1 for line in p.open("rb") if line.strip())
        elif p.suffix == ".csv":
            entry["rows"] = max(0, sum(1 for line in p.open("rb") if line.strip()) - 1)  # minus header
        files[str(p.relative_to(folder))] = entry
    return {"n_files": len(files), "total_bytes": sum(f["bytes"] for f in files.values()), "files": files}


def write_manifest(folder: Path) -> Path:
    """Write folder/manifest.json and return its path."""
    out = Path(folder) / MANIFEST
    out.write_text(json.dumps(build_manifest(folder), indent=2) + "\n")
    return out


def verify_manifest(folder: Path, raise_on_error: bool = False) -> tuple[bool, list[str]]:
    """Compare manifest.json with the files present (existence + size).

    Returns (ok, problems). With raise_on_error=True, raises DriveUploadIncomplete instead
    of returning a failure.
    """
    folder = Path(folder)
    mf = folder / MANIFEST
    problems: list[str] = []
    if not mf.exists():
        problems.append(f"{MANIFEST} missing in {folder}")
    else:
        for name, entry in json.loads(mf.read_text())["files"].items():
            p = folder / name
            if not p.exists():
                problems.append(f"missing: {name}")
            elif p.stat().st_size != entry["bytes"]:
                problems.append(f"size mismatch: {name} ({p.stat().st_size} != {entry['bytes']} bytes)")
    if problems and raise_on_error:
        raise DriveUploadIncomplete("Files do not match manifest.json (incomplete copy or upload not finished yet): " + "; ".join(problems[:5]))
    return not problems, problems
