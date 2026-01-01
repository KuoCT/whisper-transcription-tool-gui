#!/usr/bin/env bash
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
  exit 0
fi

echo "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh

echo
echo "uv installed. Please re-run whisper-transcription-tool-gui.sh to continue."
echo
if [ -t 0 ]; then
  read -r -p "Press Enter to close..."
fi
exit 1
