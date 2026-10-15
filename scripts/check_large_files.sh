#!/usr/bin/env bash
# Warn about tracked or staged files over 10 MB. Exits 1 if any are found.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
LIMIT=$((10 * 1024 * 1024))
found=0
while IFS= read -r f; do
  [[ -f "$f" ]] || continue
  size=$(wc -c < "$f")
  if (( size > LIMIT )); then
    echo "WARNING: $f is $((size / 1024 / 1024)) MB (> 10 MB)"; found=1
  fi
done < <({ git ls-files; git diff --cached --name-only; } | sort -u)
if (( found )); then exit 1; fi
echo "OK: no tracked or staged file over 10 MB."
