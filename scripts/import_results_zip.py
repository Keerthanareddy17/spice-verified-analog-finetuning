"""Unpack a results zip downloaded from Drive into runs/phase3/<run_name>/ .
If the browser already unpacked it into a folder named after the run, pass that folder instead.

Usage: python scripts/import_results_zip.py ~/Downloads/qwen25_05b_lora_results.zip
Afterwards scripts/make_results_table.py works unchanged.
"""
import argparse
from pathlib import Path

from analogft import paths
from analogft.resultszip import import_results_dir, import_results_zip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("zip_path")
    args = ap.parse_args()
    dest = paths.RUNS_DIR / "phase3"
    src = Path(args.zip_path).expanduser()
    files = import_results_dir(src, dest) if src.is_dir() else import_results_zip(src, dest)
    runs = sorted({f.relative_to(dest.resolve()).parts[0] for f in files})
    print(f"unpacked {len(files)} files into {dest} for run(s): {', '.join(runs)}")
    print("next: python scripts/make_results_table.py --runs " + " ".join(runs))


if __name__ == "__main__":
    main()
