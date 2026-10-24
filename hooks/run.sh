#!/bin/sh
# Portable hook launcher: first working python3/python runs hooks/<script>.py (stdlib only).
D="$(cd "$(dirname "$0")" && pwd)"
for p in python3 python; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c "" >/dev/null 2>&1; then
    exec "$p" "$D/$1"
  fi
done
exit 0  # no python: do not block the session
