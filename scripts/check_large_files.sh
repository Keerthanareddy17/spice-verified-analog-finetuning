#!/usr/bin/env bash
# Warn about tracked or staged files over 10 MB. Exits 1 if any are found.
# Exception (DECISIONS D23): the Phase 2 dataset files data/phase2/*.jsonl and data/phase2/build_stats.json may be up to 50 MB.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
LIMIT=$((10 * 1024 * 1024))
DATA_LIMIT=$((50 * 1024 * 1024))
found=0
while IFS= read -r f; do
  [[ -f "$f" ]] || continue
  size=$(wc -c < "$f")
  limit=$LIMIT
  case "$f" in data/phase2/*.jsonl|data/phase2/build_stats.json) limit=$DATA_LIMIT ;; esac
  if (( size > limit )); then
    echo "WARNING: $f is $((size / 1024 / 1024)) MB (> $((limit / 1024 / 1024)) MB)"; found=1
  fi
done < <({ git ls-files; git diff --cached --name-only; } | sort -u)
if (( found )); then exit 1; fi
echo "OK: no tracked or staged file over 10 MB."
