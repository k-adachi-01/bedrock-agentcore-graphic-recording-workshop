#!/usr/bin/env bash
set -euo pipefail

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo ".env is tracked by git. Remove it from history before publishing." >&2
  exit 1
fi

if [[ ! -f .dockerignore ]]; then
  echo ".dockerignore is missing." >&2
  exit 1
fi

if [[ ! -f .gcloudignore ]]; then
  echo ".gcloudignore is missing." >&2
  exit 1
fi

if grep -R --line-number \
  --exclude-dir=.git \
  --exclude-dir=.venv \
  --exclude-dir='.venv-*' \
  --exclude-dir=.pytest_cache \
  --exclude-dir=__pycache__ \
  --exclude-dir=artifacts \
  --include='*.py' --include='*.html' --include='*.md' --include='*.sh' \
  -E 'AIza[0-9A-Za-z_-]{35}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' .; then
  echo "Potential secret-like content found. Inspect the lines above." >&2
  exit 1
fi

echo "Publication safety checks passed."
