#!/bin/bash
# Watchtower daily scan + digest wrapper
# Runs scan cycle then sends digest to Telegram

cd /opt/data/home/watchtower
source venv/bin/activate

echo "=== Watchtower $(date) ==="
python -m watchtower.main --mode scan
python -m watchtower.main --mode digest
echo "=== Done ==="
