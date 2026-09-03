#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 -m app.server --provider demo --video-mode none
