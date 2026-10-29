#!/usr/bin/env bash
# Open the bitmap -> vector -> G-code workbench in the default browser.
# The page is a single offline HTML file; nothing is uploaded anywhere.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAGE="$HERE/../assets/vectorizer.html"

if [ ! -f "$PAGE" ]; then
  echo "[error] vectorizer page not found: $PAGE" >&2
  exit 1
fi

case "$(uname -s)" in
  Darwin)
    open "$PAGE"
    ;;
  Linux)
    if command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$PAGE"
    else
      echo "Open this file in a browser: $PAGE"
    fi
    ;;
  *)
    echo "Open this file in a browser: $PAGE"
    ;;
esac
