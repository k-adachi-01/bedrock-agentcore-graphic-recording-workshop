#!/usr/bin/env bash
set -euo pipefail

if [[ -f .env.keys || -f .env.production.keys ]]; then
  echo "Do not publish dotenvx private key files." >&2
  exit 1
fi

if [[ ! -f .gitignore ]]; then
  echo ".gitignore is missing." >&2
  exit 1
fi

echo "Publication safety checks passed."
