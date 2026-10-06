#!/bin/bash
# Watchtower setup script

set -e

echo "🔧 Setting up Watchtower..."

# Create virtual environment
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Virtual environment created"
fi

# Activate
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
echo "✅ Dependencies installed"

# Create data directories
mkdir -p data/snapshots data/cache

# Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "⚠️  Created .env — EDIT IT with your API keys!"
fi

# Initialize database
python -m watchtower.storage.migrations 2>/dev/null || python -c "
from watchtower.storage.database import db
print('✅ Database initialized')
"

echo ""
echo "🎉 Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys"
echo "  2. Run: source venv/bin/activate && python -m watchtower.main"
