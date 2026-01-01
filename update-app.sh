#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

relaunch=0
if [[ "${1:-}" == "--relaunch" ]]; then
  relaunch=1
fi

bash ./install-uv.sh

if ! command -v git >/dev/null 2>&1; then
  echo "git not found. Please install Git first."
  exit 1
fi

git pull --rebase
uv sync
if [[ $relaunch -eq 1 ]]; then
  nohup bash ./run-app.sh >/dev/null 2>&1 &
  exit 0
fi

bash ./run-app.sh
