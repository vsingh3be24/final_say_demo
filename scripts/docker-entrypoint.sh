#!/usr/bin/env sh
set -e

echo "==> Configuring selected official notice sources..."
python -m finalsay.services.source_onboarding --apply

PORT="${PORT:-8000}"
echo "==> Starting FinalSay backend on port ${PORT}..."
exec python -m uvicorn finalsay.main:app --host 0.0.0.0 --port "${PORT}"
