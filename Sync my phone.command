#!/bin/bash
# Bring in what the phone uploaded to Google Drive (My Drive/PhoneUsage/phone)
# and update the shared archive. No cable: the phone uploads on its own.
cd "$(dirname "$0")" && .venv/bin/python -m wellbeing ingest-phone
echo ""
read -n 1 -s -r -p "  Press any key to close..."
