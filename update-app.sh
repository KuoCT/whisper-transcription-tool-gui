#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
bash ./install-uv.sh

if ! command -v git >/dev/null 2>&1; then
  echo "git not found. Please install Git first."
  exit 1
fi

git pull --rebase
uv sync
bash ./run-app.sh
