#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
bash ./install-uv.sh
bash ./run-app.sh
