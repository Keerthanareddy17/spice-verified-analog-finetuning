"""Unpack a results zip downloaded from Drive into runs/phase3/<run_name>/ .
If the browser already unpacked it into a folder named after the run, pass that folder instead.

Usage: python scripts/import_results_zip.py ~/Downloads/qwen25_05b_lora_results.zip   (Phase 3)
       python scripts/import_results_zip.py ~/Downloads/phase4_results.zip              (Phase 4)
Afterwards scripts/make_results_table.py works unchanged.
"""
import argparse
from pathlib import Path

from analogft import paths
from analogft.resultszip import (import_phase4_dir, import_phase4_zip, import_results_dir, import_results_zip,
                                 is_phase4_zip)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("zip_path")
    args = ap.parse_args()
    src = Path(args.zip_path).expanduser()
    if (src.is_dir() and src.name == "phase4") or (src.is_file() and is_phase4_zip(src)):   # Phase 4 results
        files = import_phase4_dir(src, paths.RUNS_DIR) if src.is_dir() else import_phase4_zip(src, paths.RUNS_DIR)
        print(f"unpacked {len(files)} files into {paths.RUNS_DIR / 'phase4'}")
        print("next: python scripts/make_phase4_table.py")
        return
    dest = paths.RUNS_DIR / "phase3"
    files = import_results_dir(src, dest) if src.is_dir() else import_results_zip(src, dest)
    runs = sorted({f.relative_to(dest.resolve()).parts[0] for f in files})
    print(f"unpacked {len(files)} files into {dest} for run(s): {', '.join(runs)}")
    print("next: python scripts/make_results_table.py --runs " + " ".join(runs))


if __name__ == "__main__":
    main()
