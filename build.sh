#!/bin/bash
# Production build script

echo "⚡ Lightning Radar - Building for Production"
echo "============================================"
echo ""

# Build frontend
echo "Building React frontend..."
cd frontend
npm install
npm run build

if [ $? -ne 0 ]; then
    echo "❌ Frontend build failed"
    exit 1
fi

echo "✅ Frontend build complete"
echo ""

# Return to root
cd ..

echo "✅ Production build complete!"
echo ""
echo "To run production:"
echo "  1. Activate environment: conda activate lightning-radar"
echo "  2. Start server: python backend/app/main.py"
echo "  3. Open browser: http://localhost:8765"
