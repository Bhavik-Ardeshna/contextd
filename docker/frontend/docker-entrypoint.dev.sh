#!/bin/sh
set -e
# Ensure deps are installed when the mounted source does not have a usable node_modules volume.
if [ ! -x node_modules/.bin/vite ]; then
  npm ci --no-audit --no-fund
fi
exec npm run dev
