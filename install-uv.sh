#!/usr/bin/env bash
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
  exit 0
fi

echo "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
